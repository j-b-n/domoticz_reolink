"""
<plugin key="Reolink" name="Reolink camera" author="jbn" version="0.0.2" externallink="https://github.com/j-b-n/domoticz_reolink">
    <description>
        <br/>
        <h2>Reolink Camera Plugin</h2><br/>
        <ul style="list-style-type:square">
            <li>Doorbell - Activated when someone press the doorbell.</li>
            <li>Motion - Motion sensor activated when the camera detects motion.</li>
            <li>Person - Motion sensor activated when the camera detects a person.</li>
        </ul>
        <h2>Requirements</h2><br/>
        <ul style="list-style-type:square">
            <li>Require python package <a href="https://github.com/starkillerOG/reolink_aio"> reolink_aio </a> by starkillOG.</li>
            <li>The camera need to have ONVIF enabled. See
            <a href=
"https://support.reolink.com/hc/en-us/articles/900004435763-How-to-Set-up-Reolink-Ports-Settings-via-Reolink-Client-New-Client">
Reolink documation</a>
             for support. Remeber to restart the camera after the change!</li>
        </ul>
        <h2>Parameters</h2><br/>
        <ul style="list-style-type:square">
            <li>Camera IP address(es) - One or more camera IP addresses separated by semicolons (e.g. 10.0.0.9;10.0.0.10). Must be reachable by the Domoticz server.</li>
            <li>Camera Username(s) - Username(s) for the camera(s), semicolon-separated. If only one value is given it is used for all cameras.</li>
            <li>Camera Password(s) - Password(s) for the camera(s), semicolon-separated. If only one value is given it is used for all cameras.</li>
            <li>Camera Port(s) - Port(s) for the camera(s), semicolon-separated. If only one value is given it is used for all cameras.</li>
            <li>Domoticz ipaddress (for camera) - The ipaddress of the Domoticz server as seen from the camera.
                Used as the ONVIF webhook callback address. Must be reachable by the camera.</li>
            <li>Webhook port - A free TCP port on the Domoticz server. The plugin listens on all interfaces (0.0.0.0)
                on this port to receive ONVIF events from the camera. Must not be in use by another service.</li>
            <li>Motion reset time - The camera sends an off-signal directly after the on-signal. Use Off for default behavior.
                Otherwise the off signal will be delayed the configured number of seconds.</li>
           <li>Debug - Debug setting.</li>
        </ul>
        <br/>
    </description>

    <params>
       <param field="Address" label="Camera IP address(es)" width="300px" required="true"/>
       <param field="Username" label="Camera Username(s)" width="300px" required="true" default="admin"/>
       <param field="Password" label="Camera Password(s)" width="300px" required="true" default="" password="true"/>
       <param field="Port" label="Camera Port(s)" width="200px" required="false" default="80"/>
       <param field="Mode1" label="Domoticz ipaddress (for camera)" width="200px" required="true" default=""/>
       <param field="Mode2" label="Webhook Port" width="200px" required="true" default="8989"/>
       <param field="Mode3" label="Motion reset time" width="150px" required="true">
        <options>
           <option label="Off" value=0/>
           <option label="5 seconds" value=5/>
           <option label="10 seconds" value=10 default = "true"/>
           <option label="30 seconds" value=30 />
           <option label="60 seconds" value=60/>
           <option label="2 minutes" value=120/>
        </options>
       </param>
       <param field="Mode6" label="Debug" width="150px">
             <options>
                <option label="None" value="0"  default="true" />
                <option label="Python Only" value="2"/>
                <option label="Basic Debugging" value="62"/>
                <option label="Basic+Messages" value="126"/>
                <option label="Connections Only" value="16"/>
                <option label="Connections+Python" value="18"/>
                <option label="Connections+Queue" value="144"/>
                <option label="All" value="-1"/>
            </options>
        </param>
    </params>
</plugin>
"""
##
# Plugin
##

import threading
import time
import socket
from datetime import datetime, timedelta
import json
import os
import sys
import asyncio
import requests
from importlib.metadata import version
import reolink_utils
import DomoticzEx as Domoticz
from reolink_aio.api import Host
from reolink_aio.enums import SubType
from reolink_aio.exceptions import (ReolinkError, SubscriptionError,
                                    ReolinkTimeoutError, CredentialsInvalidError, LoginError)


