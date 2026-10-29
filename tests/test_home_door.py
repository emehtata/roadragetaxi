"""Going into houses (E on foot) and choosing one as home from inside (H): the
server decides, the client draws the interior."""
import math
from types import SimpleNamespace

from shapely.geometry import Point, Polygon

from theroadragetrip.home import DOOR_REACH_M, home_building_key, plan_entrance
from theroadragetrip.interior import generate_floor_plan
from theroadragetrip.server import SimulationServer
from test_home import _server, press


def _street(tmp_path, home=True):
    """Two identical houses (-7..7 and 93..107, 5..15), each with its yard bay at y 0;
    the first is home unless `home` is False."""
    server = _server(tmp_path)
    if home:
        server.car.x, server.car.y = 0, 0
        press(server)
    server.world.player_pedestrian = SimpleNamespace(x=0.0, y=-20.0, heading=0.0, speed=0.0)
    server._on_foot, server._inside = True, None
    return server


def _house(server, x):
    return next(b for b in server.world.building_grid.ways_in_rect(x - 1, 9, x + 1, 11))


def _door(server, x=0):
    return SimulationServer._house_door(server, _house(server, x))


def _at(server, x, y):
    server.world.player_pedestrian.x, server.world.player_pedestrian.y = x, y


def _key(server, name):
    server.world.taxi_mgr.notification_msg = ""
    getattr(SimulationServer, name)(server)
    return server.world.taxi_mgr.notification_msg


def test_front_door_is_on_the_house_wall_toward_its_yard(tmp_path):
    server = _street(tmp_path)
    (mx, my), (ox, oy) = _door(server)
    house = Polygon([(-7, 5), (7, 5), (7, 15), (-7, 15)])
    assert house.exterior.distance(Point(mx, my)) < 1e-6
    # The front door opens into the hall, whose ends are the short walls: the half toward the yard.
    assert abs(mx) == 7 and my < 10.5
    assert not house.contains(Point(ox, oy)) and math.dist((mx, my), (ox, oy)) == 1.0
    neighbour = _door(server, 100)
    assert neighbour[0][0] - 100 == mx  # the same end wall (each house has its own seed for the rest)
    assert _door(server) is _door(server)  # cached


def test_in_the_taxi_or_out_of_reach_nobody_goes_in(tmp_path):
    server = _street(tmp_path)
    door, _ = _door(server)
    _at(server, *door)
    server._on_foot = False
    assert _key(server, "_home_door_pressed") and server._inside is None
    server._on_foot = True
    _at(server, door[0], door[1] - DOOR_REACH_M - 0.5)
    assert _key(server, "_home_door_pressed") and server._inside is None
    state = SimulationServer._home_door_state(server)
    assert (state["indoors"], state["available"], state["is_home"]) == (False, False, False)
    assert [row[:2] for row in state["doors"]] == [[round(door[0], 2), round(door[1], 2)]]  # marked, not yet in reach
    _at(server, 0, -40)
    assert SimulationServer._home_door_state(server)["doors"] == []


def test_only_selected_home_opens_and_other_houses_have_no_prompt(tmp_path):
    server = _street(tmp_path)
    for x, allowed in [(0, True), (100, False)]:
        door, _ = _door(server, x)
        _at(server, door[0], door[1] - 1.5)
        state = SimulationServer._home_door_state(server)
        assert state["available"] == allowed and state["is_home"] == allowed
        if not allowed:
            assert state["doors"] == []
            assert _key(server, "_home_door_pressed") and server._inside is None
            continue
        assert state["doors"][0][3] and len(state["doors"]) == 1
        assert _key(server, "_home_door_pressed") == "" and server._inside[0] is _house(server, x)
        state = SimulationServer._home_door_state(server)
        assert (state["indoors"], state["available"], state["is_home"], state["doors"]) == (True, False, True, [])
        assert SimulationServer._home_floor_plan(server)["building_id"] == home_building_key(_house(server, x))
        _key(server, "_home_door_pressed")


