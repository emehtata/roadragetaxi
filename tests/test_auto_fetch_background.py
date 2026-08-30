import time

from theroadragetrip import Car, Scenery, Way, AutoFetchManager


def test_background_auto_fetch_updates_ways_and_bounds():
    ways = [Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="residential", half_width_m=4.5)]
    bounds = (0.0, 0.0, 1000.0, 1000.0)
    car = Car(x=995.0, y=500.0, heading=0.0, speed=0.0)

    class FakeTransformer:
        def transform(self, x, y):
            return (x / 1000.0, y / 1000.0)

    def fake_fetch(bbox):
        return [
            {"type": "node", "id": 100, "lat": 0.996, "lon": 0.5},
            {"type": "node", "id": 101, "lat": 0.997, "lon": 0.6},
            {"type": "way", "id": 200, "nodes": [100, 101], "tags": {"highway": "residential"}},
        ]

    def fake_build(elems):
        new_w = Way(points_m=[(1100.0, 490.0), (1200.0, 510.0)], highway="residential", half_width_m=4.5)
        new_scenery = Scenery(
            points_m=[(1100.0, 450.0), (1200.0, 450.0), (1200.0, 550.0), (1100.0, 550.0)],
            kind="wood",
            bbox=(1100.0, 450.0, 1200.0, 550.0),
        )
        return [new_w], [], [], [new_scenery], [], (0.0, 0.0, 1200.0, 1200.0)

    m = AutoFetchManager(ways, bounds, FakeTransformer(), fetch_func=fake_fetch, build_func=fake_build, cooldown_s=0.0)
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
    assert m.sceneries[0].trees
