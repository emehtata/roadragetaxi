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
from theroadragetrip.osm import Building, Place, Scenery, Way, associate_places_with_buildings
from theroadragetrip.geo import point_in_polygon
from theroadragetrip.physics import Car
from theroadragetrip.render import (
    DISTRICT_PLACE_KINDS,
    MAX_BUILDING_DEPTH_PX,
    MAX_BUILDING_SIGN_FONT_SIZE,
    BUILDING_WALL_COLORS,
    _building_is_commercial,
    _building_sign_anchor,
    _building_sign_angle,
    _building_sign_foreshorten,
    _building_sign_theme,
    _building_window_story_count,
    _visible_building_edges,
    _draw_buildings_uncached,
    draw_grass_texture,
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
    assert common_module._pending_static_rebuilds == set()

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
    assert common_module._pending_static_rebuilds == set()


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
