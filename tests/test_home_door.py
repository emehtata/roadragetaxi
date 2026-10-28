"""Entering and leaving the home (E on foot): the server decides, the client draws the interior."""
import math
from types import SimpleNamespace

from shapely.geometry import Point, Polygon

from theroadragetrip.home import DOOR_REACH_M, plan_entrance
from theroadragetrip.interior import generate_floor_plan
from theroadragetrip.server import SimulationServer
from test_home import _server, press


def _home_server(tmp_path):
    """Home chosen at the yard at (0, 0): the house is (-7..7, 5..15), its neighbour at x 100."""
    server = _server(tmp_path)
    server.car.x, server.car.y = 0, 0
    press(server)
    server.world.player_pedestrian = SimpleNamespace(x=0.0, y=0.0, heading=0.0, speed=0.0)
    server._on_foot, server._indoors, server._home_entrance_cache = True, False, None
    return server


def _door(server):
    return SimulationServer._home_entrance(server)


def _at(server, x, y):
    server.world.player_pedestrian.x, server.world.player_pedestrian.y = x, y


def _e(server):
    server.world.taxi_mgr.notification_msg = ""
    SimulationServer._home_door_pressed(server)
    return server.world.taxi_mgr.notification_msg


def test_entrance_is_on_the_home_wall_nearest_the_yard(tmp_path):
    server = _home_server(tmp_path)
    (mx, my), (ox, oy) = _door(server)
    house = Polygon([(-7, 5), (7, 5), (7, 15), (-7, 15)])
    assert house.exterior.distance(Point(mx, my)) < 1e-6
    # The front door opens into the hall, whose ends are the short walls: the lower half, toward the yard.
    assert abs(mx) == 7 and my < 10.5
    assert not house.contains(Point(ox, oy)) and math.dist((mx, my), (ox, oy)) == 1.0


def test_no_home_in_car_far_or_at_the_neighbours_cannot_enter(tmp_path):
    server = _home_server(tmp_path)
    door, _ = _door(server)
    _at(server, *door)
    server._on_foot = False
    assert _e(server) and not server._indoors  # in the taxi
    server._on_foot = True
    _at(server, door[0], door[1] - DOOR_REACH_M - 0.5)
    assert _e(server) and not server._indoors  # out of reach
    _at(server, door[0] + 100, door[1])  # the same spot at the neighbour's identical house
    assert not SimulationServer._home_door_available(server) and _e(server) and not server._indoors
    homeless = _home_server(tmp_path)
    homeless._home, homeless._home_entrance_cache = None, None
    _at(homeless, *door)
    assert _e(homeless) and not homeless._indoors


def test_enter_freezes_the_map_player_and_leaving_returns_to_the_doorstep(tmp_path):
    server = _home_server(tmp_path)
    door, doorstep = _door(server)
    _at(server, door[0], door[1] - 1.5)
    assert SimulationServer._home_door_available(server)
    assert _e(server) == "" and server._indoors
    assert not SimulationServer._home_door_available(server)  # no second entry from inside
    for _ in range(3):  # repeated cycles keep one state and the same doorstep
        _e(server)
        assert not server._indoors and server._on_foot
        assert (server.world.player_pedestrian.x, server.world.player_pedestrian.y) == doorstep
        assert SimulationServer._home_door_available(server)
        _e(server)
        assert server._indoors


def test_command_flag_is_one_press_and_movement_waits_indoors(tmp_path, monkeypatch):
    from test_server_headless import _build_server
    server = _build_server(tmp_path, monkeypatch)
    server._indoors = True
    server._home_entrance_cache = None
    player = server.world.player_pedestrian
    server._on_foot = True
    before = (player.x, player.y)
    from theroadragetrip.simulation import PlayerCommand
    server._latest_command = PlayerCommand(forward=1.0)
    for _ in range(10):
        server.tick(1 / 30)
    assert (player.x, player.y) == before and server._indoors  # no home here: nothing moves the player
    server._pending_home_doors = 1
    server.tick(1 / 30)
    assert not server._indoors and server._pending_home_doors == 0
    server.tick(1 / 30)
    assert (player.x, player.y) != before  # walking again outside


def test_plan_origin_maps_the_front_door_to_the_map():
    house = [(450000, 7210005), (450014, 7210005), (450014, 7210015), (450000, 7210015)]
    plan = generate_floor_plan("house", house, (450016, 7210010))
    door, doorstep = plan_entrance(plan)
    assert Polygon(house).exterior.distance(Point(door)) < 1e-6
    assert door[0] == 450014 and doorstep[0] == 450015  # the east end, toward the given entrance, stepping out
    assert generate_floor_plan("house", house, (450016, 7210010)) == plan
