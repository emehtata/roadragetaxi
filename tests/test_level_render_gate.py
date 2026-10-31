"""Map-level render gate (garage-04.md): what each level draws."""

from theroadragetrip.map_style import road_color_for_way
from theroadragetrip.osm import Way, build_ways

W, H, PX = 200, 200, 2.0
ROAD = road_color_for_way(Way([(0.0, 0.0), (1.0, 0.0)], "service", 3.0))


def _way(map_level=None, layer=0, x=0.0, service=None):
    return Way([(x, -40.0), (x, 40.0)], "service", 3.0, layer=layer, map_level=map_level, service=service)


def test_covered_level_zero_road_joins_the_surface_network():
    """level=0 is the surface (garage-05.md): a covered level=0 road is a
    surface road, not kept in level_ways."""
    world = build_ways([
        {"type": "node", "id": 1, "lat": 65.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 65.001, "lon": 25.0},
        {"type": "way", "id": 9, "nodes": [1, 2], "tags": {"highway": "service", "covered": "yes", "level": "0"}},
    ])
    assert world.level_ways == [] and [w.map_level for w in world.ways] == [0]




