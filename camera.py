"""
Camera.py is primarly meant to be runned inside a Domoticz plugin.

If given --standalone it can be run in a standalone mode, meant
for debugging.

"""
import time
import sys
import threading
import json
import asyncio
import logging
import logging.handlers
from importlib.metadata import version
import argparse
import requests
import webhook_listener
from reolink_aio.api import Host
from reolink_aio.enums import SubType
from reolink_aio.exceptions import (ReolinkError, SubscriptionError,
                                    ReolinkTimeoutError, CredentialsInvalidError, LoginError)
import reolink_utils


LOG_FILENAME = '/tmp/camera.log'
RUNNING = False

def check_runtime():
    """ Check the current runtime so it complies with the requirements."""

    requirements = {}
    requirements["reolink_aio"] = '0.9.0'

    for module in requirements:
        req_version = requirements[module]
        _version = str(version(module))
        if _version == req_version:
            debug("Version: "+module+" "+_version+" == "+req_version)
        else:
            error("Version: "+module+" "+_version+" != "+req_version)
            return False
    return True

def post(msg):
    """ Post msg to the webhook_url"""
    try:
        json_object = json.dumps(msg)
        requests.post(webhook_url, json=json_object, timeout=2)
    except requests.exceptions.RequestException as _ex:
        if DOLOGGING:
            logger.debug("Post Error: %s", str(_ex))


def log(msg):
    """ Send a Log message to the server, message in msg """
    if DOLOGGING:
        logger.debug(msg)
        return
    myobj = {'Type': 'Log',
             'Log': msg}
    post(myobj)


def error(msg):
    """ Send a Error message to the server, message in msg """
    if DOLOGGING:
        logger.debug(msg)
    else:
        myobj = {'Type': 'Log',
                 'Error': msg}
        post(myobj)


def debug(msg):
    """ Send a Debug message to the server, message in msg """
    if DOLOGGING:
        logger.debug(msg)
    else:
        myobj = {'Type': 'Log',
                 'Debug': msg}
        post(myobj)


def stop(msg):
    """ Send a Stop message to the server, message in msg """
    if DOLOGGING:
        logger.debug(msg)
    else:
        myobj = {'Type': 'Stop',
                 'Message': msg}
        post(myobj)


def get_or_create_eventloop():
    """ Get or create an asyncio eventloop """
    try:
        return asyncio.get_event_loop()
    except RuntimeError as _ex:
        if "There is no current event loop in thread" in str(_ex):
            asyncio.set_event_loop(asyncio.new_event_loop())
            return asyncio.get_event_loop()
    return None


def camera_startup(camera):
    """ Function meant to be called at startup and sends
        camera information.
    """
    camera_info = {}
    camera_info["Type"] = 'Startup'
    camera_info["Name"] = str(camera.camera_name(0))
    camera_info["Model"] = str(camera.model)
    # camera_info["Serial"] = str(camera.serial)
    # camera_info["Manufacturer"] = str(camera.manufacturer)
    camera_info["Hardware version"] = str(camera.hardware_version)
    camera_info["Software version"] = str(camera.sw_version)
    # camera_info["HTTPS"] = str(camera.use_https)
    # camera_info["Port"] = str(camera.port)
    # camera_info["Wifi connection"] = str(camera.wifi_connection)
    # camera_info["Wifi signal"] = str(camera.wifi_signal)
    # camera_info["RTMP"] = str(camera.rtmp_enabled)
    # camera_info["RTSP"] = str(camera.rtsp_enabled)
    # camera_info["ONVIF"] = str(camera.onvif_enabled)
    camera_info["Mac_address"] = str(camera.mac_address)
    camera_info["Is doorbell"] = str(camera.is_doorbell(0))
    camera_info["AI supported"] = str(camera.ai_supported(0))
    camera_info["AI types"] = str(camera.ai_supported_types(0))
    if standalone:
        log(str(camera_info))
    else:
        post(camera_info)
    return True


def camera_init(camera) -> bool:
    """" Check requirements for the camera. """
    if not camera.rtsp_enabled:
        stop("Camera RTSP is not enabled. Please enable and restart the plugin!")
        return False

    if not camera.onvif_enabled:
        stop("Camera ONVIF is not enabled. Please enable and restart the plugin!")
        return False

    return True


