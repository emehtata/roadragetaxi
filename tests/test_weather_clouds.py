"""Cloud cover (rrt-018-shadows): observed and forecast from FMI (real
responses in tests/data), cached with the rest, and the weather's own
cloud state that dims the sunlight and the building shadows."""
from datetime import datetime
from pathlib import Path

import pytest

from theroadragetrip.climate import Season
from theroadragetrip.weather import PRECIPITATION_MIN_CLOUD, WeatherSystem, WeatherType
from theroadragetrip.weather_history import (
    HourlyWeather, WeatherHistory, nearest_station_values, parse_fmi_forecast, parse_fmi_timevaluepair,
)

DATA = Path(__file__).parent / "data"
OBSERVED = (DATA / "fmi_oulu_2026-10-16_clouds.xml").read_text()  # t2m, n_man around Oulu, 06-08 UTC
FORECAST = (DATA / "fmi_forecast_oulu_2026-10-17_clouds.xml").read_text()  # Temperature, TotalCloudCover
OULU = (65.0121, 25.4651)


def test_observed_cloud_oktas_become_a_fraction_from_the_nearest_reporting_station():
    hours = nearest_station_values(parse_fmi_timevaluepair(OBSERVED), *OULU)
    covers = [weather.cloud_cover for _, weather in sorted(hours.items())]
    assert covers == [1.0, 0.875, 0.0]  # 8, 7 and 0 oktas, from the nearest station that reports cloud


def test_forecast_cloud_percent_becomes_a_fraction():
    covers = [weather.cloud_cover for weather in parse_fmi_forecast(FORECAST).values()]
    assert len(covers) == 72 and all(0.0 <= cover <= 1.0 for cover in covers)
    assert max(covers) == pytest.approx(0.511)


def test_cloud_cover_survives_the_cache(tmp_path):
    def fetch(lat, lon, start_hour, end_hour):
        return OBSERVED

    moment = datetime(2026, 10, 16, 9, 30)  # 06:30 UTC
    history = WeatherHistory(*OULU, cache_path=tmp_path / "weather.db", fetch=fetch)
    history.request(moment, moment)
    history.wait_idle(5.0)
    assert history.get(moment).cloud_cover == 1.0
    cached = WeatherHistory(*OULU, cache_path=tmp_path / "weather.db", fetch=lambda *a: pytest.fail("refetched"))
    cached.request(moment, moment)
    assert cached.get(moment).cloud_cover == 1.0


def _weather(season=Season.SUMMER, seed=1):
    weather = WeatherSystem(season=season)
    weather._rng.seed(seed)
    return weather


def test_observed_cloud_is_followed_smoothly():
    weather = _weather()
    weather.cloud_cover = 0.0
    previous = 0.0
    for _ in range(120):  # two game hours
        weather.update(60.0, 0.0, observed=HourlyWeather(cloud_cover=1.0, wawa=0))
        assert 0.0 <= weather.cloud_cover - previous < 0.1  # eases in, no jump
        previous = weather.cloud_cover
    assert weather.cloud_cover > 0.99


def test_precipitation_comes_with_clouds_but_not_necessarily_full_overcast():
    weather = _weather()
    weather.weather_type = WeatherType.RAIN
    weather._cloud_target = weather.cloud_cover = 0.1
    for _ in range(180):
        weather.update(60.0, 0.0)
        if weather.is_precipitating:
            assert weather._cloud_target >= PRECIPITATION_MIN_CLOUD
    assert 0.0 <= weather.cloud_cover <= 1.0


def test_generated_skies_follow_the_season():
    def mean_cloud(season):
        total = 0.0
        for seed in range(300):
            total += _weather(season, seed)._generated_cloud()
        return total / 300

    assert mean_cloud(Season.WINTER) > mean_cloud(Season.SUMMER) + 0.1
    assert all(0.0 <= _weather(Season.AUTUMN, seed)._generated_cloud() <= 1.0 for seed in range(100))