def check_runtime():
    """ Check the current runtime so it complies with the requirements."""
    if sys.version_info < (3, 11):
        Domoticz.Error("Python >= 3.11 is required, running: " + sys.version)
        return False

    req_version = '0.19.0'
    _version = str(version('reolink_aio'))
    if _version == req_version:
        Domoticz.Debug("Version: reolink_aio " + _version + " == " + req_version)
    else:
        Domoticz.Error("Version: reolink_aio " + _version + " != " + req_version)

    return True


class CameraProcess:
    """Handles the camera connection and ONVIF event subscription."""

    def __init__(self, camera_ipaddress, camera_port, camera_username, camera_password,
                 webhook_host, webhook_port, device_prefix=""):
        self.camera_ipaddress = camera_ipaddress
        self.camera_port = camera_port
        self.camera_username = camera_username
        self.camera_password = camera_password
        self.webhook_host = webhook_host
        self.webhook_port = webhook_port
        self.device_prefix = device_prefix
        # Internal IPC: always post to loopback — Listen() binds to 0.0.0.0
        self.webhook_url = "http://127.0.0.1:" + str(webhook_port)
        # External URL given to the camera for ONVIF callbacks
        self.camera_webhook_url = "http://" + webhook_host + ":" + str(webhook_port)
        self.RUNNING = False
        self._stop_event = threading.Event()
        self.delay_reconnect = 0
        self._camera = None

    def stop(self):
        """Signal the camera process to stop."""
        self.RUNNING = False
        self._stop_event.set()

    def post(self, msg):
        """ Post msg to the webhook_url"""
        try:
            json_object = json.dumps(msg)
            requests.post(self.webhook_url, json=json_object, timeout=5)
        except requests.exceptions.RequestException as _ex:
            Domoticz.Error("Webhook post to " + self.webhook_url + " failed: " + str(_ex))

    def log(self, msg):
        """ Send a Log message to the server, message in msg """
        myobj = {'Type': 'Log',
                 'Log': msg}
        self.post(myobj)

    def error(self, msg):
        """ Send an Error message to the server, message in msg """
        myobj = {'Type': 'Log',
                 'Error': msg}
        self.post(myobj)

    def debug(self, msg):
        """ Send a Debug message to the server, message in msg """
        myobj = {'Type': 'Log',
                 'Debug': msg}
        self.post(myobj)

    def stop_msg(self, msg):
        """ Send a Stop message to the server, message in msg """
        myobj = {'Type': 'Stop',
                 'Message': msg}
        self.post(myobj)

    def get_or_create_eventloop(self):
        """ Get or create an asyncio eventloop """
        try:
            return asyncio.get_event_loop()
        except RuntimeError as _ex:
            if "There is no current event loop in thread" in str(_ex):
                asyncio.set_event_loop(asyncio.new_event_loop())
                return asyncio.get_event_loop()
        return None

    def camera_startup(self, camera):
        """ Send camera information at startup."""
        camera_info = {}
        camera_info["Type"] = 'Startup'
        camera_info["Prefix"] = self.device_prefix
        camera_info["Name"] = str(camera.camera_name(0))
        camera_info["Model"] = str(camera.model)
        camera_info["Hardware version"] = str(camera.hardware_version)
        camera_info["Software version"] = str(camera.sw_version)
        camera_info["Mac_address"] = str(camera.mac_address)
        camera_info["Is doorbell"] = str(camera.is_doorbell(0))
        camera_info["AI supported"] = str(camera.ai_supported(0))
        camera_info["AI types"] = str(camera.ai_supported_types(0))
        self.post(camera_info)
        return True

    def camera_init(self, camera) -> bool:
        """Check camera settings. ONVIF is only required for the fallback subscription."""
        if not camera.onvif_enabled:
            self.debug("ONVIF is not enabled on the camera. Baichuan TCP events will be used as primary source.")
        return True

    def baichuan_event_callback(self):
        """Called by the Baichuan TCP event system on motion/AI/Visitor events."""
        if self._camera is None:
            return
        event = {
            "Type": "Event",
            "Prefix": self.device_prefix,
            "Motion": self._camera.motion_detected(0),
            "Visitor": self._camera.visitor_detected(0),
            "PeopleDetect": self._camera.ai_detected(0, "people"),
            "VehicleDetect": self._camera.ai_detected(0, "vehicle"),
            "Dog_cat": self._camera.ai_detected(0, "dog_cat"),
            "Face": self._camera.ai_detected(0, "face"),
        }
        # requests.post is blocking; run in a thread to avoid stalling the asyncio event loop
        threading.Thread(target=self.post, args=(event,), daemon=True).start()

    def get_camera_host(self, _camera_ipaddress, _camera_username, _camera_password, _camera_port):
        """ Get the Camera Host from Reolink API."""
        try:
            self.log("Connecting to camera at " + str(_camera_ipaddress) + ":" + str(_camera_port))
            camera_host = Host(_camera_ipaddress, _camera_username, _camera_password, port=_camera_port)
            return camera_host
        except ReolinkError as err:
            self.error("get_camera_host failed with ReolinkError: " + str(err))
            return None

    def get_camera(self):
        try:
            camera = self.get_camera_host(self.camera_ipaddress, self.camera_username,
                                          self.camera_password, self.camera_port)
        except LoginError as _ex:
            self.delay_reconnect = self.increment_delay_reconnect(self.delay_reconnect)
            if "password wrong" in str(_ex):
                self.error("Failed to login - wrong password!")
                return None
            if "password wrong" in str(_ex):
                self.error("Failed to login - username invalid!")
                return None
            self.error("Login error: " + str(_ex))
            return None
        except CredentialsInvalidError as _ex:
            self.delay_reconnect = self.increment_delay_reconnect(self.delay_reconnect)
            self.error("Login failed - credentials error! " + str(_ex))
            return None
        except ReolinkTimeoutError:
            self.delay_reconnect = self.increment_delay_reconnect(self.delay_reconnect)
            self.error("Timeout error, camera unreachable!")
            return -1
        except ReolinkError as _ex:
            self.delay_reconnect = self.increment_delay_reconnect(self.delay_reconnect)
            self.error("Camera init failed! Reolinkerror: " + str(_ex))
            return -1
        except Exception as _ex:
            self.delay_reconnect = self.increment_delay_reconnect(self.delay_reconnect)
            self.error("Camera init failed, unknown error: " + str(_ex))
            return None

        if camera is None:
            self.error("Get camera returned None!")
            return None
        return camera

    async def camera_subscribe(self, camera, _camhook_url) -> bool:
        """ Subscribe to events from the camera."""
        try:
            await camera.subscribe(_camhook_url, SubType.push, retry=False)
        except SubscriptionError as _ex:
            self.error("Camera subscriptionerror failed: " + str(_ex))
            return False
        return True

    def increment_delay_reconnect(self, i) -> int:
        if i < 9 * 60:
            i = i + 60
        return i

    async def reolink_run_init(self):
        while self.RUNNING:
            if self.delay_reconnect > 0:
                self.debug("Delay startup " + str(self.delay_reconnect) + " seconds!")
                await asyncio.sleep(self.delay_reconnect)
            camera = self.get_camera()
            if camera is None:
                self.delay_reconnect = self.increment_delay_reconnect(self.delay_reconnect)
                continue
            if camera == -1:
                return None
            self.log("Fetching camera data from " + str(self.camera_ipaddress) + "...")
            try:
                await camera.get_host_data()
                await camera.get_states()
            except ReolinkTimeoutError:
                self.delay_reconnect = self.increment_delay_reconnect(self.delay_reconnect)
                self.error("Timeout fetching camera data - camera unreachable!")
                continue
            except ReolinkError as _ex:
                self.delay_reconnect = self.increment_delay_reconnect(self.delay_reconnect)
                self.error("Failed to fetch camera data: " + str(_ex))
                continue
            except Exception as _ex:
                self.delay_reconnect = self.increment_delay_reconnect(self.delay_reconnect)
                self.error("Unexpected error fetching camera data: " + str(_ex))
                continue
            self.delay_reconnect = 0

            if not self.camera_init(camera):
                return False

            if not self.camera_startup(camera):
                continue

            # Primary: subscribe to Baichuan TCP push events
            self._camera = camera
            baichuan_ok = False
            try:
                await camera.baichuan.subscribe_events()
                camera.baichuan.register_callback(
                    "domoticz_plugin",
                    self.baichuan_event_callback,
                    cmd_id=33,   # AlarmEvent: motion/AI/visitor
                    channel=0
                )
                baichuan_ok = True
            except Exception as _ex:
                self.error("Baichuan subscription failed: " + str(_ex))

            # Fallback: ONVIF webhook subscription (only if ONVIF is enabled)
            onvif_ok = False
            if camera.onvif_enabled:
                onvif_ok = await self.camera_subscribe(camera, self.camera_webhook_url)
                if not onvif_ok:
                    self.debug("ONVIF subscription failed, relying on Baichuan only")

            self.log(
                "Connected to '" + str(camera.camera_name(0)) + "' (" + str(camera.model) + ")"
                + " | Baichuan: " + ("OK" if baichuan_ok else "FAILED")
                + " | ONVIF: " + ("OK" if onvif_ok else ("disabled" if not camera.onvif_enabled else "FAILED"))
            )

            return camera
        return False

    async def camera_logout(self, camera):
        self.log("Camera logout!")
        self._camera = None
        try:
            if camera is not None:
                camera.baichuan.unregister_callback("domoticz_plugin")
                if camera.baichuan.session_active:
                    await camera.baichuan.unsubscribe_events()
                await camera.unsubscribe()
                await camera.logout()
        except SubscriptionError as _err:
            self.error("Camera unsubscribe failed: " + str(_err))

    async def reolink_run(self):
        """ The main async loop. """
        self.RUNNING = True

        while self.RUNNING:
            camera = await self.reolink_run_init()
            if camera is None:
                continue

            ticks = 0
            while self.RUNNING:
                ticks = ticks + 1
                if ticks > 30:
                    try:
                        await camera.get_states()
                    except ReolinkTimeoutError:
                        self.error("Timeout error, camera unreachable!")
                        break
                    except Exception as _ex:
                        self.error("Camera update states failed: " + str(_ex))
                        break

                    # Baichuan: keepalive check
                    try:
                        await camera.baichuan.check_subscribe_events()
                    except Exception as _ex:
                        self.error("Baichuan keepalive failed: " + str(_ex))

                    # ONVIF fallback: renew subscription when needed
                    if camera.onvif_enabled:
                        renewtimer = camera.renewtimer()
                        if renewtimer <= 100 or not camera.subscribed(SubType.push):
                            self.debug("Renew ONVIF subscription!")
                            if not await camera.renew():
                                await self.camera_subscribe(camera, self.camera_webhook_url)
                    ticks = 0
                await asyncio.sleep(1)

        await self.camera_logout(camera)

    def async_loop(self):
        """ async_loop should run forever."""
        loop = self.get_or_create_eventloop()
        loop.run_until_complete(self.reolink_run())
        loop.run_until_complete(asyncio.sleep(1))
        loop.close()

    def run(self):
        """Run the camera logic. Blocks until the camera process stops."""
        self.RUNNING = True
        self.async_loop()


