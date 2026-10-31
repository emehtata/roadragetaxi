"""Geometry contracts, yard binding and the actual interior request envelope."""
from itertools import combinations

import pytest
from shapely.affinity import rotate, scale, translate
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from theroadragetrip.interior import GENERATOR_VERSION, _generate_cached, generate_floor_plan

REFERENCE_L = [(0, 0), (14, 0), (14, 6.5), (5.5, 6.5), (5.5, 13), (0, 13)]

# Three mapped compact L-shaped houses side by side (local metres, origin and
# address left out on purpose: real homes).
COMPACT_L_HOUSES = [
    [(42.78, 10.53), (40.55, 17.52), (35.87, 16.03), (34.10, 21.61), (43.63, 24.64), (47.62, 12.07)],
    [(20.28, 3.66), (18.68, 9.99), (13.45, 8.67), (12.33, 13.80), (11.97, 14.57), (22.96, 17.32), (26.02, 5.10)],
    [(10.06, 14.32), (10.31, 13.34), (13.29, 1.58), (7.04, 0.00), (5.33, 6.73), (1.52, 5.77), (0.77, 8.73), (0.00, 11.77)],
]

RECTANGLE = [(0, 0), (14, 0), (14, 10), (0, 10)]
FOOTPRINTS = [
    RECTANGLE, REFERENCE_L,
    *COMPACT_L_HOUSES,
    [(0, 0), (14, 1), (12, 11), (2, 10), (-1, 5)],
    [(0, 0), (14, 0), (14, 7), (8, 7), (8, 12), (0, 12)],
    [(0, 0), (3, 0), (3, 2), (0, 2)],
    [(0, 0), (16, 0), (16, 2), (0, 2)],
    [(0, 0), (14, 0), (14, 12), (10, 12), (10, 3), (4, 3), (4, 12), (0, 12)],
]


@pytest.mark.parametrize('points', FOOTPRINTS)
@pytest.mark.parametrize('angle', [0, 31, 90])
def test_geometry_contains_rooms_connected_doors_and_clear_furniture(points, angle):
    source = translate(rotate(Polygon(points), angle), 450000, 7210000)
    plan = generate_floor_plan('house-1', list(source.exterior.coords))
    assert 'error' not in plan
    outline = Polygon(plan['footprint'])
    assert outline.area == pytest.approx(source.area, abs=1e-4)
    rooms = [Polygon(room['points']) for room in plan['rooms']]
    assert unary_union(rooms).symmetric_difference(outline).area < 1e-4
    for a, b in combinations(rooms, 2):
        assert a.intersection(b).area < 1e-5
    connected = {-1}
    for _ in range(len(rooms) + 1):
        for door in plan['doors']:
            if connected.intersection(door['rooms']):
                connected.update(door['rooms'])
    assert connected == set(range(-1, len(rooms)))
    walls = unary_union([LineString(w) for w in plan['walls']])
    clearances = []
    for door in plan['doors']:
        line = LineString(door['points'])
        assert line.length == pytest.approx(0.95, abs=1e-5)
        assert line.distance(walls) < 0.001  # jambs meet the wall
        assert line.interpolate(0.5, normalized=True).distance(walls) > 0.4
        for index in door['rooms']:
            boundary = outline.boundary if index == -1 else rooms[index].boundary
            assert boundary.buffer(2e-6).covers(line)
        clearances.append(line.buffer(0.99, cap_style=3))
        assert rooms[door['rooms'][-1]].buffer(1e-6).covers(LineString([door['points'][0], door['leaf']]))
    furniture = []
    for item in plan['furniture']:
        shape = Polygon(item['points'])
        assert rooms[item['room']].buffer(1e-6).covers(shape)
        assert not any(shape.intersects(c) for c in clearances)
        assert not any(shape.intersects(other) for other in furniture)
        furniture.append(shape)
    assert all(outline.buffer(1e-6).covers(room) for room in rooms)
    assert all(outline.boundary.buffer(1e-6).covers(LineString(w)) or outline.buffer(1e-6).covers(LineString(w)) for w in plan['walls'])


@pytest.mark.parametrize('points', [[], [(0, 0)], [(0, 0), (1, 0), (2, 0)],
    [(0, 0), (3, 3), (0, 3), (3, 0)], [(0, 0), (float('nan'), 0), (0, 10)],
    [(0, 0), (float('inf'), 0), (0, 10)], None, ['bad'], [(0, 0, 1)]])
def test_invalid_geometry_returns_useful_error(points):
    assert generate_floor_plan('bad', points) == {'error': 'invalid_geometry'}


