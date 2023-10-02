import sys
import subprocess
import time
import webhook_listener
from queue import Queue, Empty
from threading  import Thread
from configparser import RawConfigParser
import os

def Log(msg):
    print(msg)

def Error(msg):
    print(msg)

def Debug(msg):
    print(msg)


def read_config(props_path: str) -> dict:
    """Reads in a properties file into variables.
    NB! this config file is kept out of commits with .gitignore. The structure of this file is such:
    # secrets.cfg
        [camera]
        ip={ip_address}
        username={username}
        password={password}
    """
    config = RawConfigParser()
    assert os.path.exists(props_path), f"Path does not exist: {props_path}"
    config.read(props_path)
    return config    


def process_post_request(request, *args, **kwargs):
    """Handle incoming webhook from Reolink for inbound messages and calls."""

#    Log("Received request:\n"
#        + "Method: {}\n".format(request.method))

    body_raw = ""
    try:
        length = int(request.headers.get('Content-Length',0))
        if length > 0:
            body_raw = request.body.read(length)
        else:
            body_raw = '{}'

        body_raw = body_raw.decode('utf-8')

        if body_raw.startswith("<?xml"):
            Log("Message from camera!")
        else:
            Log(body_raw)            
        
    except:
        print("Error!")

if __name__ == "__main__":
    config = read_config('./secrets.cfg')

    camera_ipaddress = config.get('camera', 'camera_ipaddress')
    camera_port = config.get('camera', 'camera_port')
    camera_username = config.get('camera', 'camera_username')
    camera_password = config.get('camera', 'camera_password')
    webhook_host = config.get('camera', 'webhook_host')
    webhook_port = config.get('camera', 'webhook_port')

    print("Webhook form camera.py init...")
    webhooks = webhook_listener.Listener(port=8989, handlers={"POST": process_post_request})
    webhooks.start()    
    
    process = subprocess.Popen(["python", "camera.py",
                                camera_ipaddress, camera_port,                            
                                camera_username, camera_password,
                                webhook_host, webhook_port])

    try:
        while process.poll() is None:
            time.sleep(30)

    except KeyboardInterrupt:
        #Statements to execute upon that exception
        Log("Test - Keyboard interrupt!")
    else:
        Error("Test - Something else!")


    process.terminate()
    while process.poll() is None:
        time.sleep(1)
        Log("Test - wait!")

    webhooks.stop()
    Log("Returncode: "+str(process.returncode))
    Log("Test - exit!")
