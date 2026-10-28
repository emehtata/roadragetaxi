import math
import sys
import types

import pytest

fake_pyproj = types.SimpleNamespace()


class FakeTransformer:
    @staticmethod
    def from_crs(a, b, always_xy=True):
        return FakeTransformer()

    def transform(self, lon, lat):
        return (lon * 1000.0, lat * 1000.0)

fake_pyproj.Transformer = FakeTransformer


@pytest.fixture(autouse=True)
def _fake_pyproj(monkeypatch):
    """The fake pyproj for this module's tests only, restored after each:
    installed at import, it leaked into every later test (cached
    municipality centres projected with it, e.g. a long fare to nowhere)."""
    monkeypatch.setitem(sys.modules, "pyproj", fake_pyproj)



from theroadragetrip.osm import build_ways, plant_trees
from theroadragetrip.osm import Building, Place, Scenery, SceneryObject, Way, associate_places_with_buildings
from theroadragetrip.geo import point_in_polygon
from theroadragetrip.map_style import DISTRICT_PLACE_KINDS, SCENERY_COLORS
from theroadragetrip.physics import Car
from theroadragetrip.building_style import BUILDING_WALL_COLORS, FINNISH_BUILDING_COLOR_NAMES, _building_colors_from_name, _building_is_commercial, _building_is_house, _building_window_story_count


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


def test_parking_lot_defaults_to_asphalt_surface_but_keeps_an_explicit_one():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.001, "lon": 25.0},
        {"type": "node", "id": 3, "lat": 60.001, "lon": 25.001},
        {"type": "node", "id": 4, "lat": 60.0, "lon": 25.001},
        {
            "type": "way", "id": 10, "nodes": [1, 2, 3, 4, 1],
            "tags": {"amenity": "parking"},  # no surface tag at all
        },
        {"type": "node", "id": 5, "lat": 60.002, "lon": 25.002},
        {"type": "node", "id": 6, "lat": 60.003, "lon": 25.002},
        {"type": "node", "id": 7, "lat": 60.003, "lon": 25.003},
        {"type": "node", "id": 8, "lat": 60.002, "lon": 25.003},
        {
            "type": "way", "id": 20, "nodes": [5, 6, 7, 8, 5],
            "tags": {"landuse": "parking", "surface": "gravel"},
        },
    ]

    _, _, _, sceneries, _, _ = build_ways(elements)

    parking_lots = sorted((s for s in sceneries if s.kind == "parking"), key=lambda s: s.bbox[0])
    assert len(parking_lots) == 2
    untagged, tagged = parking_lots  # the untagged way's nodes are west of the tagged one's
    assert untagged.surface == "asphalt"
    assert tagged.surface == "gravel"


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


@pytest.mark.parametrize("kind", ["biergarten", "grave_yard"])
@pytest.mark.parametrize("as_relation", [False, True])
def test_biergarten_and_graveyard_amenity_areas_are_preserved(kind, as_relation):
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.02},
        {"type": "node", "id": 3, "lat": 60.02, "lon": 25.02},
        {"type": "node", "id": 4, "lat": 60.02, "lon": 25.0},
        {"type": "way", "id": 10, "nodes": [1, 2, 3, 4, 1],
         "tags": {} if as_relation else {"amenity": kind, "name": "Example"}},
    ]
    if as_relation:
        elements.append({"type": "relation", "id": 20, "members": [{"type": "way", "ref": 10, "role": "outer"}],
                         "tags": {"type": "multipolygon", "amenity": kind, "name": "Example"}})
    world = build_ways(elements)
    assert any(area.kind == kind and area.name == "Example" for area in world.sceneries)


@pytest.mark.parametrize("kind", ["biergarten", "grave_yard"])
def test_biergarten_and_graveyard_nodes_get_visual_markers(kind):
    world = build_ways([{"type": "node", "id": 1, "lat": 60.0, "lon": 25.0, "tags": {"amenity": kind}}])
    assert any(obj.kind == kind for obj in world.scenery_objects)


