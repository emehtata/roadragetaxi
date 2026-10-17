"""Historical FMI weather (weather_history.py) - no network: FMI is faked."""
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from theroadragetrip.climate import SeasonalAppearance, appearance_with_snow_depth
from theroadragetrip.weather import WeatherSystem, WeatherType, weather_type_for_observation
from theroadragetrip.weather_history import (
    FETCH_CHUNK_HOURS,
    HourlyWeather,
    WeatherHistory,
    game_time_to_utc_hour,
    nearest_station_values,
    parse_fmi_timevaluepair,
    precipitation_from_observation,
)

FIXTURE = (Path(__file__).parent / "data" / "fmi_oulu_2025-01-15.xml").read_text()
OULU = (65.0121, 25.4651)


@pytest.mark.parametrize("kind", ["observations", "forecast"])
@pytest.mark.parametrize("failure", ["offline", "malformed", "empty"])
def test_fmi_failures_and_empty_responses_warn_in_console(caplog, kind, failure):
    calls = []
    def fetch(*args):
        calls.append(args)
        if failure == "offline":
            raise OSError("network offline")
        return "not XML" if failure == "malformed" else "<FeatureCollection/>"
    history = WeatherHistory(*OULU, fetch=fetch, fetch_forecast=fetch)
    moment = datetime(2025, 1, 15) if kind == "observations" else datetime(2999, 1, 1)
    with caplog.at_level("WARNING", logger="theroadragetrip.weather_history"):
        history.request(moment, moment)
        history.wait_idle(5.0)
    assert len(calls) == 1
    warning = next(record.getMessage() for record in caplog.records if record.levelname == "WARNING")
    assert ("FMI forecast" if kind == "forecast" else "FMI weather history") in warning
    assert history.location in warning and "generated weather" in warning
    if failure == "empty":
        assert "no usable hourly data" in warning
    else:
        assert "fetch failed" in warning and "retry in 60 s" in warning
        assert ("OSError: network offline" if failure == "offline" else "ParseError:") in warning
        history.request(moment, moment)
        history.wait_idle(5.0)
        assert len(calls) == 1  # logging must not defeat the retry backoff


def test_real_fmi_response_takes_each_parameter_from_the_nearest_station_that_has_it():
    stations = parse_fmi_timevaluepair(FIXTURE)
    assert len(stations) == 3
    hours = nearest_station_values(stations, *OULU)
    first = hours[min(hours)]
    # Temperature and wawa exist at the nearest station; hourly rain and snow
    # depth only at another one (NaN elsewhere) - all four still resolved.
    assert first == HourlyWeather(temperature_c=-3.0, precipitation_mm=0.0, wawa=0, snow_depth_cm=16.0)


def _fake_fmi(calls):
    def fetch(lat, lon, start_hour, end_hour):
        calls.append((start_hour, end_hour))
        return FIXTURE
    return fetch


def test_history_fetches_in_background_uses_hour_beginning_and_caches(tmp_path):
    calls = []
    moment = datetime(2025, 1, 15, 2, 30)  # 00:30 UTC, between the fixture's hours
    history = WeatherHistory(*OULU, cache_path=tmp_path / "weather.db", fetch=_fake_fmi(calls))
    assert history.get(moment) is None  # nothing known yet, never blocks
    history.request(moment, moment)
    history.wait_idle(5.0)
    observed = history.get(moment)
    assert observed is not None and observed.temperature_c == -3.0
    assert observed.snow_depth_cm == 16.0 and len(calls) == 1

    # Next session: served from SQLite, FMI not asked again.
    later_calls = []
    cached = WeatherHistory(*OULU, cache_path=tmp_path / "weather.db", fetch=_fake_fmi(later_calls))
    cached.request(moment, moment)
    assert cached.get(moment) == observed and later_calls == []


