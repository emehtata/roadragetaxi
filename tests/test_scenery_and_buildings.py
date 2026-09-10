import sys
import types
import os

fake_pyproj = types.SimpleNamespace()


class FakeTransformer:
    @staticmethod
    def from_crs(a, b, always_xy=True):
        return FakeTransformer()

    def transform(self, lon, lat):
        return (lon * 1000.0, lat * 1000.0)

fake_pyproj.Transformer = FakeTransformer
sys.modules["pyproj"] = fake_pyproj

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame
import theroadragetrip.render as render_module

from theroadragetrip.osm import build_ways, plant_trees
from theroadragetrip.osm import Building, Place, Scenery, SceneryObject, Way, associate_places_with_buildings
from theroadragetrip.geo import point_in_polygon
from theroadragetrip.physics import Car
from theroadragetrip.render import (
    DISTRICT_PLACE_KINDS,
    MAX_BUILDING_DEPTH_PX,
    MAX_BUILDING_SIGN_FONT_SIZE,
    BUILDING_WALL_COLORS,
    FINNISH_BUILDING_COLOR_NAMES,
    SCENERY_OBJECT_COLORS,
    _building_colors_from_name,
    _building_is_commercial,
    _building_sign_anchor,
    _building_sign_angle,
    _building_sign_foreshorten,
    _building_sign_theme,
    _building_window_story_count,
    _visible_building_edges,
    _draw_buildings_uncached,
    CONSTRUCTION_FENCE_COLOR,
    SCENERY_COLORS,
    draw_construction_fences,
    draw_grass_texture,
    draw_scenery,
    draw_scenery_objects,
    draw_trees,
    world_to_screen,
)


def test_seven_floor_building_keeps_floor_rows_separate():
    building = Building(
        [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)],
        levels=7,
    )

    assert _building_window_story_count(building) == 7


def _facade_wall_pixel_span(screen):
    """Return the vertical span of drawn wall-color pixels (facade depth)."""
    min_y, max_y = None, None
    for y in range(screen.get_height()):
        for x in range(screen.get_width()):
            if tuple(screen.get_at((x, y)))[:3] in BUILDING_WALL_COLORS:
                min_y = y if min_y is None else min(min_y, y)
                max_y = y if max_y is None else max(max_y, y)
    assert min_y is not None, "no facade wall pixels rendered"
    return max_y - min_y


def test_taller_buildings_render_a_deeper_facade():
    """A much taller building should extrude visibly further than a short
    one instead of hitting the same depth cap (regression for buildings
    beyond ~3 storeys all rendering at the same height)."""
    short = Building(
        [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)],
        bbox=(0.0, 0.0, 20.0, 20.0), height_m=6.0,
    )
    tall = Building(
        [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)],
        bbox=(0.0, 0.0, 20.0, 20.0), height_m=60.0,
    )

    pygame.init()
    try:
        # Font/surface objects cached across a pygame.quit()/init() cycle are
        # invalid; clear the sign caches so an earlier test's Font isn't reused.
        render_module._building_sign_font_cache.clear()
        render_module._building_sign_surface_cache.clear()
        short_screen = pygame.Surface((400, 400), pygame.SRCALPHA)
        _draw_buildings_uncached(short_screen, [short], 10.0, 10.0, px_per_m=9.0, screen_w=400, screen_h=400)
        tall_screen = pygame.Surface((400, 400), pygame.SRCALPHA)
        _draw_buildings_uncached(tall_screen, [tall], 10.0, 10.0, px_per_m=9.0, screen_w=400, screen_h=400)

        assert _facade_wall_pixel_span(tall_screen) > _facade_wall_pixel_span(short_screen)
    finally:
        pygame.quit()


def test_very_tall_building_facade_depth_stays_bounded():
    """Extremely tall buildings should cap out rather than growing without
    bound and dwarfing the rest of the scene. Uses a small footprint so the
    measured pixel span reflects the roof-offset depth, not the building's
    own on-screen size."""
    building = Building(
        [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)],
        bbox=(0.0, 0.0, 4.0, 4.0), height_m=120.0,
    )
    pygame.init()
    try:
        render_module._building_sign_font_cache.clear()
        render_module._building_sign_surface_cache.clear()
        screen = pygame.Surface((600, 600), pygame.SRCALPHA)
        _draw_buildings_uncached(screen, [building], 2.0, 2.0, px_per_m=9.0, screen_w=600, screen_h=600)

        footprint_span_px = 4.0 * 9.0
        assert _facade_wall_pixel_span(screen) <= footprint_span_px + MAX_BUILDING_DEPTH_PX + 4
    finally:
        pygame.quit()


def test_building_sign_foreshorten_is_full_when_wall_faces_the_camera():
    # Edge tangent and wall-normal direction perpendicular: no correction needed.
    assert _building_sign_foreshorten(1.0, 0.0, 0.0, 1.0) == 1.0


def test_building_sign_foreshorten_shrinks_for_edge_on_walls():
    # Edge tangent and wall-normal nearly parallel: wall is close to edge-on
    # to the fixed extrusion direction, so the sign is squashed down to the
    # floor clamp rather than disappearing (a raw sine of ~0) or staying at
    # its unsquashed, face-on size.
    from theroadragetrip.render.buildings import MIN_SIGN_FORESHORTEN

    nearly_parallel = _building_sign_foreshorten(1.0, 0.0, 0.999, 0.001)
    assert nearly_parallel == MIN_SIGN_FORESHORTEN

    # A moderate (45 degree) deviation from perpendicular should land
    # strictly between the floor and the unsquashed maximum.
    moderate = _building_sign_foreshorten(1.0, 0.0, 0.7071, 0.7071)
    assert MIN_SIGN_FORESHORTEN < moderate < 1.0


from theroadragetrip.taxi import TaxiManager


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
            "tags": {"building": "yes", "name": "Town Hall", "building:levels": "3"},
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
            {
                "type": "node", "id": 41,
                "lat": 60.007, "lon": 25.007,
                "tags": {"tourism": "attraction", "name": "Named Attraction"},
            },
    ]

    ways, waters, buildings, sceneries, places, bounds = build_ways(elements)

    assert len(ways) == 1
    assert ways[0].name == "Main Street"
    assert ways[0].highway == "primary"

    assert len(buildings) == 1
    assert buildings[0].name == "Town Hall"
    assert buildings[0].levels == 3
    assert buildings[0].height_m == 9.0
    assert len(buildings[0].points_m) == 5

    assert len(sceneries) == 1
    assert sceneries[0].name == "City Park"
    assert sceneries[0].kind == "park"

    assert {place.name for place in places} == {"Downtown", "Named Attraction"}
    assert next(place for place in places if place.name == "Downtown").kind == "suburb"
    assert next(place for place in places if place.name == "Named Attraction").kind == "poi"


