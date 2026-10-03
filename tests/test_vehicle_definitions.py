from theroadragetrip.vehicles.base import VEHICLE_DEFINITIONS, vehicle_definition


def test_builtin_vehicle_definitions_cover_traffic_capabilities():
    assert set(VEHICLE_DEFINITIONS) == {
        "car", "van", "truck", "bus", "motorcycle", "bicycle",
    }
    assert vehicle_definition("car").capacity == 5
    assert vehicle_definition("van").household_eligible
    assert vehicle_definition("truck").max_speed_kmh == 80.0
    assert not vehicle_definition("bus").errand_eligible
    assert vehicle_definition("motorcycle").experimental
    assert not vehicle_definition("bicycle").is_road_vehicle
    assert not vehicle_definition("bicycle").requires_parking


def test_unknown_vehicle_uses_car_definition():
    assert vehicle_definition("unknown") is VEHICLE_DEFINITIONS["car"]
