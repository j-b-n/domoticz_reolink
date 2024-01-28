<h2 align="center">
  <a href="https://domoticz.com"><img src="https://raw.githubusercontent.com/j-b-n/domoticz_reolink/main/images/domoticz_logo.png" height="75" width="75"></a>
  <a href="https://reolink.com"><img src="https://raw.githubusercontent.com/j-b-n/domoticz_reolink/main/images/reolink_logo.png" width="200"></a>
  <br>
  <i>Domoticz plugin for Reolink cameras</i>
  <br>
</h2>

### Description

This `plugin` allows you to integrate your [Reolink](https://www.reolink.com/) device (cameras) into Domoticz.

The first version is *only* tested on [Reolink Video Doorbell WiFi](https://reolink.com/product/reolink-video-doorbell-wifi/)
and might not work for other cameras!


### Prerequisites

- Python 3.9
- [reolink_aio](https://github.com/starkillerOG/reolink_aio)

### Installation
Install by navigating to your Domoticz plugin folder (example: /home/pi/domoticz/plugins).
````
git clone https://github.com/j-b-n/domoticz_reolink
sudo python3 -m pip install -r requirements.txt --upgrade
````

### Update
Update an installed plugin by enter in the plugin install folder (example: /home/pi/domoticz/plugins/domoticz_reolink).
````
git pull
sudo python3 -m pip install -r requirements.txt --upgrade
````
### Please note!
The first approach using async_io in the plugin.py file is not stable enough on my test system. I have changed to a different approach where the communication with the Reolink camera is handled in a separated subprocess (ie [camera.py](https://github.com/j-b-n/domoticz_reolink/blob/main/camera.py)). You can test the communication with the camera using [test.py](https://github.com/j-b-n/domoticz_reolink/blob/main/test.py). It uses [secrets.cfg](https://github.com/j-b-n/domoticz_reolink/blob/main/secrets.cfg) for configuration.

I will continue to explore a solution that only utilizes plugin.py.

### Frequently Asked Questions (FAQ)

**I get this error message: "Unit creation failed, Domoticz settings prevent accepting new devices."**
You need to allow Domoticz to create new devices. That is either "Allow for 5 minutes" or toggle "Accept new Hardware Devices" to on.

### Acknowledgment
This plugin use reolink_aio created by @starkillerOG found here https://github.com/starkillerOG/reolink_aio.
I also used code and inspiration from [Zigbee for Domoticz](https://github.com/zigbeefordomoticz)

**Author**

* [j-b-n](https://github.com/j-b-n)
