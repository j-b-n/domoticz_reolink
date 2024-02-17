import sys
sys.path.append('../')
import reolink_utils  # noqa: E402


def test_several_true():
    # {'Motion': True, 'FaceDetect': False, 'PeopleDetect': True, 'VehicleDetect': False,
    #  'DogCatDetect': False, 'MotionAlarm': True, 'Visitor': True, 'Any': True}
    with open("./tests/messages/several_true.xml", "r") as file:
        data = file.read()
        parse_result = reolink_utils.reolink_parse_soap(data)

    assert parse_result["Motion"] is True
    assert parse_result["FaceDetect"] is False
    assert parse_result["PeopleDetect"] is True
    assert parse_result["VehicleDetect"] is False
    assert parse_result["DogCatDetect"] is False
    assert parse_result["MotionAlarm"] is True
    assert parse_result["Visitor"] is True
    assert parse_result["Any"] is True


def test_doorbell_on():
    # {'Motion': False, 'FaceDetect': False, 'PeopleDetect': False, 'VehicleDetect': False,
    #  'DogCatDetect': False, 'MotionAlarm': False, 'Visitor': True, 'Any': True}
    with open("./tests/messages/Doorbell_on.xml", "r") as file:
        data = file.read()
        parse_result = reolink_utils.reolink_parse_soap(data)

    assert parse_result["Motion"] is False
    assert parse_result["FaceDetect"] is False
    assert parse_result["PeopleDetect"] is False
    assert parse_result["VehicleDetect"] is False
    assert parse_result["DogCatDetect"] is False
    assert parse_result["MotionAlarm"] is False
    assert parse_result["Visitor"] is True
    assert parse_result["Any"] is True


def test_all_false():
    # {'Motion': False, 'FaceDetect': False, 'PeopleDetect': False, 'VehicleDetect': False,
    #  'DogCatDetect': False, 'MotionAlarm': False, 'Visitor': False, 'Any': False}
    with open("./tests/messages/all_false.xml", "r") as file:
        data = file.read()
        parse_result = reolink_utils.reolink_parse_soap(data)

    assert parse_result["Motion"] is False
    assert parse_result["FaceDetect"] is False
    assert parse_result["PeopleDetect"] is False
    assert parse_result["VehicleDetect"] is False
    assert parse_result["DogCatDetect"] is False
    assert parse_result["MotionAlarm"] is False
    assert parse_result["Visitor"] is False
    assert parse_result["Any"] is False


def test_motion_visitor_on():
    # {'Motion': True, 'FaceDetect': False, 'PeopleDetect': False, 'VehicleDetect': False,
    #  'DogCatDetect': False, 'MotionAlarm': True, 'Visitor': True, 'Any': True}
    with open("./tests/messages/Motion_visitor_on.xml", "r") as file:
        data = file.read()
        parse_result = reolink_utils.reolink_parse_soap(data)

    assert parse_result["Motion"] is True
    assert parse_result["FaceDetect"] is False
    assert parse_result["PeopleDetect"] is False
    assert parse_result["VehicleDetect"] is False
    assert parse_result["DogCatDetect"] is False
    assert parse_result["MotionAlarm"] is True
    assert parse_result["Visitor"] is True
    assert parse_result["Any"] is True


def test_person_on():
    # {'Motion': False, 'FaceDetect': False, 'PeopleDetect': True, 'VehicleDetect': False,
    #  'DogCatDetect': False, 'MotionAlarm': False, 'Visitor': False, 'Any': True}
    with open("./tests/messages/Person_on.xml", "r") as file:
        data = file.read()
        parse_result = reolink_utils.reolink_parse_soap(data)

    assert parse_result["Motion"] is False
    assert parse_result["FaceDetect"] is False
    assert parse_result["PeopleDetect"] is True
    assert parse_result["VehicleDetect"] is False
    assert parse_result["DogCatDetect"] is False
    assert parse_result["MotionAlarm"] is False
    assert parse_result["Visitor"] is False
    assert parse_result["Any"] is True
