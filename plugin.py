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
            <li>Camera Ipaddress - The ipaddress for the camera. Must be reachable by the Domoticz server.</li>
            <li>Camera Username - The username used to login in the camera.</li>
            <li>Camera Password - The password used to login in the camera.</li>
            <li>Camera Port - The port used to communicate with the camera.</li>
            <li>Domoticz public ipaddress - The ipaddress used by the Domoticz server. Must be reachable by the camera.</li>
            <li>Webhook port - The port used by the Domoticz server for the webhook port. Must be unused.</li>
            <li>Motion reset time - The camera sends an off-signal directly after the on-signal. Use Off for default behavior.
                Otherwise the off signal will be delayed the configured number of seconds.</li>
           <li>Debug - Debug setting.</li>
        </ul>
        <br/>
    </description>

    <params>
       <param field="Address" label="Camera Ipaddress" width="200px" required="true"/>
       <param field="Username" label="Camera Username" width="200px" required="true" default="admin"/>
       <param field="Password" label="Camera Password" width="200px" required="true" default="" password="true"/>
       <param field="Port" label="Camera Port" width="200px" required="false" default="80"/>
       <param field="Mode1" label="Domoticz public ipaddress" width="200px" required="true" default=""/>
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
from datetime import datetime, timedelta
import json
import os
import reolink_utils
import subprocess
import DomoticzEx as Domoticz


