"""Live push data from Digitraffic Road over MQTT (docs/digitraffic-mqtt.md).

Only with the live clock and realtime road data both on: MQTT is "now"
data, wrong at any other game time. paho's own thread owns the socket,
reconnects with backoff and decodes JSON; the simulation only drains a
bounded number of messages per tick. Nothing is cached or saved: live data
cannot be replayed (the REST data in digitraffic_road.py can).

Source: Fintraffic / digitraffic.fi, license CC 4.0 BY.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections import deque
from datetime import datetime
from typing import Callable, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

HOST = "tie.digitraffic.fi"
PORT = 443
PATH = "/mqtt"
USER = "RoadRageTrip/live-feed"
QUEUE_MAX = 2000  # oldest dropped beyond this: a stalled tick never grows memory
RECONNECT_S = (1, 300)


def _paho_client():
    import paho.mqtt.client as mqtt

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport="websockets")
    client.ws_set_options(path=PATH, headers={"Digitraffic-User": USER})
    client.tls_set()
    client.reconnect_delay_set(*RECONNECT_S)
    return client


class LiveFeed:
    """Subscribed topics in, (topic, message, received unix s) out. Each
    root's `<root>/status` gives `updated` (unix s) and is kept apart."""

    def __init__(self, topics: Iterable[str], client_factory: Callable = _paho_client,
                 clock: Callable[[], float] = time.time) -> None:
        self.topics = list(topics)
        self.clock = clock
        self.queue: deque = deque(maxlen=QUEUE_MAX)
        self.connected = False
        self.received = 0
        self.dropped = 0
        self.last_message_at: Optional[float] = None
        self.updated: dict = {}  # root -> the feed's own last update, unix s
        self.client = client_factory()
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def start(self) -> None:
        self.client.connect_async(HOST, PORT, keepalive=60)  # offline: retried, never blocks startup
        self.client.loop_start()

    def close(self) -> None:
        self.client.disconnect()
        self.client.loop_stop()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if getattr(reason_code, "is_failure", False):
            logger.warning("Digitraffic MQTT refused: %s", reason_code)
            return
        self.connected = True
        logger.info("Digitraffic MQTT connected, %d topics", len(self.topics))
        if self.topics:  # again after every reconnect: the session is clean
            client.subscribe([(topic, 0) for topic in self.topics])

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if self.connected:
            logger.info("Digitraffic MQTT disconnected: %s", reason_code)
        self.connected = False

    def _on_message(self, client, userdata, message) -> None:
        try:
            body = json.loads(message.payload)
        except ValueError:
            return
        now = self.clock()
        self.received += 1
        self.last_message_at = now
        root, _, rest = message.topic.partition("/")
        if rest == "status":
            if isinstance(body, dict) and isinstance(body.get("updated"), (int, float)):
                self.updated[root] = body["updated"]
            return
        if len(self.queue) == self.queue.maxlen:
            self.dropped += 1
        self.queue.append((message.topic, body, now))

    def set_topics(self, topics: Iterable[str]) -> None:
        """Subscribe the new topics and drop the old ones now; reconnects use the list."""
        topics = list(topics)
        gone = [topic for topic in self.topics if topic not in topics]
        new = [topic for topic in topics if topic not in self.topics]
        self.topics = topics
        if self.connected:
            if gone:
                self.client.unsubscribe(gone)
            if new:
                self.client.subscribe([(topic, 0) for topic in new])

    def drain(self, limit: int) -> List[Tuple[str, object, float]]:
        """At most `limit` queued messages, oldest first (the tick's budget)."""
        out = []
        while self.queue and len(out) < limit:
            out.append(self.queue.popleft())
        return out

    def diagnostics(self) -> dict:
        now = self.clock()
        return {"connected": self.connected, "topics": self.topics, "received": self.received,
                "queued": len(self.queue), "dropped": self.dropped,
                "last_message_age_s": None if self.last_message_at is None else round(now - self.last_message_at, 1),
                "feed_age_s": {root: round(now - updated, 1) for root, updated in self.updated.items()}}


STATUS_TOPICS = ["weather-v2/status", "maintenance-v2/status"]
WEATHER_STATIONS = 6  # nearest first; many "GATHERING" stations are silent, so more than one
RESELECT_M = 2000.0  # the taxi moves this far: pick the nearest stations again
FRESH_S = 1800.0  # older readings are ignored
# Road weather sensors (GET /api/weather/v1/sensors).
AIR_C, WIND_MPS, WIND_FROM_DEG, RAIN_CLASS, PRECIPITATION_FORM, ROAD_STATE = 1, 16, 18, 22, 25, 27
# Precipitation form (PWD, sensor 25) -> WMO 4680 wawa, as precipitation_from_observation reads it.
PWD_WAWA = {7: 0, 8: 51, 9: 51, 10: 61, 11: 71, 12: 67, 13: 68, 14: 89, 15: 77, 16: 77, 17: 87, 18: 56, 19: 66}
# Rain class (sensor 22), where a station has no PWD: dry, rain 1-3, snow or sleet 4-6.
RAIN_CLASS_WAWA = {0: 0, 1: 61, 2: 61, 3: 61, 4: 71, 5: 71, 6: 71}
# Road state (sensor 27) -> road wetness: dry, moist, wet, wet and salty, moist and salty, slush.
# Frost, snow and ice (5-7) and a sensor fault (0) leave the game's own wetness.
ROAD_STATE_WETNESS = {1: 0.0, 2: 0.4, 3: 1.0, 4: 1.0, 8: 0.4, 9: 1.0}


