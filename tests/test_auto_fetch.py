import types
import sys
import time

from theroadragetrip import Car, Way, AutoFetchManager


class FakeTransformer:
    def transform(self, x, y):
        # Very simple fake: identity for lon/lat in small coords (meters -> degrees kinda)
        # This is just to test logic, not accurate projection
        return (x / 1000.0, y / 1000.0)


def test_auto_fetch_triggers_and_merges():
    # initial ways and bounds
    w = Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="residential", half_width_m=4.5)
    ways = [w]
    bounds = (0.0, 0.0, 1000.0, 1000.0)
    car = Car(x=995.0, y=500.0, heading=0.0, speed=0.0)

    # fake fetch returns a simple element list (nodes & way)
    def fake_fetch(bbox):
        # bbox is (south, west, north, east) in lat/lon but we don't use it here
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

    # wait for background thread to finish (timeout)
    timeout = time.time() + 2.0
    while m.is_fetching and time.time() < timeout:
        time.sleep(0.01)

    assert not m.is_fetching
    assert len(ways) == 2
    nb = m.get_bounds()
    assert nb[2] >= 1200.0


def test_auto_fetch_triggers_before_open_road_endpoint():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="motorway", half_width_m=6.0)
    ways = [way]
    car = Car(x=50.0, y=0.0, heading=0.0, speed=0.0)

    def fake_fetch(bbox):
        return []

    def fake_build(elems):
        return [], [], (0.0, 0.0, 1000.0, 1000.0)

    m = AutoFetchManager(
        ways,
        (0.0, 0.0, 1000.0, 1000.0),
        FakeTransformer(),
        fetch_func=fake_fetch,
        build_func=fake_build,
        cooldown_s=0.0,
    )
    m.dead_ends = []

    assert m.start_if_needed(car, True, margin_m=100.0, tile_size_m=500.0) is True