def test_future_is_never_requested_and_failures_back_off():
    calls = []
    history = WeatherHistory(*OULU, fetch=_fake_fmi(calls))
    history.request(datetime(2999, 1, 1), datetime(2999, 1, 3))
    assert calls == [] and history.get(datetime(2999, 1, 1)) is None

    def failing(*_args):
        calls.append("x")
        raise OSError("offline")

    broken = WeatherHistory(*OULU, fetch=failing)
    broken.request(datetime(2025, 1, 15), datetime(2025, 1, 15))
    broken.wait_idle(5.0)
    broken.request(datetime(2025, 1, 15), datetime(2025, 1, 15))  # within the retry delay: no new fetch
    broken.wait_idle(5.0)
    assert calls == ["x"] and broken.get(datetime(2025, 1, 15)) is None


def test_chunks_are_three_days_of_utc_hours():
    moment = datetime(2025, 1, 15, 12)
    chunk = int(game_time_to_utc_hour(moment)) // FETCH_CHUNK_HOURS
    assert chunk * FETCH_CHUNK_HOURS <= game_time_to_utc_hour(moment) < (chunk + 1) * FETCH_CHUNK_HOURS
    # Helsinki is UTC+2 in January: 02:00 game time is 00:00 UTC.
    assert game_time_to_utc_hour(datetime(2025, 1, 15, 2)) * 3600 % 86400 == 0


def test_present_weather_codes_map_to_game_weather():
    cases = {
        0: ("", False), 61: ("rain", False), 81: ("rain", False), 67: ("slush", False),
        71: ("snow", False), 86: ("snow", False), 95: ("rain", True), 41: ("precipitation", False),
    }
    for code, expected in cases.items():
        assert precipitation_from_observation(HourlyWeather(wawa=code)) == expected
    assert precipitation_from_observation(HourlyWeather(precipitation_mm=0.4)) == ("precipitation", False)
    assert precipitation_from_observation(HourlyWeather(temperature_c=3.0)) == (None, False)
    assert weather_type_for_observation("precipitation", -4.0) == WeatherType.SNOW
    assert weather_type_for_observation("precipitation", 3.0) == WeatherType.SLUSH
    assert weather_type_for_observation("precipitation", 12.0) == WeatherType.RAIN
    # a sensor's "drizzle" at -7 C (Kittilä, 14.12.2025) is fine snow; near 0 C it is trusted
    assert weather_type_for_observation("rain", -7.1) == WeatherType.SNOW
    assert weather_type_for_observation("rain", 0.5) == WeatherType.RAIN
    assert weather_type_for_observation("snow", 7.0) == WeatherType.SLUSH


def test_weather_follows_observations_then_generator_continues_from_them():
    weather = WeatherSystem()
    weather.update(60.0, 0.0, outside_temperature_c=-5.0, observed=HourlyWeather(temperature_c=-5.0, wawa=71))
    assert weather.weather_type == WeatherType.SNOW
    for _ in range(50):  # observed hours pin it, however long they last
        weather.update(3600.0, 0.0, outside_temperature_c=-5.0, observed=HourlyWeather(temperature_c=-5.0, wawa=71))
    assert weather.weather_type == WeatherType.SNOW
    weather.update(1.0, 0.0, outside_temperature_c=-5.0, observed=None)
    assert weather.weather_type == WeatherType.SNOW  # no jump at the hand-over
    assert weather.seconds_until_weather_change is not None

    manual = WeatherSystem()
    manual.toggle_rain()  # debug-forced weather wins over observations
    forced = manual.weather_type
    manual.update(60.0, 0.0, observed=HourlyWeather(wawa=0))
    assert manual.weather_type == forced


