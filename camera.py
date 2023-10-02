import sys
import time
import threading
import requests
import json
import asyncio
import logging
import logging.handlers
from reolink_aio.api import Host
from reolink_aio.enums import SubType
from reolink_aio.exceptions import ReolinkError, SubscriptionError
import argparse

running = True
stop_plugin = False
LOG_FILENAME = '/tmp/camera.log'

def Post(msg):
    try:
        json_object = json.dumps(msg)
        x = requests.post(camhook_url, json = json_object)
    except Exception as Ex:
        if dologging:
            logger.debug("Post Error: "+str(Ex))
    
def Log(msg):
    if dologging:
        logger.debug(msg)
    myobj = {'Log': msg}
    Post(myobj)

def Error(msg):
    if dologging:
        logger.debug(msg)
    myobj = {'Error': msg}
    Post(myobj)    

def Debug(msg):
    if dologging:
        logger.debug(msg)
    myobj = {'Debug': msg}
    Post(myobj)        

def get_or_create_eventloop():
    try:
        return asyncio.get_event_loop()
    except RuntimeError as ex:
        if "There is no current event loop in thread" in str(ex):
            asyncio.set_event_loop(asyncio.new_event_loop())
            return asyncio.get_event_loop()
    return None    
    
def async_loop( ):
    loop = get_or_create_eventloop()
    task = reolink_start()
    loop.run_until_complete(task)
    loop.run_until_complete(asyncio.sleep(1))
    loop.close()

def GetCameraHost(camera_ipaddress, camera_username, camera_password, camera_port):
    try:
        Debug("Connect camera at: "+str(camera_ipaddress))
        camera_host = Host(camera_ipaddress, camera_username, camera_password, port=camera_port)
        return camera_host
    except ReolinkError as err:
        Error("GetCameraHost failed with ReolinkError: "+str(err))
        return None
    except Exception as ex:
        Error("GetCameraHost failed with exception: "+str(ex))
        return None

async def camera_subscribe(camera, webhook_url):
    try:
        await camera.subscribe(webhook_url, SubType.push, retry=False)
    except SubscriptionError as ex:
        Error("Camera subscriptionerror failed: "+str(ex))
        running = False
    except Exception as ex:
        Error("Camera subscribe failed: "+str(ex))
        if str(ex) == "'NoneType' object is not callable":
            Error("This error can only be resolved by restarting the Domoticz server!")
            stop_plugin = True
        running = False

async def reolink_start():
    camera = GetCameraHost(camera_ipaddress, camera_username, camera_password, camera_port)
    if camera is None:
        Error("Get camera returned None!")
        return
    try:
        await camera.get_host_data()
        await camera.get_states()
    except Exception as ex:
        Error("Camera update host_data/states failed: "+str(ex))
        if str(ex).startswith("Login error"):
            Error("Login error - this error can only be resolved by restarting the Camera and after that restarting the Domoticz server!")
            stop_plugin = True
        return

    if not camera.rtsp_enabled:
        Error("Camera RTSP is not enabled. Please enable it!")
        return    
    
    if not camera.onvif_enabled:
        Error("Camera ONVIF is not enabled. Please enable it!")
        return

    Log("Camera name       : " + str(camera.camera_name(0)))
    Log("Camera model      : " + str(camera.model))
    Log("Camera mac_address: " + str(camera.mac_address))
    Log("Camera doorbell   : " + str(camera.is_doorbell(0)))

    
    await camera_subscribe(camera, webhook_url)

    ticks = 0
    while running:
        if camera is None:
            Error("Camera is None!")
            camera = GetCameraHost(camera_ipaddress, camera_username, camera_password, camera_port)

        ticks = ticks + 1
        if ticks > 10:
            await camera.get_states()
            renewtimer = camera.renewtimer()
            if renewtimer <= 100 or not camera.subscribed(SubType.push):
                Debug("Renew camera subscription!")
                if not await camera.renew():
                    await camera_subscribe(camera, webhook_url)
            ticks = 0
        await asyncio.sleep(1)

    Log("Camera logout!")
    try:
        await camera.unsubscribe()
    except SubscriptionError as ex:
        Error("Camera unsubscribe failed: "+str(ex))
    except Exception as ex:
        Error("Camera unsubscribe failed: "+str(ex))        
        
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

    Debug("args: "+str(args))
    Debug("webhook_url: "+webhook_url)
    Debug("camhook_url: "+camhook_url)

camera_thread = threading.Thread(name="Camera thread", target=async_loop, args=())
camera_thread.start()

try:
    while True:
        time.sleep(10)
        if not camera_thread.is_alive():
            running = False
            Log("camera_thread dead - restart!")
            camera_thread.join()
            camera_thread = threading.Thread(name="Camera thread", target=async_loop,
                                             args=())
            camera_thread.start()
            running = True        

#except KeyboardInterrupt:
#    #Statements to execute upon that exception
#    Log("Keyboard interrupt!")
except ex:
    Error("Something else!")

Debug("Stop camera process!")
running = False
camera_thread.join()

for thread in threading.enumerate():
    if thread.name != threading.current_thread().name:
        Log("'"+thread.name+"' is running, it must be shutdown otherwise Domoticz will abort on plugin exit.")

# Wait until queue thread has exited
Log("Threads still active: "+str(threading.active_count())+", should be 1.")
while threading.active_count() > 1:
    for thread in threading.enumerate():
        if thread.name != threading.current_thread().name:
            Log("'"+thread.name+"' is still running, waiting otherwise Domoticz will abort on plugin exit.")
        time.sleep(0.5)
            