@pytest.mark.parametrize("barrier", ["wall", "fence", "hedge", "railing"])
@pytest.mark.parametrize("tags, kind", [({"landuse": "cemetery"}, "cemetery"),
                                       ({"amenity": "grave_yard"}, "grave_yard"),
                                       ({"amenity": "biergarten"}, "biergarten")])
def test_enclosed_sites_preserve_both_ground_and_boundary(tags, kind, barrier):
    elements = [
        {"type": "node", "id": i + 1, "lat": lat, "lon": lon}
        for i, (lon, lat) in enumerate([(25, 60), (25.02, 60), (25.02, 60.02), (25, 60.02)])
    ]
    elements.append({"type": "way", "id": 24971057, "nodes": [1, 2, 3, 4, 1],
                     "tags": {**tags, "barrier": barrier, "name": "Enclosed site"}})
    world = build_ways(elements)
    assert any(area.kind == kind and area.name == "Enclosed site" for area in world.sceneries)
    assert world.railings


def test_build_ways_leaves_unmapped_forest_trees_to_the_client():
    elements = [
        {"type": "node", "id": 1, "lat": 60.1, "lon": 25.1},
        {"type": "node", "id": 2, "lat": 60.1, "lon": 25.14},
        {"type": "node", "id": 3, "lat": 60.14, "lon": 25.14},
        {"type": "node", "id": 4, "lat": 60.14, "lon": 25.1},
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": "residential"}},
        {"type": "way", "id": 20, "nodes": [1, 2, 3, 4, 1], "tags": {"natural": "wood"}},
    ]

    ways, _, _, sceneries, _, _ = build_ways(elements)

    assert sceneries[0].kind == "wood" and sceneries[0].trees == []


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


def test_neither_forests_nor_parks_create_server_trees():
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

    assert forest.trees == [] and park.trees == []


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










def test_build_ways_parses_benches_waste_baskets_and_bicycle_parking():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0, "tags": {"amenity": "bench"}},
        {"type": "node", "id": 2, "lat": 60.001, "lon": 25.001, "tags": {"amenity": "waste_basket"}},
        {"type": "node", "id": 3, "lat": 60.002, "lon": 25.002, "tags": {"amenity": "bicycle_parking"}},
        {"type": "node", "id": 5, "lat": 60.004, "lon": 25.004, "tags": {"amenity": "fountain"}},
        {"type": "node", "id": 6, "lat": 60.005, "lon": 25.005, "tags": {"amenity": "fuel"}},
        {"type": "node", "id": 7, "lat": 60.006, "lon": 25.006, "tags": {"leisure": "picnic_table"}},
        {"type": "node", "id": 8, "lat": 60.007, "lon": 25.007, "tags": {"leisure": "firepit"}},
        {"type": "node", "id": 9, "lat": 60.008, "lon": 25.008, "tags": {"barrier": "gate"}},
        {"type": "node", "id": 10, "lat": 60.009, "lon": 25.009, "tags": {"barrier": "bollard"}},
        {"type": "node", "id": 11, "lat": 60.010, "lon": 25.010, "tags": {"highway": "street_lamp"}},
        # Not street furniture - must not show up.
        {"type": "node", "id": 4, "lat": 60.003, "lon": 25.003, "tags": {"amenity": "restaurant"}},
    ]

    result = build_ways(elements)

    by_kind = {obj.kind: obj for obj in result.scenery_objects}
    assert set(by_kind) == {
        "bench", "waste_basket", "bicycle_parking", "fountain", "fuel",
        "picnic_table", "firepit", "gate", "bollard", "street_lamp",
    }
    assert by_kind["bench"].id == 1
    assert by_kind["waste_basket"].id == 2
    assert by_kind["bicycle_parking"].id == 3
    assert by_kind["fountain"].id == 5
    assert by_kind["fuel"].id == 6
    assert by_kind["picnic_table"].id == 7
    assert by_kind["firepit"].id == 8
    assert by_kind["gate"].id == 9
    assert by_kind["bollard"].id == 10
    assert by_kind["street_lamp"].id == 11