class BasePlugin:

    CAMERADEVICES = {"Doorbell": 1, "Motion": 2, "Person": 3, "Vehicle": 4, "Dog_cat": 5, "Face": 6}
    DEVICENAME = {"Doorbell": "Doorbell", "Motion": "Motion", "People": "Person",
                  "Vehicle": "Vehicle", "Dog_cat": "Animal", "Face": "Face", "Animal":"Animal"}
    RULES_DEVICE_MAP = {"Motion": "Motion", "Visitor": "Doorbell", "PeopleDetect": "Person", "Dog_cat":"Animal", "Animal":"Animal"}
    THREADDEVICES = ["Motion", "Person", "Animal"]  # Create an "off" thread for these devices!
    threads = {}

    def __init__(self):
        self.stop_plugin = False
        self.running = True
        self.initialized = False

        self.camera_ipaddress = ""
        self.camera_port = 0
        self.camera_username = ""
        self.camera_password = ""

        self.webhook_host = ""
        self.webhook_port = 0
        self.webhook_url = ""

        self.task = None
        self.process = None

    def onStart(self):
        global _plugin

        if Parameters["Mode6"] != "0":
            Domoticz.Debugging(int(Parameters["Mode6"]))
            Domoticz.Debug("onStart called")

        self.camera_ipaddress = Parameters["Address"]
        self.camera_port = Parameters["Port"]
        self.camera_password = Parameters["Password"]
        self.camera_username = Parameters["Username"]
        self.webhook_host = Parameters["Mode1"]
        self.webhook_port = Parameters["Mode2"]
        self.motion_resettime = Parameters["Mode3"]

        if self.webhook_port is None or int(self.webhook_port) < 1000:
            Domoticz.Error("Webhook port must be an integer and have a value above 1000!")
            self.running = False
            return

        self.webhook_url = "http://" + self.webhook_host + ":" + str(self.webhook_port)

        Domoticz.Heartbeat(30)

        ##
        # Create webhook
        ##
        self.httpClientConn = Domoticz.Connection(Name="Camera webhook", Transport="TCP/IP", Protocol="HTTP",
                                                  Address=self.webhook_host, Port=self.webhook_port)
        self.httpClientConn.Listen()
        self.camera_thread = threading.Thread(name="Camera thread", target=BasePlugin.camera_loop, args=(self,))
        self.camera_thread.start()

    def camera_startup(self, camera_info):
        ##
        # Create device if it is not created
        ##
        self.initialized = True

        # Implement solution to create all types
        supported = camera_info["AI types"].strip('][').replace("'", '').split(', ')
        supported.append('motion')

        i = 0
        for x in supported:
            supported[i] = x.capitalize()
            i = i + 1

        if 'Is doorbell' in camera_info and str(camera_info['Is doorbell']) == 'True':
            str(supported.append('Doorbell'))

        #Domoticz.Log('Camera_info: '+str(camera_info))
        #Domoticz.Log('Supported: '+str(supported))

        for _device in supported:
            if self.DEVICENAME[_device] not in Devices:
                create_device(self.DEVICENAME[_device], self.CAMERADEVICES[self.DEVICENAME[_device]])

    def camera_loop(self):
        try:
            path = Parameters['HomeFolder'] + "camera.py"
            self.process = subprocess.Popen(["python3",
                                             path,
                                             self.camera_ipaddress,
                                             self.camera_port,
                                             self.camera_username,
                                             self.camera_password,
                                             self.webhook_host,
                                             self.webhook_port])

            # Domoticz.Log(str(path)+" "+
            #             str(self.camera_ipaddress)+" "+
            #             str(self.camera_port)+" "+
            #             str(self.camera_username)+" "+
            #             str(self.camera_password)+" "+
            #             str(self.webhook_host)+" "+
            #             str(self.webhook_port))

            Domoticz.Debug("Camera process poll: " + str(self.process.poll()))
            while True:
                if self.stop_plugin:
                    break
                # Domoticz.Debug("Camera process poll: " + str(self.process.poll()))
                if self.process is not None:
                    if self.process.poll() is not None:
                        Domoticz.Error("Camera process dead: " + str(self.process.returncode))
                        self.process = subprocess.Popen(["python3", path,
                                                         self.camera_ipaddress, self.camera_port,
                                                         self.camera_username, self.camera_password,
                                                         self.webhook_host, self.webhook_port])
                time.sleep(15)
        except Exception as err:
            Domoticz.Error("handleMessage: " + str(err))

        Domoticz.Debug("Terminate camera process!")
        self.process.terminate()
        while self.process.poll() is None:
            time.sleep(1)
            Domoticz.Debug("Waiting for process to die!")
            self.process.kill()

    def onStop(self):
        self.running = False
        self.stop_plugin = True
        self.camera_thread.join()

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
            Domoticz.Debug("Connected successfully to: " + Connection.Address + ":" + Connection.Port)
        else:
            Domoticz.Debug("Failed to connect (" + str(Status) + ") to: " + Connection.Address + ":"
                           + Connection.Port + " with error: " + Description)
        Domoticz.Debug(str(Connection))

    def switch_off(self, device):
        # if rule in self.RULES_DEVICE_MAP:
        # device = self.RULES_DEVICE_MAP[rule]
        # else:
        # device = rule
        Domoticz.Log("Send Off to " + device)
        if device == "Doorbell":
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
        if device_name == "Doorbell":
            return ("1", "0")
        else:
            return ("On", "Off")

    def parse_update_device(self, parse_result, device_name):
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

    def parse_camera_message(self, data):
        if len(data) < 1 or not self.initialized:
            return

        try:
            parse_result = reolink_utils.reolink_parse_soap(data)
        except Exception:
            # Domoticz.Error("Failed to parse message: " + str(ex) + " Starts with: " + str(data)[:10] +
            #               " Ends with: " + str(data)[-10:])
            # Domoticz.Error("Failed to parse, Error: " + str(ex) +
            #               " Message: " + str(data))
            return

        if parse_result is not None:
            for rule in parse_result:
                if rule in self.RULES_DEVICE_MAP:
                    device_name = self.RULES_DEVICE_MAP[rule]
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
                    if key != "Type":
                        Domoticz.Log("Camera " + key
                                     + " : " + str(json_obj[key]))

            if json_obj["Type"] == "Log":
                self.do_log(json_obj)

            if json_obj["Type"] == "Stop":
                self.stop_plugin = True
                Domoticz.Error(str(json_obj["Message"]))

        except Exception as err:
            Domoticz.Error("Logging error: " + str(err)
                           + " ->" + data)

    def onMessage(self, connection, message):
        Domoticz.Debug("onMessage called for connection: " + connection.Address + ":" + connection.Port)

        if connection.Address not in [self.camera_ipaddress, self.webhook_host]:
            Domoticz.Error("Unauthorized access attempt by " + connection.Address + " - not in approved ip-list!")
            return

        if "Headers" not in message:
            return
        if "Data" not in message:
            return
        if "Content-Type" in message["Headers"]:
            if message["Headers"]["Content-Type"] == "application/json":
                self.parse_json_message(message["Data"])
                return
            if "application/soap+xml;" in message["Headers"]["Content-Type"]:
                self.parse_camera_message(message["Data"])
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
        # Make sure the device is turned off even if a timer for some reson has failed!
        # Resons might be a restart of Domoticz.
        #
        for device in self.CAMERADEVICES:
            if device in Devices:
                for unitnr in Devices[device].Units:
                    if (Devices[device].Units[unitnr].sValue == "1" or Devices[device].Units[unitnr].sValue == "On"):
                        now = datetime.now()
                        devicetime = datetime.strptime(Devices[device].Units[unitnr].LastUpdate, '%Y-%m-%d %H:%M:%S')
                        td = timedelta(seconds=int(self.motion_resettime) + 60)
                        if now - devicetime > td:
                            Domoticz.Debug(device + " is on for some reason, turning off!")
                            self.switch_off(device)

        if not self.camera_thread.is_alive():
            self.running = False
            Domoticz.Log("Camera thread is dead - restarting!")
            self.camera_thread.join()
            self.camera_thread = threading.Thread(name="Camera thread", target=BasePlugin.camera_loop,
                                                  args=(self,))
            self.camera_thread.start()
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