def test_without_a_home_any_house_can_be_viewed(tmp_path):
    server = _street(tmp_path, home=False)
    for x in [0, 100]:
        _at(server, *_door(server, x)[0])
        assert SimulationServer._home_door_state(server)["available"]
        _key(server, "_home_door_pressed")
        assert server._inside[0] is _house(server, x)
        _key(server, "_home_door_pressed")


def test_position_only_saved_home_also_restricts_entry(tmp_path):
    server = _street(tmp_path)
    server._home_building_key = None
    for x, allowed in [(0, True), (100, False)]:
        _at(server, *_door(server, x)[0])
        state = SimulationServer._home_door_state(server)
        assert state["available"] == allowed and state["is_home"] == allowed
        _key(server, "_home_door_pressed")
        assert (server._inside is not None) == allowed
        if allowed:
            _key(server, "_home_door_pressed")


def test_leaving_returns_to_the_doorstep_every_time(tmp_path):
    server = _street(tmp_path)
    door, doorstep = _door(server)
    _at(server, door[0], door[1] - 1.5)
    _key(server, "_home_door_pressed")
    assert server.audio.sounds[-1] == ("pedestrian.front_door", door)  # the door sounds where it is
    for _ in range(3):  # repeated visits: one state, the same doorstep
        _key(server, "_home_door_pressed")
        assert server._inside is None and server._on_foot
        assert (server.world.player_pedestrian.x, server.world.player_pedestrian.y) == doorstep
        _key(server, "_home_door_pressed")
        assert server._inside is not None


def test_h_inside_selects_home_and_replacing_it_requires_confirmation_in_yard(tmp_path):
    from theroadragetrip.home import load_home, load_home_building_key
    server = _street(tmp_path, home=False)
    _at(server, *_door(server, 100)[0])
    _key(server, "_home_door_pressed")
    assert _key(server, "_home_pressed") and server._home_building_key == home_building_key(_house(server, 100))
    assert server._home[:2] == (100, 0)  # the taxi comes home to the yard bay
    assert load_home_building_key(server.homes_file, "Oulu") == server._home_building_key
    _key(server, "_home_door_pressed")
    server._on_foot = False
    server.car.x, server.car.y = 0, 0
    _key(server, "_home_pressed")  # a home already: H again in the new yard to move
    assert server._home_building_key == home_building_key(_house(server, 100))
    _key(server, "_home_pressed")
    assert server._home_building_key == home_building_key(_house(server, 0))
    assert load_home(server.homes_file, "Oulu")[:2] == (0, 0)


def test_h_inside_a_house_without_a_bay_uses_the_doorstep(tmp_path):
    server = _street(tmp_path, home=False)
    server.world.parking_spaces = []
    door, doorstep = _door(server)
    _at(server, *door)
    _key(server, "_home_door_pressed")
    _key(server, "_home_pressed")
    assert server._home[:2] == doorstep


def test_command_flag_is_one_press_and_movement_waits_indoors(tmp_path, monkeypatch):
    from test_server_headless import _build_server
    from theroadragetrip.simulation import PlayerCommand
    server = _build_server(tmp_path, monkeypatch)
    player = server.world.player_pedestrian
    server._on_foot = True
    outside = (player.x + 1.0, player.y)
    server._inside = (None, ((player.x, player.y), outside))
    before = (player.x, player.y)
    server._latest_command = PlayerCommand(forward=1.0)
    for _ in range(10):
        server.tick(1 / 30)
    assert (player.x, player.y) == before and server._inside is not None
    server._pending_home_doors = 1
    server.tick(1 / 30)
    assert server._inside is None and server._pending_home_doors == 0
    assert (player.x, player.y) != before  # on the doorstep, walking again


def test_plan_origin_maps_the_front_door_to_the_map():
    house = [(450000, 7210005), (450014, 7210005), (450014, 7210015), (450000, 7210015)]
    plan = generate_floor_plan("house", house, (450016, 7210010))
    door, doorstep = plan_entrance(plan)
    assert Polygon(house).exterior.distance(Point(door)) < 1e-6
    assert door[0] == 450014 and doorstep[0] == 450015  # the east end, toward the given entrance, stepping out
    assert generate_floor_plan("house", house, (450016, 7210010)) == plan