def test_building_height_precedes_levels_for_facade_depth():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.001},
        {"type": "node", "id": 3, "lat": 60.001, "lon": 25.001},
        {"type": "node", "id": 4, "lat": 60.001, "lon": 25.0},
        {
            "type": "way", "id": 99, "nodes": [1, 2, 3, 4, 1],
            "tags": {"building": "yes", "height": "30", "building:levels": "7"},
        },
    ]

    result = build_ways(elements)

    assert result.buildings[0].height_m == 30.0
    assert result.buildings[0].levels == 7


def test_building_part_with_height_and_levels_is_renderable_building_data():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.001},
        {"type": "node", "id": 3, "lat": 60.001, "lon": 25.001},
        {"type": "node", "id": 4, "lat": 60.001, "lon": 25.0},
        {
            "type": "way", "id": 100, "nodes": [1, 2, 3, 4, 1],
            "tags": {"building": "yes", "name": "Valkealinnantalo"},
        },
        {"type": "node", "id": 5, "lat": 60.0002, "lon": 25.0002},
        {"type": "node", "id": 6, "lat": 60.0002, "lon": 25.0008},
        {"type": "node", "id": 7, "lat": 60.0008, "lon": 25.0008},
        {"type": "node", "id": 8, "lat": 60.0008, "lon": 25.0002},
        {
            "type": "way", "id": 101, "nodes": [5, 6, 7, 8, 5],
            "tags": {"building:part": "yes", "height": "30", "building:levels": "7"},
        },
    ]

    result = build_ways(elements)

    part = next(building for building in result.buildings if building.levels == 7)
    assert part.height_m == 30.0


def test_associate_places_with_buildings_uses_building_geometry():
    buildings = [
        Building(
            [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)],
            bbox=(0.0, 0.0, 20.0, 20.0),
        ),
        Building(
            [(40.0, 0.0), (60.0, 0.0), (60.0, 20.0), (40.0, 20.0)],
            bbox=(40.0, 0.0, 60.0, 20.0),
        ),
    ]
    places = [Place(10.0, 10.0, "Cafe", "cafe"), Place(80.0, 10.0, "Outside", "poi")]

    associate_places_with_buildings(buildings, places)

    assert [place.name for place in buildings[0].associated_places] == ["Cafe"]
    assert buildings[1].associated_places == []


def test_build_ways_generates_trees_in_offroad_scenery():
    elements = [
        {"type": "node", "id": 1, "lat": 60.1, "lon": 25.1},
        {"type": "node", "id": 2, "lat": 60.1, "lon": 25.14},
        {"type": "node", "id": 3, "lat": 60.14, "lon": 25.14},
        {"type": "node", "id": 4, "lat": 60.14, "lon": 25.1},
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": "residential"}},
        {"type": "way", "id": 20, "nodes": [1, 2, 3, 4, 1], "tags": {"natural": "wood"}},
    ]

    ways, _, _, sceneries, _, _ = build_ways(elements)

    assert sceneries[0].trees
    assert all(tree_y > ways[0].half_width_m + 3.0 + 60100.0 for _, tree_y in sceneries[0].trees)


def test_build_ways_classifies_every_natural_scenery_kind_as_a_relation_too():
    """Regression: build_ways()'s multipolygon-relation branch used to
    whitelist a different, inconsistent set of natural=* values (forest/
    wood/scrub/grass - no sand/heath, plus "forest" which isn't a real OSM
    natural=* value) than its own way branch (wood/scrub/grass/sand/heath).
    Both now read NATURAL_SCENERY_KINDS (osm/constants.py) - the same
    constant the Overpass query builds its whitelist from - so a
    multipolygon-mapped heath or dune (common real OSM patterns) is
    classified the same way a plain way with the same tag would be."""
    from theroadragetrip.osm.constants import NATURAL_SCENERY_KINDS

    for i, kind in enumerate(NATURAL_SCENERY_KINDS):
        base = i * 10
        elements = [
            {"type": "node", "id": base + 1, "lat": 60.0 + i * 0.01, "lon": 25.0},
            {"type": "node", "id": base + 2, "lat": 60.0 + i * 0.01, "lon": 25.001},
            {"type": "node", "id": base + 3, "lat": 60.001 + i * 0.01, "lon": 25.001},
            {"type": "node", "id": base + 4, "lat": 60.001 + i * 0.01, "lon": 25.0},
            {"type": "way", "id": base + 100, "nodes": [base + 1, base + 2, base + 3, base + 4, base + 1], "tags": {}},
            {
                "type": "relation",
                "id": base + 200,
                "members": [{"type": "way", "ref": base + 100, "role": "outer"}],
                "tags": {"type": "multipolygon", "natural": kind},
            },
        ]

        ways, waters, buildings, sceneries, places, bounds = build_ways(elements)

        assert len(sceneries) == 1, f"natural={kind} was not classified as scenery"
        assert sceneries[0].kind == kind