def test_determinism_variation_winding_and_cache_invalidation():
    _generate_cached.cache_clear()
    plan = generate_floor_plan('one', RECTANGLE)
    assert generate_floor_plan('one', RECTANGLE[::-1]) == plan
    assert _generate_cached.cache_info().hits == 1
    _generate_cached.cache_clear()
    assert generate_floor_plan('one', RECTANGLE) == plan
    assert generate_floor_plan('two', RECTANGLE) != plan
    changed = generate_floor_plan('one', [(0, 0), (16, 0), (16, 10), (0, 10)])
    assert changed['area_m2'] != plan['area_m2']
    assert _generate_cached('one', tuple(RECTANGLE), None, GENERATOR_VERSION + 1)['version'] != plan['version']
    assert {'hall', 'living', 'kitchen', 'bedroom', 'bathroom'} <= {r['kind'] for r in plan['rooms']}
    assert len(plan['furniture']) >= 8
    for i, room in enumerate(plan['rooms']):
        if room['kind'] == 'bedroom':
            assert any(item['room'] == i and item['kind'] == 'bed' for item in plan['furniture'])


def test_home_binding_migration_persistence_and_missing_building(tmp_path):
    from test_home import _server, press
    from theroadragetrip.home import load_home_building_key, save_home
    from theroadragetrip.server import SimulationServer
    from theroadragetrip.physics import SpatialWayGrid

    server = _server(tmp_path)
    assert SimulationServer._home_floor_plan(server) == {'error': 'no_home'}
    server.car.x, server.car.y = 0, 0
    press(server)
    key = server._home_building_key
    assert key and load_home_building_key(server.homes_file, 'Oulu') == key
    first = SimulationServer._home_floor_plan(server)
    assert first['building_id'] == key
    assert SimulationServer._home_floor_plan(server) == first
    # A position-only save is upgraded using its actual yard building.
    save_home(server.homes_file, 'Oulu', server._home)
    server._home_building_key = None
    assert SimulationServer._home_floor_plan(server) == first
    assert load_home_building_key(server.homes_file, 'Oulu') == key
    server.world.building_grid = SpatialWayGrid([])
    assert SimulationServer._home_floor_plan(server) == {'error': 'home_unavailable'}
    assert server._home_building_key == key  # never silently select the neighbour


def test_invalid_selection_preserves_existing_home(tmp_path):
    from test_home import _server, press
    from theroadragetrip.physics import SpatialWayGrid
    server = _server(tmp_path)
    server.car.x, server.car.y = 0, 0
    press(server)
    old = server._home, server._home_building_key
    server.world.building_grid = SpatialWayGrid([])
    server.car.x = 100
    assert 'footprint' in press(server)
    assert (server._home, server._home_building_key) == old


def test_slot_keeps_building_key_on_save_and_reload(tmp_path, monkeypatch):
    from test_save_slots import _server
    from theroadragetrip.home import save_home
    server = _server(tmp_path, monkeypatch, slot='interior')
    key = 'footprint:1.00,2.00,3.00,4.00'
    save_home(server.homes_file, str(server.chosen_city or ''), (1, 2, 3), in_save=True, building_key=key)
    assert server.save_game()
    restored = _server(tmp_path, monkeypatch, slot='interior')
    assert restored._home == (1, 2, 3) and restored._home_building_key == key
    restored._clear_home()
    assert _server(tmp_path, monkeypatch, slot='interior')._home_building_key is None


def test_interior_request_uses_real_server_dispatch(tmp_path, monkeypatch):
    from unittest.mock import Mock
    from test_server_headless import _build_server
    from theroadragetrip import protocol
    server = _build_server(tmp_path, monkeypatch)
    connection = Mock(is_closed=False)
    connection.try_recv_all.return_value = [{'type': 'command', 'version': 1, 'command': {}, 'home_interior': True}]
    server._clients.append(connection)
    server._apply_incoming_messages()
    reply = connection.send.call_args.args[0]
    assert protocol.decode(protocol.encode(reply)) == {'type': 'home_interior', 'version': 1, 'plan': {'error': 'no_home'}}
    connection.send.reset_mock()
    connection.try_recv_all.return_value = [{'type': 'command', 'version': 1, 'home_interior': 'true'}]
    server._apply_incoming_messages()
    connection.send.assert_not_called()


