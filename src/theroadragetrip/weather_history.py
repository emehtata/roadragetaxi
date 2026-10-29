"""Historical weather observations from FMI (Finnish Meteorological Institute).

Opt-in (Settings -> historical weather). For the game's current city and
game time this answers "what was the weather here, then?" from FMI's open
hourly observations - temperature, precipitation, present-weather code and
snow depth - and None whenever that isn't known (future/now, a gap, offline),
in which case the caller keeps using generated weather.

FMI WFS, stored query fmi::observations::weather::timevaluepair (same source
as the moekki cottage gallery). Queried by a bounding box around the city:
each parameter takes the nearest station that actually reported it that hour
(e.g. Oulu's airport reports temperature but not hourly rain, and only a few
stations measure snow depth). Fetches run on a background thread and are
cached in SQLite, including hours that had no data, so nothing is re-asked.
"""
from __future__ import annotations

import hashlib
import logging
import math
import sqlite3
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from .calendar import FINLAND_TZ as GAME_TIMEZONE  # the system time-zone database, else the Finnish rule

logger = logging.getLogger(__name__)

FMI_WFS_URL = "https://opendata.fmi.fi/wfs"
FMI_STORED_QUERY = "fmi::observations::weather::timevaluepair"
FMI_PARAMETERS = ("t2m", "r_1h", "wawa", "snow_aws", "ws_10min", "wd_10min", "n_man")  # n_man: cloud cover, oktas 0-8
# Around the city centre: ~65 km each way at 61-65 N. Many stations report
# only temperature/wind (Sysmä's nearest, Luhanka 25 km, has no rain gauge
# or present-weather sensor; the nearest with rain were 39-61 km away), and
# snow depth is measured at few stations - each parameter still comes from
# the nearest station that reported it.
SEARCH_HALF_LAT_DEG = 0.6
SEARCH_HALF_LON_DEG = 1.2
FETCH_CHUNK_HOURS = 72  # one request per 3 days of hourly data
REQUEST_TIMEOUT_S = 30.0
FETCH_RETRY_DELAY_S = 60.0  # after a failed fetch (offline), wait before asking FMI again
# Game times after the latest observation: FMI's meteorologist-edited point
# forecast (~72 h ahead, hourly). Refreshed at most once per real hour and
# cached on disk too; stale hours remain usable if a refresh fails.
FMI_FORECAST_QUERY = "fmi::forecast::edited::weather::scandinavia::point::timevaluepair"
FMI_FORECAST_PARAMETERS = ("Temperature", "Precipitation1h", "WeatherSymbol3", "WindSpeedMS", "WindDirection", "TotalCloudCover")  # cloud %
FORECAST_REFRESH_S = 3600.0
RECENT_REFRESH_S = 3600.0  # a cached chunk still reaching into the last hours: fetched again after this
FORECAST = "forecast"  # pending-work marker next to observation chunk numbers

_NS = {
    "wml2": "http://www.opengis.net/waterml/2.0",
    "gml": "http://www.opengis.net/gml/3.2",
}


@dataclass(frozen=True)
class HourlyWeather:
    """One hour of observed weather; any field may be unknown (None)."""

    temperature_c: Optional[float] = None
    precipitation_mm: Optional[float] = None
    wawa: Optional[int] = None  # WMO 4680 present weather (automatic station)
    snow_depth_cm: Optional[float] = None
    wind_speed_mps: Optional[float] = None  # 10-min mean at 10 m
    wind_from_deg: Optional[float] = None  # bearing the wind blows from
    source: str = "observed"  # "observed" (FMI station) or "forecast" (FMI edited forecast)
    cloud_cover: Optional[float] = None  # 0 clear .. 1 overcast (observed oktas / 8, forecast % / 100)