def test_observed_snow_depth_drives_snow_cover():
    autumn_date = SeasonalAppearance(summer=0.25, autumn=0.75)
    assert appearance_with_snow_depth(autumn_date, 20.0) == SeasonalAppearance(winter=1.0)
    half = appearance_with_snow_depth(autumn_date, 5.0)
    assert half.winter == 0.5 and abs(half.summer - 0.125) < 1e-9 and abs(half.autumn - 0.375) < 1e-9
    # Snowless midwinter date: bare, late-autumn ground instead of white.
    assert appearance_with_snow_depth(SeasonalAppearance(winter=1.0), 0.0) == SeasonalAppearance(autumn=1.0)


FORECAST_FIXTURE = (Path(__file__).parent / "data" / "fmi_forecast_oulu_2026-09-24.xml").read_text()


def test_forecast_fills_future_game_time_after_observations_and_keeps_snow():
    from theroadragetrip.weather_history import parse_fmi_forecast

    hours = parse_fmi_forecast(FORECAST_FIXTURE)
    assert len(hours) == 25 and all(weather.source == "forecast" for weather in hours.values())
    assert {weather.wawa for weather in hours.values()} <= {0, 61, 67, 71, 80, 85, 95}

    forecast_calls, observation_calls = [], []

    def fake_forecast(lat, lon):
        forecast_calls.append((lat, lon))
        return FORECAST_FIXTURE

    history = WeatherHistory(*OULU, fetch=_fake_fmi(observation_calls), fetch_forecast=fake_forecast)
    history.request(datetime(2025, 1, 15), datetime(2025, 1, 15))  # observations (fixture: 16 cm snow)
    history.wait_idle(5.0)
    assert forecast_calls == []  # a window entirely in the past never asks for a forecast
    now = datetime.now()
    history.request(now, now + timedelta(hours=24))
    history.wait_idle(5.0)
    assert len(forecast_calls) == 1
    forecast_moment = datetime(2026, 9, 24, 20, 0)  # inside the fixture forecast, after its observations
    forecast = history.get(forecast_moment)
    assert forecast is not None and forecast.source == "forecast"
    assert forecast.snow_depth_cm == 16.0  # no depth forecast: last observed depth carries on
    assert history.source_at(forecast_moment) == "forecast"
    assert history.source_at(datetime(2025, 1, 15, 3)) == "observed"
    assert history.source_at(datetime(2031, 1, 1)) == "generated"

    history.request(now, now + timedelta(hours=24))  # refreshed at most once per real hour
    history.wait_idle(5.0)
    assert len(forecast_calls) == 1


def test_forecast_weather_symbols_map_to_game_weather():
    from theroadragetrip.weather_history import _wawa_for_weather_symbol

    expected = {1: "", 3: "", 21: "rain", 32: "rain", 41: "snow", 53: "snow", 62: "rain", 72: "slush", 82: "slush", 91: ""}
    for symbol, kind in expected.items():
        assert precipitation_from_observation(HourlyWeather(wawa=_wawa_for_weather_symbol(symbol)))[0] == kind
    assert precipitation_from_observation(HourlyWeather(wawa=_wawa_for_weather_symbol(63))) == ("rain", True)


def test_recent_chunks_and_the_forecast_are_cached_for_an_hour(tmp_path, monkeypatch):
    """Not-yet-final data (the last hours, the forecast) is cached too: a new
    session within an hour asks FMI for nothing; after it, both again."""
    import theroadragetrip.weather_history as wh

    observation_calls, forecast_calls = [], []

    def fake_forecast(lat, lon):
        forecast_calls.append((lat, lon))
        return FORECAST_FIXTURE

    def session():
        history = WeatherHistory(*OULU, cache_path=tmp_path / "weather.db", fetch=_fake_fmi(observation_calls),
                                 fetch_forecast=fake_forecast)
        now = datetime.now()
        history.request(now - timedelta(hours=1), now + timedelta(hours=24))
        history.wait_idle(5.0)
        return history

    first = session()
    assert len(observation_calls) >= 1 and len(forecast_calls) == 1
    calls = len(observation_calls)
    second = session()
    assert len(observation_calls) == calls and len(forecast_calls) == 1  # all from SQLite
    moment = datetime(2026, 9, 24, 20, 0)  # in the fixture forecast
    assert second.get(moment).temperature_c == first.get(moment).temperature_c and second.source_at(moment) == "forecast"
    real_time = wh.time.time
    monkeypatch.setattr(wh.time, "time", lambda: real_time() + 2 * 3600)  # two hours later
    session()
    assert len(observation_calls) > calls and len(forecast_calls) == 2


