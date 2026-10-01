"""Level-aware collision (garage-06.md): a building collides only on its own
logical map level (None = surface 0); no level is inferred from geometry."""
import pytest

from theroadragetrip.osm import Building, Way
from theroadragetrip.physics import Car
from theroadragetrip.taxi import TaxiManager

SQUARE = [(4.0, -3.0), (8.0, -3.0), (8.0, 3.0), (4.0, 3.0)]


def _crash(building, car_level, ways=None, manager=None):
    car = Car(x=5.0, y=0.0, heading=0.0, speed=4.0, map_level=car_level)
    manager = manager or TaxiManager(ways=[])
    return manager.check_building_collision(car, [building], sim_time=1.0, previous_position=(3.0, 0.0), ways=ways)


@pytest.mark.parametrize("building_level, car_level, crashes", [
    (None, 0, True), (None, -1, False), (0, 0, True),
    (-1, -1, True), (-1, 0, False), (-1, -2, False), (1, 1, True),
])
def test_building_collides_only_on_its_own_level(building_level, car_level, crashes):
    assert _crash(Building(SQUARE, map_level=building_level), car_level) is crashes


def test_surface_building_over_an_underground_road_stays_a_surface_obstacle():
    """No geometry inference: the level -1 road under it neither makes the
    building underground nor exempts it on the surface."""
    garage_road = Way([(0.0, 0.0), (20.0, 0.0)], "service", 4.0, map_level=-1)
    building = Building(SQUARE)
    assert _crash(building, -1, ways=[garage_road]) is False
    assert _crash(building, 0, ways=[]) is True  # the surface network doesn't hold the level -1 road


def test_road_overlap_exemption_uses_the_cars_level_roads():
    """A level -1 building crossed by a level -1 road (the player's level -1
    network) doesn't stop the car, same rule as on the surface."""
    garage_road = Way([(0.0, 0.0), (20.0, 0.0)], "service", 4.0, map_level=-1)
    assert _crash(Building(SQUARE, map_level=-1), -1, ways=[garage_road]) is False
    assert _crash(Building(SQUARE, map_level=-1), -1, ways=[]) is True


def test_level_switching_reuses_the_collision_index():
    """0 -> -1 -> -2 -> 0 changes which candidates collide, not the index."""
    manager = TaxiManager(ways=[])
    buildings = [Building(SQUARE), Building(SQUARE, map_level=-1)]
    results = []
    for level in (0, -1, -2, 0):
        car = Car(x=5.0, y=0.0, heading=0.0, speed=4.0, map_level=level)
        results.append(manager.check_building_collision(car, buildings, sim_time=10.0 * len(results), previous_position=(3.0, 0.0)))
        grid_state = (manager._building_collision_ref, manager._building_collision_count)
        assert grid_state == (buildings, len(buildings))
    assert results == [True, True, False, True]  # -2 is an empty level: no fallback to the surface