def test_tree_density_follows_osm_scenery_type():
    forest = Scenery(
        [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        "forest",
        bbox=(0.0, 0.0, 100.0, 100.0),
    )
    park = Scenery(
        [(200.0, 0.0), (300.0, 0.0), (300.0, 100.0), (200.0, 100.0)],
        "park",
        bbox=(200.0, 0.0, 300.0, 100.0),
    )

    plant_trees([forest, park], [])

    assert len(forest.trees) > len(park.trees)
    assert len(park.trees) <= 6


def test_plant_trees_uses_real_osm_positions_instead_of_procedural():
    """A scenery area with real natural=tree data must use exactly those
    positions - not a procedurally-generated count/layout - and must never
    get topped up with fake trees by a later plant_trees() call (e.g.
    autofetch's road-recheck pass)."""
    forest = Scenery(
        [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        "forest",
        bbox=(0.0, 0.0, 100.0, 100.0),
    )
    real_trees = [(10.0, 10.0), (50.0, 50.0), (90.0, 10.0)]
    # A tree outside the polygon (and one far away) must not leak in.
    real_trees_with_noise = real_trees + [(500.0, 500.0)]

    plant_trees([forest], [], real_trees=real_trees_with_noise)

    assert forest.trees == real_trees
    assert forest.trees_from_osm is True
    assert len(forest.tree_variations) == len(forest.trees)

    plant_trees([forest], [])  # simulate a later re-merge call, no real_trees passed
    assert forest.trees == real_trees  # still untouched, not topped up procedurally


def test_plant_trees_plants_a_real_tree_even_where_it_overlaps_a_parking_lot():
    """Every real natural=tree OSM node must be planted, full stop - even
    one that geometrically falls inside a parking-lot polygon (a common
    OSM edge case: a tree right at the edge of a bordering grass/park area
    that also falls within a neighboring lot's boundary). OSM says the
    tree is there, so it must be there too; dropping it would mean a real
    tree silently missing from the map. (Keeping it visible despite a
    parking lot possibly painting over it is a rendering z-order concern,
    not a reason to discard real data.)"""
    grass = Scenery(
        [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        "grass",
        bbox=(0.0, 0.0, 100.0, 100.0),
    )
    parking = Scenery(
        [(40.0, 40.0), (100.0, 40.0), (100.0, 100.0), (40.0, 100.0)],
        "parking",
        bbox=(40.0, 40.0, 100.0, 100.0),
    )
    inside_lot = (60.0, 60.0)  # inside both grass and parking
    clear_of_lot = (10.0, 10.0)  # inside grass only

    plant_trees([grass, parking], [], real_trees=[inside_lot, clear_of_lot])

    assert sorted(grass.trees) == sorted([inside_lot, clear_of_lot])
    assert grass.trees_from_osm is True


def test_draw_trees_paints_over_a_road_drawn_after_the_scenery_layer():
    """Regression for a real tree rendering invisible under a road/parking
    surface: those are drawn as their *own*, later frame layers (draw_ways,
    draw_parking_spaces), well after the static-cached draw_scenery() pass
    - so a tree drawn as part of that scenery pass can end up covered by a
    road painted right over it afterwards, even though the tree isn't
    logically "on" that road. draw_trees() must be called (as main/__init__.py
    now does) *after* every ground-level layer, so nothing painted earlier
    in the frame - scenery fill, water, road, parking - can hide a real
    tree."""
    import pygame as pygame_module
    from theroadragetrip.render import common as common_module

    # draw_trees() has its own static cache now (see its docstring) -
    # reset the shared throttle so this test's call isn't denied by
    # leftover state from another test in the same run.
    common_module.begin_static_cache_frame()
    common_module._pending_static_rebuilds.clear()

    overlap = [(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)]
    grass = Scenery(overlap, "grass", bbox=(0.0, 0.0, 40.0, 40.0), trees=[(20.0, 20.0)], tree_variations=[0.5])

    screen_w, screen_h, px_per_m = 200, 200, 4.0
    screen = pygame.Surface((screen_w, screen_h))
    draw_scenery(screen, [grass], 20.0, 20.0, px_per_m=px_per_m, screen_w=screen_w, screen_h=screen_h)

    # Simulate a road/parking surface drawn after the scenery layer,
    # covering the whole viewport (as draw_ways/draw_parking_spaces would
    # for a wide driveway loop) - same opaque-fill mechanism, standing in
    # for the real thing without needing a Way + spatial grid here.
    road_color = (142, 142, 138)
    pygame_module.draw.rect(screen, road_color, screen.get_rect())

    draw_trees(screen, [grass], 20.0, 20.0, px_per_m=px_per_m, screen_w=screen_w, screen_h=screen_h)

    tree_px = world_to_screen(20.0, 20.0, 20.0, 20.0, px_per_m, screen_w, screen_h)
    pixel = tuple(screen.get_at(tree_px))[:3]
    assert pixel != road_color, "tree pixel is the road fill color - tree got painted over"


def test_draw_trees_and_scenery_objects_are_cached_across_stationary_frames():
    """Regression: splitting trees/scenery_objects out of draw_scenery()'s
    cache (to fix them rendering under a road, see the test above) briefly
    left them with no cache of their own at all - redrawing every tree and
    every bench/statue from scratch every single frame regardless of
    whether the camera moved, a real perf regression (most visible at
    night, when the lighting pass already eats most of the frame budget).
    Each must now behave like every other static layer: rebuild only on a
    genuine cache miss, reuse the surface object otherwise."""
    from theroadragetrip.render import common as common_module

    common_module._tree_frame_cache_key = None
    common_module._tree_frame_cache_surface = None
    common_module._scenery_object_frame_cache_key = None
    common_module._scenery_object_frame_cache_surface = None
    common_module.begin_static_cache_frame()
    common_module._pending_static_rebuilds.clear()

    grass = Scenery(
        [(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)],
        "grass", bbox=(0.0, 0.0, 40.0, 40.0), trees=[(20.0, 20.0)], tree_variations=[0.5],
    )
    bench = SceneryObject(x=20.0, y=20.0, kind="bench")
    screen = pygame.Surface((200, 200))

    draw_trees(screen, [grass], 20.0, 20.0, px_per_m=4.0, screen_w=200, screen_h=200)
    first_tree_surface = common_module._tree_frame_cache_surface
    assert first_tree_surface is not None

    draw_scenery_objects(screen, [bench], 20.0, 20.0, px_per_m=4.0, screen_w=200, screen_h=200)
    first_object_surface = common_module._scenery_object_frame_cache_surface
    assert first_object_surface is not None

    # Same camera and zoom, next frame: both must reuse their cached
    # surface, not rebuild from scratch.
    common_module.begin_static_cache_frame()
    draw_trees(screen, [grass], 20.0, 20.0, px_per_m=4.0, screen_w=200, screen_h=200)
    assert common_module._tree_frame_cache_surface is first_tree_surface
    draw_scenery_objects(screen, [bench], 20.0, 20.0, px_per_m=4.0, screen_w=200, screen_h=200)
    assert common_module._scenery_object_frame_cache_surface is first_object_surface


def test_build_ways_parses_benches_waste_baskets_and_bicycle_parking():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0, "tags": {"amenity": "bench"}},
        {"type": "node", "id": 2, "lat": 60.001, "lon": 25.001, "tags": {"amenity": "waste_basket"}},
        {"type": "node", "id": 3, "lat": 60.002, "lon": 25.002, "tags": {"amenity": "bicycle_parking"}},
        # Not street furniture - must not show up.
        {"type": "node", "id": 4, "lat": 60.003, "lon": 25.003, "tags": {"amenity": "restaurant"}},
    ]

    result = build_ways(elements)

    by_kind = {obj.kind: obj for obj in result.scenery_objects}
    assert set(by_kind) == {"bench", "waste_basket", "bicycle_parking"}
    assert by_kind["bench"].id == 1
    assert by_kind["waste_basket"].id == 2
    assert by_kind["bicycle_parking"].id == 3


def test_build_ways_parses_statues_but_not_plain_plaques():
    """Only 3D statue-like memorials/artwork become a "statue" scenery
    object - a flat plaque or bare stele isn't worth its own icon."""
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0, "tags": {"historic": "memorial", "memorial": "statue", "name": "Founder"}},
        {"type": "node", "id": 2, "lat": 60.001, "lon": 25.001, "tags": {"historic": "memorial", "memorial": "bust"}},
        {"type": "node", "id": 3, "lat": 60.002, "lon": 25.002, "tags": {"tourism": "artwork", "artwork_type": "sculpture"}},
        # Excluded: flat/text memorials, not statues.
        {"type": "node", "id": 4, "lat": 60.003, "lon": 25.003, "tags": {"historic": "memorial", "memorial": "plaque"}},
        {"type": "node", "id": 5, "lat": 60.004, "lon": 25.004, "tags": {"historic": "memorial", "memorial": "stele"}},
        {"type": "node", "id": 6, "lat": 60.005, "lon": 25.005, "tags": {"tourism": "artwork", "artwork_type": "mural"}},
    ]

    result = build_ways(elements)

    statues = {obj.id: obj for obj in result.scenery_objects}
    assert set(statues) == {1, 2, 3}
    assert all(obj.kind == "statue" for obj in statues.values())
    assert statues[1].name == "Founder"


