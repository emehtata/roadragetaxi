from theroadragetrip.vehicles.base import VEHICLE_DEFINITIONS, vehicle_definition


def test_builtin_vehicle_definitions_cover_traffic_capabilities():
    assert set(VEHICLE_DEFINITIONS) == {
        "car", "van", "truck", "bus", "tractor", "motorcycle", "bicycle",
    }
    assert vehicle_definition("car").capacity == 5
    assert vehicle_definition("van").household_eligible
    assert vehicle_definition("truck").max_speed_kmh == 80.0
    assert not vehicle_definition("bus").errand_eligible
    assert vehicle_definition("tractor").max_speed_kmh == 60.0 and vehicle_definition("tractor").traffic_weight > 0.0
    assert vehicle_definition("motorcycle").experimental
    assert not vehicle_definition("bicycle").is_road_vehicle
    assert not vehicle_definition("bicycle").requires_parking


def test_unknown_vehicle_uses_car_definition():
    assert vehicle_definition("unknown") is VEHICLE_DEFINITIONS["car"]


def test_snow_brings_out_more_tractors():
    import random
    from theroadragetrip.npc import NPCVehicleManager

    manager = NPCVehicleManager(target_count=0)
    random.seed(1)
    clear = sum(manager._pick_vehicle_type() == "tractor" for _ in range(4000))
    manager.snowy = True
    snowing = sum(manager._pick_vehicle_type() == "tractor" for _ in range(4000))
    assert clear < 160 and snowing > 400  # ~2% vs ~14% of traffic
