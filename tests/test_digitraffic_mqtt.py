"""Digitraffic MQTT live feed (digitraffic_mqtt.py) against a fake paho client."""
from types import SimpleNamespace

from theroadragetrip import digitraffic_mqtt as dm


class FakeClient:
    def __init__(self):
        self.subscribed, self.calls = [], []

    def subscribe(self, topics):
        self.subscribed.append(topics)

    def connect_async(self, *args, **kwargs):
        self.calls.append("connect_async")

    def loop_start(self):
        self.calls.append("loop_start")


def _feed(topics=("weather-v2/status", "maintenance-v2/routes/state-roads")):
    now = [1000.0]
    client = FakeClient()
    feed = dm.LiveFeed(topics, client_factory=lambda: client, clock=lambda: now[0])
    return feed, client, now


def _message(topic, payload):
    return SimpleNamespace(topic=topic, payload=payload)


def test_subscribes_on_every_connect_and_tracks_the_connection():
    feed, client, _ = _feed()
    feed.start()
    assert client.calls == ["connect_async", "loop_start"]  # never a blocking connect
    ok = SimpleNamespace(is_failure=False)
    feed._on_connect(client, None, None, ok)
    feed._on_disconnect(client, None, None, ok)
    feed._on_connect(client, None, None, ok)
    assert feed.connected and len(client.subscribed) == 2
    feed._on_connect(client, None, None, SimpleNamespace(is_failure=True))
    assert len(client.subscribed) == 2


def test_status_is_kept_apart_data_is_queued_and_junk_ignored():
    feed, client, now = _feed()
    feed._on_message(client, None, _message("weather-v2/status", b'{"updated": 990}'))
    feed._on_message(client, None, _message("maintenance-v2/routes/state-roads", b'{"x": 25.4, "y": 65.0}'))
    feed._on_message(client, None, _message("maintenance-v2/routes/state-roads", b"not json"))
    now[0] = 1003.0
    assert feed.drain(10) == [("maintenance-v2/routes/state-roads", {"x": 25.4, "y": 65.0}, 1000.0)]
    diagnostics = feed.diagnostics()
    assert diagnostics["feed_age_s"] == {"weather-v2": 13.0} and diagnostics["received"] == 2
    assert diagnostics["last_message_age_s"] == 3.0


def test_the_queue_is_bounded_and_drained_in_budgets(monkeypatch):
    monkeypatch.setattr(dm, "QUEUE_MAX", 3)
    feed, client, _ = _feed()
    for i in range(5):
        feed._on_message(client, None, _message("weather-v2/1/1", b'{"value": %d}' % i))
    assert feed.dropped == 2
    assert [body["value"] for _, body, _ in feed.drain(2)] == [2, 3]  # oldest first, within the budget
    assert [body["value"] for _, body, _ in feed.drain(2)] == [4]


class FakeRest:
    def __init__(self, collection, data=None):
        self.collection, self.data = collection, data or {}

    def get_json(self, path, params=None, *, max_age_s=None):
        assert max_age_s
        if path == "/api/weather/v1/stations":
            return self.collection
        return {"sensorValues": self.data.get(int(path.split("/")[-2]), [])}


def _station(station_id, lon, lat, status="GATHERING"):
    return {"id": station_id, "geometry": {"coordinates": [lon, lat, 0.0]}, "properties": {"collectionStatus": status}}


def _road_weather(data=None):
    feed, client, now = _feed(dm.STATUS_TOPICS)
    feed.connected = True
    client.unsubscribed = []
    client.unsubscribe = client.unsubscribed.append
    stations = [_station(1, 25.0, 65.0), _station(2, 25.1, 65.0), _station(3, 25.0, 65.0, status="REMOVED_TEMPORARILY")]
    stations += [_station(10 + i, 27.0 + i, 62.0) for i in range(dm.WEATHER_STATIONS)]
    weather = dm.RoadWeather(feed, FakeRest({"features": stations}, data), lambda x, y: (25.0 + x / 1e5, 65.0 + y / 1e5),
                             clock=lambda: now[0], load_async=False)
    weather.load()
    return weather, feed, client, now