class BasePlugin:

    CAMERADEVICES = {"Doorbell": 1, "Motion": 2, "Person": 3, "Vehicle": 4, "Animal": 5, "Face": 6}
    DEVICENAME = {"Doorbell": "Doorbell", "Motion": "Motion", "People": "Person", "Person": "Person",
                  "Vehicle": "Vehicle", "Dog_cat": "Animal", "Face": "Face", "Animal": "Animal"}
    RULES_DEVICE_MAP = {"Motion": "Motion", "Visitor": "Doorbell", "PeopleDetect": "Person", "Dog_cat": "Animal", "Animal": "Animal", "VehicleDetect": "Vehicle", "Face": "Face"}
    THREADDEVICES = ["Motion", "Person", "Animal", "Vehicle"]  # Create an "off" thread for these devices!
    threads = {}

    def __init__(self):
        self.stop_plugin = False
        self.running = True

        self.webhook_host = ""
        self.webhook_port = 0
        self.motion_resettime = 0

        self.camera_configs = []       # list of (ip, port, username, password, prefix)
        self.camera_ip_to_prefix = {}  # camera IP -> device prefix (for ONVIF routing)
        self.camera_processes = []     # one CameraProcess per camera
        self.camera_threads = []       # one thread per camera

        self.task = None
        self._stop_event = threading.Event()

    def onStart(self):
        global _plugin

        if Parameters["Mode6"] != "0":
            Domoticz.Debugging(int(Parameters["Mode6"]))
            Domoticz.Debug("onStart called")

        self.webhook_host = Parameters["Mode1"]
        self.webhook_port = Parameters["Mode2"]
        self.motion_resettime = Parameters["Mode3"]

        if self.webhook_port is None or int(self.webhook_port) < 1000:
            Domoticz.Error("Webhook port must be an integer and have a value above 1000!")
            self.running = False
            return

        # Parse semicolon-separated camera parameters
        addresses = [a.strip() for a in Parameters["Address"].split(';') if a.strip()]
        usernames_raw = [u.strip() for u in Parameters["Username"].split(';') if u.strip()]
        passwords_raw = [p.strip() for p in Parameters["Password"].split(';') if p.strip()]
        ports_raw = [p.strip() for p in Parameters["Port"].split(';') if p.strip()]

        n = len(addresses)
        if n == 0:
            Domoticz.Error("No camera IP address configured!")
            self.running = False
            return

        # If fewer usernames/passwords/ports than cameras, use the first value for all
        usernames = usernames_raw if len(usernames_raw) >= n else [usernames_raw[0]] * n
        passwords = passwords_raw if len(passwords_raw) >= n else [passwords_raw[0]] * n
        ports = ports_raw if len(ports_raw) >= n else [ports_raw[0]] * n

        multi_camera = (n > 1)
        self.camera_configs = []
        self.camera_ip_to_prefix = {}
        for i, addr in enumerate(addresses):
            prefix = ("Cam" + str(i + 1) + " ") if multi_camera else ""
            self.camera_configs.append((addr, ports[i], usernames[i], passwords[i], prefix))
            self.camera_ip_to_prefix[addr] = prefix

        Domoticz.Status("Configuring " + str(n) + " camera(s): " + ", ".join(addresses))
        Domoticz.Heartbeat(30)

        ##
        # Create webhook listener (binds to 0.0.0.0)
        ##
        self.httpClientConn = Domoticz.Connection(Name="Camera webhook", Transport="TCP/IP", Protocol="HTTP",
                                                  Port=self.webhook_port)
        self.httpClientConn.Listen()
        self.camera_processes = [None] * n
        self.camera_threads = []
        for i in range(n):
            t = threading.Thread(name="Camera thread " + str(i + 1),
                                 target=BasePlugin.camera_loop, args=(self, i))
            self.camera_threads.append(t)
            t.start()
            if i < n - 1:
                time.sleep(0.5)  # stagger starts to avoid webhook race at startup

    def camera_startup(self, camera_info):
        ##
        # Create devices if they are not created
        ##
        prefix = camera_info.get("Prefix", "")

        supported = camera_info["AI types"].strip('][').replace("'", '').split(', ')
        supported.append('motion')
        supported = [s.strip().capitalize() for s in supported]

        if 'Is doorbell' in camera_info and str(camera_info['Is doorbell']) == 'True':
            supported.append('Doorbell')

        for _device in supported:
            if _device not in self.DEVICENAME:
                Domoticz.Debug(f"Unknown device type: {_device}, skipping device creation")
                continue
            base_name = self.DEVICENAME[_device]
            device_name = prefix + base_name
            if device_name not in Devices:
                create_device(device_name, self.CAMERADEVICES[base_name])

    def camera_loop(self, camera_index=0):
        (cam_ip, cam_port, cam_user, cam_pass, cam_prefix) = self.camera_configs[camera_index]
        try:
            if not check_runtime():
                Domoticz.Error("Runtime environment not met. Terminating camera!")
                return

            # Wait for Domoticz to finish binding the webhook port after onStart() returns.
            # Poll 127.0.0.1 (Listen binds to 0.0.0.0, always reachable locally).
            deadline = time.time() + 30
            while time.time() < deadline:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(1)
                    if sock.connect_ex(('127.0.0.1', int(self.webhook_port))) == 0:
                        break
                time.sleep(0.5)
            else:
                Domoticz.Error("Webhook port " + str(self.webhook_port)
                               + " not available after 30 seconds - aborting!")
                return

            while True:
                if self.stop_plugin:
                    break

                cam = CameraProcess(
                    cam_ip, cam_port, cam_user, cam_pass,
                    self.webhook_host, self.webhook_port, cam_prefix
                )
                self.camera_processes[camera_index] = cam
                cam.run()

                if self.stop_plugin:
                    break

                Domoticz.Error("Camera " + cam_ip + " process ended unexpectedly. Restarting in 15 seconds!")
                if self._stop_event.wait(timeout=15):
                    break
        except Exception as err:
            Domoticz.Error("camera_loop error for " + cam_ip + ": " + str(err))

        Domoticz.Debug("Camera loop for " + cam_ip + " terminated!")

    def onStop(self):
        self.running = False
        self.stop_plugin = True
        self._stop_event.set()

        for proc in self.camera_processes:
            if proc is not None:
                proc.stop()

        # Cancel any pending motion-reset timer threads
        for device, thread in list(self.threads.items()):
            if thread is not None and thread.is_alive():
                thread.cancel()

        for t in self.camera_threads:
            t.join(timeout=30)
            if t.is_alive():
                Domoticz.Error("Camera thread '" + t.name + "' did not stop within timeout!")

        for thread in threading.enumerate():
            if thread.name != threading.current_thread().name:
                Domoticz.Log("'" + thread.name
                             + "' is running, it must be shutdown otherwise Domoticz will abort on plugin exit.")

        # Wait until queue thread has exited
        Domoticz.Log("Threads still active: " + str(threading.active_count()) + ", should be 1.")
        while threading.active_count() > 1:
            for thread in threading.enumerate():
                if thread.name != threading.current_thread().name:
                    Domoticz.Log("'" + thread.name
                                 + "' is still running, waiting otherwise Domoticz will abort on plugin exit.")
            time.sleep(0.5)

    def onConnect(self, Connection, Status, Description):
        if Status == 0:
            Domoticz.Debug("Incoming connection from: " + Connection.Address + ":" + Connection.Port)
        else:
            Domoticz.Error("Webhook listen failed on " + Connection.Address + ":" + Connection.Port
                           + " (Status " + str(Status) + "): " + Description)
        Domoticz.Debug(str(Connection))

    def switch_off(self, device):
        Domoticz.Log("Send Off to " + device)
        if device.endswith("Doorbell"):
            sval_off = 0
        else:
            sval_off = "Off"
        update_device(device, Unit=1, sValue=sval_off, nValue=0)
        self.threads[device] = None

    def start_thread(self, device):
        Domoticz.Debug("Start thread for device " + device
                       + " send off in " + str(self.motion_resettime)
                       + " seconds")
        if device in self.threads:
            if self.threads[device] is not None:
                if self.threads[device].is_alive():
                    # Domoticz.Error("Device thread for " + device + " is alive! Cancel old thread and start new one!")
                    self.threads[device].cancel()
                    time.sleep(0.1)
                    while self.threads[device].is_alive():
                        Domoticz.Error("Device thread for " + device + " is STILL alive! Cancel!!")
                        self.threads[device].cancel()
                        time.sleep(0.1)

        t = threading.Timer(int(self.motion_resettime), self.switch_off, [device])
        t.start()
        self.threads[device] = t

    def write_debug_file(self, device_name, state, data):
        try:
            if state == "fail":
                state = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            file_path = "/tmp/" + device_name + "_" + state + ".xml"
            file_size = os.path.getsize(file_path)
            if file_size < 5000:
                with open(file_path, "wb") as binary_file:
                    binary_file.write(data)
        except FileNotFoundError:
            # Domoticz.Error("File not found: " + file_path)
            with open(file_path, "wb") as binary_file:
                binary_file.write(data)
        except OSError:
            Domoticz.Error("OS error occurred: " + file_path)

    def get_sval(self, device_name):
        if device_name.endswith("Doorbell"):
            return ("1", "0")
        else:
            return ("On", "Off")

    def parse_update_device(self, parse_result, device_name):
        if device_name not in Devices:
            return
        (sval_on, sval_off) = self.get_sval(device_name)
        if parse_result:
            # self.write_debug_file(device_name, "on", data)
            if Devices[device_name].Units[1].sValue != sval_on:
                Domoticz.Log("Send On to " + device_name)
                update_device(device_name, Unit=1, sValue=sval_on, nValue=1)
                if int(self.motion_resettime) > 0:
                    if device_name in self.THREADDEVICES:
                        self.start_thread(device_name)
        else:
            # self.write_debug_file(device_name, "off", data)
            if int(self.motion_resettime) < 1:
                Domoticz.Log("Send Off to " + device_name)
                update_device(device_name, Unit=1, sValue=sval_off, nValue=0)

        return

    def parse_camera_message(self, data, prefix=""):
        if len(data) < 1:
            return

        try:
            parse_result = reolink_utils.reolink_parse_soap(data)
        except Exception:
            return

        if parse_result is not None:
            for rule in parse_result:
                if rule in self.RULES_DEVICE_MAP:
                    device_name = prefix + self.RULES_DEVICE_MAP[rule]
                    try:
                        self.parse_update_device(parse_result[rule], device_name)
                    except Exception as ex:
                        Domoticz.Error("Failed to update device! Error: " + str(ex))

    def do_log(self, json_obj):
        if "Log" in json_obj:
            Domoticz.Log(str(json_obj["Log"]))
        if "Debug" in json_obj:
            Domoticz.Debug(str(json_obj["Debug"]))
        if "Error" in json_obj:
            Domoticz.Error(str(json_obj["Error"]))

    def parse_json_message(self, data):
        try:
            lines = data.splitlines()
            json_obj = json.loads(json.loads(lines[len(lines) - 1]))

            if "Type" not in json_obj:
                return

            if json_obj["Type"] == "Startup":
                self.camera_startup(json_obj)
                for key in json_obj:
                    if key not in ("Type", "Prefix"):
                        Domoticz.Log("Camera " + key
                                     + " : " + str(json_obj[key]))

            if json_obj["Type"] == "Log":
                self.do_log(json_obj)

            if json_obj["Type"] == "Stop":
                self.stop_plugin = True
                Domoticz.Error(str(json_obj["Message"]))

            if json_obj["Type"] == "Event":
                prefix = json_obj.get("Prefix", "")
                for rule, state in json_obj.items():
                    if rule in ("Type", "Prefix"):
                        continue
                    if rule in self.RULES_DEVICE_MAP:
                        device_name = prefix + self.RULES_DEVICE_MAP[rule]
                        try:
                            self.parse_update_device(bool(state), device_name)
                        except Exception as ex:
                            Domoticz.Error("Failed to update device from Baichuan event! Error: " + str(ex))

        except Exception as err:
            Domoticz.Error("Logging error: " + str(err)
                           + " ->" + str(data))

    def onMessage(self, connection, message):
        Domoticz.Debug("onMessage called for connection: " + connection.Address + ":" + connection.Port)

        # Allow loopback (internal IPC), all configured camera IPs, and the Domoticz IP
        allowed = {'127.0.0.1', self.webhook_host} | set(self.camera_ip_to_prefix.keys())
        if connection.Address not in allowed:
            Domoticz.Error("Unauthorized access attempt by " + connection.Address + " - not in approved ip-list!")
            connection.Send({"Status": "403 Forbidden",
                             "Headers": {"Content-Type": "text/plain", "Connection": "close"},
                             "Data": "Forbidden"})
            return

        if "Headers" not in message:
            return
        if "Data" not in message:
            return

        # Always send HTTP 200 so the caller (requests.post / camera) doesn't see a disconnect
        connection.Send({"Status": "200 OK",
                         "Headers": {"Content-Type": "text/plain", "Connection": "close"},
                         "Data": ""})

        if "Content-Type" in message["Headers"]:
            if message["Headers"]["Content-Type"] == "application/json":
                self.parse_json_message(message["Data"])
                return
            if "application/soap+xml;" in message["Headers"]["Content-Type"]:
                prefix = self.camera_ip_to_prefix.get(connection.Address, "")
                self.parse_camera_message(message["Data"], prefix)
                return
        Domoticz.Log("Unknown message: " + str(message))
        return

    def onCommand(self, DeviceID, Unit, Command, Level, Color):
        Domoticz.Log("onCommand called for Device " + str(DeviceID) + " Unit " + str(Unit)
                     + ": Parameter '" + str(Command) + "', Level: " + str(Level) + " Color " + str(Color))

    def onNotification(self, Name, Subject, Text, Status, Priority, Sound, ImageFile):
        Domoticz.Debug("Notification: " + Name + "," + Subject + "," + Text + "," + Status + ","
                       + str(Priority) + "," + Sound + "," + ImageFile)

    def onDisconnect(self, Connection):
        Domoticz.Debug("onDisconnect called for connection '" + Connection.Name + "'.")

    def onHeartbeat(self):
        if self.stop_plugin:
            return
        #
        # Make sure the device is turned off even if a timer for some reason has failed!
        # Reasons might be a restart of Domoticz.
        #
        for device_id in list(Devices.keys()):
            for unitnr in Devices[device_id].Units:
                if Devices[device_id].Units[unitnr].sValue in ("1", "On"):
                    now = datetime.now()
                    devicetime = datetime.strptime(Devices[device_id].Units[unitnr].LastUpdate, '%Y-%m-%d %H:%M:%S')
                    td = timedelta(seconds=int(self.motion_resettime) + 60)
                    if now - devicetime > td:
                        Domoticz.Debug(device_id + " is on for some reason, turning off!")
                        self.switch_off(device_id)

        for i, t in enumerate(self.camera_threads):
            if not t.is_alive():
                self.running = False
                Domoticz.Log("Camera thread '" + t.name + "' is dead - restarting!")
                t.join()
                new_t = threading.Thread(name=t.name, target=BasePlugin.camera_loop, args=(self, i))
                self.camera_threads[i] = new_t
                new_t.start()
                self.running = True


