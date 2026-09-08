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

from theroadragetrip.osm import build_ways, plant_trees
from theroadragetrip.osm import Building, Place, Scenery, Way, associate_places_with_buildings
from theroadragetrip.physics import Car
from theroadragetrip.render import _building_is_commercial, _building_window_story_count, _visible_building_edges
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