def async_loop():
    """ async_loop should run forever."""
    loop = get_or_create_eventloop()
    task = reolink_run()
    loop.run_until_complete(task)
    loop.run_until_complete(asyncio.sleep(1))
    loop.close()


def get_camera_host(_camera_ipaddress, _camera_username, _camera_password, _camera_port):
    """ Get the Camera Host from Reolink API.
    camera_ipaddress is the public ipaddress for the camera.
    camera_username is the username for an admin user.
    camera_password is the passsord.
    camera_port the port the camera uses.
    """
    try:
        debug("Connect camera at: " + str(camera_ipaddress))
        camera_host = Host(_camera_ipaddress, _camera_username, _camera_password, port=_camera_port)
        return camera_host
    except ReolinkError as err:
        error("get_camera_host failed with ReolinkError: " + str(err))
        return None


def get_camera():
    try:
        camera = get_camera_host(camera_ipaddress, camera_username, camera_password, camera_port)
    except LoginError as _ex:
        delay_reconnect = increment_delay_reconnect(delay_reconnect)
        if "password wrong" in str(_ex):
            error("Failed to login - wrong password!")
            return None
        if "password wrong" in str(_ex):
            error("Failed to login - username invalid!")
            return None
        error("Login error: " + str(_ex))
        return None
    except CredentialsInvalidError as _ex:
        delay_reconnect = increment_delay_reconnect(delay_reconnect)
        error("Login failed - credentials error! " + str(_ex))
        return None
    except ReolinkTimeoutError:
        delay_reconnect = increment_delay_reconnect(delay_reconnect)
        error("Timeout error, camera unreachable!")
        return -1
    except ReolinkError as _ex:
        delay_reconnect = increment_delay_reconnect(delay_reconnect)
        error("Camera init failed! Reolinkerror: " + str(_ex))
        return -1
    except Exception as _ex:
        delay_reconnect = increment_delay_reconnect(delay_reconnect)
        error("Camera init failed, unknown error: " + str(_ex))
        return None

    if camera is None:
        error("Get camera returned None!")
        return None
    return camera


async def camera_subscribe(camera, _camhook_url) -> bool:
    """ Subsribe to events from the camera."""
    try:
        await camera.subscribe(_camhook_url, SubType.push, retry=False)
    except SubscriptionError as _ex:
        error("Camera subscriptionerror failed: " + str(_ex))
        return False
    return True


def increment_delay_reconnect(i) -> int:
    if i < 9 * 60:
        i = i + 60
    return i


async def reolink_run_init():
    global RUNNING
    delay_reconnect = 0

    while RUNNING:
        if delay_reconnect > 0:
            debug("Delay startup " + str(delay_reconnect) + " seconds!")
            await asyncio.sleep(delay_reconnect)
        camera = get_camera()
        if camera is None:
            delay_reconnect = increment_delay_reconnect(delay_reconnect)
            continue
        if camera == -1:
            return
        await camera.get_host_data()
        await camera.get_states()
        delay_reconnect = 0

        if not camera_init(camera):
            return False

        if not camera_startup(camera):
            continue

        if not await camera_subscribe(camera, webhook_url):
            continue
        return camera
    return False


async def camera_logout(camera):
    log("Camera logout!")
    try:
        if camera is not None:
            await camera.unsubscribe()
            await camera.logout()
    except SubscriptionError as _err:
        error("Camera unsubscribe failed: " + str(_err))


async def reolink_run():
    """ The main loop. """
    global RUNNING
    RUNNING = True

    while RUNNING:
        camera = await reolink_run_init()
        if camera is None:
            continue

        ticks = 0
        while RUNNING:
            ticks = ticks + 1
            if ticks > 30:
                try:
                    await camera.get_states()
                except ReolinkTimeoutError:
                    error("Timeout error, camera unreachable!")
                    break
                except Exception as _ex:
                    error("Camera update states failed: " + str(_ex))
                    break

                renewtimer = camera.renewtimer()
                if renewtimer <= 100 or not camera.subscribed(SubType.push):
                    debug("Renew camera subscription!")
                    if not await camera.renew():
                        RUNNING = await camera_subscribe(camera, webhook_url)
                ticks = 0
            await asyncio.sleep(1)

    await camera_logout(camera)


