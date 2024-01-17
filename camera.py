""" Camera.py is meant to be runned inside a Domoticz plugin."""
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

LOG_FILENAME = '/tmp/camera.log'

def post(msg):
    """ Post msg to the camhook_url"""
    try:
        json_object = json.dumps(msg)
        requests.post(camhook_url, json = json_object, timeout=2)
    except requests.exceptions.RequestException as _ex:
        if dologging:
            logger.debug("Post Error: %s", str(_ex))

def log(msg):
    """ Send a Log message to the server, message in msg """
    if dologging:
        logger.debug(msg)
    myobj = {'Type': 'Log',
             'Log': msg}
    post(myobj)


def error(msg):
    """ Send a Error message to the server, message in msg """
    if dologging:
        logger.debug(msg)
    myobj = {'Type': 'Log',
             'Error': msg}
    post(myobj)

def debug(msg):
    """ Send a Debug message to the server, message in msg """
    if dologging:
        logger.debug(msg)
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

def async_loop( ):
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

async def camera_subscribe(camera, _webhook_url):
    """ Subsribe to events from the camera."""
    try:
        await camera.subscribe(_webhook_url, SubType.push, retry=False)
    except SubscriptionError as _ex:
        error("Camera subscriptionerror failed: "+str(_ex))
        return False
    except Exception as _ex:
        error("Camera subscribe failed: "+str(_ex))
        if str(_ex) == "'NoneType' object is not callable":
            error("This error can only be resolved by restarting the Domoticz server!")
        return False
    return True

async def reolink_start():
    """ The main loop. """
    camera = get_camera_host(camera_ipaddress, camera_username, camera_password, camera_port)
    if camera is None:
        error("Get camera returned None!")
        return
    try:
        await camera.get_host_data()
        await camera.get_states()
    except Exception as _ex:
        error("Camera update host_data/states failed: "+str(_ex))
        if str(_ex).startswith("Login error"):
            error("Login error - this error can only be resolved by restarting "+
                  "the Camera and after that restarting the Domoticz server!")

        return

    if not camera.rtsp_enabled:
        error("Camera RTSP is not enabled. Please enable it!")
        return

    if not camera.onvif_enabled:
        error("Camera ONVIF is not enabled. Please enable it!")
        return

    log("Camera name       : " + str(camera.camera_name(0)))
    log("Camera model      : " + str(camera.model))
    log("Camera mac_address: " + str(camera.mac_address))
    log("Camera doorbell   : " + str(camera.is_doorbell(0)))

    running = True
    await camera_subscribe(camera, webhook_url)

    ticks = 0
    while running:
        if camera is None:
            error("Camera is None!")
            camera = get_camera_host(camera_ipaddress, camera_username,
                                     camera_password, camera_port)

        ticks = ticks + 1
        if ticks > 10:
            await camera.get_states()
            renewtimer = camera.renewtimer()
            if renewtimer <= 100 or not camera.subscribed(SubType.push):
                debug("Renew camera subscription!")
                if not await camera.renew():
                    running = await camera_subscribe(camera, webhook_url)
            ticks = 0
        await asyncio.sleep(1)

    log("Camera logout!")
    try:
        await camera.unsubscribe()
    except SubscriptionError as _err:
        error("Camera unsubscribe failed: "+str(_err))
    except Exception as _ex:
        error("Camera unsubscribe failed: "+str(_ex))

    await camera.logout()
    camera = None

parser = argparse.ArgumentParser()

parser.add_argument("camera_ipaddress", help="Camera ipaddress",type=str)
parser.add_argument("camera_port", help="Camera port",type=str)
parser.add_argument("camera_username", help="Camera username",type=str)
parser.add_argument("camera_password", help="Camera password",type=str)
parser.add_argument("webhook_host", help="Webhook host ipaddress",type=str)
parser.add_argument("webhook_port", help="Webhook port",type=str)
parser.add_argument("--log", help="Activate logging to /tmp/camera.log",action='store_true')

args = parser.parse_args()

dologging = args.log

camera_ipaddress = args.camera_ipaddress
camera_port = args.camera_port
camera_username = args.camera_username
camera_password = args.camera_password
webhook_host = args.webhook_host
webhook_port = args.webhook_port
webhook_url = "http://"+webhook_host+":"+str(webhook_port)
camhook_url = "http://"+webhook_host+":"+str(webhook_port)

if dologging:
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

camera_thread = threading.Thread(name="Camera thread", target=async_loop, args=())
camera_thread.start()

try:
    while True:
        time.sleep(10)
        if not camera_thread.is_alive():
            log("camera_thread dead - restart!")
            camera_thread.join()
            camera_thread = threading.Thread(name="Camera thread", target=async_loop,
                                             args=())
            camera_thread.start()

#except KeyboardInterrupt:
#    #Statements to execute upon that exception
#    log("Keyboard interrupt!")
except Exception as ex:
    error("Something else - "+str(ex))

debug("Stop camera process!")
camera_thread.join()

for thread in threading.enumerate():
    if thread.name != threading.current_thread().name:
        log("'"+thread.name+"' is running, it must be shutdown otherwise Domoticz "+
            "will abort on plugin exit.")

# Wait until queue thread has exited
log("Threads still active: "+str(threading.active_count())+", should be 1.")
while threading.active_count() > 1:
    for thread in threading.enumerate():
        if thread.name != threading.current_thread().name:
            log("'"+thread.name+"' is still running, waiting otherwise Domoticz will "+
                "abort on plugin exit.")
        time.sleep(0.5)