def test_build_ways_aligns_a_bench_beside_its_nearby_footway():
    """Regression: a bench used to always render as the same axis-aligned
    box regardless of what path it sits beside. It must now snap to the
    nearest way (a footway here, not a road) and get pushed out past that
    way's edge on whichever side the raw node already leaned towards."""
    elements = [
        {"type": "node", "id": 1, "lat": 60.000, "lon": 25.000},
        {"type": "node", "id": 2, "lat": 60.000, "lon": 25.010},
        # Nudged a touch off the (horizontal) footway's line.
        {"type": "node", "id": 3, "lat": 60.0002, "lon": 25.005, "tags": {"amenity": "bench"}},
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": "footway"}},
    ]

    result = build_ways(elements)

    benches = [o for o in result.scenery_objects if o.kind == "bench"]
    assert len(benches) == 1
    bench = benches[0]
    assert bench.direction_angle is not None
    footway_y = result.ways[0].points_m[0][1]
    # Pushed out past the footway's half-width, not sitting on its
    # centerline or left floating at its raw (off-center) node position.
    assert abs(bench.y - footway_y) > 0.0


def test_build_ways_aligns_bicycle_parking_and_gates_with_their_path():
    """Bicycle parking rendered axis-aligned across a diagonal street: it
    follows the nearby way like a bench. A gate stands on its path, so it
    takes the path's direction without being pushed off it."""
    elements = [
        {"type": "node", "id": 1, "lat": 60.000, "lon": 25.000},
        {"type": "node", "id": 2, "lat": 60.010, "lon": 25.010},
        {"type": "node", "id": 3, "lat": 60.0051, "lon": 25.005, "tags": {"amenity": "bicycle_parking"}},
        {"type": "node", "id": 4, "lat": 60.002, "lon": 25.002, "tags": {"barrier": "gate"}},
        {"type": "way", "id": 10, "nodes": [1, 4, 2], "tags": {"highway": "footway"}},
    ]

    result = build_ways(elements)

    by_kind = {o.kind: o for o in result.scenery_objects}
    assert abs(by_kind["bicycle_parking"].direction_angle - math.pi / 4) < 1e-6
    gate = by_kind["gate"]
    assert abs(gate.direction_angle - math.pi / 4) < 1e-6
    assert (gate.x, gate.y) == (25.002 * 1000.0, 60.002 * 1000.0)


def test_build_ways_leaves_a_bench_unaligned_with_no_nearby_way():
    """Without any way close enough to snap to, a bench keeps its raw OSM
    position and an unset direction_angle - the pre-existing behavior for
    every scenery object, not a crash or a bogus alignment."""
    elements = [
        {"type": "node", "id": 1, "lat": 60.000, "lon": 25.000, "tags": {"amenity": "bench"}},
    ]

    result = build_ways(elements)

    bench = result.scenery_objects[0]
    assert bench.direction_angle is None
    assert bench.x == 25.000 * 1000.0
    assert bench.y == 60.000 * 1000.0




def test_build_ways_uses_explicit_width_tag_for_a_footway():
    """Real OSM data commonly tags width=* on footways/cycleways - it must
    be used as a rendering-width hint instead of the flat per-type
    default (RENDER-audit.md follow-up)."""
    elements = [
        {"type": "node", "id": 1, "lat": 60.000, "lon": 25.000},
        {"type": "node", "id": 2, "lat": 60.001, "lon": 25.001},
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": "footway", "width": "3.0"}},
        {"type": "node", "id": 3, "lat": 60.002, "lon": 25.002},
        {"type": "node", "id": 4, "lat": 60.003, "lon": 25.003},
        {"type": "way", "id": 11, "nodes": [3, 4], "tags": {"highway": "footway"}},
    ]

    result = build_ways(elements)

    by_id = {way.osm_id: way for way in result.ways}
    assert by_id[10].half_width_m == 1.5  # 3.0m width / 2
    assert by_id[11].half_width_m == 1.2  # untagged: falls back to the footway default