@pytest.mark.timing
def test_home_selection_and_plan_round_trip_over_tcp(tmp_path, monkeypatch):
    from test_client_server_integration import _start_server, _tick_until
    from theroadragetrip import transport
    from theroadragetrip.osm import Building, ParkingSpace
    from theroadragetrip.physics import SpatialWayGrid

    server = _start_server(monkeypatch)
    connection = transport.connect(server.host, server.port)
    try:
        x, y = server.car.x, server.car.y
        building = Building(points_m=[(x - 7, y + 5), (x + 7, y + 5), (x + 7, y + 15), (x - 7, y + 15)],
                            bbox=(x - 7, y + 5, x + 7, y + 15), building_type='detached')
        server.world.building_grid = SpatialWayGrid([building])
        server.world.parking_spaces = [ParkingSpace(points_m=[(x - 2, y - 1), (x + 2, y - 1), (x + 2, y + 1), (x - 2, y + 1)],
                                                   bbox=(x - 2, y - 1, x + 2, y + 1), source_building_key=tuple(round(v, 2) for v in building.bbox))]
        server.homes_file = tmp_path / 'home.json'
        server._home, server._home_building_key, server._on_foot = None, None, False
        connection.send({'type': 'command', 'version': 1, 'command': {'home': True}})
        assert _tick_until(server, lambda: server._home is not None)
        connection.send({'type': 'command', 'version': 1, 'command': {}, 'home_interior': True})
        replies = []
        def received():
            replies.extend(connection.try_recv_all())
            return any(m['type'] == 'home_interior' for m in replies)
        assert _tick_until(server, received)
        plan = next(m['plan'] for m in replies if m['type'] == 'home_interior')
        assert plan['building_id'] == server._home_building_key and len(plan['rooms']) > 1
        assert all('plan' not in m for m in replies if m['type'] == 'state')
    finally:
        connection.close()
        server.close()


# Real detached houses (local metres, origin left out on purpose): small wings
# came out as one open room, a hall end without a straight wall, and L-shapes whose
# rooms had thin strips along the hall where the door went (a walker was stuck).
REAL_HOUSES = [
    [(37.12, 24.40), (35.53, 30.73), (30.29, 29.41), (29.18, 34.55), (28.81, 35.31), (39.80, 38.06), (42.87, 25.84)],
    [(59.62, 31.27), (57.40, 38.26), (52.71, 36.78), (50.94, 42.35), (60.47, 45.38), (64.46, 32.81)],
    [(26.91, 35.06), (27.15, 34.08), (30.13, 22.32), (23.88, 20.74), (22.18, 27.47), (18.36, 26.51), (17.61, 29.47), (16.84, 32.51)],
    [(37.02, 74.37), (40.35, 62.46), (29.55, 59.45), (28.17, 64.41), (31.97, 65.47), (30.02, 72.43)],
    [(51.31, 77.93), (54.62, 66.27), (44.11, 63.29), (42.58, 68.67), (46.70, 69.84), (44.92, 76.12)],
    [(25.66, 58.00), (15.29, 55.40), (14.11, 60.05), (17.79, 60.98), (15.81, 68.84), (22.50, 70.52)],
    [(7.16, 67.21), (10.83, 54.64), (1.30, 51.87), (0.00, 56.32), (3.83, 57.44), (1.47, 65.55)],
    [(23.35, 0.00), (21.37, 7.68), (31.54, 10.30), (33.52, 2.63)],
    [(46.90, 14.19), (49.00, 7.06), (58.81, 9.94), (56.70, 17.07)],
]


@pytest.mark.parametrize('points', REAL_HOUSES)
def test_real_family_houses_get_rooms(points):
    plan = generate_floor_plan('real', [(x + 425000, y + 7216000) for x, y in points])
    assert plan['simple'] or {'bedroom', 'bathroom'} <= {r['kind'] for r in plan['rooms']}
    assert sum(not generate_floor_plan('real', [(x + 425000, y + 7216000) for x, y in house])['simple'] for house in REAL_HOUSES) >= len(REAL_HOUSES) - 1
    assert sum(door['rooms'][0] == -1 for door in plan['doors']) == 1