def test_draw_scenery_objects_renders_each_kind_and_respects_viewport():
    from theroadragetrip.render import common as common_module

    # draw_scenery_objects() has its own static cache now - reset the
    # shared throttle so this test's call isn't denied by leftover state
    # from another test in the same run.
    common_module.begin_static_cache_frame()
    common_module._pending_static_rebuilds.clear()

    screen_w, screen_h, px_per_m = 200, 200, 8.0
    on_screen = SceneryObject(x=0.0, y=0.0, kind="bench")
    off_screen = SceneryObject(x=5000.0, y=5000.0, kind="bench")
    screen = pygame.Surface((screen_w, screen_h))
    background = (20, 120, 40)
    screen.fill(background)

    draw_scenery_objects(screen, [on_screen, off_screen], 0.0, 0.0, px_per_m=px_per_m, screen_w=screen_w, screen_h=screen_h)

    sx, sy = world_to_screen(0.0, 0.0, 0.0, 0.0, px_per_m, screen_w, screen_h)
    assert tuple(screen.get_at((sx, sy)))[:3] == SCENERY_OBJECT_COLORS["bench"]

    # The off-screen bench must not have touched any pixel - the whole
    # surface besides the on-screen bench's icon should still be background.
    non_background = sum(
        1
        for x in range(screen_w)
        for y in range(screen_h)
        if tuple(screen.get_at((x, y)))[:3] != background
    )
    assert non_background > 0  # the on-screen bench did draw something
    assert non_background < screen_w * screen_h // 4  # nowhere near "covers everything"


def test_scenery_colors_differ_by_landuse_value():
    """Different landuse/leisure/natural kinds must render distinct colors
    (regression: everything used to fall back to one generic green)."""
    assert SCENERY_COLORS["forest"] != SCENERY_COLORS["grass"]
    assert SCENERY_COLORS["residential"] != SCENERY_COLORS["forest"]
    assert SCENERY_COLORS["brownfield"] != SCENERY_COLORS["construction"]
    assert SCENERY_COLORS["farmland"] != SCENERY_COLORS["grass"]
    # No accidental collisions among the most common real-world kinds.
    common_kinds = [
        "forest", "grass", "residential", "commercial", "retail",
        "industrial", "farmland", "brownfield", "construction",
        "playground", "park",
    ]
    colors = [SCENERY_COLORS[k] for k in common_kinds]
    assert len(set(colors)) == len(colors)


def test_draw_construction_fences_outlines_construction_scenery_only():
    from theroadragetrip.render import common as common_module

    common_module.begin_static_cache_frame()
    common_module._pending_static_rebuilds.clear()

    screen_w, screen_h, px_per_m = 200, 200, 8.0
    construction = Scenery(
        [(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)],
        "construction",
        bbox=(-10.0, -10.0, 10.0, 10.0),
    )
    park = Scenery(
        [(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)],
        "park",
        bbox=(-10.0, -10.0, 10.0, 10.0),
    )
    screen = pygame.Surface((screen_w, screen_h))
    screen.fill((0, 0, 0))

    draw_construction_fences(screen, [construction], 0.0, 0.0, px_per_m=px_per_m, screen_w=screen_w, screen_h=screen_h)
    fence_pixels = sum(
        1
        for x in range(screen_w)
        for y in range(screen_h)
        if tuple(screen.get_at((x, y)))[:3] == CONSTRUCTION_FENCE_COLOR
    )
    assert fence_pixels > 0

    screen.fill((0, 0, 0))
    draw_construction_fences(screen, [park], 0.0, 0.0, px_per_m=px_per_m, screen_w=screen_w, screen_h=screen_h)
    fence_pixels_park = sum(
        1
        for x in range(screen_w)
        for y in range(screen_h)
        if tuple(screen.get_at((x, y)))[:3] == CONSTRUCTION_FENCE_COLOR
    )
    assert fence_pixels_park == 0