def parse_fmi_timevaluepair(xml_text: str) -> Dict[Tuple[float, float], Dict[str, Dict[int, float]]]:
    """{(lat, lon) of station: {parameter: {utc_epoch_hour: value}}}; NaN dropped."""
    root = ET.fromstring(xml_text)
    stations: Dict[Tuple[float, float], Dict[str, Dict[int, float]]] = {}
    for member in root:
        position = None
        for element in member.iter():
            if element.tag.endswith("}pos") and element.text:
                lat, lon = (float(v) for v in element.text.split()[:2])
                position = (lat, lon)
                break
        if position is None:
            continue
        for series in member.iter(f"{{{_NS['wml2']}}}MeasurementTimeseries"):
            parameter = series.get(f"{{{_NS['gml']}}}id", "").rsplit("-", 1)[-1]
            values = stations.setdefault(position, {}).setdefault(parameter, {})
            for point in series.iter(f"{{{_NS['wml2']}}}MeasurementTVP"):
                time_text = point.findtext("wml2:time", namespaces=_NS)
                value_text = point.findtext("wml2:value", namespaces=_NS)
                if not time_text or not value_text:
                    continue
                value = float(value_text)
                if math.isnan(value):
                    continue
                moment = datetime.strptime(time_text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                values[int(moment.timestamp() // 3600)] = value
    return stations


def nearest_station_values(
    stations: Dict[Tuple[float, float], Dict[str, Dict[int, float]]], lat: float, lon: float,
) -> Dict[int, HourlyWeather]:
    """Per hour, each parameter from the nearest station that reported it."""
    cos_lat = math.cos(math.radians(lat))
    by_distance = sorted(
        stations.items(),
        key=lambda item: (item[0][0] - lat) ** 2 + ((item[0][1] - lon) * cos_lat) ** 2,
    )
    hours = sorted({hour for _, series in stations.items() for values in series.values() for hour in values})
    result = {}
    for hour in hours:
        picked = {}
        for parameter in FMI_PARAMETERS:
            for _, series in by_distance:
                value = series.get(parameter, {}).get(hour)
                if value is not None:
                    picked[parameter] = value
                    break
        snow = picked.get("snow_aws")
        result[hour] = HourlyWeather(
            temperature_c=picked.get("t2m"),
            precipitation_mm=picked.get("r_1h"),
            wawa=int(picked["wawa"]) if "wawa" in picked else None,
            # FMI reports -1 for "no snow cover".
            snow_depth_cm=max(0.0, snow) if snow is not None else None,
            wind_speed_mps=picked.get("ws_10min"),
            wind_from_deg=picked.get("wd_10min"),
            # n_man is 0-8 oktas; 9 is "sky obscured" (fog): overcast for the sun
            cloud_cover=min(1.0, picked["n_man"] / 8.0) if "n_man" in picked else None,
        )
    return result


def _fetch_fmi(lat: float, lon: float, start_hour: int, end_hour: int, http_get=None) -> str:
    if http_get is None:
        import requests
        http_get = requests.get
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    response = http_get(FMI_WFS_URL, params={
        "service": "WFS", "version": "2.0.0", "request": "getFeature",
        "storedquery_id": FMI_STORED_QUERY,
        "bbox": f"{lon - SEARCH_HALF_LON_DEG},{lat - SEARCH_HALF_LAT_DEG},"
                f"{lon + SEARCH_HALF_LON_DEG},{lat + SEARCH_HALF_LAT_DEG}",
        "starttime": datetime.fromtimestamp(start_hour * 3600, timezone.utc).strftime(fmt),
        "endtime": datetime.fromtimestamp(end_hour * 3600, timezone.utc).strftime(fmt),
        "timestep": 60,
        "parameters": ",".join(FMI_PARAMETERS),
    }, timeout=REQUEST_TIMEOUT_S)
    response.raise_for_status()
    return response.text


def _fetch_fmi_forecast(lat: float, lon: float, http_get=None) -> str:
    if http_get is None:
        import requests
        http_get = requests.get
    response = http_get(FMI_WFS_URL, params={
        "service": "WFS", "version": "2.0.0", "request": "getFeature",
        "storedquery_id": FMI_FORECAST_QUERY,
        "latlon": f"{lat},{lon}",
        "timestep": 60,
        "parameters": ",".join(FMI_FORECAST_PARAMETERS),
    }, timeout=REQUEST_TIMEOUT_S)
    response.raise_for_status()
    return response.text


def _wawa_for_weather_symbol(symbol: Optional[float]) -> Optional[int]:
    """FMI WeatherSymbol3 -> the equivalent observed wawa code, so forecasts
    share precipitation_from_observation's mapping."""
    if symbol is None:
        return None
    code = int(symbol)
    if 61 <= code <= 64:
        return 95  # thunder
    if 21 <= code <= 23:
        return 80  # rain showers
    if 31 <= code <= 33:
        return 61  # rain
    if 41 <= code <= 43:
        return 85  # snow showers
    if 51 <= code <= 53:
        return 71  # snow
    if 71 <= code <= 73 or 81 <= code <= 83:
        return 67  # sleet
    return 0  # clear / cloudy / fog: dry


def parse_fmi_forecast(xml_text: str) -> Dict[int, HourlyWeather]:
    """{utc_epoch_hour: HourlyWeather(source="forecast")} for one point."""
    stations = parse_fmi_timevaluepair(xml_text)
    if not stations:
        return {}
    series = next(iter(stations.values()))
    temperature = series.get("Temperature", {})
    precipitation = series.get("Precipitation1h", {})
    symbol = series.get("WeatherSymbol3", {})
    wind_speed = series.get("WindSpeedMS", {})
    wind_from = series.get("WindDirection", {})
    cloud = series.get("TotalCloudCover", {})
    return {
        hour: HourlyWeather(
            temperature_c=temperature.get(hour),
            precipitation_mm=precipitation.get(hour),
            wawa=_wawa_for_weather_symbol(symbol.get(hour)),
            wind_speed_mps=wind_speed.get(hour),
            wind_from_deg=wind_from.get(hour),
            source="forecast",
            cloud_cover=max(0.0, min(1.0, cloud[hour] / 100.0)) if hour in cloud else None,
        )
        for hour in sorted(set(temperature) | set(precipitation) | set(symbol))
    }


def game_time_to_utc_hour(moment: datetime) -> float:
    """Naive local game datetime (Finnish time) -> fractional UTC epoch hour."""
    aware = moment.replace(tzinfo=GAME_TIMEZONE) if moment.tzinfo is None else moment
    return aware.timestamp() / 3600.0


def gradual_weather(history, moment: datetime, key: str = "") -> Optional[HourlyWeather]:
    """Sample interpolated hourly weather in stable five-minute steps."""
    sample = moment.replace(minute=moment.minute - moment.minute % 5, second=0, microsecond=0)
    hour = sample.replace(minute=0)
    previous, current, following = (history.get(hour + timedelta(hours=offset)) for offset in (-1, 0, 1))

    def boundary(at: datetime) -> datetime:
        digest = hashlib.sha256(f"{key}:{at.isoformat()}".encode()).digest()
        slot = int.from_bytes(digest[:8], "little") % 12 - 6
        return at + timedelta(minutes=(slot if slot < 0 else slot + 1) * 5)

    selected = previous if sample < boundary(hour) else following if sample >= boundary(hour + timedelta(hours=1)) else current
    if current is not None and following is not None and current.temperature_c is not None and following.temperature_c is not None:
        fraction = (sample - hour).total_seconds() / 3600.0
        temperature = current.temperature_c + (following.temperature_c - current.temperature_c) * fraction
        if selected is not None:
            selected = replace(selected, temperature_c=temperature)
    return selected


class WeatherHistory:
    """Observed hourly weather for one location, fetched in the background.

    get() never blocks or touches the network: it answers from memory,
    and request() queues missing 3-day chunks for the worker thread.
    """

    def __init__(
        self,
        lat: float,
        lon: float,
        cache_path: Optional[Path] = None,
        fetch: Optional[Callable[[float, float, int, int], str]] = None,
        fetch_forecast: Optional[Callable[[float, float], str]] = None,
    ) -> None:
        self.lat, self.lon = lat, lon
        self.location = f"{lat:.2f},{lon:.2f}"
        self._fetch = fetch or _fetch_fmi
        self._fetch_forecast = fetch_forecast or _fetch_fmi_forecast
        self._hours: Dict[int, HourlyWeather] = {}
        self._forecast_hours: Dict[int, HourlyWeather] = {}
        self._forecast_fetched_at: Optional[float] = None  # time.monotonic()
        self._latest_snow: Tuple[int, Optional[float]] = (-1, None)  # (utc hour, cm) newest observed depth
        self._covered_chunks: set = set()
        self._pending: List[int] = []
        self._lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        self._retry_after = 0.0  # time.monotonic(): no new fetches before this after a failure
        self._db = None
        self._cache_path = cache_path  # opened on first request(): nothing on disk while unused

    def _open_cache(self) -> None:
        cache_path, self._cache_path = self._cache_path, None
        if cache_path is not None:
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                self._db = sqlite3.connect(str(cache_path), check_same_thread=False)
                self._db.executescript(
                    # _v4: cloud cover added (_v3: wind, wider station search); older chunks are fetched again.
                    "CREATE TABLE IF NOT EXISTS weather_hours_v4 (location TEXT, hour INTEGER, temperature REAL,"
                    " precipitation REAL, wawa INTEGER, snow_depth REAL, wind_speed REAL, wind_from REAL, cloud REAL,"
                    " PRIMARY KEY (location, hour));"
                    "CREATE TABLE IF NOT EXISTS fetched_chunks_v4 (location TEXT, chunk INTEGER,"
                    " PRIMARY KEY (location, chunk));"
                    # Not final yet (the last hours, the forecast): reused for an hour of wall time.
                    "CREATE TABLE IF NOT EXISTS recent_chunks_v4 (location TEXT, chunk INTEGER, fetched_at REAL,"
                    " PRIMARY KEY (location, chunk));"
                    "CREATE TABLE IF NOT EXISTS forecast_hours_v2 (location TEXT, hour INTEGER, fetched_at REAL,"
                    " temperature REAL, precipitation REAL, wawa INTEGER, wind_speed REAL, wind_from REAL, cloud REAL,"
                    " PRIMARY KEY (location, hour));"
                )
            except sqlite3.Error as exc:
                logger.warning("Weather history cache unavailable (%s); using memory only", exc)
                self._db = None

    # -- lookups (main thread, never blocking) ------------------------------

    def get(self, moment: datetime) -> Optional[HourlyWeather]:
        """FMI weather for the hour beginning at `moment`; None if unknown."""
        hour = math.floor(game_time_to_utc_hour(moment))
        with self._lock:
            current = self._hours.get(hour) or self._forecast_hours.get(hour)
            latest_snow = self._latest_snow[1]
        if current is None:
            return None
        if current.source == "forecast" and current.snow_depth_cm is None and latest_snow is not None:
            # No snow-depth forecast: the ground keeps its last observed snow.
            current = replace(current, snow_depth_cm=latest_snow)
        return current

    def source_at(self, moment: datetime) -> str:
        """"observed", "forecast" or "generated" (nothing known)."""
        observed = self.get(moment)
        return observed.source if observed is not None else "generated"

    def previous(self, moment: datetime):
        """Latest earlier FMI hour with precipitation, including unloaded disk history.
        Returns (UTC epoch hour, weather) or None; caller caches this per game hour."""
        hour = math.floor(game_time_to_utc_hour(moment))
        with self._lock:
            candidates = {h: w for h, w in self._forecast_hours.items() if h < hour}
            candidates.update({h: w for h, w in self._hours.items()
                               if h < hour and precipitation_from_observation(w)[0] is not None})
            if self._db is not None:
                for table, source, snow in (("weather_hours_v4", "observed", "snow_depth"),
                                            ("forecast_hours_v2", "forecast", "NULL")):
                    try:
                        row = self._db.execute(
                            f"SELECT hour,temperature,precipitation,wawa,{snow},wind_speed,wind_from,cloud "
                            f"FROM {table} WHERE location=? AND hour<? AND (wawa IS NOT NULL OR precipitation IS NOT NULL) "
                            "ORDER BY hour DESC LIMIT 1", (self.location, hour),
                        ).fetchone()
                    except sqlite3.Error:
                        continue
                    if row is not None:
                        h, temperature, precipitation, wawa, depth, speed, direction, cloud = row
                        if h not in candidates or source == "observed":
                            candidates[h] = HourlyWeather(temperature, precipitation, wawa, depth, speed, direction, source, cloud)
            usable = [(h, w) for h, w in candidates.items() if precipitation_from_observation(w)[0] is not None]
            return max(usable, key=lambda item: item[0]) if usable else None

    # -- fetching ------------------------------------------------------------

    def request(self, start: datetime, end: datetime) -> None:
        """Make sure hours between two game times get loaded (background)."""
        first = math.floor(game_time_to_utc_hour(start)) // FETCH_CHUNK_HOURS
        last = math.floor(game_time_to_utc_hour(end)) // FETCH_CHUNK_HOURS
        now_chunk = math.floor(datetime.now(timezone.utc).timestamp() / 3600.0) // FETCH_CHUNK_HOURS
        if time.monotonic() < self._retry_after:
            return
        with self._lock:
            if self._cache_path is not None:
                self._open_cache()
            for chunk in range(first, last + 1):
                if chunk in self._covered_chunks or chunk in self._pending or chunk > now_chunk:
                    continue
                if self._load_cached_chunk(chunk):
                    continue
                first_hour = max(chunk * FETCH_CHUNK_HOURS, math.floor(game_time_to_utc_hour(start)))
                last_hour = min((chunk + 1) * FETCH_CHUNK_HOURS - 1, math.floor(game_time_to_utc_hour(end)))
                if all(hour in self._hours for hour in range(first_hour, last_hour + 1)):
                    continue  # existing observations never expire; fetch only when hours are missing
                self._pending.append(chunk)
            reaches_future = game_time_to_utc_hour(end) > datetime.now(timezone.utc).timestamp() / 3600.0
            forecast_stale = (
                self._forecast_fetched_at is None
                or time.monotonic() - self._forecast_fetched_at > FORECAST_REFRESH_S
            )
            if reaches_future and self._forecast_fetched_at is None and self._load_cached_forecast():
                forecast_stale = False
            if reaches_future and forecast_stale and FORECAST not in self._pending:
                self._pending.append(FORECAST)
            if self._pending and (self._worker is None or not self._worker.is_alive()):
                self._worker = threading.Thread(target=self._work, name="weather-history", daemon=True)
                self._worker.start()

    def wait_idle(self, timeout_s: float) -> None:
        worker = self._worker
        if worker is not None:
            worker.join(timeout_s)

    def _load_cached_chunk(self, chunk: int) -> bool:
        """Load retained observations; True if no refresh is needed.
        Called with the lock held. Only incomplete chunks can expire."""
        if self._db is None:
            return False
        try:
            complete = self._db.execute(
                "SELECT 1 FROM fetched_chunks_v4 WHERE location=? AND chunk=?", (self.location, chunk),
            ).fetchone() is not None
            recent = self._db.execute(
                "SELECT fetched_at FROM recent_chunks_v4 WHERE location=? AND chunk=?",
                (self.location, chunk),
            ).fetchone()
            if not complete and recent is None:
                return False
            fresh = complete or recent[0] > time.time() - RECENT_REFRESH_S
            rows = self._db.execute(
                "SELECT hour, temperature, precipitation, wawa, snow_depth, wind_speed, wind_from, cloud FROM weather_hours_v4"
                " WHERE location=? AND hour>=? AND hour<?",
                (self.location, chunk * FETCH_CHUNK_HOURS, (chunk + 1) * FETCH_CHUNK_HOURS),
            ).fetchall()
        except sqlite3.Error:
            return False
        for hour, temperature, precipitation, wawa, snow_depth, wind_speed, wind_from, cloud in rows:
            self._hours[hour] = HourlyWeather(temperature, precipitation, wawa, snow_depth, wind_speed, wind_from, cloud_cover=cloud)
        self._remember_snow(self._hours)
        if fresh:
            self._covered_chunks.add(chunk)
        return fresh

    def _load_cached_forecast(self) -> bool:
        """Load even stale hours for offline use; return whether still fresh.
        Called with the lock held; age always follows the real fetch time."""
        if self._db is None:
            return False
        try:
            rows = self._db.execute(
                "SELECT hour, fetched_at, temperature, precipitation, wawa, wind_speed, wind_from, cloud FROM forecast_hours_v2"
                " WHERE location=?", (self.location,),
            ).fetchall()
        except sqlite3.Error:
            return False
        if not rows:
            return False
        self._forecast_hours = {hour: HourlyWeather(temperature, precipitation, wawa, None, wind_speed, wind_from, "forecast", cloud)
                                for hour, _, temperature, precipitation, wawa, wind_speed, wind_from, cloud in rows}
        self._forecast_fetched_at = time.monotonic() - (time.time() - min(row[1] for row in rows))
        return time.monotonic() - self._forecast_fetched_at <= FORECAST_REFRESH_S

    def _work(self) -> None:
        while True:
            with self._lock:
                if not self._pending:
                    return
                chunk = self._pending[0]
            if chunk == FORECAST:
                if not self._work_forecast():
                    return
                continue
            start_hour = chunk * FETCH_CHUNK_HOURS
            end_hour = start_hour + FETCH_CHUNK_HOURS - 1
            try:
                stations = parse_fmi_timevaluepair(self._fetch(self.lat, self.lon, start_hour, end_hour))
                hours = nearest_station_values(stations, self.lat, self.lon)
            except Exception as exc:  # network/parse failure: stay on generated weather
                logger.warning(
                    "FMI weather history fetch failed for %s, UTC hours %d-%d: %s: %s; "
                    "cached data retained, generated weather used where FMI data is unavailable; retry in %.0f s",
                    self.location, start_hour, end_hour, type(exc).__name__, exc, FETCH_RETRY_DELAY_S,
                )
                with self._lock:
                    self._pending.clear()
                self._retry_after = time.monotonic() + FETCH_RETRY_DELAY_S
                return
            if not hours:
                logger.warning(
                    "FMI weather history returned no usable hourly data for %s, UTC hours %d-%d; "
                    "using cached or generated weather where FMI data is unavailable",
                    self.location, start_hour, end_hour,
                )
            complete = end_hour < datetime.now(timezone.utc).timestamp() / 3600.0 - 2
            with self._lock:
                self._hours.update(hours)
                self._remember_snow(hours)
                self._covered_chunks.add(chunk)
                self._pending.remove(chunk)
                # A chunk reaching into the last hours isn't final yet: cached
                # as recent, so a session within the hour reuses it and a later
                # one fetches it again.
                if self._db is not None:
                    try:
                        self._db.executemany(
                            "INSERT OR REPLACE INTO weather_hours_v4 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            [(self.location, hour, w.temperature_c, w.precipitation_mm, w.wawa, w.snow_depth_cm,
                              w.wind_speed_mps, w.wind_from_deg, w.cloud_cover)
                             for hour, w in hours.items()],
                        )
                        if complete:
                            self._db.execute(
                                "INSERT OR REPLACE INTO fetched_chunks_v4 VALUES (?, ?)", (self.location, chunk),
                            )
                        else:
                            self._db.execute(
                                "INSERT OR REPLACE INTO recent_chunks_v4 VALUES (?, ?, ?)", (self.location, chunk, time.time()),
                            )
                        self._db.commit()
                    except sqlite3.Error as exc:
                        logger.warning("Weather history cache write failed (%s)", exc)
            logger.info("FMI weather history: %s chunk %d, %d hours", self.location, chunk, len(hours))

    def _remember_snow(self, hours: Dict[int, HourlyWeather]) -> None:
        """Called with the lock held: track the newest observed snow depth."""
        for hour, weather in hours.items():
            if weather.snow_depth_cm is not None and hour > self._latest_snow[0]:
                self._latest_snow = (hour, weather.snow_depth_cm)

    def _work_forecast(self) -> bool:
        """Fetch the point forecast; False (and back off) on failure."""
        try:
            hours = parse_fmi_forecast(self._fetch_forecast(self.lat, self.lon))
            if not hours:
                raise ValueError("no usable hourly data")
        except Exception as exc:
            logger.warning(
                "FMI forecast fetch failed for %s: %s: %s; "
                "cached data retained, generated weather used where FMI data is unavailable; retry in %.0f s",
                self.location, type(exc).__name__, exc, FETCH_RETRY_DELAY_S,
            )
            with self._lock:
                self._pending.clear()
            self._retry_after = time.monotonic() + FETCH_RETRY_DELAY_S
            return False
        with self._lock:
            self._forecast_hours = hours
            self._forecast_fetched_at = time.monotonic()
            self._pending.remove(FORECAST)
            if self._db is not None:
                try:
                    self._db.execute("DELETE FROM forecast_hours_v2 WHERE location=?", (self.location,))
                    self._db.executemany(
                        "INSERT OR REPLACE INTO forecast_hours_v2 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [(self.location, hour, time.time(), w.temperature_c, w.precipitation_mm, w.wawa,
                          w.wind_speed_mps, w.wind_from_deg, w.cloud_cover) for hour, w in hours.items()],
                    )
                    self._db.commit()
                except sqlite3.Error as exc:
                    logger.warning("Weather forecast cache write failed (%s)", exc)
        if hours:
            first = datetime.fromtimestamp(min(hours) * 3600, GAME_TIMEZONE)
            last = datetime.fromtimestamp(max(hours) * 3600, GAME_TIMEZONE)
            logger.info("FMI forecast: %s, %d hours %s - %s", self.location, len(hours), f"{first:%d.%m. %H:%M}", f"{last:%d.%m. %H:%M}")
        return True


def precipitation_from_observation(observation: HourlyWeather) -> Tuple[Optional[str], bool]:
    """(kind, thunder) from an observation: kind is "rain", "slush",
    "snow", "precipitation" (type left to temperature), "" (dry) or None
    (unknown). WMO 4680 wawa codes from automatic stations."""
    code = observation.wawa
    if code is not None:
        if 90 <= code <= 99:
            return "rain", True
        if code in (67, 68):
            return "slush", False
        if 70 <= code <= 78 or 85 <= code <= 87:
            return "snow", False
        if 50 <= code <= 66 or 80 <= code <= 84 or code == 89:
            return "rain", False
        if 40 <= code <= 42:
            return "precipitation", False
        return "", False
    if observation.precipitation_mm is not None:
        return ("precipitation" if observation.precipitation_mm >= 0.1 else ""), False
    return None, False
