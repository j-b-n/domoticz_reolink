"""
<plugin key="Reolink" name="Reolink camera" author="jbn" version="0.0.1" externallink="https://github.com/j-b-n/domoticz_reolink">
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
            <li>Require python package <a href="https://github.com/starkillerOG/reolink_aio">reolink_aio</a> by starkillOG.</li>
            <li>The camera need to have ONVIF enabled. See <a href="https://support.reolink.com/hc/en-us/articles/900004435763-How-to-Set-up-Reolink-Ports-Settings-via-Reolink-Client-New-Client-/">Reolink documation</a> for support. Remeber to restart the camera after the change!</li>
        </ul>
        <h2>Parameters</h2><br/>
        <ul style="list-style-type:square">
            <li>Camera Ipaddress - The ipaddress for the camera. Must be reachable by the Domoticz server.</li>
            <li>Camera Username - The username used to login in the camera.</li>
            <li>Camera Password - The password used to login in the camera.</li>
            <li>Camera Port - The port used to communicate with the camera.</li>
            <li>Domoticz public ipaddress - The ipaddress used by the Domoticz server. Must be reachable by the camera.</li>
            <li>Webhook port - The port used by the Domoticz server for the webhook port. Must be unused.</li>
            <li>Motion reset time - The camera sends an off-signal directly after the on-signal. Use Off for default behavior. Otherwise the off signal will be delayed the configured number of seconds.</li>
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
import DomoticzEx as Domoticz
import threading
import time
from datetime import datetime, timedelta
import json
import os
from xml.etree import ElementTree as XML
import subprocess

class BasePlugin:
    RULES = ["Motion","FaceDetect","PeopleDetect","VehicleDetect","DogCatDetect","MotionAlarm","Visitor"]
    CAMERADEVICES = {"Doorbell":1,"Motion":2,"Person":3}
    RULES_DEVICE_MAP = {"Motion":"Motion","Visitor":"Doorbell","PeopleDetect":"Person"}
    THREADDEVICES = ["Motion","Person"] #Create an "off" thread for these devices!
    threads = {}

    def __init__(self):
        self.stop_plugin = False
        self.running = True
        self.camera_ipaddress=""
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
        self.camera_password  = Parameters["Password"]
        self.camera_username  = Parameters["Username"]
        self.webhook_host = Parameters["Mode1"]
        self.webhook_port = Parameters["Mode2"]
        self.motion_resettime = Parameters["Mode3"]

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

#        self.camhookConn = Domoticz.Connection(Name="Camera process webhook", Transport="TCP/IP",
#                                               Protocol="JSON",
#                                               Address="127.0.0.1",
#                                               Port=self.webhook_port)
#        self.camhookConn.Listen()

        
        self.camera_thread = threading.Thread(name="Camera thread", target=BasePlugin.camera_loop, args=(self,))        
        self.camera_thread.start()


    def camera_loop( self ):
        try:
#            Domoticz.Log("CWD: "+os. getcwd())
            # "/home/pi/domoticz/plugins/domoticz_reolink/camera.py"
            path = os.getcwd()+"/plugins/domoticz_reolink/camera.py"
            self.process = subprocess.Popen(["python", path,
                                             self.camera_ipaddress,self.camera_port,
                                             self.camera_username,self.camera_password,
                                             self.webhook_host,self.webhook_port
                                             ])

            #Domoticz.Debug("Camera process poll: "+str(self.process.poll()))
            while True:
                if self.stop_plugin:
                    break
                #Domoticz.Debug("Camera process poll: "+str(self.process.poll()))
                if self.process is not None:
                    if self.process.poll() is not None:
                        Domoticz.Error("Camera process dead: "+str(self.process.returncode))
                        self.process = subprocess.Popen(["python", path,
                                                         self.camera_ipaddress,self.camera_port,
                                                         self.camera_username,self.camera_password,
                                                         self.webhook_host,self.webhook_port
                                                         ])
                time.sleep(5)
        except Exception as err:
            Domoticz.Error("handleMessage: "+str(err))

        Domoticz.Log("Terminate camera process!")
        self.process.terminate()
        while self.process.poll() is None:
            time.sleep(1)
            Domoticz.Log("Waiting for process to die!")
            self.process.kill()


    def onStop(self):
        self.running = False
        self.stop_plugin = True
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
            time.sleep(0.5)


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

        if data is None or len(data) < 500:
            return result

        try:
            root = XML.fromstring(data)
        except Exception as ex:
            Domoticz.Error("Failed to parse message from camera as XML!")
            return result

        try:
        
            for message in root.iter('{http://docs.oasis-open.org/wsn/b-2}NotificationMessage'):
                topic_element = message.find("{http://docs.oasis-open.org/wsn/b-2}Topic[@Dialect='http://www.onvif.org/ver10/tev/topicExpression/ConcreteSet']")
                if topic_element is None or topic_element.text is None:
                    continue

                rule = os.path.basename(topic_element.text)
                if not rule:
                    continue
               

                key = "State"
                if rule == "Motion":
                    key = "IsMotion"

                data_element = message.find(f".//\u007bhttp://www.onvif.org/ver10/schema\u007dSimpleItem[@Name='{key}']")
                if data_element is None:
                    continue

                state = data_element.attrib["Value"] == "true"
                result[rule] = state
                
                if state:
                    result["Any"] = True
        except Exception as ex:
            Domoticz.Error("Failed to parse message!"+str(ex))
            return result            

        return result


    def switch_off(self, device):
#        if rule in self.RULES_DEVICE_MAP:
#            device = self.RULES_DEVICE_MAP[rule]
#        else:
#            device = rule
        Domoticz.Log("Send Off to "+device)
        update_device(device, Unit=1, sValue="Off" , nValue=0)
        self.threads[device] = None
    
    def start_thread(self, device):
        Domoticz.Debug("Start thread for device "+device+" send off in "+str(self.motion_resettime)+" seconds")        
        if device in self.threads:
             if self.threads[device] is not None:
                if(self.threads[device].is_alive()):
                    #Domoticz.Error("Device thread for "+device+" is alive! Cancel old thread and start new one!")
                    self.threads[device].cancel()
                    time.sleep(0.1)
                    while self.threads[device].is_alive():                        
                        Domoticz.Error("Device thread for "+device+" is STILL alive! Cancel!!")
                        self.threads[device].cancel()
                        time.sleep(0.1)

        t = threading.Timer(int(self.motion_resettime), self.switch_off, [device])
        t.start()                
        self.threads[device] = t

    def write_debug_file(self, device_name, state, data):
        try:
            file_path = "/tmp/"+device_name+"_"+state+".xml"
            file_size = os.path.getsize(file_path)
            if file_size < 5000:
                with open(file_path, "wb") as binary_file:
                    binary_file.write(data)
        except FileNotFoundError:
            Domoticz.Error("File not found: "+file_path)
            with open(file_path, "wb") as binary_file:
                binary_file.write(data)                                
        except OSError:
            Domoticz.Error("OS error occurred: "+file_path)    

    def parseCameramessage(self, data):
        parse_result =  self.reolink_parse_soap(data)

        if parse_result is not None:
            for rule in parse_result:
                if rule in self.RULES_DEVICE_MAP:
                    device_name = self.RULES_DEVICE_MAP[rule]

                    try:
                        if parse_result[rule] == True:
                            #self.write_debug_file(device_name, "on", data)
                            if Devices[device_name].Units[1].sValue == "Off":
                                Domoticz.Log("Send On to "+device_name)
                                update_device(device_name, Unit=1, sValue="On" , nValue=1)
                            if(int(self.motion_resettime) > 0):
                                if device_name in self.THREADDEVICES:
                                    self.start_thread(device_name)
                        else:
                            #self.write_debug_file(device_name, "off", data)                        
                            if(int(self.motion_resettime) < 1):
                                Domoticz.Log("Send Off to "+device)
                                update_device(device_name, Unit=1, sValue="Off" , nValue=0)
                        
                    except Exception as ex:
                        Domoticz.Error("Failed to update device! Error: "+str(ex))        
            
    def onMessage(self, connection, data):
        Domoticz.Debug("onMessage called for connection: "+connection.Address+":"+connection.Port)

        if len(data) < 50:
            Domoticz.Debug("OnMessage less than 50 bytes: "+str(data))
        if connection.Address.startswith(self.camera_ipaddress) or data.startswith(b"<SOAP-ENV:Envelope"):
            self.parseCameramessage(data)
        else:
            Domoticz.Debug("Response data: "+str(data))

            if len(data) > 20:
                try:
                    lines = data.splitlines()
                    s = lines[len(lines)-1] 
                    s = s.decode("utf-8")
                    json_obj = json.loads(json.loads(lines[len(lines)-1] ))
                    
                    if "Log" in json_obj:
                        Domoticz.Log( str( json_obj["Log"] ))
                    if "Debug" in json_obj:
                        Domoticz.Debug( str( json_obj["Debug"] ))
                    if "Error" in json_obj:
                        Domoticz.Error( str( json_obj["Error"] ))
                except Exception as err:
                    Domoticz.Error("Logging error: "+str(err))
        
            
            #self.camhookConn.Send({"Status":"200 OK", "Headers": {"Connection": "keep-alive", "Accept": "Content-Type: text/html; charset=UTF-8"}, "Data": "{Data: Ok}"})
            
            #resp = "<!doctype html><html><head></head><body><h1>Successful GET!!!</h1><body></html>"
            #connection.Send({"Status":"200 OK", "Headers": {"Connection": "keep-alive", "Accept": "Content-Type: text/html; charset=UTF-8"}, "Data": resp})

        return


    def onCommand(self, DeviceID, Unit, Command, Level, Color):
        Domoticz.Log("onCommand called for Device " + str(DeviceID) + " Unit " + str(Unit) + ": Parameter '" + str(Command) + "', Level: " + str(Level)+" Color "+str(Color))

    def onNotification(self, Name, Subject, Text, Status, Priority, Sound, ImageFile):
        Domoticz.Debug("Notification: " + Name + "," + Subject + "," + Text + "," + Status + "," + str(Priority) + "," + Sound + "," + ImageFile)

    def onDisconnect(self, Connection):
        Domoticz.Debug("onDisconnect called for connection '"+Connection.Name+"'.")

    def onHeartbeat(self):
        #
        # Make sure the device is turned off even if a timer for some reson has failed!
        # Resons might be a restart of Domoticz.
        #
        for device in self.CAMERADEVICES:
            for unitnr in Devices[device].Units:
                if(Devices[device].Units[unitnr].sValue == "1"):
                    now = datetime.now()
                    devicetime = datetime.strptime(Devices[device].Units[unitnr].LastUpdate, '%Y-%m-%d %H:%M:%S')
                    td = timedelta(seconds=int(self.motion_resettime)+60)
                    if (now - devicetime > td):
                        Domoticz.Debug(device+" is on for some reason, turning off!")
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

####
## Generic helper functions
####
        
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
