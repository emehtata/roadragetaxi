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

from theroadragetrip.osm import build_ways, plant_trees
from theroadragetrip.osm import Building, Place, Scenery, Way, associate_places_with_buildings
from theroadragetrip.geo import point_in_polygon
from theroadragetrip.physics import Car
from theroadragetrip.render import (
    DISTRICT_PLACE_KINDS,
    MAX_BUILDING_SIGN_FONT_SIZE,
    _building_is_commercial,
    _building_sign_anchor,
    _building_window_story_count,
    _visible_building_edges,
    _draw_buildings_uncached,
    world_to_screen,
)


def test_seven_floor_building_keeps_floor_rows_separate():
    building = Building(
        [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)],
        levels=7,
    )

    assert _building_window_story_count(building) == 7
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


def test_toscana_draw_buildings_renders_facade_sign_pixels():
    pygame.init()
    try:
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

        gold_pixels = []
        for pixel_y in range(screen.get_height()):
            for pixel_x in range(screen.get_width()):
                red, green, blue, alpha = screen.get_at((pixel_x, pixel_y))
                if (red, green, blue) == (211, 169, 70) and alpha:
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


def test_building_sign_font_stays_realistic_when_zoomed_in():
    assert MAX_BUILDING_SIGN_FONT_SIZE == 32
