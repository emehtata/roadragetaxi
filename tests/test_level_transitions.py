"""Driving through a parking entrance between map levels (garage-08.md)."""
import pytest

from theroadragetrip.level_transitions import LevelTransitions, resolve_connectors
from theroadragetrip.map_level import SURFACE_LEVEL, LevelRoadNetworks, explicit_levels, visible_on_level
from theroadragetrip.osm import Building, LevelConnector, Way
from theroadragetrip.physics import Car, SpatialWayGrid, get_current_road_at_car
from theroadragetrip.taxi import TaxiManager


def _road(osm_id, points, level=None, layer=0):
    from theroadragetrip.map_level import parse_map_level
    return Way(points, "service", 3.0, osm_id=osm_id, layer=layer, level=level, map_level=parse_map_level(level))


# Oulu pattern: outside driveway (no level) -> entrance node at (0, 0) -> inside ramp level=0;-1.
OUTSIDE = _road(1, [(-30.0, 0.0), (0.0, 0.0)])
RAMP = _road(2, [(0.0, 0.0), (30.0, 0.0)], level="0;-1")
GARAGE_AISLE = _road(3, [(30.0, 0.0), (60.0, 0.0)], level="-1")


def _entrance(osm_id=10, x=0.0, y=0.0, roads=(1, 2), level=None):
    from theroadragetrip.map_level import parse_map_level
    return LevelConnector("node", osm_id, "parking_entrance", x, y, map_level=parse_map_level(level), level=level,
                          road_osm_ids=tuple(roads))


def _transitions(connectors, ways=(OUTSIDE, RAMP), level_ways=(GARAGE_AISLE,)):
    return LevelTransitions(resolve_connectors(connectors, ways, level_ways)[0])


def _drive(transitions, car, x, way):
    previous = (car.x, car.y)
    car.x = x
    return transitions.update(car, previous, way)


@pytest.mark.parametrize("level, expected", [
    (None, frozenset()), ("0", {0}), ("-1", {-1}), ("0;-1", {0, -1}), (" -1 ; -2 ", {-1, -2}),
    ("0-1", frozenset()), ("1.5", frozenset()), ("0;x", frozenset()), ("foo", frozenset()),
])
def test_explicit_levels(level, expected):
    assert explicit_levels(_road(1, [(0, 0), (1, 0)], level=level)) == expected


def test_layer_tunnel_and_covered_are_not_levels():
    tunnel = Way([(0, 0), (1, 0)], "service", 3.0, layer=-1, is_tunnel=True)
    assert explicit_levels(tunnel) == frozenset()


@pytest.mark.parametrize("roads, own_level, expected", [
    ([None, "0;-1"], None, {0: -1, -1: 0}),           # the Oulu pattern
    (["-1", "-1;-2"], None, {-1: -2, -2: -1}),        # deeper levels work the same
    (["0", "0"], None, {}),                            # same level: nothing to change to
    ([None, None], None, {}),                          # no evidence
    ([None, None], "-1", {}),                          # the entrance's own level alone is no evidence
    (["0;-1;-2", None], None, {}),                     # ambiguous: never picks one
    ([None, "0;-1"], "-2", {}),                        # own level contradicts the roads: rejected
])
def test_resolved_destinations(roads, own_level, expected):
    ways = [_road(i + 1, [(0, 0), (1, 0)], level=level) for i, level in enumerate(roads)]
    topologies, _ = resolve_connectors([_entrance(roads=[w.osm_id for w in ways], level=own_level)], ways, [])
    found = {level: t.destination(level) for t in topologies for level in (-2, -1, 0, 1)
             if t.destination(level) is not None}
    assert found == expected


def test_missing_road_waits_for_its_tile_and_garage_levels_never_count():
    topologies, stats = resolve_connectors([_entrance(roads=(1, 2, 99))], [OUTSIDE, RAMP], [])
    assert topologies == [] and stats["missing_roads"] == 1
    # Only the outside road: a garage with levels -2..-1 around it changes nothing.
    topologies, stats = resolve_connectors([_entrance(roads=(1,))], [OUTSIDE], [])
    assert topologies == [] and stats["no_level_evidence"] == 1


def test_driving_through_changes_level_once_and_back_on_the_way_out():
    transitions = _transitions([_entrance()])
    car = Car(-10.0, 0.0, 0.0, 5.0)
    assert _drive(transitions, car, -5.0, OUTSIDE) is None and car.map_level == 0  # approaching
    assert _drive(transitions, car, 2.0, OUTSIDE) == (10, 0, -1) and car.map_level == -1
    assert _drive(transitions, car, 1.0, RAMP) is None and car.map_level == -1  # wobble on the node: disarmed
    assert _drive(transitions, car, 3.0, RAMP) is None
    for x in (20.0, 40.0, 20.0, 5.0):  # into the garage and back: re-armed once 10 m away
        _drive(transitions, car, x, RAMP)
    assert car.map_level == -1
    assert _drive(transitions, car, -2.0, RAMP) == (10, -1, 0) and car.map_level == 0


