import math

from theroadragetrip.ferries import DOCK_WAIT_S, FERRY_LENGTH_M, FerryManager
from theroadragetrip.osm.build import FERRY_KIND, _is_car_ferry
from theroadragetrip.osm.models import Railway, Water
from theroadragetrip.physics import Car, is_car_fully_in_water, water_ahead_speed_limit


def _route(points):
    return Railway(points_m=points, kind=FERRY_KIND)


def _run(mgr, seconds, car=None, dt=0.1):
    for _ in range(int(seconds / dt)):
        mgr.update(dt, (0.0, 0.0), car)


def test_only_ferries_that_carry_cars():
    assert _is_car_ferry({"route": "ferry", "motor_vehicle": "yes"})
    assert _is_car_ferry({"route": "ferry", "ferry": "secondary"})  # Vartsala
    assert not _is_car_ferry({"route": "ferry"})  # a passenger boat
    assert not _is_car_ferry({"route": "ferry", "ferry": "trunk", "motor_vehicle": "no"})
    assert not _is_car_ferry({"route": "ferry", "ferry": "footway"})
    assert not _is_car_ferry({"highway": "secondary"})


def test_the_taxi_stopped_on_the_deck_crosses_with_the_ferry():
    mgr = FerryManager([_route([(0.0, 0.0), (500.0, 0.0)])])
    _run(mgr, 2.5)
    (ferry,) = mgr.ferries
    car = Car(x=FERRY_LENGTH_M / 2.0, y=2.0, heading=0.3, speed=0.0)
    assert mgr.on_deck(car.x, car.y) and ferry.state == "DOCKED"
    _run(mgr, 5.0, car)  # stopped on the deck: it leaves long before DOCK_WAIT_S
    assert ferry.state == "CROSSING"
    for _ in range(3000):  # ~2 minutes across
        _run(mgr, 0.1, car)
        if ferry.state == "DOCKED":
            break
    assert ferry.state == "DOCKED"
    assert math.isclose(car.x, 500.0 - FERRY_LENGTH_M / 2.0, abs_tol=0.01) and math.isclose(car.y, 2.0, abs_tol=0.01)
    assert math.isclose(car.heading, 0.3, abs_tol=1e-6)
    _run(mgr, DOCK_WAIT_S - 5.0, car)  # still aboard on the far side: it does not hurry back
    assert ferry.state == "DOCKED"


def test_it_never_leaves_with_a_car_half_on_the_ramp():
    mgr = FerryManager([_route([(0.0, 0.0), (500.0, 0.0)])])
    _run(mgr, 2.5)
    car = Car(x=0.0, y=0.0, heading=0.0, speed=0.0)  # half on the deck, half on the landing
    _run(mgr, DOCK_WAIT_S + 5.0, car)
    assert mgr.ferries[0].state == "DOCKED"
    car.x = -10.0  # backed off the deck
    _run(mgr, 1.0, car)
    assert mgr.ferries[0].state == "CROSSING"


def test_the_other_directions_way_has_no_ferry_of_its_own():
    # Prostvik-Lillmalo: one OSM way each way, a few metres apart
    mgr = FerryManager([_route([(0.0, 0.0), (500.0, 0.0)]), _route([(495.0, 12.0), (5.0, 12.0)]),
                        _route([(0.0, 900.0), (20.0, 900.0)])])  # too short to cross
    assert len(mgr.routes) == 1


def test_the_deck_is_dry_for_the_water_brake_and_sinking():
    sea = [Water(points_m=[(-100.0, -100.0), (100.0, -100.0), (100.0, 100.0), (-100.0, 100.0)], kind="sea", is_polygon=True)]
    car = Car(x=0.0, y=0.0, heading=0.0, speed=8.0)
    assert is_car_fully_in_water(car, sea)
    assert not is_car_fully_in_water(car, sea, dry=lambda x, y: abs(x) < 25.0)
    assert water_ahead_speed_limit(car, sea, 7) is not None
    assert water_ahead_speed_limit(car, sea, 7, dry=lambda x, y: abs(x) < 25.0) is None
