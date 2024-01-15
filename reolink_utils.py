from xml.etree import ElementTree as XML
import os

def ReolinkParseSOAP(Data):
    RULES = ["Motion","FaceDetect","PeopleDetect","VehicleDetect","DogCatDetect","MotionAlarm","Visitor"]
    RESULT = {}

    for rule in RULES:
        RESULT[rule] = False

    RESULT["Any"] = False

    if Data is None or len(Data) < 2:
        return

    root = XML.fromstring(Data)

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
                RESULT[rule] = True
                RESULT["Any"] = True
        elif rule in RULES:
            data_element = message.find(".//{http://www.onvif.org/ver10/schema}SimpleItem[@Name='State']")
            if data_element is None:
                continue
            if "Value" in data_element.attrib and data_element.attrib["Value"] == "true":
                RESULT[rule] = True
                RESULT["Any"] = True
        return RESULT


if __name__ == "__main__":
    with open("message/Person_on.xml") as my_file:
        Data = my_file.read()
        res = ReolinkParseSOAP(Data)
        print(res)
