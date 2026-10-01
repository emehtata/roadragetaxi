"""Station platforms: railway=platform areas are paved walkable ground (not
the grass under them), and highway=platform ways are never drivable."""
from theroadragetrip.osm import build_ways


def _nodes():
    return [
        {"type": "node", "id": i, "lat": 65.0 + dy, "lon": 25.0 + dx}
        for i, (dx, dy) in enumerate([(0, 0), (0.001, 0), (0.001, 0.0002), (0, 0.0002)], start=1)
    ]


def test_railway_platform_area_is_paved_scenery():
    elements = _nodes() + [
        {"type": "way", "id": 10, "nodes": [1, 2, 3, 4, 1],
         "tags": {"railway": "platform", "public_transport": "platform", "area": "yes", "surface": "paved"}},
        {"type": "way", "id": 11, "nodes": [1, 2, 3, 4, 1], "tags": {"landuse": "grass"}},
    ]
    _, _, _, sceneries, _, _ = build_ways(elements)
    kinds = sorted(s.kind for s in sceneries)
    assert kinds == ["grass", "pedestrian_area"]


def test_highway_platform_is_not_drivable_even_with_bus_tag():
    elements = _nodes() + [
        {"type": "way", "id": 20, "nodes": [1, 2], "tags": {"highway": "platform", "public_transport": "platform"}},
        {"type": "way", "id": 21, "nodes": [3, 4], "tags": {"highway": "platform", "bus": "yes"}},
    ]
    ways, _, _, _, _, _ = build_ways(elements)
    assert len(ways) == 2
    assert not any(w.is_drivable for w in ways)
