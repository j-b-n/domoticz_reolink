""" This module is meant to be shared between the plugin and other code, like tests """
from xml.etree import ElementTree as XML
import os


def reolink_parse_soap(data) -> dict:
    """ This function takes data and parse it according to the Reolink specification
     and returns true for any of the types that is detected. """

    rules = ["Motion", "FaceDetect", "PeopleDetect", "VehicleDetect", "DogCatDetect",
             "MotionAlarm", "Visitor"]
    result = {}

    for rule in rules:
        result[rule] = False

    result["Any"] = False

    if data is None or len(data) < 100:
        return result

    try:
        root = XML.fromstring(data)
    except Exception as ex:
        return

    for message in root.iter('{http://docs.oasis-open.org/wsn/b-2}NotificationMessage'):
        topic_element = message.find("{http://docs.oasis-open.org/wsn/b-2}Topic[@Dialect='" +
                                     "http://www.onvif.org/ver10/tev/topicExpression/ConcreteSet']")
        if topic_element is None:
            continue
        rule = os.path.basename(topic_element.text)
        if not rule:
            continue

        if rule == "Motion":
            data_element = message.find(".//{http://www.onvif.org/ver10/schema}SimpleItem[@Name='IsMotion']")
            if data_element is None:
                continue
            if "Value" in data_element.attrib and data_element.attrib["Value"] == "true":
                result[rule] = True
                result["Any"] = True
        elif rule in rules:
            data_element = message.find(".//{http://www.onvif.org/ver10/schema}SimpleItem[@Name='State']")
            if data_element is None:
                continue
            if "Value" in data_element.attrib and data_element.attrib["Value"] == "true":
                result[rule] = True
                result["Any"] = True
        return result


if __name__ == "__main__":
    with open("tests/messages/Person_on.xml", encoding="utf-8") as my_file:
        _data = my_file.read()
        res = reolink_parse_soap(_data)
        print(res)
