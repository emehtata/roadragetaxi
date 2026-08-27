# Test relation multipolygon handling in build_ways
import sys
import types

fake_pyproj = types.SimpleNamespace()
class FakeTransformer:
    @staticmethod
    def from_crs(a, b, always_xy=True):
        return FakeTransformer()
    def transform(self, lon, lat):
        return (lon * 1000.0, lat * 1000.0)
fake_pyproj.Transformer = FakeTransformer
sys.modules["pyproj"] = fake_pyproj

from theroadragetrip import build_ways


def test_relation_multipolygon_water():
    # nodes that form a square and closed way
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.001},
        {"type": "node", "id": 3, "lat": 60.001, "lon": 25.001},
        {"type": "node", "id": 4, "lat": 60.001, "lon": 25.0},
        {"type": "way", "id": 100, "nodes": [1,2,3,4,1], "tags": {}},
        {"type": "relation", "id": 200, "members": [{"type": "way", "ref": 100, "role": "outer"}], "tags": {"type": "multipolygon", "natural": "water"}},
    ]
    ways, waters, buildings, sceneries, places, bounds = build_ways(elements)
    assert len(waters) == 1
    w = waters[0]
    assert w.is_polygon is True
    assert len(w.points_m) == 5