def test_plant_trees_uses_real_osm_positions_in_kinds_with_no_procedural_density():
    """A scenery kind with no procedural density (e.g. "grass", or any
    landuse/leisure value not in tree_density) must still use real OSM
    tree data when the area actually has some - real data shouldn't
    require also being a kind eligible for made-up trees."""
    grass = Scenery(
        [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        "grass",
        bbox=(0.0, 0.0, 100.0, 100.0),
    )
    real_trees = [(20.0, 20.0), (60.0, 40.0)]

    plant_trees([grass], [], real_trees=real_trees)

    assert grass.trees == real_trees
    assert grass.trees_from_osm is True

    # And still gets nothing procedural when no real trees are nearby.
    empty_grass = Scenery(
        [(200.0, 0.0), (300.0, 0.0), (300.0, 100.0), (200.0, 100.0)],
        "grass",
        bbox=(200.0, 0.0, 300.0, 100.0),
    )
    plant_trees([empty_grass], [], real_trees=real_trees)
    assert empty_grass.trees == []
    assert empty_grass.trees_from_osm is False


def test_build_ways_uses_real_osm_trees_instead_of_procedural():
    elements = [
        {"type": "node", "id": 1, "lat": 60.1, "lon": 25.1},
        {"type": "node", "id": 2, "lat": 60.1, "lon": 25.14},
        {"type": "node", "id": 3, "lat": 60.14, "lon": 25.14},
        {"type": "node", "id": 4, "lat": 60.14, "lon": 25.1},
        {"type": "way", "id": 20, "nodes": [1, 2, 3, 4, 1], "tags": {"natural": "wood"}},
        # Two surveyed real trees inside the wood polygon.
        {"type": "node", "id": 5, "lat": 60.12, "lon": 25.12, "tags": {"natural": "tree"}},
        {"type": "node", "id": 6, "lat": 60.13, "lon": 25.13, "tags": {"natural": "tree"}},
    ]

    ways, _, _, sceneries, _, _ = build_ways(elements)

    assert sceneries[0].trees_from_osm is True
    assert sorted(sceneries[0].trees) == sorted([(25120.0, 60120.0), (25130.0, 60130.0)])


def test_build_ways_parses_taxi_stops():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0, "tags": {"highway": "taxi_stop"}},
        {"type": "node", "id": 2, "lat": 60.001, "lon": 25.001, "tags": {"amenity": "taxi"}},
    ]

    result = build_ways(elements)

    assert [stop.id for stop in result.taxi_stops] == [1, 2]


def test_build_ways_parses_parking_area_as_scenery():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.001, "lon": 25.0},
        {"type": "node", "id": 3, "lat": 60.001, "lon": 25.001},
        {"type": "node", "id": 4, "lat": 60.0, "lon": 25.001},
        {
            "type": "way",
            "id": 10,
            "nodes": [1, 2, 3, 4, 1],
            "tags": {"amenity": "parking", "name": "Parking Area"},
        },
    ]

    result = build_ways(elements)

    assert len(result.sceneries) == 1
    assert result.sceneries[0].kind == "parking"


def test_hard_tree_impact_knocks_tree_down_and_smokes_taxi():
    manager = TaxiManager([Way([(0.0, 0.0), (100.0, 0.0)], "residential", 4.0)])
    scenery = Scenery([(0.0, -20.0), (20.0, -20.0), (20.0, 20.0)], "park", trees=[(0.0, 0.0)])
    car = Car(x=0.0, y=0.0, heading=0.0, speed=25.0)

    assert manager.check_tree_collision(car, [scenery], 1.0, previous_position=(-10.0, 0.0))
    assert (id(scenery), 0) in manager.fallen_trees
    assert manager.tree_effects[(id(scenery), 0)]["angle"] == car.heading
    assert manager.tree_wait_timer == 5.0
    assert manager.taxi_smoke_timer == 5.0


def test_driving_into_construction_fence_stops_the_car_and_penalizes():
    """A construction-site scenery is fenced off - a car driving into it
    must crash the same way a building does, not pass straight through."""
    manager = TaxiManager([Way([(0.0, 0.0), (100.0, 0.0)], "residential", 4.0)])
    construction = Scenery(
        [(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)],
        "construction",
        bbox=(-10.0, -10.0, 10.0, 10.0),
    )
    car = Car(x=0.0, y=0.0, heading=0.0, speed=20.0)
    score_before = manager.total_score

    assert manager.check_fence_collision(car, [construction], 1.0, previous_position=(-20.0, 0.0))
    assert (car.x, car.y) == (-20.0, 0.0)
    assert car.speed == 0.0
    assert manager.total_score < score_before

    # A non-construction scenery (e.g. a park) must not trigger a crash.
    park = Scenery(
        [(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)],
        "park",
        bbox=(-10.0, -10.0, 10.0, 10.0),
    )
    car2 = Car(x=0.0, y=0.0, heading=0.0, speed=20.0)
    assert not manager.check_fence_collision(car2, [park], 1.0, previous_position=(-20.0, 0.0))


def test_building_window_rows_follow_osm_levels():
    building = Building(
        [(0.0, 0.0), (10.0, 0.0), (10.0, 12.0), (0.0, 12.0)],
        height_m=99.0,
        levels=4,
    )

    assert _building_window_story_count(building) == 4


def test_commercial_buildings_are_marked_for_storefront_ground_floor():
    commercial = Building(
        [(0.0, 0.0), (10.0, 0.0), (10.0, 12.0), (0.0, 12.0)],
        levels=5,
        venue_type="restaurant",
    )
    residential = Building(
        [(20.0, 0.0), (30.0, 0.0), (30.0, 12.0), (20.0, 12.0)],
        levels=5,
        venue_type="residential",
    )

    assert _building_is_commercial(commercial) is True
    assert _building_is_commercial(residential) is False


def test_visible_facades_work_for_different_building_shapes():
    shapes = [
        [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)],
        [(0.0, 0.0), (20.0, 0.0), (10.0, 20.0)],
        [(0.0, 0.0), (30.0, 0.0), (30.0, 10.0), (15.0, 10.0), (15.0, 25.0), (0.0, 25.0)],
    ]
    for points in shapes:
        roof = [(x - 7.0, y - 10.0) for x, y in points]
        visible = _visible_building_edges(points, roof)
        assert visible
        assert len(visible) < len(points)

    rectangle = [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)]
    rectangle_roof = [(x - 7.0, y - 10.0) for x, y in rectangle]
    assert _visible_building_edges(rectangle, rectangle_roof) == {1, 2}


def test_restaurant_place_is_not_a_map_district_label():
    assert "restaurant" not in DISTRICT_PLACE_KINDS
    assert "city" in DISTRICT_PLACE_KINDS


def test_toscana_render_sign_anchor_lands_on_facade_not_roof_center():
    building = Building(
        [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)],
        bbox=(0.0, 0.0, 20.0, 20.0),
    )
    restaurant = Place(10.0, 10.0, "Toscana", "restaurant")
    building.associated_places = [restaurant]

    anchor = _building_sign_anchor(building, restaurant.x, restaurant.y, 0)

    assert anchor == (10.0, 0.0)
    assert anchor != (restaurant.x, restaurant.y)


