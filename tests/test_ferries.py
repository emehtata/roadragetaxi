import math
import random
from types import SimpleNamespace

from theroadragetrip.ferries import DOCK_WAIT_S, FERRY_LENGTH_M, FERRY_WIDTH_M, SUMMON_M, FerryManager
from theroadragetrip.osm.build import FERRY_KIND, _is_car_ferry
from theroadragetrip.osm.models import Railway, Water
from theroadragetrip.physics import Car, is_car_fully_in_water, water_ahead_speed_limit

HALF = FERRY_LENGTH_M / 2.0
FAR = 500.0 - HALF  # the far landing's deck centre on a 500 m crossing


def _car(x, y, heading=0.0, speed=0.0):
    return Car(x=x, y=y, heading=heading, speed=speed)


def _route(points):
    return Railway(points_m=points, kind=FERRY_KIND)


def _manager():
    return FerryManager([_route([(0.0, 0.0), (500.0, 0.0)])], rng=random.Random(1))


def _run(mgr, seconds, car=None, npcs=None, dt=0.1):
    for _ in range(int(round(seconds / dt))):
        mgr.update(dt, (0.0, 0.0), car, npcs)


def _until_docked(mgr, ferry, car=None):
    for _ in range(3000):  # ~2 minutes across
        _run(mgr, 0.1, car)
        if ferry.state == "DOCKED":
            return


class FakeNPCs:
    """The NPC vehicle manager's ferry interface."""

    def __init__(self):
        self.vehicles, self.ashore = [], []

    def ferry_car(self, x, y, heading):
        vehicle = SimpleNamespace(car=_car(x, y, heading, 0.0))
        self.vehicles.append(vehicle)
        return vehicle

    def ferry_car_ashore(self, vehicle):
        self.ashore.append(vehicle)


def test_only_ferries_that_carry_cars():
    assert _is_car_ferry({"route": "ferry", "motor_vehicle": "yes"})
    assert _is_car_ferry({"route": "ferry", "ferry": "secondary"})  # Vartsala
    assert not _is_car_ferry({"route": "ferry"})  # a passenger boat
    assert not _is_car_ferry({"route": "ferry", "ferry": "trunk", "motor_vehicle": "no"})
    assert not _is_car_ferry({"route": "ferry", "ferry": "footway"})
    assert not _is_car_ferry({"highway": "secondary"})


def test_the_ferry_is_at_the_landing_the_taxi_drives_to():
    mgr = _manager()
    _run(mgr, 2.5)
    (ferry,) = mgr.ferries
    assert ferry.landing == 0
    _run(mgr, 0.1, _car(500.0 + SUMMON_M - 20.0, 0.0, math.pi, 10.0))  # coming to the far landing
    assert ferry.landing == 1 and math.isclose(ferry.s, FAR)


def test_it_waits_for_the_taxi_and_leaves_once_the_taxi_is_aboard():
    mgr = _manager()
    _run(mgr, 2.5)
    (ferry,) = mgr.ferries
    car = _car(-20.0, 0.0, 0.0, 0.0)  # parked by the landing
    _run(mgr, DOCK_WAIT_S * 3, car)
    assert ferry.state == "DOCKED"  # however long the taxi takes
    car.x, car.y, car.heading = HALF, 2.0, 0.3  # stopped on the deck
    _run(mgr, 5.0, car)
    assert ferry.state == "CROSSING"
    _until_docked(mgr, ferry, car)
    assert ferry.landing == 1
    assert math.isclose(car.x, FAR, abs_tol=0.01) and math.isclose(car.y, 2.0, abs_tol=0.01)
    assert math.isclose(car.heading, 0.3, abs_tol=1e-6)
    _run(mgr, DOCK_WAIT_S * 2, car)  # still aboard on the far side: it does not take the taxi back
    assert ferry.state == "DOCKED"


def test_it_never_leaves_with_a_car_half_on_the_ramp():
    mgr = _manager()
    _run(mgr, 2.5)
    car = _car(0.0, 0.0, 0.0, 0.0)  # half on the deck, half on the landing
    _run(mgr, DOCK_WAIT_S + 5.0, car)
    assert mgr.ferries[0].state == "DOCKED"


def test_away_from_the_taxi_it_shuttles():
    mgr = _manager()
    _run(mgr, 2.5)
    _run(mgr, DOCK_WAIT_S + 1.0, _car(5000.0, 0.0))
    assert mgr.ferries[0].state == "CROSSING"


def test_the_side_rails_stop_a_car_the_ends_do_not():
    mgr = _manager()
    _run(mgr, 2.5)
    rail = FERRY_WIDTH_M / 2.0
    assert mgr.blocks(_car(HALF, rail + 0.5, 0.0), (HALF, rail + 1.5))  # from the water onto the deck
    assert mgr.blocks(_car(HALF, rail + 0.5, 0.0), (HALF, rail - 1.2))  # off the side into the sea
    assert not mgr.blocks(_car(1.0, 0.0, 0.0), (-1.0, 0.0))  # over the ramp
    assert not mgr.blocks(_car(HALF + 1.0, 1.0, 0.0), (HALF, 1.0))  # along the deck


def test_npc_cars_arrive_aboard_and_drive_off_once_the_taxi_moves_aside():
    mgr = _manager()
    npcs = FakeNPCs()
    _run(mgr, 2.5, None, npcs)
    (ferry,) = mgr.ferries
    for _ in range(50):  # summoned to and fro until it brings cars
        _run(mgr, 0.1, _car(520.0, 0.0), npcs)
        if ferry.riders:
            break
        _run(mgr, 0.1, _car(-20.0, 0.0), npcs)
        if ferry.riders:
            break
    assert ferry.riders
    end_x, sign = (0.0, -1) if ferry.landing == 0 else (500.0, 1)
    blocking = _car(end_x + sign * 3.0, ferry.riders[0].across)  # on the ramp, in their way
    _run(mgr, 10.0, blocking, npcs)
    assert not npcs.ashore
    _run(mgr, 40.0, _car(end_x + sign * 100.0, 0.0), npcs)  # driven off, out of the way
    assert len(npcs.ashore) == len(npcs.vehicles) and not ferry.riders
    for vehicle in npcs.ashore:
        assert (vehicle.car.x - end_x) * sign > 0.0  # off the deck, on the landing


def test_the_other_directions_way_has_no_ferry_of_its_own():
    # Prostvik-Lillmalo: one OSM way each way, a few metres apart
    mgr = FerryManager([_route([(0.0, 0.0), (500.0, 0.0)]), _route([(495.0, 12.0), (5.0, 12.0)]),
                        _route([(0.0, 900.0), (20.0, 900.0)])])  # too short to cross
    assert len(mgr.routes) == 1


def test_the_deck_is_dry_for_the_water_brake_and_sinking():
    sea = [Water(points_m=[(-100.0, -100.0), (100.0, -100.0), (100.0, 100.0), (-100.0, 100.0)], kind="sea", is_polygon=True)]
    car = _car(0.0, 0.0, 0.0, 8.0)
    assert is_car_fully_in_water(car, sea)
    assert not is_car_fully_in_water(car, sea, dry=lambda x, y: abs(x) < 25.0)
    assert water_ahead_speed_limit(car, sea, 7) is not None
    assert water_ahead_speed_limit(car, sea, 7, dry=lambda x, y: abs(x) < 25.0) is None
