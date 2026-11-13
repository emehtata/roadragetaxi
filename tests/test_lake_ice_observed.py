from datetime import date, datetime, timedelta
from types import SimpleNamespace

from theroadragetrip.climate import lake_ice_thickness_cm
from theroadragetrip.server import CAR_ICE_MIN_CM, SimulationServer
from theroadragetrip.weather_history import HourlyWeather, WeatherHistory, game_time_to_utc_hour

DAY = date(2026, 11, 28)


def _history(days):
    """WeatherHistory with observed hourly data: {date: (mean °C, snow cm)}."""
    history = WeatherHistory(65.0, 25.5, fetch=lambda *a: "", fetch_forecast=lambda *a: "")
    history.request = lambda start, end: None
    for day, (temp, snow) in days.items():
        base = int(game_time_to_utc_hour(datetime(day.year, day.month, day.day)))
        for h in range(24):
            history._hours[base + h] = HourlyWeather(temperature_c=temp, snow_depth_cm=snow)
    return history


def _server(history, snow=None):
    server = SimulationServer.__new__(SimulationServer)
    server.calendar = SimpleNamespace(date=DAY, latitude=65.0, current=datetime(2026, 11, 28, 12))
    server.world = SimpleNamespace(lake_ice_cm=0.0, lake_ice_holds=False)
    server.weather_history = history
    server._test_snow_depth = snow
    server._update_lake_ice(None)
    return server


def _span(n, temp, snow=0.0):
    return {DAY - timedelta(days=i): (temp, snow) for i in range(n)}


def test_mild_late_november_oulu_has_no_ice():
    # Mild autumn: +6 °C easing to -1 °C by mid-November, then thaw days at +2 °C.
    days = {DAY - timedelta(days=i): (6.0 - 7.0 * (88 - i) / 78 if i >= 10 else 2.0, 0.0) for i in range(89)}
    server = _server(_history(days))
    assert server.world.lake_ice_cm < 1.0
    assert server.world.lake_ice_holds is False


def test_freezing_late_november_oulu_holds():
    server = _server(_history(_span(25, -8.0)))
    assert server.world.lake_ice_cm >= CAR_ICE_MIN_CM
    assert server.world.lake_ice_holds is True


def test_no_observations_falls_back_to_climate():
    assert _server(None).world.lake_ice_cm == lake_ice_thickness_cm(DAY, 65.0, 0.5)
    assert _server(_history({}), snow=0.0).world.lake_ice_cm == lake_ice_thickness_cm(DAY, 65.0, 1.0)


def test_ice_recomputes_when_observed_days_arrive():
    history = _history(_span(3, -8.0))
    server = _server(history)
    key, ice = server._lake_ice_key, server.world.lake_ice_cm
    history._hours.update(_history(_span(20, -8.0))._hours)
    server._update_lake_ice(None)
    assert server._lake_ice_key != key and server.world.lake_ice_cm > ice