def test_facade_sign_angle_stays_upright_across_zoom():
    assert _building_sign_angle((0.0, 0.0), (100.0, 100.0)) == -45.0
    assert _building_sign_angle((0.0, 0.0), (1000.0, 1000.0)) == -45.0
    assert _building_sign_angle((0.0, 0.0), (-100.0, -100.0)) == -45.0


def test_toscana_draw_buildings_renders_facade_sign_pixels():
    pygame.init()
    try:
        render_module._building_sign_font_cache.clear()
        render_module._building_sign_surface_cache.clear()
        building = Building(
            [(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)],
            bbox=(0.0, 0.0, 40.0, 40.0),
            associated_places=[Place(20.0, 20.0, "Toscana", "restaurant")],
        )
        screen = pygame.Surface((400, 400), pygame.SRCALPHA)
        screen.fill((0, 0, 0, 0))
        _draw_buildings_uncached(
            screen, [building], 20.0, 20.0, px_per_m=9.0,
            screen_w=400, screen_h=400,
        )

        _, border_color, _ = _building_sign_theme("restaurant")
        gold_pixels = []
        for pixel_y in range(screen.get_height()):
            for pixel_x in range(screen.get_width()):
                red, green, blue, alpha = screen.get_at((pixel_x, pixel_y))
                if (red, green, blue) == border_color and alpha:
                    gold_pixels.append((pixel_x, pixel_y))

        assert gold_pixels, "Toscana facade sign did not render"
        center_y = sum(pixel_y for _, pixel_y in gold_pixels) / len(gold_pixels)
        roof_center_y = world_to_screen(20.0, 20.0, 20.0, 20.0, 9.0, 400, 400)[1]
        assert abs(center_y - roof_center_y) > 8.0
        screen_points = [
            world_to_screen(x, y, 20.0, 20.0, 9.0, 400, 400)
            for x, y in building.points_m
        ]
        roof_points = [(x - 30.0 * 0.7, y - 30.0) for x, y in screen_points]
        assert not any(point_in_polygon(x, y, roof_points) for x, y in gold_pixels)
    finally:
        pygame.quit()


def test_named_building_renders_name_on_visible_facade():
    pygame.init()
    try:
        render_module._building_sign_font_cache.clear()
        render_module._building_sign_surface_cache.clear()
        building = Building(
            [(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)],
            name="Generic Hall",
            bbox=(0.0, 0.0, 40.0, 40.0),
        )
        screen = pygame.Surface((400, 400), pygame.SRCALPHA)
        _draw_buildings_uncached(
            screen, [building], 20.0, 20.0, px_per_m=9.0,
            screen_w=400, screen_h=400,
        )
        gold_pixels = [
            (x, y)
            for y in range(400)
            for x in range(400)
            if tuple(screen.get_at((x, y)))[:3] == (211, 169, 70)
        ]
        assert gold_pixels, "named building facade sign did not render"
    finally:
        pygame.quit()


def test_building_sign_font_stays_realistic_when_zoomed_in():
    assert MAX_BUILDING_SIGN_FONT_SIZE == 32


def test_facade_sign_does_not_cover_the_door():
    """A sign anchored at the same entrance as a door must not be drawn over
    it (regression: signs used to anchor directly on top of the door)."""
    pygame.init()
    try:
        render_module._building_sign_font_cache.clear()
        render_module._building_sign_surface_cache.clear()
        building = Building(
            [(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)],
            bbox=(0.0, 0.0, 40.0, 40.0),
            entrances=[(20.0, 0.0)],
            associated_places=[Place(20.0, 20.0, "Toscana", "restaurant")],
        )
        screen = pygame.Surface((400, 400), pygame.SRCALPHA)
        _draw_buildings_uncached(
            screen, [building], 20.0, 20.0, px_per_m=9.0, screen_w=400, screen_h=400,
        )

        door_pixels = {
            (x, y)
            for y in range(400)
            for x in range(400)
            if tuple(screen.get_at((x, y)))[:3] == (58, 48, 42)
        }
        _, border_color, _ = _building_sign_theme("restaurant")
        sign_pixels = {
            (x, y)
            for y in range(400)
            for x in range(400)
            if tuple(screen.get_at((x, y)))[:3] == border_color
        }
        assert door_pixels, "door did not render"
        assert sign_pixels, "sign did not render"
        assert door_pixels.isdisjoint(sign_pixels)

        # The sign should sit entirely above where doors are drawn.
        door_top_y = min(y for _, y in door_pixels)
        sign_bottom_y = max(y for _, y in sign_pixels)
        assert sign_bottom_y <= door_top_y
    finally:
        pygame.quit()


def test_door_sits_at_ground_level_on_a_tall_building():
    """Regression: doors were anchored/sized off DOOR_TOP_V_RATIO of the
    *whole* facade depth, which only reached the ground by coincidence on
    a short building - a tall, multi-storey building's door floated a
    third to half way up its wall instead of sitting at its base."""
    pygame.init()
    try:
        tall_building = Building(
            [(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)],
            bbox=(0.0, 0.0, 40.0, 40.0),
            entrances=[(20.0, 0.0)],
            height_m=24.0,
        )
        screen = pygame.Surface((400, 400), pygame.SRCALPHA)
        _draw_buildings_uncached(
            screen, [tall_building], 20.0, 20.0, px_per_m=9.0, screen_w=400, screen_h=400,
        )
        door_pixels = {
            (x, y)
            for y in range(400)
            for x in range(400)
            if tuple(screen.get_at((x, y)))[:3] == (58, 48, 42)
        }
        assert door_pixels, "door did not render"

        ground_y = world_to_screen(20.0, 0.0, 20.0, 20.0, 9.0, 400, 400)[1]
        door_bottom_y = max(y for _, y in door_pixels)
        # The door's base must sit right at the entrance's ground point,
        # not floating well above it (a few px of line thickness/AA only).
        assert abs(door_bottom_y - ground_y) <= 3
    finally:
        pygame.quit()


