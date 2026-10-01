"""Map-level render gate (garage-04.md): what each level draws."""
import pygame
import pytest

from theroadragetrip.map_level import level_view_ways, visible_on_level
from theroadragetrip.osm import Way, build_ways
from theroadragetrip.physics import SpatialWayGrid
from theroadragetrip.render import draw_level_ways, draw_ways
from theroadragetrip.render.common import road_color_for_way

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


def _pixel(draw):
    pygame.init()
    screen = pygame.Surface((W, H))
    screen.fill((0, 0, 0))
    draw(screen)
    return tuple(screen.get_at((W // 2, H // 2)))[:3]


def _level_pixel(ways, level_ways, current):
    grid = SpatialWayGrid(level_view_ways(ways, level_ways))
    return _pixel(lambda screen: draw_level_ways(screen, grid, current, 0.0, 0.0, px_per_m=PX, screen_w=W, screen_h=H))


def test_level_ways_draw_only_on_their_own_level():
    level_ways = [_way(-1), _way(-2, x=0.0), _way(0, x=0.0)]
    for current in (0, -1, -2, -1, 0):  # transitions: same data, nothing rebuilt
        drawn = [w for w in level_ways if w.map_level == current]
        assert len(drawn) == 1
        assert _level_pixel([], [drawn[0]], current) == ROAD
        others = [w for w in level_ways if w.map_level != current]
        assert _level_pixel([], others, current) == (0, 0, 0)


def test_level_zero_entry_in_level_ways_draws_on_the_surface():
    """A covered level=0 road lives in level_ways; it must not be lost."""
    world = build_ways([
        {"type": "node", "id": 1, "lat": 65.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 65.001, "lon": 25.0},
        {"type": "way", "id": 9, "nodes": [1, 2], "tags": {"highway": "service", "covered": "yes", "level": "0"}},
    ])
    assert world.ways == [] and [w.map_level for w in world.level_ways] == [0]
    grid = SpatialWayGrid(level_view_ways(world.ways, world.level_ways))
    assert [w.map_level for w in grid.ways_in_rect(*world.level_ways[0].bbox)] == [0]


def test_parking_aisle_on_level_minus_one_leaves_the_surface_cache_for_its_level():
    aisle = _way(-1, service="parking_aisle")
    surface = _way(None, x=60.0)
    ways = [aisle, surface]  # the import keeps parking aisles in world.ways
    grid = SpatialWayGrid(ways)
    assert _pixel(lambda screen: draw_ways(
        screen, ways, 0.0, 0.0, px_per_m=PX, screen_w=W, screen_h=H, spatial_grid=grid,
    )) == (0, 0, 0)
    assert level_view_ways(ways, []) == [aisle]
    assert _level_pixel(ways, [], -1) == ROAD
    assert _level_pixel(ways, [], 0) == (0, 0, 0)  # never twice on the surface


def test_surface_road_still_draws():
    road = _way(None)
    grid = SpatialWayGrid([road])
    assert _pixel(lambda screen: draw_ways(
        screen, [road], 0.0, 0.0, px_per_m=PX, screen_w=W, screen_h=H, spatial_grid=grid,
    )) != (0, 0, 0)
