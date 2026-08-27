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

from theroadragetrip.osm import build_ways


def test_build_ways_buildings_and_scenery_and_names():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.001, "lon": 25.001},
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": "primary", "name": "Main Street"}},
        {"type": "node", "id": 3, "lat": 60.002, "lon": 25.002},
        {"type": "node", "id": 4, "lat": 60.003, "lon": 25.002},
        {"type": "node", "id": 5, "lat": 60.003, "lon": 25.003},
        {"type": "node", "id": 6, "lat": 60.002, "lon": 25.003},
        {
            "type": "way",
            "id": 20,
            "nodes": [3, 4, 5, 6, 3],
            "tags": {"building": "yes", "name": "Town Hall"},
        },
        {"type": "node", "id": 7, "lat": 60.004, "lon": 25.004},
        {"type": "node", "id": 8, "lat": 60.005, "lon": 25.004},
        {"type": "node", "id": 9, "lat": 60.005, "lon": 25.005},
        {
            "type": "way",
            "id": 30,
            "nodes": [7, 8, 9, 7],
            "tags": {"leisure": "park", "name": "City Park"},
        },
        {
            "type": "node",
            "id": 40,
            "lat": 60.006,
            "lon": 25.006,
            "tags": {"place": "suburb", "name": "Downtown"},
        },
    ]

    ways, waters, buildings, sceneries, places, bounds = build_ways(elements)

    assert len(ways) == 1
    assert ways[0].name == "Main Street"
    assert ways[0].highway == "primary"

    assert len(buildings) == 1
    assert buildings[0].name == "Town Hall"
    assert len(buildings[0].points_m) == 5

    assert len(sceneries) == 1
    assert sceneries[0].name == "City Park"
    assert sceneries[0].kind == "park"

    assert len(places) == 1
    assert places[0].name == "Downtown"
    assert places[0].kind == "suburb"
