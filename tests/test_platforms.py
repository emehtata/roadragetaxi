"""Station platforms: railway=platform areas are paved walkable ground (not
the grass under them), and highway=platform ways are never drivable."""
import math

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


def test_platform_centreline_is_dense_and_joined_to_steps_ending_on_it():
    """Steps/footways ending on a platform connect to its centreline (or an
    island platform is unreachable), and the centreline has a node every few
    metres (routes start at the nearest node, which must be on the platform)."""
    nodes = [  # ~110 m long, ~22 m wide platform
        {"type": "node", "id": 1, "lat": 65.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 65.0, "lon": 25.0023},
        {"type": "node", "id": 3, "lat": 65.0002, "lon": 25.0023},
        {"type": "node", "id": 4, "lat": 65.0002, "lon": 25.0},
        {"type": "node", "id": 5, "lat": 65.0001, "lon": 25.0011},  # stairs top, on the platform
        {"type": "node", "id": 6, "lat": 64.9995, "lon": 25.0011},  # stairs bottom, off it
    ]
    elements = nodes + [
        {"type": "way", "id": 10, "nodes": [1, 2, 3, 4, 1], "tags": {"railway": "platform", "area": "yes"}},
        {"type": "way", "id": 11, "nodes": [6, 5], "tags": {"highway": "steps"}},
    ]
    ways, _, _, _, _, _ = build_ways(elements)
    centreline = next(w for w in ways if w.highway == "platform")
    gaps = [math.dist(a, b) for a, b in zip(centreline.points_m, centreline.points_m[1:])]
    assert max(gaps) <= 8.0 + 1e-6
    stairs_top = next(w for w in ways if w.highway == "steps").points_m[-1]
    connector = next(w for w in ways if w.highway == "footway")
    assert connector.points_m[0] == stairs_top
    assert connector.points_m[-1] in centreline.points_m
