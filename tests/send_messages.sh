#!/bin/sh
# If you want to test the message parsing:
# Start camera.py on server
# Change 10.0.0.100 to your server
# Change 8999 to your port

echo "Sending messages..."
OUTPUT=$(curl -H 'Content-Type: application/soap+xml;' -X POST 10.0.0.100:8999 -d @./messages/several_true.xml 2>/dev/null)
echo " Several true: ${OUTPUT}"
OUTPUT=$(curl -H 'Content-Type: application/soap+xml;' -X POST 10.0.0.100:8999 -d @./messages/Doorbell_on.xml 2>/dev/null)
echo " Doorbell true: ${OUTPUT}"
OUTPUT=$(curl -H 'Content-Type: application/soap+xml;' -X POST 10.0.0.100:8999 -d @./messages/all_false.xml 2>/dev/null)
echo " All false: ${OUTPUT}"
