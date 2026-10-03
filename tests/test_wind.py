import math

from theroadragetrip.physics import Car, update_car_physics
from theroadragetrip.weather import WeatherSystem
from theroadragetrip.weather_history import HourlyWeather


def _coast(wind, heading=0.0, seconds=2.0):
    car = Car(x=0.0, y=0.0, heading=heading, speed=25.0)
    for _ in range(int(seconds * 60)):
        update_car_physics(car, 1.0, 0.0, 0.0, 0.0, 1 / 60, block_offroad=False, wind=wind)
    return car


def test_headwind_slows_tailwind_helps_and_calm_is_unchanged():
    calm = _coast((0.0, 0.0))
    head = _coast((-20.0, 0.0))  # car drives east, air moves west
    tail = _coast((20.0, 0.0))
    assert head.speed < calm.speed < tail.speed
    assert calm.heading == 0.0


def test_crosswind_yaws_the_car_downwind():
    from_north = _coast((0.0, -20.0))  # air moving south pushes an eastbound car right
    from_south = _coast((0.0, 20.0))
    assert from_north.heading < -0.01 and from_north.y < 0.0
    assert from_south.heading > 0.01 and from_south.y > 0.0


def test_wind_never_moves_or_reverses_a_stopped_car():
    car = Car(x=0.0, y=0.0, heading=0.0, speed=0.0)
    for _ in range(120):
        update_car_physics(car, 0.0, 0.0, 0.0, 0.0, 1 / 60, block_offroad=False, wind=(-30.0, 0.0))
    assert car.speed == 0.0 and (car.x, car.y) == (0.0, 0.0)


def test_weather_follows_observed_wind_and_trees_lean_downwind():
    weather = WeatherSystem()
    observed = HourlyWeather(wind_speed_mps=18.0, wind_from_deg=270.0)  # westerly gale
    for _ in range(40):
        weather.update(3600.0, 0.0, observed=observed)
    assert math.isclose(weather.wind_speed_mps, 18.0, abs_tol=0.01)
    assert math.isclose(weather.wind_from_deg, 270.0, abs_tol=0.01)
    east, north = weather.tree_lean_m
    assert east > 0.5 and abs(north) < 1e-6  # crowns lean east

    weather.update(3600.0, 0.0, observed=HourlyWeather())  # no wind data: generator continues from here
    assert 0.0 <= weather.wind_from_deg < 360.0
