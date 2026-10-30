"""The taxi stops at bollards and lamp posts (OSM point features)."""
import math
from types import SimpleNamespace

import pytest

from theroadragetrip.physics import Car, update_car_physics
from theroadragetrip.taxi import TaxiManager


def test_driving_into_a_bollard_stops_once_per_impact_and_benches_dont_count():
    taxi = TaxiManager(ways=[])
    objects = [SimpleNamespace(x=2.0, y=0.0, kind="bollard"), SimpleNamespace(x=0.0, y=5.0, kind="bench")]
    car = Car(x=0.5, y=0.0, heading=0.0, speed=5.0)
    assert taxi.check_post_collision(car, objects, 0.0, previous_position=(0.0, 0.0))
    assert (car.x, car.y, car.speed) == (0.0, 0.0, 0.0) and taxi.total_score == -50
    car.x, car.speed = 0.5, 5.0
    assert taxi.check_post_collision(car, objects, 1.0, previous_position=(0.0, 0.0))
    assert taxi.total_score == -50  # same impact: no second penalty

    lamp_beside = [SimpleNamespace(x=0.0, y=3.0, kind="street_lamp")]
    assert not taxi.check_post_collision(Car(x=0.0, y=0.0, heading=0.0, speed=5.0), lamp_beside, 2.0)
    lamp_ahead = lamp_beside + [SimpleNamespace(x=1.9, y=0.0, kind="street_lamp")]
    assert taxi.check_post_collision(Car(x=0.0, y=0.0, heading=0.0, speed=5.0), lamp_ahead, 2.0)  # another scenery list: re-indexed


def test_hit_hard_a_lamp_bends_over_breaks_and_lets_the_taxi_through():
    taxi = TaxiManager(ways=[])
    lamp = SimpleNamespace(x=2.0, y=0.0, kind="street_lamp")
    car = Car(x=0.5, y=0.0, heading=0.0, speed=60.0 / 3.6)
    assert taxi.check_post_collision(car, [lamp], 0.0, previous_position=(0.0, 0.0))
    assert lamp.knocked_angle == 0.0 and taxi.broken_lamps == {(2.0, 0.0)} and taxi.knocked_posts == 1
    assert car.x == 0.5 and 0.0 < car.speed < 60.0 / 3.6  # not stopped, slowed
    assert taxi.total_score == -50
    assert not taxi.check_post_collision(car, [lamp], 5.0, previous_position=(0.0, 0.0))  # lies flat now

@pytest.mark.parametrize('heading', [0.0, math.pi / 2, -1.7916929165777684])
@pytest.mark.parametrize('kind', ['bollard', 'street_lamp'])
def test_reverse_clears_an_existing_front_corner_overlap(heading, kind):
    taxi = TaxiManager(ways=[])
    # The reported Tervakukkatie bollard in car-local metres.
    along, across = 2.109298111454215, 0.9001576428779481
    post = SimpleNamespace(x=along * math.cos(heading) - across * math.sin(heading),
                           y=along * math.sin(heading) + across * math.cos(heading), kind=kind)
    car = Car(x=0.0, y=0.0, heading=heading, speed=0.0, engine_on=True)
    for tick in range(90):
        previous = car.x, car.y
        update_car_physics(car, 0.0, 1.0, 0.0, 0.0, 1 / 30)
        assert not taxi.check_post_collision(car, [post], tick / 30, previous_position=previous)
    assert math.dist((0.0, 0.0), (car.x, car.y)) > 2.0
    assert car.speed < 0 and taxi.total_score == 0 and taxi.knocked_posts == 0


@pytest.mark.parametrize('direction', [-1, 1])
def test_existing_overlap_cannot_be_pushed_further_into_a_post(direction):
    taxi = TaxiManager(ways=[])
    post = SimpleNamespace(x=direction * 2.1, y=0.0, kind='bollard')
    car = Car(x=direction * 0.01, y=0.0, heading=0.0, speed=direction * 1.0)
    assert taxi.check_post_collision(car, [post], 0.0, previous_position=(0.0, 0.0))
    assert (car.x, car.y, car.speed) == (0.0, 0.0, 0.0)
    assert taxi.total_score == -50


def test_backing_away_from_one_post_still_checks_the_next_post():
    taxi = TaxiManager(ways=[])
    posts = [SimpleNamespace(x=2.1, y=0.0, kind='bollard'), SimpleNamespace(x=-2.1, y=0.0, kind='bollard')]
    car = Car(x=-0.01, y=0.0, heading=0.0, speed=-1.0)
    assert taxi.check_post_collision(car, posts, 0.0, previous_position=(0.0, 0.0))
    assert (car.x, car.y, car.speed) == (0.0, 0.0, 0.0)
    assert taxi.total_score == -50
