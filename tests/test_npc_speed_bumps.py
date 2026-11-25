"""docs/specs/terrain-following-bodies.md part 1: NPC cars never hop, they slow for a speed bump ahead (game policy)."""
import math
from types import SimpleNamespace

from theroadragetrip.npc import NPC_SPEED_BUMP_MPS, spawn_npc, update_npc
from theroadragetrip.osm import Way
from theroadragetrip.residents import ResidentManager
from theroadragetrip.traffic_world import TrafficWorld
from theroadragetrip.vertical import BumpField


def _drive(bumps, ticks=900):
    ways = [Way(points_m=[(i * 20.0, 0.0), ((i + 1) * 20.0, 0.0)], highway="secondary", half_width_m=4.5, speed_limit_kmh=50) for i in range(15)]
    tw = TrafficWorld(ways)
    residents = ResidentManager()
    _, driver, vehicle = spawn_npc(1, residents, tw, ways, (0.0, 0.0), (300.0, 0.0))
    vehicle.car.speed = 50.0 / 3.6
    manager = SimpleNamespace(bump_field=BumpField(bumps) if bumps else None)
    over, before = [], []
    for _ in range(ticks):
        update_npc(vehicle, driver, 1 / 60, tw, residents, manager=manager)
        if bumps and abs(vehicle.car.x - 150.0) < 1.5:
            over.append(vehicle.car.speed)
        if vehicle.car.x < 100.0:
            before.append(vehicle.car.speed)
        if vehicle.car.x > 160.0:
            break
    return over, before


def test_npc_slows_to_bump_speed_and_never_hops():
    hump = SimpleNamespace(x=150.0, y=0.0, direction_angle=0.0, kind="hump", width_m=6.0)
    over, before = _drive([hump])
    assert over, "the car never reached the bump"
    assert max(over) <= NPC_SPEED_BUMP_MPS + 0.7, f"{max(over) * 3.6:.1f} km/h over the bump"
    assert max(before) > 40 / 3.6, "it cruised before the bump's approach"


def test_no_bump_no_slowdown():
    over, before = _drive([])
    assert min(before[-60:]) > 40 / 3.6


def test_bump_field_ahead_only_on_the_line():
    bump = SimpleNamespace(x=50.0, y=0.0, direction_angle=0.0, kind="hump", width_m=6.0)
    field = BumpField([bump])
    assert field.ahead(0.0, 0.0, 0.0, 30.0) is None  # beyond the reach
    assert math.isclose(field.ahead(10.0, 0.0, 0.0, 60.0), 50.0 - 1.85 - 10.0)  # to the bump's start
    assert field.ahead(0.0, 0.0, math.pi, 30.0) is None  # behind it
    assert field.ahead(0.0, 20.0, 0.0, 30.0) is None  # another street
    assert math.isclose(field.ahead(30.0, 0.0, 0.0, 30.0), 50.0 - 1.85 - 30.0)


def test_a_garage_level_car_ignores_a_surface_bump():
    """The review's level leak: the field is indexed by x, y only, so the NPC's own map level must keep it out."""
    from unittest.mock import MagicMock

    class Spy(BumpField):
        asked = 0

        def ahead(self, *args, **kwargs):
            Spy.asked += 1
            return super().ahead(*args, **kwargs)

    hump = SimpleNamespace(x=150.0, y=0.0, direction_angle=0.0, kind="hump", width_m=6.0)
    ways = [Way(points_m=[(i * 20.0, 0.0), ((i + 1) * 20.0, 0.0)], highway="secondary", half_width_m=4.5, speed_limit_kmh=50) for i in range(15)]
    tw = TrafficWorld(ways)
    residents = ResidentManager()
    _, driver, vehicle = spawn_npc(1, residents, tw, ways, (0.0, 0.0), (300.0, 0.0))
    manager = SimpleNamespace(bump_field=Spy([hump]), population_diagnostics=MagicMock())
    update_npc(vehicle, driver, 1 / 60, tw, residents, manager=manager)
    assert Spy.asked == 1  # a surface car asks the field
    vehicle.car.map_level = -1
    update_npc(vehicle, driver, 1 / 60, tw, residents, manager=manager)
    assert Spy.asked == 1  # a car on a garage level does not


def test_a_narrow_cushion_slows_only_cars_that_ride_it():
    cushion = SimpleNamespace(x=50.0, y=0.0, direction_angle=0.0, kind="cushion", width_m=6.0)
    field = BumpField([cushion])
    assert field.ahead(0.0, 0.0, 0.0, 30.0 + 30.0) is not None  # on its line
    assert field.ahead(0.0, 2.9, 0.0, 60.0) is None  # 2.9 m aside: beside the 1.8 m cushion and its half car width
    assert BumpField([SimpleNamespace(**{**cushion.__dict__, "kind": "table"})]).ahead(0.0, 2.9, 0.0, 60.0) is not None  # a table spans the lane
