"""
Camera.py is primarly meant to be runned inside a Domoticz plugin.

If given --standalone it can be run in a standalone mode, meant
for debugging.

"""
import time
import threading
import json
import asyncio
import logging
import logging.handlers
import argparse
from reolink_aio.api import Host
from reolink_aio.enums import SubType
from reolink_aio.exceptions import ReolinkError, SubscriptionError
import requests
import webhook_listener
import reolink_utils

LOG_FILENAME = '/tmp/camera.log'
RUNNING = False


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
    else:
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
    if not camera.rtsp_enabled:
        error("Camera RTSP is not enabled. Please enable it!")
        return False

    if not camera.onvif_enabled:
        error("Camera ONVIF is not enabled. Please enable it!")
        return False

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


def async_loop():
    """ async_loop should run forever."""
    loop = get_or_create_eventloop()
    task = reolink_start()
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
        debug("Connect camera at: "+str(camera_ipaddress))
        camera_host = Host(_camera_ipaddress, _camera_username, _camera_password, port=_camera_port)
        return camera_host
    except ReolinkError as err:
        error("get_camera_host failed with ReolinkError: "+str(err))
        return None


async def camera_subscribe(camera, _camhook_url):
    """ Subsribe to events from the camera."""
    try:
        await camera.subscribe(_camhook_url, SubType.push, retry=False)
    except SubscriptionError as _ex:
        error("Camera subscriptionerror failed: "+str(_ex))
        return False
    return True


def get_camera():
    camera = get_camera_host(camera_ipaddress, camera_username, camera_password, camera_port)
    if camera is None:
        error("Get camera returned None!")
        return
    return camera


async def reolink_start():
    """ The main loop. """
    camera = get_camera()

    try:
        await camera.get_host_data()
        await camera.get_states()
    except Exception as _ex:
        error("Camera update host_data/states failed: "+str(_ex))
        if str(_ex).startswith("Login error"):
            error("Login error - this error can only be resolved by restarting " +
                  "the Camera and after that restarting the Domoticz server!")
        return

    if not camera_startup(camera):
        return

    # log("Camera name       : " + str(camera.camera_name(0)))
    # log("Camera model      : " + str(camera.model))
    # log("Camera mac_address: " + str(camera.mac_address))
    # log("Camera doorbell   : " + str(camera.is_doorbell(0)))

    global RUNNING
    RUNNING = True
    await camera_subscribe(camera, webhook_url)

    ticks = 0
    while RUNNING:

        # if camera is None:
        #    error("Camera is None!")
        #    camera = get_camera_host(camera_ipaddress, camera_username,
        #                             camera_password, camera_port)

        ticks = ticks + 1
        if ticks > 10:
            await camera.get_states()
            renewtimer = camera.renewtimer()
            if renewtimer <= 100 or not camera.subscribed(SubType.push):
                debug("Renew camera subscription!")
                if not await camera.renew():
                    RUNNING = await camera_subscribe(camera, webhook_url)
            ticks = 0
        await asyncio.sleep(1)

    log("Camera logout!")
    try:
        await camera.unsubscribe()
    except SubscriptionError as _err:
        error("Camera unsubscribe failed: "+str(_err))

    await camera.logout()


def camera_process_post_request(request):
    """Handle incoming webhook from Reolink camera for inbound messages and calls."""

    # log("Received request:\n"
    #    + "Method: {}\n".format(request.method))

    try:
        length = int(request.headers.get('Content-Length', 0))
        if length > 0:
            body_raw = request.body.read(length)
        else:
            body_raw = '{}'

        body_raw = body_raw.decode('utf-8')
    except ValueError:
        log("Error!")

    try:
        parse_result = reolink_utils.reolink_parse_soap(body_raw)
        log(parse_result)
    except Exception as _ex:
        log("Failed to parse message: " + str(_ex) +
            " Starts with: " + str(body_raw)[:10] +
            " Ends with: " + str(body_raw)[-10:])


parser = argparse.ArgumentParser()

parser.add_argument("camera_ipaddress", help="Camera ipaddress", type=str)
parser.add_argument("camera_port", help="Camera port", type=str)
parser.add_argument("camera_username", help="Camera username", type=str)
parser.add_argument("camera_password", help="Camera password", type=str)
parser.add_argument("webhook_host", help="Webhook host ipaddress", type=str)
parser.add_argument("webhook_port", help="Webhook port", type=str)
parser.add_argument("--log", help="Activate logging to /tmp/camera.log", action='store_true')
parser.add_argument("--standalone", help="Run in standalone mode!", action='store_true')

args = parser.parse_args()

DOLOGGING = args.log
standalone = args.standalone

if standalone:
    DOLOGGING = True

camera_ipaddress = args.camera_ipaddress
camera_port = args.camera_port
camera_username = args.camera_username
camera_password = args.camera_password
webhook_host = args.webhook_host
webhook_port = args.webhook_port
webhook_url = "http://" + webhook_host+":" + str(webhook_port)
camhook_url = "http://" + camera_ipaddress+":" + str(camera_port)

if DOLOGGING:
    logger = logging.getLogger("Camera")
    logger.setLevel(logging.DEBUG)

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

    debug("args: "+str(args))
    debug("webhook_url: "+webhook_url)
    debug("camhook_url: "+camhook_url)


if standalone:
    print("Running in standalone mode! Terminate by pressing ctrl-c")
    log("Running in standalone mode!")
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
        time.sleep(1)
        if not camera_thread.is_alive():
            log("camera_thread dead - restart!")
            camera_thread.join()
            camera_thread = threading.Thread(name="Camera thread",
                                             target=async_loop,
                                             daemon=False,
                                             args=())
            camera_thread.start()

except KeyboardInterrupt:
    log("Keyboard interrupt!")
    if standalone:
        print("Terminating program, please wait!")

RUNNING = False
debug("Terminate processes!")
if standalone:
    webhooks.stop()

camera_thread.join()

try:
    # Wait until queue thread has exited
    while threading.active_count() > 1:
        RUNNING = False
        log("Threads still active: "+str(threading.active_count())+", should be 1.")
        for thread in threading.enumerate():
            if thread.name != threading.current_thread().name:
                log("'" + thread.name +
                    "' is still running, waiting otherwise Domoticz will " +
                    "abort on plugin exit.")
        time.sleep(2)
        log("Threads: " + str(threading.active_count()))
except KeyboardInterrupt:
    log("Keyboard interrupt!!")

debug("Terminated camera program!")
if standalone:
    print("Program terminated")
