import types
import sys
import time
from concurrent.futures import Future

from theroadragetrip import Car, Way, AutoFetchManager
from theroadragetrip.osm import MapData, _snap_projected_bbox


class FakeTransformer:
    def transform(self, x, y):
        # Very simple fake: identity for lon/lat in small coords (meters -> degrees kinda)
        # This is just to test logic, not accurate projection
        return (x / 1000.0, y / 1000.0)


def test_auto_fetch_bbox_snaps_to_stable_tile_key():
    assert _snap_projected_bbox((2490.0, 10.0, 2990.0, 510.0), 500.0) == (
        2000.0, 0.0, 3000.0, 1000.0
    )
    assert _snap_projected_bbox((2410.0, 20.0, 2910.0, 520.0), 500.0) == (
        2000.0, 0.0, 3000.0, 1000.0
    )


def test_auto_fetch_triggers_and_merges():
    # initial ways and bounds
    w = Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="residential", half_width_m=4.5)
    ways = [w]
    bounds = (0.0, 0.0, 1000.0, 1000.0)
    car = Car(x=995.0, y=500.0, heading=0.0, speed=0.0)

    # fake fetch returns a simple element list (nodes & way)
    requested_bboxes = []

    def fake_fetch(bbox):
        # bbox is (south, west, north, east) in lat/lon but we don't use it here
        requested_bboxes.append(bbox)
        return [
            {"type": "node", "id": 100, "lat": 0.996, "lon": 0.5},
            {"type": "node", "id": 101, "lat": 0.997, "lon": 0.6},
            {"type": "way", "id": 200, "nodes": [100, 101], "tags": {"highway": "residential"}},
        ]

    # fake build_ways will convert those elements into metric points shifted beyond current maxx
    def fake_build(elems):
        new_w = Way(points_m=[(1100.0, 490.0), (1200.0, 510.0)], highway="residential", half_width_m=4.5)
        # New bounds extend maxx; no water features in fake build
        return [new_w], [], (0.0, 0.0, 1200.0, 1200.0)

    transformer = FakeTransformer()

    m = AutoFetchManager(ways, bounds, transformer, fetch_func=fake_fetch, build_func=fake_build, cooldown_s=0.0)
    started = m.start_if_needed(car, True, margin_m=10.0, tile_size_m=500.0)
    assert started is True
    assert m.get_trigger_reason() == "bbox east edge"

    # wait for background thread to finish (timeout)
    timeout = time.time() + 2.0
    while m.is_fetching and time.time() < timeout:
        time.sleep(0.01)

    assert not m.is_fetching
    assert len(ways) == 2
    nb = m.get_bounds()
    assert nb[2] >= 1200.0
    south, west, north, east = requested_bboxes[0]
    assert abs((south + north) / 2.0 - car.y / 1000.0) < 1e-12
    assert abs((west + east) / 2.0 - car.x / 1000.0) < 1e-12
    assert m.start_if_needed(car, True, margin_m=10.0, tile_size_m=500.0) is False


def test_auto_fetch_uses_binary_cache_preload():
    way = Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="residential", half_width_m=4.5)
    cached = MapData(
        [Way(points_m=[(1100.0, 490.0), (1200.0, 510.0)], highway="residential", half_width_m=4.5)],
        [], [], [], [], (0.0, 0.0, 1200.0, 1200.0),
        [], [], [], [], [], [], [], [],
    )
    calls = []

    class Cache:
        @staticmethod
        def area_id(bbox):
            return "cached-area"

        def preload(self, area_id, bbox, **kwargs):
            calls.append((area_id, bbox))
            future = Future()
            future.set_result(cached)
            return future

    m = AutoFetchManager(
        [way], (0.0, 0.0, 1000.0, 1000.0), FakeTransformer(),
        world_cache_manager=Cache(), cooldown_s=0.0,
    )
    m.start_if_needed(Car(x=995.0, y=500.0, heading=0.0, speed=0.0), True, margin_m=10.0, tile_size_m=500.0)
    deadline = time.time() + 2.0
    while m.is_fetching and time.time() < deadline:
        time.sleep(0.01)
    assert calls and calls[0][0] == "cached-area"
    assert len(m.ways) == 2


