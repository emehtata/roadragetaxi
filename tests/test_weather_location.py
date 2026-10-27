"""Weather follows the restored/current taxi, independently of its starting city."""
from datetime import datetime
from types import SimpleNamespace

from theroadragetrip.server import SimulationServer
from theroadragetrip.taxi import municipality_points
from theroadragetrip.weather_history import HourlyWeather


def _server(monkeypatch, city):
    centres = {p[0]: p[1:3] for p in municipality_points() if p[4] is None}
    created = []
    def history(lat, lon, cache_path):
        instance = SimpleNamespace(lat=lat, lon=lon, cache_path=cache_path,
                                   request=lambda *args: None,
                                   get=lambda moment: HourlyWeather(temperature_c=2.0 if lat < 65 else 8.0, wawa=0))
        created.append(instance)
        return instance
    monkeypatch.setattr('theroadragetrip.server.WeatherHistory', history)
    server = SimulationServer.__new__(SimulationServer)
    server.car = SimpleNamespace(x=centres[city][0], y=centres[city][1])
    server.chosen_city = server.weather_city = 'Oulu'
    server.weather_history = None
    server._historical_weather = True
    server._weather_check_position = server._weather_centre = None
    server._fallback_weather_hour = datetime(2026, 10, 21, 22)
    server._fallback_weather = 'old Oulu rain'
    return server, centres, created


def test_weather_starts_at_restored_raahe_position(monkeypatch):
    server, _, created = _server(monkeypatch, 'Raahe')
    server.calendar = SimpleNamespace(current=datetime(2026, 10, 21, 22))
    server.world = SimpleNamespace(weather=SimpleNamespace(weather_source='generated'))
    observed = server._update_outside()
    assert observed.temperature_c == server.world.weather.outside_temperature_c == 2.0
    assert server.weather_city == 'Raahe'
    assert server.chosen_city == 'Oulu'
    assert 64.5 < created[0].lat < 64.8 and 24.3 < created[0].lon < 24.7
    assert server._fallback_weather_hour is None and server._fallback_weather is None


def test_driving_intercity_retargets_history_without_reusing_origin_weather(monkeypatch):
    server, centres, created = _server(monkeypatch, 'Oulu')
    server._update_weather_location()
    origin_history = server.weather_history
    server._update_weather_location()
    assert len(created) == 1
    server.car.x, server.car.y = centres['Raahe']
    server._update_weather_location()
    assert server.weather_city == 'Raahe'
    assert server.weather_history is not origin_history
    assert len(created) == 2 and created[0].cache_path == created[1].cache_path
    server.car.x += 100
    server._update_weather_location()
    assert len(created) == 2  # no new provider/fetch for every frame or short movement


def test_weather_boundary_does_not_flip_for_small_movements(monkeypatch):
    import math
    server, centres, created = _server(monkeypatch, 'Oulu')
    points = [p for p in municipality_points() if p[0] in centres and p[0] in ('Oulu', 'Raahe') and p[4] is None]
    monkeypatch.setattr('theroadragetrip.taxi.municipality_points', lambda: points)
    server._update_weather_location()
    a, b = centres['Oulu'], centres['Raahe']
    distance = math.dist(a, b)
    def near_boundary(toward_raahe):
        server.car.x = (a[0] + b[0]) / 2 + (b[0] - a[0]) / distance * toward_raahe
        server.car.y = (a[1] + b[1]) / 2 + (b[1] - a[1]) / distance * toward_raahe
        server._update_weather_location()
    near_boundary(100)
    assert server.weather_city == 'Oulu'
    near_boundary(1600)
    assert server.weather_city == 'Raahe' and len(created) == 2
