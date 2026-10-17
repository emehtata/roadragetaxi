import math
from types import SimpleNamespace

from theroadragetrip.physics import Car
from theroadragetrip.osm import Way, YieldSign
from theroadragetrip.traffic_rules import crossing_yield_decision


def cars():
    east = Car(-15.0, -2.0, 0.0, 8.0)
    north = Car(2.0, -15.0, math.pi / 2.0, 8.0)
    east.way = Way([(-100, 0), (100, 0)], "residential", 3.5)
    north.way = Way([(0, -100), (0, 100)], "residential", 3.5)
    return east, north


def test_right_hand_traffic_has_priority_without_signs():
    east, north = cars()
    decision = crossing_yield_decision(east, [north])
    assert decision is not None
    assert decision.reason == "yielding to traffic from right"
    assert decision.target_speed_mps < east.speed
    assert crossing_yield_decision(north, [east]) is None
    east.x = -5.5
    assert crossing_yield_decision(east, [north]).target_speed_mps == 0.0
    north.y = 10.0  # the other car has cleared the crossing
    assert crossing_yield_decision(east, [north]) is None


def test_signed_approach_does_not_take_priority_from_the_right():
    east, north = cars()
    sign = YieldSign(2.0, -8.0, direction_angle=math.pi / 2.0)
    assert crossing_yield_decision(east, [north], signs=[sign]) is None
    assert crossing_yield_decision(north, [east], signs=[sign]) is not None


def test_priority_road_overrides_default_right_hand_rule():
    east, north = cars()
    east.way.priority_road = True
    assert crossing_yield_decision(east, [north]) is None
    assert crossing_yield_decision(north, [east]) is not None


def test_completed_stop_does_not_remove_crossing_yield_or_repeat_after_map_refresh():
    from theroadragetrip.osm import StopSign
    from theroadragetrip.traffic_rules import stop_sign_decision
    east, north = cars()
    east.speed = 0
    sign = StopSign(east.x + east.length_m / 2 + 1, east.y, id=9, direction_angle=0)
    driver = SimpleNamespace(stop_sign_key=None, stop_sign_satisfied=False)
    assert stop_sign_decision(east, driver, [sign]).target_speed_mps == 0
    assert driver.stop_sign_satisfied
    refreshed = StopSign(sign.x, sign.y, id=9, direction_angle=0)
    assert stop_sign_decision(east, driver, [refreshed]) is None
    assert crossing_yield_decision(east, [north], signs=[refreshed]) is not None
    stop_sign_decision(east, driver, [])
    assert not driver.stop_sign_satisfied


def test_parallel_parked_and_different_level_vehicles_do_not_cause_yielding():
    east, north = cars()
    north.heading = 0.0
    assert crossing_yield_decision(east, [north]) is None
    north.heading = math.pi / 2.0
    north.state = SimpleNamespace(value="PARKED")
    assert crossing_yield_decision(east, [north]) is None
    del north.state
    north.way.layer = 1
    assert crossing_yield_decision(east, [north]) is None


def test_two_npcs_cross_safely_and_the_yielding_driver_resumes():
    from theroadragetrip.npc import NPCVehicleManager, NPCState, Driver, PathPoint, place_parked_npc
    from theroadragetrip.residents import ResidentManager
    from theroadragetrip.traffic_world import TrafficWorld

    east, north = cars()
    residents = ResidentManager()
    manager = NPCVehicleManager(target_count=0, min_count=0)
    world = TrafficWorld([east.way, north.way])
    for index, car in enumerate((east, north), 1):
        vehicle = place_parked_npc(index, (car.x, car.y), None)
        vehicle.car.heading = car.heading
        vehicle.car.speed = car.speed
        vehicle.way = car.way
        vehicle.state = NPCState.CRUISING
        resident = residents.create(mode="driving")
        vehicle.owner_id = resident.resident_id
        resident.active_vehicle_id = index
        end = (100.0, car.y) if index == 1 else (car.x, 100.0)
        path = [PathPoint(car.x, car.y, car.way), PathPoint(*end, car.way)]
        manager.vehicles.append(vehicle)
        manager.drivers[index] = Driver(resident.resident_id, index, path, end, current_way=car.way)
    yielded = False
    for _ in range(300):
        manager.update(1.0 / 30.0, 0.0, 0.0, residents, world, world.ways)
        yielded |= "yielding" in manager.drivers[1].decision.reason
        assert all(v.state != NPCState.CRASHED for v in manager.vehicles)
    assert yielded
    assert manager.vehicles[0].x > 10.0
    assert manager.vehicles[1].y > 10.0