def test_proximity_standing_still_or_another_road_never_fires():
    transitions = _transitions([_entrance()])
    car = Car(0.5, 0.0, 0.0, 0.0)
    for _ in range(5):  # parked on the entrance
        assert _drive(transitions, car, 0.5, OUTSIDE) is None
    passing = Car(-10.0, 3.0, 0.0, 5.0)  # drives past right beside it on an unrelated road
    cross_street = _road(50, [(-30.0, 3.0), (30.0, 3.0)])
    assert _drive(transitions, passing, 10.0, cross_street) is None
    side = Car(-10.0, 6.0, 0.0, 5.0)  # on a connector road but 6 m off the node
    assert _drive(transitions, side, 10.0, OUTSIDE) is None
    assert car.map_level == passing.map_level == side.map_level == SURFACE_LEVEL


def test_other_connectors_dont_interfere():
    far = _entrance(osm_id=11, x=500.0, roads=(1, 2))
    transitions = _transitions([_entrance(), far])
    car = Car(-5.0, 0.0, 0.0, 5.0)
    assert _drive(transitions, car, 5.0, OUTSIDE) == (10, 0, -1)


def test_level_change_flows_into_driving_rendering_and_collision():
    """The existing level-aware systems follow car.map_level - nothing else changes."""
    ways = [OUTSIDE, RAMP]
    surface_grid = SpatialWayGrid(ways, map_level=SURFACE_LEVEL)
    networks = LevelRoadNetworks(ways, [GARAGE_AISLE])
    transitions = _transitions([_entrance()])
    car = Car(-5.0, 0.0, 0.0, 5.0)
    _drive(transitions, car, 2.0, OUTSIDE)
    assert car.map_level == -1
    roads, grid = networks.network(car.map_level)
    assert {w.osm_id for w in roads} == {2, 3}  # the ramp drives on both of its levels
    assert get_current_road_at_car(car, ways=roads, spatial_grid=grid, car_roads_only=True) is RAMP
    assert get_current_road_at_car(car, ways=ways, spatial_grid=surface_grid, car_roads_only=True) is RAMP
    surface_building = Building([(1.0, -2.0), (4.0, -2.0), (4.0, 2.0), (1.0, 2.0)])
    assert not visible_on_level(surface_building, car.map_level)
    assert TaxiManager(ways=[]).check_building_collision(car, [surface_building], sim_time=1.0) is False


def _oulu_stub_world(stub_tags):
    """The 7 unresolved Oulu entrances (garage-09.md): outside driveway ->
    entrance node -> 2-node tunnel=yes driveway stub ending on the outline
    of a parking building; nothing in reach carries a level."""
    from theroadragetrip.osm import build_ways
    nodes = [(1, 65.0, 25.0), (2, 65.0, 25.0002), (3, 65.0, 25.0004),  # driveway, entrance, stub end
             (4, 65.0001, 25.0004), (5, 65.0001, 25.0008), (6, 64.9999, 25.0008), (7, 64.9999, 25.0004)]
    elements = [{"type": "node", "id": i, "lat": lat, "lon": lon} for i, lat, lon in nodes]
    elements[1]["tags"] = {"amenity": "parking_entrance", "parking": "underground"}
    elements += [
        {"type": "way", "id": 100, "nodes": [1, 2], "tags": {"highway": "service", "service": "driveway"}},
        {"type": "way", "id": 101, "nodes": [2, 3],
         "tags": {"highway": "service", "service": "driveway", "tunnel": "yes", "maxheight": "2.3", **stub_tags}},
        {"type": "way", "id": 102, "nodes": [3, 4, 5, 6, 7, 3],
         "tags": {"building": "parking", "parking": "underground", "parking:levels": "2"}},
    ]
    return build_ways(elements)


def test_oulu_tunnel_stub_without_level_stays_dropped_and_its_entrance_unresolved():
    world = _oulu_stub_world({})
    assert 101 not in {w.osm_id for w in (*world.ways, *world.level_ways)}  # never a surface road
    assert world.parking_garages[0].levels == (-2, -1)  # known garage levels decide nothing
    topologies, stats = resolve_connectors(world.level_connectors, world.ways, world.level_ways)
    assert topologies == [] and stats["missing_roads"] == 1


def test_the_same_stub_with_an_explicit_level_resolves():
    world = _oulu_stub_world({"level": "0;-1"})
    topologies, _ = resolve_connectors(world.level_connectors, world.ways, world.level_ways)
    assert [(t.connector.osm_id, t.destination(0), t.destination(-1)) for t in topologies] == [(2, -1, 0)]