def _reading(station, sensor, value, at=1000.0):
    return (f"weather-v2/{station}/{sensor}", {"value": value, "time": at}, at)


def test_road_weather_follows_the_nearest_stations_and_resubscribes_on_moving():
    weather, feed, client, _ = _road_weather()
    assert [s for s, _, _ in weather.stations if s == 3] == []  # not collecting
    weather.update(0.0, 0.0, [])
    assert weather.nearest[:2] == [1, 2] and "weather-v2/1/#" in feed.topics and "weather-v2/status" in feed.topics
    weather.update(500.0, 0.0, [])  # under RESELECT_M: no new subscription
    assert len(client.subscribed) == 1
    weather.update(250_000.0, -300_000.0, [])  # ~27.5 E 62 N: the far group
    assert 1 not in weather.nearest and "weather-v2/1/#" in client.unsubscribed[0]


def test_road_weather_reads_the_nearest_fresh_sensor_as_an_observation():
    from theroadragetrip.weather_history import precipitation_from_observation

    weather, _, _, now = _road_weather()
    weather.update(0.0, 0.0, [])
    assert weather.observation() is None
    weather.update(0.0, 0.0, [_reading(2, dm.AIR_C, 3.5), _reading(2, dm.PRECIPITATION_FORM, 12),
                              _reading(1, dm.AIR_C, -1.0, at=now[0] - dm.FRESH_S - 1),  # station 1: stale
                              _reading(99, dm.AIR_C, 20.0), ("weather-v2/2/x", {"value": 1}, 0.0)])  # not near; junk
    observed = weather.observation()
    assert observed.temperature_c == 3.5 and precipitation_from_observation(observed) == ("slush", False)
    weather.update(0.0, 0.0, [_reading(1, dm.AIR_C, -1.0), _reading(1, dm.RAIN_CLASS, 5)])
    observed = weather.observation()  # station 1 is nearer, fresh now; its PWD form is missing, station 2's is used
    assert observed.temperature_c == -1.0 and precipitation_from_observation(observed) == ("slush", False)
    now[0] += dm.FRESH_S + 1  # station 2's PWD form ages out; station 1 reports again
    weather.update(0.0, 0.0, [_reading(1, dm.RAIN_CLASS, 5, at=now[0])])
    assert precipitation_from_observation(weather.observation()) == ("snow", False)  # station 1's rain class


def test_road_state_sets_the_wetness():
    weather, _, _, _ = _road_weather()
    weather.update(0.0, 0.0, [_reading(1, dm.ROAD_STATE, 3)])
    assert weather.road_wetness() == 1.0
    weather.update(0.0, 0.0, [_reading(1, dm.ROAD_STATE, 1, at=1001.0)])  # dry
    assert weather.road_wetness() == 0.0
    weather.update(0.0, 0.0, [_reading(1, dm.ROAD_STATE, 7, at=1002.0)])  # ice: the game's own wetness
    assert weather.road_wetness() is None


def test_rest_seeds_the_startup_gap_and_never_overwrites_newer_mqtt():
    seen = "1970-01-01T00:16:30Z"  # 990 s: 10 s before the fake clock's now
    weather, _, _, _ = _road_weather({1: [{"id": dm.WIND_MPS, "value": 4.0, "measuredTime": seen},
                                          {"id": dm.AIR_C, "value": 9.0, "measuredTime": seen}]})
    weather.update(0.0, 0.0, [_reading(1, dm.AIR_C, 2.0)])  # MQTT at 1000 s: newer than the seed
    observed = weather.observation()
    assert observed.wind_speed_mps == 4.0 and observed.temperature_c == 2.0