def test_facade_sign_size_scales_with_zoom_like_a_real_object():
    """Sign dimensions are capped in meters, not pixels, so they stay a
    believable real-world size (a few metres wide) at every zoom instead of
    a fixed pixel size that shrinks or balloons as the camera zooms."""
    pygame.init()
    try:
        render_module._building_sign_font_cache.clear()
        render_module._building_sign_surface_cache.clear()
        building = Building(
            [(0.0, 0.0), (60.0, 0.0), (60.0, 40.0), (0.0, 40.0)],
            bbox=(0.0, 0.0, 60.0, 40.0),
            height_m=14.0,
            # A long name so the rendered text is always wider than the real-world
            # sign-width cap (the thing under test), not the other way around.
            associated_places=[Place(30.0, 20.0, "Ravintola Toscana Deluxe", "restaurant")],
        )
        _, border_color, _ = _building_sign_theme("restaurant")

        def sign_pixel_width(px_per_m):
            screen = pygame.Surface((1200, 1200), pygame.SRCALPHA)
            _draw_buildings_uncached(
                screen, [building], 30.0, 20.0, px_per_m=px_per_m, screen_w=1200, screen_h=1200,
            )
            xs = [
                x for y in range(1200) for x in range(1200)
                if tuple(screen.get_at((x, y)))[:3] == border_color
            ]
            assert xs, f"sign did not render at px_per_m={px_per_m}"
            return max(xs) - min(xs)

        narrow_zoom_width = sign_pixel_width(9.0)
        wide_zoom_width = sign_pixel_width(18.0)

        # Roughly double the zoom should roughly double the on-screen sign
        # size, not keep a fixed pixel size.
        assert wide_zoom_width > narrow_zoom_width * 1.4
        # And it should stay within a believable real-world sign footprint
        # (some slack for the sign quad's facade skew widening its on-screen
        # bounding box beyond its own u-axis width).
        from theroadragetrip.render.buildings import MAX_BUILDING_SIGN_WIDTH_M
        slack_px = 20
        assert narrow_zoom_width <= MAX_BUILDING_SIGN_WIDTH_M * 9.0 + slack_px
        assert wide_zoom_width <= MAX_BUILDING_SIGN_WIDTH_M * 18.0 + slack_px
    finally:
        pygame.quit()


def test_facade_sign_color_matches_business_type():
    default_theme = _building_sign_theme(None)
    restaurant_theme = _building_sign_theme("restaurant")
    pharmacy_theme = _building_sign_theme("pharmacy")
    bank_theme = _building_sign_theme("bank")

    # Distinct business categories get visibly distinct colors...
    assert len({restaurant_theme[1], pharmacy_theme[1], bank_theme[1]}) == 3
    assert restaurant_theme != default_theme
    # ...and anything unrecognized falls back to the original look rather
    # than an arbitrary color.
    assert _building_sign_theme("some_unmapped_osm_tag") == default_theme
    assert _building_sign_theme(None) == default_theme


def test_grass_texture_is_cached_across_stationary_frames():
    """Regression: draw_grass_texture used to redraw the whole screen from
    scratch (~100+ individual tile blits) every single frame regardless of
    whether the camera had moved. It should now behave like the other
    static layers: rebuild only on a genuine cache miss."""
    from theroadragetrip.render import common as common_module

    pygame.init()
    try:
        common_module._grass_frame_cache_key = None
        common_module._grass_frame_cache_surface = None
        screen = pygame.Surface((400, 300))

        # _allow_static_rebuild's one-rebuild-per-frame throttle uses a
        # module-level counter shared across every static layer and reset
        # once per real game frame via begin_static_cache_frame(); reset it
        # explicitly here so an earlier test's leftover state can't make an
        # "allowed" rebuild below spuriously get throttled.
        common_module.begin_static_cache_frame()
        draw_grass_texture(screen, 0.0, 0.0, px_per_m=9.0, screen_w=400, screen_h=300)
        first_surface = common_module._grass_frame_cache_surface
        assert first_surface is not None

        # Same camera and zoom: must reuse the cached surface, not rebuild.
        draw_grass_texture(screen, 0.0, 0.0, px_per_m=9.0, screen_w=400, screen_h=300)
        assert common_module._grass_frame_cache_surface is first_surface

        # A small move within the cache padding: still reused.
        draw_grass_texture(screen, 1.0, 1.0, px_per_m=9.0, screen_w=400, screen_h=300)
        assert common_module._grass_frame_cache_surface is first_surface

        # A move far past the padding: must rebuild (a fresh frame's budget,
        # since real gameplay would have called begin_static_cache_frame()
        # again by now too).
        common_module.begin_static_cache_frame()
        draw_grass_texture(screen, 500.0, 500.0, px_per_m=9.0, screen_w=400, screen_h=300)
        assert common_module._grass_frame_cache_surface is not first_surface
    finally:
        pygame.quit()


def test_grass_texture_rebuild_does_not_redraw_every_tile_every_frame():
    """The uncached tile-blitting path should only run on an actual cache
    miss, not once per frame."""
    from theroadragetrip.render import common as common_module
    from theroadragetrip.render.scenery import _draw_grass_texture_uncached

    pygame.init()
    try:
        common_module._grass_frame_cache_key = None
        common_module._grass_frame_cache_surface = None
        common_module.begin_static_cache_frame()
        screen = pygame.Surface((400, 300))

        rebuild_calls = 0
        original = _draw_grass_texture_uncached

        def counting_uncached(*args, **kwargs):
            nonlocal rebuild_calls
            rebuild_calls += 1
            return original(*args, **kwargs)

        import theroadragetrip.render.scenery as scenery_module
        scenery_module._draw_grass_texture_uncached = counting_uncached
        try:
            for _ in range(10):
                draw_grass_texture(screen, 0.0, 0.0, px_per_m=9.0, screen_w=400, screen_h=300)
        finally:
            scenery_module._draw_grass_texture_uncached = original

        assert rebuild_calls == 1
    finally:
        pygame.quit()


def test_simultaneous_routine_cache_misses_are_spread_across_frames():
    """Most of a layer's frame_cache_key is a shared, quantized camera
    position, so an entirely ordinary cache-padding/zoom-bucket crossing
    during continuous driving goes stale for *every* layer on the very same
    frame just as reliably as an explicit camera jump does. Regression: an
    earlier version of this throttle only denied a layer already queued via
    invalidate_static_caches()/invalidate_static_caches_for_camera_jump(),
    so a routine multi-layer staleness burst (no explicit invalidation
    involved) let every layer rebuild on the same frame, uncached - the
    periodic full-cost spike ("FPS drops... every few seconds") that this
    throttle exists to prevent. Every miss must now queue and be spread
    across frames, one layer's rebuild per frame, regardless of how it went
    stale."""
    from theroadragetrip.render import common as common_module

    common_module.begin_static_cache_frame()
    common_module._pending_static_rebuilds.clear()
    fake_surface = object()  # anything that isn't None

    # Two unrelated layers go stale on the same frame with no explicit
    # invalidate_static_caches() call at all - just like an ordinary
    # bucket-crossing during continuous panning.
    assert common_module._allow_static_rebuild("roads", fake_surface) is True
    assert common_module._allow_static_rebuild("buildings", fake_surface) is False

    # Next frame: budget resets, so the layer that lost the race gets its turn.
    common_module.begin_static_cache_frame()
    assert common_module._allow_static_rebuild("buildings", fake_surface) is True


