import sys
import types

# Provide a lightweight fake `pyproj` so tests don't need the real dependency.
fake_pyproj = types.SimpleNamespace()

class FakeTransformer:
    @staticmethod
    def from_crs(a, b, always_xy=True):
        return FakeTransformer()

    def transform(self, lon, lat):
        # Simple, deterministic transform for tests: scale up lon/lat by 1000
        return (lon * 1000.0, lat * 1000.0)

fake_pyproj.Transformer = FakeTransformer
sys.modules["pyproj"] = fake_pyproj

from theroadragetrip import build_ways


def test_build_ways_transforms():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.001, "lon": 25.001},
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": "residential"}},
    ]

    ways, waters, buildings, sceneries, places, bounds = build_ways(elements)
    assert len(ways) == 1
    assert len(waters) == 0
    assert len(buildings) == 0
    assert len(sceneries) == 0
    assert len(places) == 0
    w = ways[0]
    # With our fake transformer lon*1000,lat*1000
    x1, y1 = 25.0 * 1000.0, 60.0 * 1000.0
    x2, y2 = 25.001 * 1000.0, 60.001 * 1000.0
    assert w.points_m[0] == (x1, y1)
    assert w.points_m[1] == (x2, y2)
    assert w.highway == "residential"
