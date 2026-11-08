"""The on-foot interaction framework (fps-3d-view spec, phase 3): the server
picks what E does here, nearest kind first, and validates it again on the press."""
import math

from theroadragetrip.interaction import building_in_reach, describe_building, pick
from theroadragetrip.osm.models import Building
from theroadragetrip.pedestrian import PlayerPedestrian
from theroadragetrip.physics import Car


class _Grid:
    def __init__(self, buildings):
        self.buildings = buildings

    def ways_in_rect(self, *_):
        return self.buildings


SHOP = Building(points_m=[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)], name="Kauppa", street="Testikatu", housenumber="3")


def test_a_building_is_in_reach_only_near_its_wall():
    grid = _Grid([SHOP])
    assert building_in_reach(grid, 5.0, -1.5) is SHOP
    assert building_in_reach(grid, 5.0, -6.0) is None


def test_a_building_reads_as_its_name_and_address_else_nothing():
    assert describe_building(SHOP) == "Kauppa, Testikatu 3"
    assert describe_building(Building(points_m=[], building_type="yes")) == ""


def test_the_taxi_door_comes_before_a_house_door_before_a_building():
    car = Car(x=5.0, y=-4.0, heading=0.0, speed=0.0)
    at_door = PlayerPedestrian(car.x + 0.8, car.y + 1.53)
    assert pick(car, at_door, house_door=True, grid=_Grid([SHOP]))["kind"] == "taxi_door"
    far = PlayerPedestrian(5.0, -1.0)
    assert pick(car, far, house_door=True, grid=_Grid([SHOP]))["kind"] == "house_door"
    picked = pick(car, far, house_door=False, grid=_Grid([SHOP]))
    assert picked == {"kind": "building", "label": "Kauppa, Testikatu 3"}
    assert pick(car, PlayerPedestrian(50.0, 50.0), house_door=False, grid=_Grid([SHOP])) == {}
    assert math.isfinite(car.x)