def test_auto_fetch_does_not_trigger_from_open_road_endpoint():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="motorway", half_width_m=6.0)
    ways = [way]
    car = Car(x=50.0, y=0.0, heading=0.0, speed=1.0)

    def fake_fetch(bbox):
        return []

    def fake_build(elems):
        return [], [], (0.0, 0.0, 1000.0, 1000.0)

    m = AutoFetchManager(
        ways,
        (-1000.0, -1000.0, 1000.0, 1000.0),
        FakeTransformer(),
        fetch_func=fake_fetch,
        build_func=fake_build,
        cooldown_s=0.0,
    )
    m.dead_ends = []

    assert m.start_if_needed(car, True, margin_m=100.0, tile_size_m=500.0) is False


def test_auto_fetch_does_not_trigger_far_from_open_endpoint():
    way = Way(points_m=[(0.0, 0.0), (1000.0, 0.0)], highway="motorway", half_width_m=6.0)
    car = Car(x=500.0, y=0.0, heading=0.0, speed=0.0)

    m = AutoFetchManager(
        [way],
        (0.0, -100.0, 2000.0, 100.0),
        FakeTransformer(),
        fetch_func=lambda bbox: [],
        build_func=lambda elems: ([], [], (0.0, 0.0, 2000.0, 100.0)),
        cooldown_s=0.0,
    )
    m.dead_ends = []

    assert m.start_if_needed(car, True, margin_m=100.0, tile_size_m=500.0) is False


def test_auto_fetch_triggers_near_disconnected_current_road_endpoint():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="secondary", half_width_m=6.0)
    car = Car(x=90.0, y=0.0, heading=0.0, speed=5.0)

    m = AutoFetchManager(
        [way],
        (-1000.0, -1000.0, 1000.0, 1000.0),
        FakeTransformer(),
        fetch_func=lambda bbox: [],
        build_func=lambda elems: ([], [], (-1000.0, -1000.0, 1000.0, 1000.0)),
        cooldown_s=0.0,
    )
    m.dead_ends = []

    assert m.start_if_needed(car, True, margin_m=20.0, tile_size_m=500.0, current_way=way) is True
    assert m.get_trigger_reason() == "road endpoint"


def test_auto_fetch_requests_area_ahead_of_early_road_endpoint():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="secondary", half_width_m=6.0)
    car = Car(x=90.0, y=0.0, heading=0.0, speed=5.0)
    requested = []

    manager = AutoFetchManager(
        [way],
        (-1000.0, -1000.0, 1000.0, 1000.0),
        FakeTransformer(),
        fetch_func=lambda bbox: requested.append(bbox) or [],
        build_func=lambda elems: ([], [], (-1000.0, -1000.0, 1000.0, 1000.0)),
        cooldown_s=0.0,
    )
    manager.dead_ends = []

    assert manager.start_if_needed(car, True, margin_m=20.0, tile_size_m=500.0, current_way=way)
    deadline = time.time() + 2.0
    while manager.is_fetching and time.time() < deadline:
        time.sleep(0.01)

    assert requested
    assert requested[0][3] > car.x / 1000.0
    assert requested[0][3] - car.x / 1000.0 >= 0.4


def test_auto_fetch_triggers_while_stopped_at_road_endpoint_only_once():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="secondary", half_width_m=6.0)
    car = Car(x=90.0, y=0.0, heading=0.0, speed=0.0)
    m = AutoFetchManager(
        [way],
        (-1000.0, -1000.0, 1000.0, 1000.0),
        FakeTransformer(),
        fetch_func=lambda bbox: [],
        build_func=lambda elems: ([], [], (-1000.0, -1000.0, 1000.0, 1000.0)),
        cooldown_s=0.0,
    )
    m.dead_ends = []

    assert m.start_if_needed(car, True, margin_m=20.0, tile_size_m=500.0, current_way=way) is True
    assert m.start_if_needed(car, True, margin_m=20.0, tile_size_m=500.0, current_way=way) is False


def test_auto_fetch_does_not_treat_t_junction_as_open_endpoint():
    through_road = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=4.5)
    side_road = Way(points_m=[(50.0, -100.0), (50.0, 0.0)], highway="residential", half_width_m=4.5)
    car = Car(x=50.0, y=-50.0, heading=1.5708, speed=1.0)

    m = AutoFetchManager(
        [through_road, side_road],
        (-1000.0, -1000.0, 1000.0, 1000.0),
        FakeTransformer(),
        fetch_func=lambda bbox: [],
        build_func=lambda elems: ([], [], (0.0, 0.0, 2000.0, 2000.0)),
        cooldown_s=0.0,
    )
    m.dead_ends = []

    assert m.start_if_needed(car, True, margin_m=100.0, tile_size_m=500.0) is False