global _plugin

_plugin = BasePlugin()


def onStart():
    global _plugin
    _plugin.onStart()


def onStop():
    global _plugin
    _plugin.onStop()


def onConnect(Connection, Status, Description):
    global _plugin
    _plugin.onConnect(Connection, Status, Description)


def onMessage(Connection, Data):
    global _plugin
    _plugin.onMessage(Connection, Data)


def onCommand(DeviceID, Unit, Command, Level, Color):
    global _plugin
    _plugin.onCommand(DeviceID, Unit, Command, Level, Color)


def onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile):
    global _plugin
    _plugin.onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile)


def onDisconnect(Connection):
    global _plugin
    _plugin.onDisconnect(Connection)


def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()


##
# Generic helper functions
##


def create_device(device_name, device_id):
    if device_name == "Doorbell":
        switch_type = 1
    else:
        switch_type = 8

    Domoticz.Log("Create device " + str(device_name) + " with id " + str(device_id)
                 + " Switchtype: " + str(switch_type))
    Domoticz.Unit(Name=device_name, DeviceID=device_name, Unit=1,
                  Type=244, Subtype=73, Switchtype=switch_type, Used=1).Create()


def update_device(ID, Unit=1, sValue=0, nValue=0, TimedOut=0, AlwaysUpdate=0):
    # Make sure that the Domoticz device still exists (they can be deleted) before updating it
    if Devices is not None and ID in Devices:
        if (str(Devices[ID].Units[Unit].sValue) != str(sValue)
                or str(Devices[ID].Units[Unit].nValue) != str(nValue)
                or str(Devices[ID].TimedOut) != str(TimedOut)
                or AlwaysUpdate == 1):

            if sValue is None:
                sValue = Devices[ID].Units[Unit].sValue
            Devices[ID].Units[Unit].sValue = str(sValue)
            if isinstance(sValue, (int, float)):
                Devices[ID].Units[Unit].LastLevel = sValue
            elif isinstance(sValue, dict):
                Devices[ID].Units[Unit].Color = json.dumps(sValue)
            Devices[ID].Units[Unit].nValue = nValue
            Devices[ID].TimedOut = TimedOut
            Devices[ID].Units[Unit].Update(Log=True)

            Domoticz.Debug('Update device value:' + str(ID) + ' Unit: ' + str(Unit)
                           + ' sValue: ' + str(sValue) + ' nValue: ' + str(nValue) + ' TimedOut=' + str(TimedOut))