def test_camera_jump_lets_every_layer_take_its_turn_without_starvation():
    """invalidate_static_caches_for_camera_jump() - called after a respawn
    or a fresh session's starting camera snaps somewhere new - only resets
    each layer's frame_cache_key so its next draw call notices it's stale;
    _allow_static_rebuild's self-queuing (see its docstring) is what
    actually spreads the resulting simultaneous staleness burst (grass
    included, since unlike the other five it's not covered by
    invalidate_static_caches()) across several frames instead of six full,
    uncached redraws landing on one, while still guaranteeing every layer
    eventually gets its turn."""
    from theroadragetrip.render import common as common_module

    common_module.begin_static_cache_frame()
    common_module._pending_static_rebuilds.clear()
    common_module.invalidate_static_caches_for_camera_jump()
    fake_surface = object()
    layers = ["roads", "buildings", "scenery", "water", "labels", "grass"]

    # Nothing is queued yet - invalidating just clears the cache keys;
    # queuing happens lazily as each layer's draw call actually notices its
    # own miss.
    assert not common_module._pending_static_rebuilds

    allowed = set()
    for _ in range(len(layers)):
        common_module.begin_static_cache_frame()
        for layer in layers:
            if layer in allowed:
                continue
            if common_module._allow_static_rebuild(layer, fake_surface):
                allowed.add(layer)
                break  # only one rebuild allowed per frame

    # Every layer got its turn within one frame per other layer, with none
    # starved out indefinitely.
    assert allowed == set(layers)
    assert not common_module._pending_static_rebuilds


def test_last_drawn_layer_is_not_starved_by_continuously_stale_earlier_ones():
    """Regression: labels is drawn dead last every frame (after grass,
    scenery, water, roads, buildings, ...). The old throttle granted its
    single per-frame rebuild to whichever layer's draw call simply
    happened to run first and was stale *that* frame - with no memory of
    who'd been waiting - so during continuous driving (bucket-crossings
    make every layer miss on the same frame routinely, not rarely) an
    earlier layer that kept going stale too, frame after frame, could win
    every single time, starving labels indefinitely. This is exactly what
    made toggling to label mode 2 appear to do nothing while driving: its
    forced cache miss just kept losing the race and stayed stuck showing
    mode 1's stale surface. Priority must go to the longest-waiting layer,
    not whoever's asked first this frame."""
    from theroadragetrip.render import common as common_module

    common_module.begin_static_cache_frame()
    common_module._pending_static_rebuilds.clear()
    fake_surface = object()
    # "grass" first, "labels" last - the real per-frame draw order.
    layers = ["grass", "scenery", "water", "roads", "buildings", "labels"]

    serviced_order = []
    for _ in range(len(layers) * 2):  # generous budget - real bound is len(layers)
        common_module.begin_static_cache_frame()
        for layer in layers:
            # Every layer goes stale on every frame - continuous driving,
            # not a one-off burst that settles once each layer succeeds
            # once (unlike the camera-jump test above).
            if common_module._allow_static_rebuild(layer, fake_surface):
                serviced_order.append(layer)
        if len(set(serviced_order)) == len(layers):
            break

    assert set(serviced_order) == set(layers), (
        f"labels (and/or others) never got a turn - serviced: {serviced_order}"
    )
    # "labels" must win within one frame per other layer waiting alongside
    # it, not be pushed out indefinitely by "grass" re-qualifying every frame.
    assert serviced_order.index("labels") < len(layers)


def test_static_rebuild_always_allows_the_very_first_build():
    """A layer with no cached surface yet has nothing to show if denied, so
    it's exempt from the throttle regardless of how many other layers are
    also building for the first time on the same frame (e.g. initial world
    load)."""
    from theroadragetrip.render import common as common_module

    common_module.begin_static_cache_frame()
    assert common_module._allow_static_rebuild("roads", None) is True
    assert common_module._allow_static_rebuild("buildings", None) is True
    assert common_module._allow_static_rebuild("scenery", None) is True


def test_finnish_color_name_maps_to_expected_wall_color():
    assert _building_colors_from_name("Sininen talo")[0] == FINNISH_BUILDING_COLOR_NAMES["sini"]
    assert _building_colors_from_name("Punatalo Oy")[0] == FINNISH_BUILDING_COLOR_NAMES["puna"]
    assert _building_colors_from_name("Valkea Kartano")[0] == FINNISH_BUILDING_COLOR_NAMES["valkea"]
    assert _building_colors_from_name("Kissankulma") is None
    assert _building_colors_from_name(None) is None


def test_building_named_with_a_color_renders_in_that_color():
    """A building whose OSM name names a Finnish color (e.g. "Sininen
    talo") should render with that color instead of the usual
    pseudo-random per-building wall/roof pick."""
    pygame.init()
    try:
        # Font/surface objects cached across a pygame.quit()/init() cycle are
        # invalid; clear the sign caches so an earlier test's Font isn't reused.
        render_module._building_sign_font_cache.clear()
        render_module._building_sign_surface_cache.clear()
        screen = pygame.Surface((200, 200))
        sentinel_bg = (255, 0, 255)  # not used by any building/roof color
        screen.fill(sentinel_bg)

        building = Building(
            [(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)],
            name="Sininen talo",
            height_m=8.0,
        )
        _draw_buildings_uncached(
            screen, [building], camx=0.0, camy=0.0, px_per_m=5.0, screen_w=200, screen_h=200,
        )

        expected_wall = FINNISH_BUILDING_COLOR_NAMES["sini"]
        seen_colors = {
            tuple(screen.get_at((x, y))[:3])
            for x in range(30, 170)
            for y in range(30, 170)
        }
        assert expected_wall in seen_colors
        assert not seen_colors & set(BUILDING_WALL_COLORS), (
            "named building still used the default pseudo-random palette"
        )
    finally:
        pygame.quit()