@pytest.mark.parametrize("failure", ["offline", "malformed", "empty"])
@pytest.mark.parametrize("restart", [False, True])
def test_stale_forecast_survives_failed_refresh_and_restart(tmp_path, monkeypatch, failure, restart):
    import threading
    import theroadragetrip.weather_history as wh

    cache = tmp_path / "weather.db"
    future = datetime(2999, 1, 1)  # request only a forecast, independent of today's observation chunk
    moment = datetime(2026, 9, 24, 20)
    history = WeatherHistory(*OULU, cache_path=cache, fetch_forecast=lambda *a: FORECAST_FIXTURE)
    history.request(future, future)
    history.wait_idle(5.0)
    expected = history.get(moment)
    assert expected is not None
    original_age = history._forecast_fetched_at
    real_time, real_monotonic = wh.time.time, wh.time.monotonic
    monkeypatch.setattr(wh.time, "time", lambda: real_time() + 2 * 3600)
    monkeypatch.setattr(wh.time, "monotonic", lambda: real_monotonic() + 2 * 3600)
    started, release = threading.Event(), threading.Event()
    calls = []

    def fail(*args):
        calls.append(args)
        started.set()
        assert release.wait(5.0)
        if failure == "offline":
            raise OSError("offline")
        return "not XML" if failure == "malformed" else "<FeatureCollection/>"

    if restart:
        history = WeatherHistory(*OULU, cache_path=cache, fetch_forecast=fail)
    else:
        history._fetch_forecast = fail
    history.request(future, future)
    try:
        assert started.wait(5.0)  # stale data is usable even while the network request is pending
        assert history.get(moment) == expected
    finally:
        release.set()
        history.wait_idle(5.0)
    assert history.get(moment) == expected
    assert history._forecast_fetched_at == pytest.approx(original_age, abs=0.1)
    history.request(future, future)
    history.wait_idle(5.0)
    assert len(calls) == 1  # retry backoff, not a fetch per game tick

    # Neither memory nor the last successful disk cache was erased or marked fresh.
    later = WeatherHistory(*OULU, cache_path=cache)
    with later._lock:
        later._open_cache()
        assert not later._load_cached_forecast()
    assert later.get(moment) == expected
    assert later.get(datetime(2999, 1, 1)) is None  # never extrapolate beyond cached hours


def test_successful_refresh_replaces_and_persists_forecast(tmp_path, monkeypatch):
    import theroadragetrip.weather_history as wh

    cache = tmp_path / "weather.db"
    future = datetime(2999, 1, 1)
    moment = datetime(2026, 9, 24, 20)
    history = WeatherHistory(*OULU, cache_path=cache, fetch_forecast=lambda *a: FORECAST_FIXTURE)
    history.request(future, future)
    history.wait_idle(5.0)
    old = history.get(moment)
    real_monotonic = wh.time.monotonic
    monkeypatch.setattr(wh.time, "monotonic", lambda: real_monotonic() + 2 * 3600)
    from dataclasses import replace
    new = replace(old, temperature_c=old.temperature_c + 1)
    hour = int(game_time_to_utc_hour(moment))
    monkeypatch.setattr(wh, "parse_fmi_forecast", lambda xml: {hour: new})
    history.request(future, future)
    history.wait_idle(5.0)
    assert history.get(moment) == new
    later = WeatherHistory(*OULU, cache_path=cache)
    with later._lock:
        later._open_cache()
        assert later._load_cached_forecast()
    assert later.get(moment) == new
