"""Level-aware driving network (garage-05.md): each road drives only on
its own logical map level (None = surface 0), nothing connects levels."""
import pytest

from theroadragetrip.map_level import SURFACE_LEVEL, LevelRoadNetworks, on_map_level
from theroadragetrip.osm import Way
from theroadragetrip.physics import Car, SpatialWayGrid, get_current_road_at_car
from theroadragetrip.traffic_world import RouteGraphBuild


def _road(map_level=None, layer=0, service=None, x=0.0):
    return Way([(x, 0.0), (x, 100.0)], "service", 3.0, layer=layer, map_level=map_level, service=service)


@pytest.mark.parametrize("road_level, drivable_on", [
    (None, {0}), (0, {0}), (-1, {-1}), (-2, {-2}), (1, {1}),
])
def test_membership(road_level, drivable_on):
    assert {level for level in (-2, -1, 0, 1) if on_map_level(_road(road_level), level)} == drivable_on


def test_surface_grid_keeps_surface_roads_and_drops_off_level_ones():
    surface, explicit_zero, tunnel = _road(None), _road(0, x=10.0), _road(None, layer=-1, x=20.0)
    aisle = _road(-1, service="parking_aisle", x=30.0)  # kept in world.ways by the import
    ways = [surface, explicit_zero, tunnel, aisle]
    grid = SpatialWayGrid(ways, map_level=SURFACE_LEVEL)
    assert set(map(id, grid.ways_in_rect(-50, -50, 100, 150))) == {id(surface), id(explicit_zero), id(tunnel)}
    assert grid.indexed_way_count == len(ways)  # map sync's staleness check stays consistent


def test_level_networks_hold_each_level_alone():
    aisle = _road(-1, service="parking_aisle")
    garage_road, deeper, upper = _road(-1, x=5.0), _road(-2), _road(1)
    networks = LevelRoadNetworks([_road(None), aisle], [garage_road, deeper, upper])
    assert networks.levels() == [-2, -1, 1]
    roads, grid = networks.network(-1)
    assert set(map(id, roads)) == {id(aisle), id(garage_road)}
    assert set(map(id, grid.ways_in_rect(-50, -50, 100, 150))) == {id(aisle), id(garage_road)}
    assert networks.network(-2)[0] == [deeper]
    assert networks.network(-3)[0] == []  # no roads there: empty, never the surface
    assert all(road.map_level not in (None, 0) for level in networks.levels() for road in networks.network(level)[0])


def test_overlapping_roads_on_different_levels_stay_apart():
    """Same geometry on levels 0 and -1: the car finds the road of its own level only."""
    surface, garage = _road(None), _road(-1)
    surface_grid = SpatialWayGrid([surface, garage], map_level=SURFACE_LEVEL)
    garage_roads, garage_grid = LevelRoadNetworks([surface, garage]).network(-1)
    car = Car(0.0, 50.0, 1.5708, 0.0)
    assert get_current_road_at_car(car, ways=[surface, garage], spatial_grid=surface_grid, car_roads_only=True) is surface
    assert get_current_road_at_car(car, ways=garage_roads, spatial_grid=garage_grid, car_roads_only=True) is garage


def test_route_graph_is_surface_only_and_unconnected_to_levels():
    surface, garage = _road(None), _road(-1, x=0.0)  # identical geometry
    build = RouteGraphBuild([surface, garage])
    build.advance(float("inf"))
    surface_only = RouteGraphBuild([surface])
    surface_only.advance(float("inf"))
    assert build.nodes == surface_only.nodes and build.edges == surface_only.edges


def test_level_switching_only_changes_the_selected_network():
    """0 -> -1 -> -2 -> -1 -> 0 is a lookup on prebuilt networks: nothing is
    rebuilt or fetched, and the surface grid is untouched."""
    ways = [_road(None), _road(-1, service="parking_aisle")]
    surface_grid = SpatialWayGrid(ways, map_level=SURFACE_LEVEL)
    networks = LevelRoadNetworks(ways, [_road(-2)])
    revisions = (surface_grid.revision, *(networks.network(level)[1].revision for level in networks.levels()))
    selected = []
    for level in (0, -1, -2, -1, 0):
        roads, grid = (ways, surface_grid) if level == SURFACE_LEVEL else networks.network(level)
        selected.append([road.map_level for road in roads if on_map_level(road, level)])
    assert selected == [[None], [-1], [-2], [-1], [None]]
    assert revisions == (surface_grid.revision, *(networks.network(level)[1].revision for level in networks.levels()))
