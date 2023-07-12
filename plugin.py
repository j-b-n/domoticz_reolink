"""
<plugin key="Reolink" name="Reolink camera" author="jbn" version="0.0.1" externallink="https://github.com/j-b-n/domoticz_reolink">

    <params>
       <param field="Address" label="Camera Ipaddress" width="200px" required="false"/>
       <param field="Username" label="Camera Username" width="200px" required="false" default="admin"/>
       <param field="Password" label="Camera Password" width="200px" required="false" default="" password="true"/>
       <param field="Port" label="Camera Port" width="200px" required="false" default="80"/>
       <param field="Mode1" label="Webhook Host" width="200px" required="false" default=""/>
       <param field="Mode2" label="Webhook Port" width="200px" required="false" default="8989"/>
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
# When this plugin is restarted while the Domoticz server is running the old Python interpreter is not cleared enough thus
# leaving cached versions of
# * asyncio
# * datetime
#     This manifests in reolink_aio when calling datetime.strptime with the error
#     'NoneType' object is not callable
#
# The root-cause error in Python is tracked here: https://github.com/python/cpython/issues/71587
#
# Removing the loaded modules and then importing them solves this issue.
#
# Similar issue is found here:
# PyO3 modules may only be initialized once per interpreter process, https://www.domoticz.com/forum/viewtopic.php?f=65&t=40417
# and the work-around: https://github.com/zigbeefordomoticz/Domoticz-Zigbee/commit/ba6d729f337ce4fd38a4afb62d9eb8d639d1f84d
#
# Perhaps reolink_aio shoudl change to
# "Conversely, the datetime.strptime() class method creates a datetime object from a string representing a date and time and
# a corresponding format string. datetime.strptime(date_string, format) is equivalent to
# datetime(*(time.strptime(date_string, format)[0:6]))."
#
##
import sys
sys.modules["_asyncio"] = None
sys.modules["_datetime"] = None
import datetime

##
# Plugin
##
import DomoticzEx as Domoticz
import threading
import time
import json
import os
from xml.etree import ElementTree as XML
import asyncio
from reolink_aio.api import Host
from reolink_aio.enums import SubType
from reolink_aio.exceptions import ReolinkError, SubscriptionError

class BasePlugin:
    RULES = ["Motion","FaceDetect","PeopleDetect","VehicleDetect","DogCatDetect","MotionAlarm","Visitor"]
    CAMERADEVICES = {"Doorbell":1,"Motion":2,"Person":3}
    RULES_DEVICE_MAP = {"Motion":"Motion","Visitor":"Doorbell","PeopleDetect":"Person"}

    def __init__(self):
        self.running = True
        self.camera_thread = threading.Thread(name="Camera thread", target=BasePlugin.async_loop, args=(self,))

        self.camera_ipaddress=""
        self.camera_port = 0
        self.camera_username = ""
        self.camera_password = ""

        self.webhook_host = ""
        self.webhook_port = 0
        self.webhook_url = ""

        self.task = None

    def async_loop( self ):
        loop = get_or_create_eventloop()
        self.task = reolink_start(self)
        loop.run_until_complete(self.task)
        loop.run_until_complete(asyncio.sleep(1))
        loop.close()

    def onStart(self):
        global _plugin

        if Parameters["Mode6"] != "0":
            Domoticz.Debugging(int(Parameters["Mode6"]))
            #DumpConfigToLog()
            Domoticz.Debug("onStart called")

        self.camera_ipaddress = Parameters["Address"]
        self.camera_port = Parameters["Port"]
        self.camera_password  = Parameters["Password"]
        self.camera_username  = Parameters["Username"]
        self.webhook_host = Parameters["Mode1"]
        self.webhook_port = Parameters["Mode2"]

        if self.webhook_port is None or int(self.webhook_port) < 1000:
            Domoticz.Error("Webhook port must be an integer and have a value above 1000!")
            self.running = False
            return

        self.webhook_url = "http://"+self.webhook_host+":"+str(self.webhook_port)

        Domoticz.Heartbeat(30)

        ####
        ## Create device if it is not created
        ####
        for _device in self.CAMERADEVICES:
            if _device not in Devices:
                create_device(_device, self.CAMERADEVICES[_device])

        ####
        ## Create webhook
        ####
        self.httpClientConn = Domoticz.Connection(Name="Camera webhook", Transport="TCP/IP", Protocol="XML",
                                                  Address="127.0.0.1", Port=self.webhook_port)
        self.httpClientConn.Listen()

        self.camera_thread.start()


    def onStop(self):
        self.running = False
        self.camera_thread.join()

        for thread in threading.enumerate():
            if thread.name != threading.current_thread().name:
                Domoticz.Log("'"+thread.name+"' is running, it must be shutdown otherwise Domoticz will abort on plugin exit.")


        # Wait until queue thread has exited
        Domoticz.Log("Threads still active: "+str(threading.active_count())+", should be 1.")
        while threading.active_count() > 1:
            for thread in threading.enumerate():
                if thread.name != threading.current_thread().name:
                    Domoticz.Log("'"+thread.name+"' is still running, waiting otherwise Domoticz will abort on plugin exit.")
            time.sleep(1.0)


    def onConnect(self, Connection, Status, Description):
        if Status == 0:
            Domoticz.Debug("Connected successfully to: "+Connection.Address+":"+Connection.Port)
        else:
            Domoticz.Debug("Failed to connect ("+str(Status)+") to: "+Connection.Address+":"+Connection.Port+" with error: "+Description)
        Domoticz.Debug(str(Connection))


    def reolink_parse_soap(self, data):
        result = {}

        for rule in self.RULES:
            result[rule] = False

        result["Any"] = False

        if data is None or len(data) < 2:
            return result

        try:
            root = XML.fromstring(data)
        except Exception as ex:
            return result

        for message in root.iter('{http://docs.oasis-open.org/wsn/b-2}NotificationMessage'):
            topic_element = message.find("{http://docs.oasis-open.org/wsn/b-2}Topic[@Dialect='http://www.onvif.org/ver10/tev/topicExpression/ConcreteSet']")
            if topic_element is None:
                continue
            #print("Topic:",topic_element)
            rule = os.path.basename(topic_element.text)
            #print("Rule:",rule)
            if not rule:
                continue

            if rule == "Motion":
                data_element = message.find(".//{http://www.onvif.org/ver10/schema}SimpleItem[@Name='IsMotion']")
                if data_element is None:
                    continue
                if "Value" in data_element.attrib and data_element.attrib["Value"] == "true":
                    result[rule] = True
                    result["Any"] = True
            elif rule in self.RULES:
                data_element = message.find(".//{http://www.onvif.org/ver10/schema}SimpleItem[@Name='State']")
                if data_element is None:
                    continue
                if "Value" in data_element.attrib and data_element.attrib["Value"] == "true":
                    result[rule] = True
                    result["Any"] = True
        return result


    def onMessage(self, connection, data):
        Domoticz.Debug("onMessage called for connection: "+connection.Address+":"+connection.Port)

        parse_result =  self.reolink_parse_soap(data)

        if parse_result is not None:
            for rule in parse_result:
                if rule in self.RULES_DEVICE_MAP:
                    device_name = self.RULES_DEVICE_MAP[rule]
                    try:
                        if parse_result[rule] == True:
                            update_device(device_name, Unit=1, sValue=1 , nValue=1)
                        else:
                            update_device(device_name, Unit=1, sValue=0 , nValue=0)
                    except Exception as ex:
                        Domoticz.Error("Failed to update device! Error: "+str(ex))

    def onCommand(self, DeviceID, Unit, Command, Level, Color):
        Domoticz.Log("onCommand called for Device " + str(DeviceID) + " Unit " + str(Unit) + ": Parameter '" + str(Command) + "', Level: " + str(Level)+" Color "+str(Color))

    def onNotification(self, Name, Subject, Text, Status, Priority, Sound, ImageFile):
        Domoticz.Debug("Notification: " + Name + "," + Subject + "," + Text + "," + Status + "," + str(Priority) + "," + Sound + "," + ImageFile)

    def onDisconnect(self, Connection):
        Domoticz.Debug("onDisconnect called for connection '"+Connection.Name+"'.")

    def onHeartbeat(self):

        if not self.camera_thread.is_alive():
            self.running = False
            Domoticz.Log("camera_thread dead - restart!")
            self.camera_thread.join()
            self.camera_thread = threading.Thread(name="Camera thread", target=BasePlugin.async_loop,
                                                  args=(self,))
            self.camera_thread.start()
            self.running = True

def get_or_create_eventloop():
    try:
        return asyncio.get_event_loop()
    except RuntimeError as ex:
        if "There is no current event loop in thread" in str(ex):
            asyncio.set_event_loop(asyncio.new_event_loop())
            return asyncio.get_event_loop()
    return None

def GetCameraHost(camera_ipaddress, camera_username, camera_password, camera_port):
    try:
        Domoticz.Debug("Connect camera at: "+str(camera_ipaddress))
        camera_host = Host(camera_ipaddress, camera_username, camera_password, port=camera_port)
        return camera_host
    except ReolinkError as err:
        Domoticz.Error("GetCameraHost failed with ReolinkError: "+str(err))
        return None
    except Exception as ex:
        Domoticz.Error("GetCameraHost failed with exception: "+str(ex))
        return None

async def camera_subscribe(camera, webhook_url):
    try:
        await camera.subscribe(webhook_url, SubType.push, retry=False)
    except SubscriptionError as ex:
        Domoticz.Error("Camera subscriptionerror failed: "+str(ex))
    except Exception as ex:
        Domoticz.Error("Camera subscribe failed: "+str(ex))


async def reolink_start(self):
    camera = GetCameraHost(self.camera_ipaddress, self.camera_username, self.camera_password, self.camera_port)
    if camera is None:
        Domoticz.Error("Get camera returned None!")
        return
    try:
        await camera.get_host_data()
        await camera.get_states()
    except Exception as ex:
        Domoticz.Error("Camera update host_data/states failed: "+str(ex))
        return

    Domoticz.Log("Camera name: "+ str(camera.camera_name(0)))
    Domoticz.Log("Camera model: "+ str(camera.model))
    Domoticz.Log("Camera mac_address: "+ str(camera.mac_address))
    Domoticz.Log("Camera doorbell: "+ str(camera.is_doorbell(0)))

    await camera_subscribe(camera, self.webhook_url)

    while self.running:
        if camera is None:
            Domoticz.Error("Camera is None!")
            camera = GetCameraHost(self.camera_ipaddress, self.camera_username, self.camera_password, self.camera_port)
            camera = GetCameraHost(self.camera_ipaddress, self.camera_username, self.camera_password, self.camera_port)

        await camera.get_states()
        renewtimer = camera.renewtimer()
        if renewtimer <= 100 or not camera.subscribed(SubType.push):
            Domoticz.Debug("Renew camera subscription!")
            if not await camera.renew():
                await camera_subscribe(camera, self.webhook_url)

        await asyncio.sleep(5)

    Domoticz.Log("Camera logout!")
    try:
        await camera.unsubscribe()
    except SubscriptionError as ex:
        Domoticz.Error("Camera unsubscribe failed: "+str(ex))
    except Exception as ex:
        Domoticz.Error("Camera unsubscribe failed: "+str(ex))        
        
    camera.logout()
    camera = None

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

####
## Generic helper functions
####
def DumpConfigToLog():
    for x in Parameters:
        if Parameters[x] != "":
            Domoticz.Debug( "'" + x + "':'" + str(Parameters[x]) + "'")
    Domoticz.Debug("Device count: " + str(len(Devices)))
    for x in Devices:
        Domoticz.Debug("Device:           " + str(x) + " - " + str(Devices[x]))
        Domoticz.Debug("Device ID:       '" + str(Devices[x].ID) + "'")
        Domoticz.Debug("Device Name:     '" + Devices[x].Name + "'")
        Domoticz.Debug("Device nValue:    " + str(Devices[x].nValue))
        Domoticz.Debug("Device sValue:   '" + Devices[x].sValue + "'")
        Domoticz.Debug("Device LastLevel: " + str(Devices[x].LastLevel))


def create_device(device_name, device_id):
    if device_name == "Doorbell":
        switch_type = 1
    else:
        switch_type = 8

    Domoticz.Log("Create - device_name: "+str(device_name)+" id: "+str(device_id)+
                 " Switchtype: "+str(switch_type))
    Domoticz.Unit(Name=device_name, DeviceID=device_name, Unit=1,
                  Type=244, Subtype=73, Switchtype=switch_type, Used=1).Create()


def update_device(ID, Unit = 1, sValue= 0, nValue = 0, TimedOut = 0, AlwaysUpdate = 0):
    # Make sure that the Domoticz device still exists (they can be deleted) before updating it
    if Devices is not None and ID in Devices:
        if str(Devices[ID].Units[Unit].sValue) != str(sValue) or str(Devices[ID].Units[Unit].nValue) != str(nValue) or str(Devices[ID].TimedOut) != str(TimedOut) or AlwaysUpdate == 1:
            if sValue == None:
                sValue = Devices[ID].Units[Unit].sValue
            Devices[ID].Units[Unit].sValue = str(sValue)
            if type(sValue) == int or type(sValue) == float:
                Devices[ID].Units[Unit].LastLevel = sValue
            elif type(sValue) == dict:
                Devices[ID].Units[Unit].Color = json.dumps(sValue)
            Devices[ID].Units[Unit].nValue = nValue
            Devices[ID].TimedOut = TimedOut
            Devices[ID].Units[Unit].Update(Log=True)

            Domoticz.Debug('Update device value:' + str(ID) + ' Unit: ' + str(Unit) +
                           ' sValue: ' +  str(sValue) + ' nValue: ' + str(nValue) + ' TimedOut=' + str(TimedOut))