def parse_weather_stations(collection: Optional[dict]) -> List[Tuple[int, float, float]]:
    """(id, lon, lat) of the stations collecting data."""
    out = []
    for feature in (collection or {}).get("features", []):
        coordinates = (feature.get("geometry") or {}).get("coordinates") or []
        if (feature.get("properties") or {}).get("collectionStatus") == "GATHERING" and len(coordinates) >= 2:
            out.append((int(feature["id"]), float(coordinates[0]), float(coordinates[1])))
    return out


class RoadWeather:
    """Live road weather near the taxi: the nearest stations' sensors as an
    observation the weather system follows (in place of FMI while fresh)."""

    def __init__(self, feed: LiveFeed, client, to_lonlat: Callable[[float, float], Tuple[float, float]],
                 clock: Callable[[], float] = time.time, load_async: bool = True) -> None:
        self.feed, self.client, self.to_lonlat, self.clock = feed, client, to_lonlat, clock
        self.stations: List[Tuple[int, float, float]] = []
        self.nearest: List[int] = []
        self.values: dict = {}  # (station, sensor) -> (value, unix s)
        self._picked_at: Optional[Tuple[float, float]] = None
        self._seeded: list = []  # (station, sensor, value, unix s) from REST, appended by a thread
        self.load_async = load_async
        if load_async:  # the catalogue is REST (cached a day): never on the tick
            threading.Thread(target=self.load, name="digitraffic-weather-stations", daemon=True).start()

    def load(self) -> None:
        self.stations = parse_weather_stations(self.client.get_json("/api/weather/v1/stations", max_age_s=86400.0))
        logger.info("Digitraffic road weather: %d stations", len(self.stations))

    def update(self, x: float, y: float, messages) -> None:
        # Pick first: a reading is kept only from the stations picked.
        if self.stations and (self._picked_at is None or math.dist(self._picked_at, (x, y)) > RESELECT_M):
            self._picked_at = (x, y)
            lon, lat = self.to_lonlat(x, y)
            scale = math.cos(math.radians(lat))
            self.nearest = [station for station, _, _ in sorted(
                self.stations, key=lambda s: ((s[1] - lon) * scale) ** 2 + (s[2] - lat) ** 2)[:WEATHER_STATIONS]]
            self.values = {key: value for key, value in self.values.items() if key[0] in self.nearest}
            new = [station for station in self.nearest if not any(key[0] == station for key in self.values)]
            self.feed.set_topics(STATUS_TOPICS + [f"weather-v2/{station}/#" for station in self.nearest])
            # MQTT sends a station's sensors only every few minutes: start from REST's current values.
            if self.load_async:
                threading.Thread(target=self.seed, args=(new,), name="digitraffic-weather-seed", daemon=True).start()
            else:
                self.seed(new)
        readings = []
        while self._seeded:
            readings.append(self._seeded.pop(0))
        for topic, body, _ in messages:
            parts = topic.split("/")
            if (len(parts) == 3 and parts[0] == "weather-v2" and parts[1].isdigit() and parts[2].isdigit()
                    and isinstance(body, dict) and isinstance(body.get("value"), (int, float))):
                readings.append((int(parts[1]), int(parts[2]), float(body["value"]), float(body.get("time") or self.clock())))
        for station, sensor, value, at in readings:
            known = self.values.get((station, sensor))
            if station in self.nearest and (known is None or at >= known[1]):  # never older over newer
                self.values[(station, sensor)] = (value, at)

    def seed(self, stations) -> None:
        for station in stations:
            body = self.client.get_json(f"/api/weather/v1/stations/{station}/data", max_age_s=60.0)
            for reading in (body or {}).get("sensorValues", []):
                measured = reading.get("measuredTime")
                if isinstance(reading.get("value"), (int, float)) and isinstance(reading.get("id"), int) and measured:
                    at = datetime.fromisoformat(measured.replace("Z", "+00:00")).timestamp()
                    self._seeded.append((station, reading["id"], float(reading["value"]), at))

    def _fresh(self, sensor: int) -> Optional[float]:
        now = self.clock()
        for station in self.nearest:  # nearest first
            reading = self.values.get((station, sensor))
            if reading is not None and now - reading[1] <= FRESH_S:
                return reading[0]
        return None

    def observation(self):
        """weather_history.HourlyWeather now, or None without fresh readings."""
        from .weather_history import HourlyWeather

        temperature, form, rain = self._fresh(AIR_C), self._fresh(PRECIPITATION_FORM), self._fresh(RAIN_CLASS)
        wawa = PWD_WAWA.get(int(form)) if form is not None else RAIN_CLASS_WAWA.get(int(rain)) if rain is not None else None
        if temperature is None and wawa is None:
            return None
        return HourlyWeather(temperature_c=temperature, wawa=wawa, wind_speed_mps=self._fresh(WIND_MPS),
                             wind_from_deg=self._fresh(WIND_FROM_DEG), source="observed")

    def road_wetness(self) -> Optional[float]:
        """The road wetness the station reports, or None (frozen, faulty or unknown)."""
        state = self._fresh(ROAD_STATE)
        return None if state is None else ROAD_STATE_WETNESS.get(int(state))

    def diagnostics(self) -> dict:
        observation = self.observation()
        return {"stations": len(self.stations), "nearest": self.nearest, "readings": len(self.values),
                "observation": None if observation is None else vars(observation), "road_wetness": self.road_wetness()}
