"""Multi-point manoeuvres (manoeuvre.py; npc._plan_manoeuvre)."""
import math

from theroadragetrip import manoeuvre
from theroadragetrip.npc import NPCState, update_npc, spawn_npc
from theroadragetrip.osm import Way
from theroadragetrip.physics import min_turn_radius
from theroadragetrip.residents import ResidentManager
from theroadragetrip.traffic_world import TrafficWorld
from theroadragetrip.physics import is_point_on_road


def test_an_about_face_in_a_street_is_a_three_point_turn():
    street = lambda x, y, yaw: abs(y) < 4.0  # a 9 m street: no U-turn in one sweep at 3.7 m
    runs = manoeuvre.plan((0.0, -2.0, 0.0), (0.0, 2.0, math.pi), 3.7, street)
    assert runs is not None and len(runs) >= 3 and runs[1][0][3] == -1  # forward, reverse, forward ...
    assert all(street(x, y, yaw) for run in runs for x, y, yaw, _ in run)
    assert manoeuvre.plan((0.0, -2.0, 0.0), (0.0, 2.0, math.pi), 3.7, lambda x, y, yaw: abs(y) < 2.5) is None  # no room


def test_a_car_facing_the_wrong_way_turns_round_in_the_street_to_set_off():
    """Reviewed driving: from standstill, its route going the other way, a car
    with a real turning circle used to pivot on the spot; it now makes a
    three-point turn, the body on the street throughout."""
    ways = [Way(points_m=[(-200.0, 0.0), (0.0, 0.0), (200.0, 0.0)], highway="residential", half_width_m=4.5)]
    world, residents = TrafficWorld(ways), ResidentManager()
    _, driver, vehicle = spawn_npc(1, residents, world, ways, (0.0, -2.0), (150.0, 0.0))
    vehicle.car.x, vehicle.car.y, vehicle.car.heading, vehicle.car.speed = 0.0, -2.0, math.pi, 0.0  # nose west
    reversed_at_all = False
    for _ in range(30 * 40):
        update_npc(vehicle, driver, 1 / 30, world, residents)
        reversed_at_all |= vehicle.car.speed < -0.1
        assert is_point_on_road(vehicle.x, vehicle.y, ways=ways)
        if math.cos(vehicle.heading) > 0.95 and vehicle.x > 30.0:
            break
    assert reversed_at_all and math.cos(vehicle.heading) > 0.95 and vehicle.x > 30.0  # turned round, and on its way east
    assert vehicle.state != NPCState.CRASHED and min_turn_radius(vehicle.car) > 3.0
