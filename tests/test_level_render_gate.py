"""Map-level render gate (garage-04.md): what each level draws."""
import pytest

from theroadragetrip.map_level import level_view_ways, visible_on_level
from theroadragetrip.map_style import road_color_for_way
from theroadragetrip.osm import Way, build_ways
from theroadragetrip.physics import SpatialWayGrid

W, H, PX = 200, 200, 2.0
ROAD = road_color_for_way(Way([(0.0, 0.0), (1.0, 0.0)], "service", 3.0))


def _way(map_level=None, layer=0, x=0.0, service=None):
    return Way([(x, -40.0), (x, 40.0)], "service", 3.0, layer=layer, map_level=map_level, service=service)


@pytest.mark.parametrize("current, visible", [
    (0, {None, 0}),
    (-1, {-1}),
    (-2, {-2}),
])
def test_visibility_table(current, visible):
    assert {level for level in (None, 0, -1, -2) if visible_on_level(_way(level), current)} == visible


def test_layer_and_map_level_stay_independent():
    tunnel = _way(None, layer=-1)
    assert visible_on_level(tunnel, 0) and not visible_on_level(tunnel, -1)
    garage = _way(-2, layer=-1)
    assert (garage.layer, garage.map_level) == (-1, -2)
    assert visible_on_level(garage, -2) and not visible_on_level(garage, 0)


def test_covered_level_zero_road_joins_the_surface_network():
    """level=0 is the surface (garage-05.md): a covered level=0 road is a
    surface road, drawn by draw_ways, not kept in level_ways."""
    world = build_ways([
        {"type": "node", "id": 1, "lat": 65.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 65.001, "lon": 25.0},
        {"type": "way", "id": 9, "nodes": [1, 2], "tags": {"highway": "service", "covered": "yes", "level": "0"}},
    ])
    assert world.level_ways == [] and [w.map_level for w in world.ways] == [0]