@pytest.mark.parametrize('points', FOOTPRINTS + REAL_HOUSES)
@pytest.mark.parametrize('entrance', [None, (-3, -3), (30, 20)])
def test_every_door_can_be_walked_through(points, entrance):
    """A walker (godot/home_walk.gd) steps STEP_IN_M through every door onto clear floor on both sides."""
    from theroadragetrip.interior import STEP_IN_M, WALK_CLEAR_M
    from shapely.geometry import Point
    origin = points[0]
    plan = generate_floor_plan('walk', points, None if entrance is None else (origin[0] + entrance[0], origin[1] + entrance[1]))
    rooms = [Polygon(room['points']) for room in plan['rooms']]
    walls = unary_union([LineString(w) for w in plan['walls']])
    clear = Polygon(plan['footprint']).difference(walls.buffer(WALK_CLEAR_M - 0.02))
    for door in plan['doors']:
        a, b = door['points']
        middle = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        n = ((door['leaf'][0] - a[0]) / 0.95, (door['leaf'][1] - a[1]) / 0.95)  # into its destination
        inside = Point(middle[0] + n[0] * STEP_IN_M, middle[1] + n[1] * STEP_IN_M)
        assert clear.contains(inside) and rooms[door['rooms'][-1]].contains(inside)
        if door['rooms'][0] >= 0:
            back = Point(middle[0] - n[0] * STEP_IN_M, middle[1] - n[1] * STEP_IN_M)
            assert clear.contains(back) and rooms[door['rooms'][0]].contains(back)


@pytest.mark.parametrize("angle", [0, 31, 90, 180, 270])
def test_reference_l_has_short_hall_corner_entrance_and_long_living_wing(angle):
    source = rotate(Polygon(REFERENCE_L), angle, origin=(0, 0))
    plan = generate_floor_plan("reference-L", list(source.exterior.coords))
    rooms = {room["kind"]: Polygon(room["points"]) for room in plan["rooms"]}
    assert set(rooms) == {"vestibule", "hall", "living_kitchen", "bedroom", "bathroom", "closet", "stairs"}
    assert rooms["living_kitchen"].area > source.area / 2
    assert rooms["hall"].area < source.area / 10
    assert rooms["bedroom"].area >= 12
    assert plan["doors"][0]["rooms"] == [-1, 0]
    assert plan["rooms"][0]["kind"] == "vestibule"
    front = translate(LineString(plan["doors"][0]["points"]), *plan["origin"])
    corner_wall = rotate(LineString([(5.5, 6.5), (14, 6.5)]), angle, origin=(0, 0))
    assert corner_wall.buffer(2e-6).covers(front)
    hall_index = next(i for i, room in enumerate(plan["rooms"]) if room["kind"] == "hall")
    assert all(hall_index in door["rooms"] for door in plan["doors"][1:])


def test_small_l_keeps_existing_layout_instead_of_cramped_reference():
    plan = generate_floor_plan("small-L", [(0, 0), (8, 0), (8, 4), (4, 4), (4, 8), (0, 8)])
    assert "vestibule" not in {room["kind"] for room in plan["rooms"]}


@pytest.mark.parametrize("points", COMPACT_L_HOUSES, ids=["L1", "L2", "L3"])
@pytest.mark.parametrize("angle,reflection", [(0, 1), (31, 1), (90, -1)])
def test_compact_l_houses_use_compact_reference_through_house_plan(points, angle, reflection, tmp_path):
    from test_home import _server
    from theroadragetrip.home import home_building_key, house_plan
    from theroadragetrip.osm import Building
    from theroadragetrip.physics import SpatialWayGrid
    from theroadragetrip.server import SimulationServer

    source = rotate(scale(Polygon(points), xfact=reflection, origin=(0, 0)), angle, origin=(0, 0))
    building = Building(points_m=list(source.exterior.coords), bbox=source.bounds, street="Kotikuja", housenumber="2", building_type="detached")
    plan = house_plan(building, [])
    kinds = [room["kind"] for room in plan["rooms"]]
    assert set(kinds) == {"vestibule", "hall", "living_kitchen", "bedroom", "bathroom"}
    assert kinds[plan["doors"][0]["rooms"][-1]] == "vestibule"
    rooms = {room["kind"]: Polygon(room["points"]) for room in plan["rooms"]}
    assert rooms["bedroom"].area >= 10
    assert rooms["bathroom"].area >= 3
    assert rooms["hall"].area < 6
    assert rooms["living_kitchen"].area > source.area / 2
    assert {"bed", "toilet", "sink"} <= {item["kind"] for item in plan["furniture"]}
    assert plan["name"] == "Kotikuja 2"

    server = _server(tmp_path)
    server.world.building_grid = SpatialWayGrid([building])
    server.world.parking_spaces = []
    server._home = (*source.centroid.coords[0], 0)
    server._home_building_key = home_building_key(building)
    server._inside = None
    assert SimulationServer._home_floor_plan(server) == plan
    server._inside = (building, None)
    assert SimulationServer._home_floor_plan(server) == plan
