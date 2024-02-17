import sys
sys.path.append('../')
import reolink_utils

def test_several_true():
    with open("./messages/several_true.xml", "r") as file:
        #{'Motion': True, 'FaceDetect': False, 'PeopleDetect': True, 'VehicleDetect': False, 'DogCatDetect': False, 'MotionAlarm': True, 'Visitor': True, 'Any': True}
        data = file.read()
        parse_result = reolink_utils.reolink_parse_soap(data)

    assert parse_result["Motion"] == True
    assert parse_result["FaceDetect"] == False
    assert parse_result["PeopleDetect"] == True
    assert parse_result["VehicleDetect"] == False
    assert parse_result["DogCatDetect"] == False
    assert parse_result["MotionAlarm"] == True
    assert parse_result["Visitor"] == True
    assert parse_result["Any"] == True


def test_doorbell_on():
    #{'Motion': False, 'FaceDetect': False, 'PeopleDetect': False, 'VehicleDetect': False, 'DogCatDetect': False, 'MotionAlarm': False, 'Visitor': True, 'Any': True}
    with open("./messages/Doorbell_on.xml", "r") as file:
        data = file.read()
        parse_result = reolink_utils.reolink_parse_soap(data)

    assert parse_result["Motion"] == False
    assert parse_result["FaceDetect"] == False
    assert parse_result["PeopleDetect"] == False
    assert parse_result["VehicleDetect"] == False
    assert parse_result["DogCatDetect"] == False
    assert parse_result["MotionAlarm"] == False
    assert parse_result["Visitor"] == True
    assert parse_result["Any"] == True

def test_all_false():
    #{'Motion': False, 'FaceDetect': False, 'PeopleDetect': False, 'VehicleDetect': False, 'DogCatDetect': False, 'MotionAlarm': False, 'Visitor': False, 'Any': False}
    with open("./messages/all_false.xml", "r") as file:
        data = file.read()
        parse_result = reolink_utils.reolink_parse_soap(data)
        print(parse_result)

    assert parse_result["Motion"] == False
    assert parse_result["FaceDetect"] == False
    assert parse_result["PeopleDetect"] == False
    assert parse_result["VehicleDetect"] == False
    assert parse_result["DogCatDetect"] == False
    assert parse_result["MotionAlarm"] == False
    assert parse_result["Visitor"] == False
    assert parse_result["Any"] == False

def test_motion_visitor_on():
    #{'Motion': True, 'FaceDetect': False, 'PeopleDetect': False, 'VehicleDetect': False, 'DogCatDetect': False, 'MotionAlarm': True, 'Visitor': True, 'Any': True}
    with open("./messages/Motion_visitor_on.xml", "r") as file:
        data = file.read()
        parse_result = reolink_utils.reolink_parse_soap(data)

    assert parse_result["Motion"] == True
    assert parse_result["FaceDetect"] == False
    assert parse_result["PeopleDetect"] == False
    assert parse_result["VehicleDetect"] == False
    assert parse_result["DogCatDetect"] == False
    assert parse_result["MotionAlarm"] == True
    assert parse_result["Visitor"] == True
    assert parse_result["Any"] == True

def test_person_on():
    #{'Motion': False, 'FaceDetect': False, 'PeopleDetect': True, 'VehicleDetect': False, 'DogCatDetect': False, 'MotionAlarm': False, 'Visitor': False, 'Any': True}
    with open("./messages/Person_on.xml", "r") as file:
        data = file.read()
        parse_result = reolink_utils.reolink_parse_soap(data)

    assert parse_result["Motion"] == False
    assert parse_result["FaceDetect"] == False
    assert parse_result["PeopleDetect"] == True
    assert parse_result["VehicleDetect"] == False
    assert parse_result["DogCatDetect"] == False
    assert parse_result["MotionAlarm"] == False
    assert parse_result["Visitor"] == False
    assert parse_result["Any"] == True
