"""Geometry contracts, yard binding and the actual interior request envelope."""
from itertools import combinations

import pytest
from shapely.affinity import rotate, translate
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from theroadragetrip.interior import GENERATOR_VERSION, _generate_cached, generate_floor_plan

RECTANGLE = [(0, 0), (14, 0), (14, 10), (0, 10)]
FOOTPRINTS = [
    RECTANGLE,
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