def test_build_ways_ignores_a_bogus_width_tag():
    elements = [
        {"type": "node", "id": 1, "lat": 60.000, "lon": 25.000},
        {"type": "node", "id": 2, "lat": 60.001, "lon": 25.001},
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": "footway", "width": "not-a-number"}},
    ]

    result = build_ways(elements)

    assert result.ways[0].half_width_m == 1.2  # untouched footway default


def test_build_ways_accepts_a_narrow_informal_trail_width():
    """Regression: an informal desire-line trail (highway=path,
    surface=dirt) is routinely tagged width=0.2-0.3 in real OSM data -
    narrower than this project's own 1.2 footway/path default. An
    earlier version of parse_road_half_width_m rejected anything under
    0.5m as implausible, silently falling every one of these real,
    narrower-than-default trails back to the flat default - "the brown
    (dirt-surface) paths have a width attribute that seems not to be
    in use"."""
    elements = [
        {"type": "node", "id": 1, "lat": 60.000, "lon": 25.000},
        {"type": "node", "id": 2, "lat": 60.001, "lon": 25.001},
        {
            "type": "way", "id": 10, "nodes": [1, 2],
            "tags": {"highway": "path", "surface": "dirt", "width": "0.2"},
        },
    ]

    result = build_ways(elements)

    assert result.ways[0].half_width_m == 0.1  # 0.2m width / 2, not the 1.2 default


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


def test_build_ways_parses_fuel_forecourt_as_paved_scenery():
    """A fuel-station forecourt (amenity=fuel way) used to fall through
    every branch entirely - no landuse/leisure tag, not "amenity=parking" -
    and vanished (or became a bare text label if named). It should render
    like a parking lot: a paved Scenery, defaulting to asphalt."""
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.001, "lon": 25.0},
        {"type": "node", "id": 3, "lat": 60.001, "lon": 25.001},
        {"type": "node", "id": 4, "lat": 60.0, "lon": 25.001},
        {
            "type": "way",
            "id": 10,
            "nodes": [1, 2, 3, 4, 1],
            "tags": {"amenity": "fuel", "name": "Neste"},
        },
    ]

    result = build_ways(elements)

    assert len(result.sceneries) == 1
    assert result.sceneries[0].kind == "fuel"
    assert result.sceneries[0].surface == "asphalt"
    assert len(result.scenery_objects) == 1
    assert result.scenery_objects[0].kind == "fuel"
    assert result.scenery_objects[0].name == "Neste"
    assert result.scenery_objects[0].id == 10
    assert result.scenery_objects[0].is_area is True


def test_build_ways_creates_fuel_pumps_for_named_roof_station_area():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.001, "lon": 25.0},
        {"type": "node", "id": 3, "lat": 60.001, "lon": 25.001},
        {"type": "node", "id": 4, "lat": 60.0, "lon": 25.001},
        {
            "type": "way",
            "id": 159917622,
            "nodes": [1, 2, 3, 4, 1],
            "tags": {
                "amenity": "fuel",
                "building": "roof",
                "brand": "Neste",
                "name": "Neste Express Oulu Lävistäjä",
            },
        },
    ]

    result = build_ways(elements)

    assert len(result.buildings) == 1
    assert result.buildings[0].building_type == "roof"
    assert len(result.scenery_objects) == 1
    station = result.scenery_objects[0]
    assert station.kind == "fuel"
    assert station.name == "Neste Express Oulu Lävistäjä"
    assert station.id == 159917622
    assert station.is_area is True


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


def test_commercial_detection_covers_full_sign_theme_venue_types():
    # windows.md: previously only COMMERCIAL_AMENITIES' narrow food/drink
    # list was recognized - supermarkets, pharmacies, banks, hotels, and
    # other shop=*/amenity=* venues from SIGN_CATEGORY_BY_VENUE_TYPE must
    # also render a storefront ground floor.
    for venue_type in ("supermarket", "pharmacy", "bank", "hotel"):
        building = Building(
            [(0.0, 0.0), (10.0, 0.0), (10.0, 12.0), (0.0, 12.0)],
            levels=3,
            venue_type=venue_type,
        )
        assert _building_is_commercial(building) is True, venue_type




