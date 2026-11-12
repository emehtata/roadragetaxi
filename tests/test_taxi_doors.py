"""Getting out of and back into the taxi (fps-3d-view spec, phase 2): the
server checks the exit (stopped, a free side) and the driver's door reach;
the taxi keeps its place and state."""
import math

from theroadragetrip.pedestrian import PlayerPedestrian
from theroadragetrip.physics import Car
from theroadragetrip.server import NullAudio
from theroadragetrip.simulation import apply_enter_exit_vehicle, driver_door, driver_door_available

AUDIO = NullAudio()


def _car(**kw):
    return Car(x=100.0, y=50.0, heading=math.pi / 2, speed=kw.pop("speed", 0.0), engine_on=True, **kw)


def test_no_getting_out_while_moving():
    car, ped = _car(speed=6.0), PlayerPedestrian(0.0, 0.0)
    assert apply_enter_exit_vehicle(car, ped, False, AUDIO) is False
    assert car.speed == 6.0 and (ped.x, ped.y) == (0.0, 0.0)


def test_gets_out_at_the_drivers_door_and_the_taxi_stays_put():
    car, ped = _car(speed=0.3), PlayerPedestrian(0.0, 0.0)
    assert apply_enter_exit_vehicle(car, ped, False, AUDIO) is True
    door = driver_door(car)
    assert math.isclose(ped.x, door[0]) and math.isclose(ped.y, door[1]) and ped.x < car.x  # heading north: the left is west
    assert (car.x, car.y, car.heading, car.speed, car.engine_on) == (100.0, 50.0, math.pi / 2, 0.0, True)


def test_a_wall_at_the_drivers_door_lets_the_driver_out_on_the_other_side_or_not_at_all():
    car, ped = _car(), PlayerPedestrian(0.0, 0.0)
    assert apply_enter_exit_vehicle(car, ped, False, AUDIO, blocked=lambda x, y: x < 100.0) is True
    assert ped.x > car.x
    ped = PlayerPedestrian(0.0, 0.0)
    assert apply_enter_exit_vehicle(car, ped, False, AUDIO, blocked=lambda x, y: True) is False
    assert (ped.x, ped.y) == (0.0, 0.0)


def test_door_prompt_only_within_reach_of_a_standing_taxi():
    car = _car()
    door = driver_door(car)
    assert driver_door_available(car, PlayerPedestrian(door[0] + 0.5, door[1]))
    assert not driver_door_available(car, PlayerPedestrian(door[0] - 3.0, door[1]))
    car.speed = 3.0
    assert not driver_door_available(car, PlayerPedestrian(*door))


def test_getting_back_in_keeps_the_taxi_where_it_was():
    car = _car()
    door = driver_door(car)
    assert apply_enter_exit_vehicle(car, PlayerPedestrian(*door), True, AUDIO) is False
    assert (car.x, car.y, car.heading) == (100.0, 50.0, math.pi / 2)
    assert apply_enter_exit_vehicle(car, PlayerPedestrian(door[0] - 5.0, door[1]), True, AUDIO) is True  # out of reach


def test_no_getting_in_beyond_the_drivers_door_or_beside_a_moving_taxi():
    car = _car()
    door = driver_door(car)
    assert apply_enter_exit_vehicle(car, PlayerPedestrian(car.x + 1.0, car.y), True, AUDIO) is True  # passenger side, < 3 m from centre
    car.speed = 3.0
    assert apply_enter_exit_vehicle(car, PlayerPedestrian(*door), True, AUDIO) is True
    assert car.speed == 3.0