def test_road_ice_follows_the_road_surface_state_and_temperatures():
    weather, _, _, now = _road_weather()
    weather.update(0.0, 0.0, [])
    assert weather.road_ice() is None  # nothing fresh: the game's own rule

    def state(*readings):
        now[0] += 1.0
        weather.update(0.0, 0.0, [_reading(1, sensor, value, at=now[0]) for sensor, value in readings])
        return weather.road_ice()

    assert state((dm.ROAD_STATE, 7)) == 1.0 and state((dm.ROAD_STATE, 5)) == 0.5  # ice, frost
    assert state((dm.ROAD_STATE, 4), (dm.ROAD_C, -6.0)) == 0.0  # wet and salty: no ice even at -6
    assert state((dm.ROAD_STATE, 3), (dm.ROAD_C, -1.0), (dm.FREEZING_POINT_C, -3.0)) == 0.0  # above the brine's freezing point
    assert state((dm.ROAD_STATE, 3), (dm.ROAD_C, -4.0)) == 1.0  # wet, below it: black ice
    assert state((dm.ROAD_STATE, 2), (dm.ROAD_C, -4.0)) == 0.4  # moist: patchy
    assert state((dm.ROAD_STATE, 0)) is None  # a sensor fault


def test_the_weather_takes_the_stations_road_ice():
    from theroadragetrip.weather import WeatherSystem

    weather = WeatherSystem()
    weather.wetness = 1.0
    weather.update(1.0, 1.0, outside_temperature_c=-5.0)
    assert weather.road_ice_fraction == 1.0
    weather.road_ice_override = 0.0  # salted
    assert weather.road_ice_fraction == 0.0


def test_real_plough_routes_clear_road_snow_once_and_are_fetched_again_later():
    from theroadragetrip.weather import WeatherSystem

    calls = []

    class Routes:
        def get_json(self, path, params=None, *, max_age_s=None):
            calls.append(params)
            assert path == "/api/maintenance/v1/tracking/routes" and params["taskId"] == "PLOUGHING_AND_SLUSH_REMOVAL"
            return {"features": [{"properties": {"id": 7}, "geometry": {"type": "LineString", "coordinates": [[0.0, 0.0, 0.0], [0.0003, 0.0, 0.0]]}},
                                 {"properties": {"id": 8}, "geometry": {"type": "Point", "coordinates": [0.0001, 0.0005, 0.0]}}]}

    now = [10_000.0]
    ploughs = dm.LivePloughing(Routes(), lambda x, y: (x / 1e5, y / 1e5), lambda lon, lat: (lon * 1e5, lat * 1e5),
                               clock=lambda: now[0], load_async=False)
    weather = WeatherSystem()
    weather.road_snow = 2.0
    ploughs.update(0.0, 0.0, weather)
    assert weather.road_snow_at(15.0, 1.0) == 0.0 and weather.road_snow_at(15.0, 50.0) == 2.0  # along the 30 m route only
    assert ploughs.applied == 1 and calls[0]["xMin"] < 0.0 < calls[0]["xMax"]
    ploughs.update(0.0, 0.0, weather)
    assert len(calls) == 1  # within the poll interval
    now[0] += dm.PLOUGH_POLL_S
    ploughs.update(0.0, 0.0, weather)
    assert len(calls) == 2 and ploughs.applied == 1  # the same route is not applied twice


def test_subscriptions_are_logged(caplog):
    import logging

    feed, client, _ = _feed(["weather-v2/status"])
    client.unsubscribe = lambda topics: None
    with caplog.at_level(logging.INFO, logger="theroadragetrip.digitraffic_mqtt"):
        feed._on_connect(client, None, None, SimpleNamespace(is_failure=False))
        feed.set_topics(["weather-v2/1/#"])
    assert "subscribed: weather-v2/status" in caplog.text
    assert "unsubscribed: weather-v2/status" in caplog.text and "subscribed: weather-v2/1/#" in caplog.text