def test_restaurant_place_is_not_a_map_district_label():
    assert "restaurant" not in DISTRICT_PLACE_KINDS
    assert "city" in DISTRICT_PLACE_KINDS




































def test_finnish_color_name_maps_to_expected_wall_color():
    assert _building_colors_from_name("Sininen talo")[0] == FINNISH_BUILDING_COLOR_NAMES["sini"]
    assert _building_colors_from_name("Punatalo Oy")[0] == FINNISH_BUILDING_COLOR_NAMES["puna"]
    assert _building_colors_from_name("Valkea Kartano")[0] == FINNISH_BUILDING_COLOR_NAMES["valkea"]
    assert _building_colors_from_name("Kissankulma") is None
    assert _building_colors_from_name(None) is None




# --- windows.md: house classification, window density, and night illumination ---

def test_house_building_type_is_classified_as_a_house():
    house = Building([(0.0, 0.0), (8.0, 0.0), (8.0, 8.0), (0.0, 8.0)], building_type="detached", levels=1)
    apartment = Building([(0.0, 0.0), (8.0, 0.0), (8.0, 8.0), (0.0, 8.0)], building_type="apartments", levels=5)

    assert _building_is_house(house) is True
    assert _building_is_house(apartment) is False


def test_short_untagged_building_falls_back_to_house_by_height():
    short_untagged = Building([(0.0, 0.0), (8.0, 0.0), (8.0, 8.0), (0.0, 8.0)], levels=1)
    tall_untagged = Building([(0.0, 0.0), (8.0, 0.0), (8.0, 8.0), (0.0, 8.0)], levels=6)

    assert _building_is_house(short_untagged) is True
    assert _building_is_house(tall_untagged) is False




















# --- bin-loader-v6.md: incremental illuminated-window cache -----------------

def _window_block(count: int, x0: float = 0.0):
    return [
        Building(
            [(x0 + i * 22.0, 0.0), (x0 + i * 22.0 + 18.0, 0.0), (x0 + i * 22.0 + 18.0, 18.0), (x0 + i * 22.0, 18.0)],
            levels=5, height_m=15.0, bbox=(x0 + i * 22.0, 0.0, x0 + i * 22.0 + 18.0, 18.0),
        )
        for i in range(count)
    ]


















def test_build_ways_reads_a_charging_station_with_its_capacity_and_road_direction():
    elements = [
        {"type": "node", "id": 1, "lat": 60.000, "lon": 25.000},
        {"type": "node", "id": 2, "lat": 60.010, "lon": 25.010},
        {"type": "node", "id": 3, "lat": 60.0051, "lon": 25.005, "tags": {"amenity": "charging_station", "capacity": "4"}},
        {"type": "node", "id": 4, "lat": 60.0022, "lon": 25.002, "tags": {"amenity": "charging_station", "capacity": "lots", "level": "-1"}},
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": "service"}},
    ]

    result = build_ways(elements)

    stations = {o.id: o for o in result.scenery_objects if o.kind == "charging_station"}
    assert stations[3].capacity == 4 and stations[4].capacity is None  # a bad tag: unknown, not a crash
    assert stations[3].level is None and stations[4].level == -1  # in a garage
    assert abs(stations[3].direction_angle - math.pi / 4) < 1e-6  # faces the road it stands by...
    assert (stations[3].x, stations[3].y) == (25.005 * 1000.0, 60.0051 * 1000.0)  # ...where it was mapped


def test_mapped_shrubs_keep_their_position_beside_houses():
    result = build_ways([
        {"type": "node", "id": 1, "lat": 65.066, "lon": 25.413, "tags": {"natural": "shrub"}},
    ])
    shrub, = result.scenery_objects
    assert (shrub.kind, shrub.id, shrub.x, shrub.y) == ("shrub", 1, 25413.0, 65066.0)