def camera_process_post_request(request):
    """Handle incoming webhook from Reolink camera for inbound messages and calls when in standalone mode."""

    # log("Received request:\n"
    #    + "Method: {}\n".format(request.method))

    try:
        length = int(request.headers.get('Content-Length', 0))
        if length > 0:
            body_raw = request.body.read(length)
        else:
            body_raw = '{}'
        # body_raw = body_raw.decode('utf-8')
    except ValueError:
        log("Error!")

    try:
        parse_result = reolink_utils.reolink_parse_soap(body_raw)
        log(parse_result)
    except Exception as _ex:
        log("Failed to parse message: " + str(_ex)
            + " Starts with: " + str(body_raw)[:10]
            + " Ends with: " + str(body_raw)[-10:])


parser = argparse.ArgumentParser()

parser.add_argument("camera_ipaddress", help="Camera ipaddress", type=str)
parser.add_argument("camera_port", help="Camera port", type=str)
parser.add_argument("camera_username", help="Camera username", type=str)
parser.add_argument("camera_password", help="Camera password", type=str)
parser.add_argument("webhook_host", help="Webhook host ipaddress", type=str)
parser.add_argument("webhook_port", help="Webhook port", type=str)
parser.add_argument("--log", help="Activate logging to /tmp/camera.log",
                    action='store_true')
parser.add_argument("--standalone", help="Run in standalone mode!", action='store_true')

args = parser.parse_args()

PRINTMODE = False
DOLOGGING = args.log
standalone = args.standalone

if standalone and not DOLOGGING:
    PRINTMODE = True
    DOLOGGING = True

camera_ipaddress = args.camera_ipaddress
camera_port = args.camera_port
camera_username = args.camera_username
camera_password = args.camera_password
webhook_host = args.webhook_host
webhook_port = args.webhook_port
webhook_url = "http://" + webhook_host + ":" + str(webhook_port)
camhook_url = "http://" + camera_ipaddress + ":" + str(camera_port)

if DOLOGGING:
    logger = logging.getLogger("Camera")
    logger.setLevel(logging.DEBUG)

    if PRINTMODE:
        handler = logging.StreamHandler(sys.stdout)
    else:
        handler = logging.handlers.TimedRotatingFileHandler(LOG_FILENAME,
                                                            when='midnight',
                                                            interval=1,
                                                            backupCount=5,
                                                            encoding=None,
                                                            delay=False,
                                                            utc=False)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(message)s')
    handler.setFormatter(formatter)

    logger.addHandler(handler)

    debug("args: " + str(args))
    debug("webhook_url: " + webhook_url)
    debug("camhook_url: " + camhook_url)

if not check_runtime():
    debug("Runtime environment not met. Terminating!")
    sys.exit()

if standalone:
    log("Running in standalone mode! Terminate by pressing ctrl-c")
    webhooks = webhook_listener.Listener(port=int(webhook_port),
                                         handlers={"POST": camera_process_post_request})
    webhooks.start()

RUNNING = True
camera_thread = threading.Thread(name="Camera thread", target=async_loop,
                                 daemon=False,
                                 args=())
camera_thread.start()

try:
    while RUNNING:
        time.sleep(5)
        if not camera_thread.is_alive():
            debug("camera_thread dead - restart in 60 seconds!")
            camera_thread.join()
            time.sleep(60)
            camera_thread = threading.Thread(name="Camera thread",
                                             target=async_loop,
                                             daemon=False,
                                             args=())
            camera_thread.start()

except KeyboardInterrupt:
    log("Keyboard interrupt!")
    if standalone:
        log("Terminating program, please wait!")

RUNNING = False
debug("Terminate processes!")
if standalone:
    webhooks.stop()

camera_thread.join()

try:
    # Wait until queue thread has exited
    while threading.active_count() > 1:
        RUNNING = False
        log("Threads still active: " + str(threading.active_count()) + ", should be 1.")
        for thread in threading.enumerate():
            if thread.name != threading.current_thread().name:
                log("'" + thread.name
                    + "' is still running, waiting otherwise Domoticz will "
                    + "abort on plugin exit.")
        time.sleep(2)
        log("Threads: " + str(threading.active_count()))
except KeyboardInterrupt:
    log("Keyboard interrupt!!")

debug("Terminated camera program!")
if standalone:
    log("Program terminated")
