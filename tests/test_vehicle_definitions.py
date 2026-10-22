from theroadragetrip.vehicles.base import VEHICLE_DEFINITIONS, vehicle_definition


def test_builtin_vehicle_definitions_cover_traffic_capabilities():
    assert set(VEHICLE_DEFINITIONS) == {
        "car", "van", "truck", "bus", "tractor", "camper_van", "car_caravan", "motorcycle", "bicycle",
    }
    assert vehicle_definition("car").capacity == 5
    assert vehicle_definition("van").household_eligible
    assert vehicle_definition("truck").max_speed_kmh == 80.0
    assert not vehicle_definition("bus").errand_eligible
    assert vehicle_definition("tractor").max_speed_kmh == 60.0 and vehicle_definition("tractor").traffic_weight > 0.0
    caravan = vehicle_definition("car_caravan")  # 80 km/h: slower than cars, but still motorway traffic (> 70, § 58)
    assert caravan.max_speed_kmh == 80.0 and not caravan.errand_eligible
    assert caravan.length_m == 4.3 and caravan.trailer.kind == "caravan"  # a car, and the caravan a body of its own
    assert vehicle_definition("camper_van").max_speed_kmh is None and vehicle_definition("camper_van").traffic_weight > 0.0
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


def test_holiday_vehicles_are_a_summer_thing():
    import random
    from collections import Counter
    from theroadragetrip.npc import NPCVehicleManager

    manager = NPCVehicleManager(target_count=1)
    random.seed(5)
    summer = Counter(manager._pick_vehicle_type() for _ in range(20000))
    manager.snowy = True
    winter = Counter(manager._pick_vehicle_type() for _ in range(20000))
    holiday = lambda counts: counts["camper_van"] + counts["car_caravan"]
    assert holiday(summer) > 150 and holiday(winter) < holiday(summer) * 0.3
