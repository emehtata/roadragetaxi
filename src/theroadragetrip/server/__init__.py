"""The headless simulation server (client-server-02.md).

Owns the one authoritative `world`/`car`, runs `simulation.advance_simulation`
at a fixed rate, and publishes a state snapshot to every connected client
after each tick, to the Godot client. No display: it runs on
a machine with no graphical environment.

Live map expansion (auto-fetch as the car nears the loaded bbox's edge):
server/map_sync.py streams and merges tiles, runs the map sync in
budgeted steps, and the server resends the chunks that changed
(--no-auto-fetch turns it off). The server runs the same
`advance_simulation` tick as the old single-process game otherwise.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace

import logging
import math
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Optional


from .. import protocol
from ..navigation_route import NavigationRoute
from ..map_chunks import CHUNK_SIZE_M, LOAD_RADIUS, ChunkIndex, cell_of, chunk_id, plan
from ..police import SpeedCameraSpawner
from ..tile_streaming import world_to_tile
from .map_sync import MapStreamer, prepare_initial_window
from ..protocol import LOCAL_PLAYER_ID
from ..map_style import FIELDS_FROZEN_WINTER_WEIGHT
from ..calendar import GameCalendar, darkness_for_sun_altitude, sports_lights_hours, finnish_utc_offset_hours, solar_position_on, grid_azimuth
from ..career import career_path, gig_odometer_path, load_career
from ..arena_crowds import GAME_DURATION
from ..config import CONFIG_PATH, cities_from_config, default_city_configuration, get_overpass_endpoints
from ..world_loader import load_world, resolve_city
from ..viewport import SCREEN_H, SCREEN_W
from ..simulation import RAGE_SHOUT_DURATION_S, PlayerCommand, advance_simulation, apply_enter_exit_vehicle
from ..physics import reset_trip, respawn_car
from ..home import clear_homes, CONFIRM_S, at_house_yard, homes_path, is_same_home, load_home, save_home
from ..localization import SUPPORTED_LANGUAGES, tr
from ..moon import moon_info_on, moon_position_at
from ..transport import Listener
from ..weather import WeatherSystem, raining_last_hour, weather_type_for_observation
from ..weather_history import WeatherHistory, gradual_weather, precipitation_from_observation, game_time_to_utc_hour
from ..calendar import clamp_start_datetime
from ..osm import CACHE_DIR
from ..climate import appearance_with_snow_depth, typical_temperature

logger = logging.getLogger(__name__)

SPORTS_ICE_DARKNESS = 0.5  # darker than this (sun ~3 degrees down) and unlit: nobody skates or plays
SOCCER_SNOW_WEIGHT = 0.05  # a winter (snow) weight under this: the pitches are bare

# Nominal camera fallback for headless runs and clients without view reports.
# Godot supplies its actual world-space bounds for dynamic interest/culling.
_DEFAULT_PX_PER_M = 9.0


class NullAudio:
    """The server has no sound; every audio cue advance_simulation would
    normally play (crash sfx, driver lines, ...) becomes a no-op here -
    only the client renders/plays anything."""

    def __getattr__(self, _name):
        def _noop(*_args, **_kwargs):
            return None

        return _noop


class EventAudio(NullAudio):
    """NullAudio that remembers each sound cue as a semantic event for the
    clients ({"type": "sound", "group": "collision.building", "at": [x, y]}),
    which decide how to present it. Loops and per-frame audio state stay
    no-ops - a client derives those from the state itself."""

    def __init__(self, rng=None) -> None:
        self.events: list = []
        self._edges: dict = {}
        # Speech (godot-final-07): speech.py chooses the line; a line
        # is "busy" until its recording would have finished, on the
        # simulation clock (advance()).
        import random as _random

        from ..speech import Speech, recorded_lines
        self._clips = {speaker: recorded_lines(speaker) for speaker in ("driver", "passenger")}
        self._speech = Speech(lambda speaker, key: key in self._clips[speaker], rng or _random)
        self.clock = 0.0
        self._busy_until = 0.0

    def advance(self, dt: float) -> None:
        """The server tick's simulation time (the speech timing runs on it)."""
        self.clock += max(0.0, dt)

    def _speak(self, line) -> None:
        if line is None:
            return
        from ..speech import SUBTITLE_S
        g, language, audio_hash = line["key"]
        self._busy_until = self.clock + self._clips[line["speaker"]][line["key"]]
        self.events.append({"type": "speech", "speaker": line["speaker"], "speaker_name": line["speaker_name"],
                            "gender": g, "language": language, "hash": audio_hash, "text": line["text"],
                            "duration_s": SUBTITLE_S})

    def _busy(self) -> bool:
        return self.clock < self._busy_until

    def play_driver_line(self, situation, language, gender="man"):
        self._speak(self._speech.driver(situation, language, gender, self.clock, self._busy()))

    def play_passenger_line_for_situation(self, situation, gender, language, speaker_name=None):
        self._speak(self._speech.passenger_for_situation(situation, gender, language, speaker_name, self._busy()))

    def update_passenger_speech(self, active, gender, language, dt, speaker_name=None):
        self._speak(self._speech.passenger_tick(active, gender, language, dt, speaker_name, self._busy()))

    def play_passenger_line(self, finnish_text, gender, language, speaker_name=None):
        self._speak(self._speech.passenger_line(finnish_text, gender, language, speaker_name, self._busy()))

    def play_group(self, group_id, volume=1.0, variation=None, at=None):
        self.events.append({"type": "sound", "group": group_id, **({"at": list(at)} if at else {})})

    def play(self, name, volume=1.0, at=None):
        self.events.append({"type": "sound", "group": name, **({"at": list(at)} if at else {})})

    def on_rise(self, key, active, group_id, volume=1.0):
        rose = active and not self._edges.get(key, False)
        self._edges[key] = active
        if rose:
            self.play_group(group_id)
        return rose

    def take_events(self) -> list:
        events, self.events = self.events, []
        return events



NPC_BRAKE_DECEL_MPS2 = 0.8  # slowing harder than rolling resistance: the brake lamps are lit


def npc_braking(npc, last_speed: float, dt: float) -> bool:
    """An NPC's brake lamps: slowing down, or standing in traffic (a
    driver holds the brake at a light or in a queue); not parked, not
    reversing, not on foot."""
    if npc.state == "PARKED" or getattr(npc, "is_on_foot", False) or npc.speed < -0.05:
        return False
    if abs(npc.speed) < 0.3:
        return True
    return dt > 0.0 and (abs(last_speed) - abs(npc.speed)) / dt > NPC_BRAKE_DECEL_MPS2

# How far past the merged objects' extent the map sync's own edits reach
# (a new road's generated house bays ~35 m, the trees it removes, its lamps).
CHANGED_AREA_MARGIN_M = 50.0


class SimulationServer:
    def __init__(self, args, config, city_choice=None, startup_progress=None):
        """`city_choice` (a `_choose_city`-shaped SimpleNamespace) lets an
        embedding client that already ran its own interactive city menu
        hand the resolved choice straight to the server, instead of the
        server independently re-resolving one from raw CLI args - the two
        must never disagree about which city/bbox is being played. The
        standalone `python -m theroadragetrip.server` process (no client
        menu involved) resolves it here instead, CLI-driven, no menu."""
        self.args = args
        from .startup_progress import StartupProgress
        progress = startup_progress or StartupProgress(getattr(args, "startup_progress", None))
        progress("starting")
        self.tick_rate = max(1.0, float(getattr(args, "tick_rate", 30.0)))
        self.audio = EventAudio()
        self.language = getattr(args, "language", None) or config.get("game", "language", fallback="") or "en"
        self.physics_mode = config.get("game", "physics_realism", fallback="arcade")
        self.career_file = career_path(CONFIG_PATH)
        self.gig_odometer_file = gig_odometer_path(CONFIG_PATH)
        # A gig save slot: the slot file is the gig car file, and a saved
        # game continues in its city, around the car, at its game time.
        self.save_slot_file = None
        saved = {}
        if getattr(args, "save_slot", None) and getattr(args, "game_mode", "gig_driver") != "career":
            from ..save_slots import read_slot, slot_path
            self.save_slot_file = self.gig_odometer_file = slot_path(CONFIG_PATH, args.save_slot)
            saved = read_slot(self.save_slot_file)
            if saved.get("city") and saved.get("bbox"):
                args.preset, args.bbox = saved["city"], saved["bbox"]
                args.place_name = saved.get("place_name") or None
        self.save_count = 0  # saves written: the client's "saved" acknowledgement
        self._fares_opened = False  # no fares or pre-bookings until the game has started (the first client)
        self._pending_save = False

        overpass_endpoints = get_overpass_endpoints(config)
        bus_stops_enabled = True  # always: an old ini's bus_stops = false (the former default) is ignored
        roadworks_enabled = config.getboolean("game", "roadworks_enabled", fallback=False)
        # Loading never streams; the map grows while playing (map_sync.py).
        self._auto_fetch = bool(getattr(args, "auto_fetch", True)) and not getattr(args, "use_sample", False)
        if getattr(args,"intercity_fares",False) and not self._auto_fetch:
            raise ValueError("Intercity fares require automatic map streaming and cannot use the sample map.")
        args.auto_fetch = False

        if city_choice is None:
            if getattr(args, "game_mode", "gig_driver") == "career":
                city_centers, bbox_presets = default_city_configuration()
                cities = list(city_centers)
                career = load_career(self.career_file, len(cities))
                selected = len(cities) - 1 - int(career["city_index"])
                chosen = cities[selected]
                city_choice = SimpleNamespace(
                    chosen_city=chosen, camera_city_name=chosen, bbox=bbox_presets[chosen.lower()],
                    city_centers=city_centers, bbox_presets=bbox_presets, game_mode="career",
                    career=career, force_refresh=args.force_refresh, cities_list=cities,
                    selected_city_idx=selected, language=self.language,
                )
            else:
                city_centers, bbox_presets = cities_from_config(config)
                city_choice = resolve_city(args, city_centers, bbox_presets)
        self.chosen_city = city_choice.chosen_city
        self.bbox = city_choice.bbox  # the loaded box (the F12 debug JSON)
        self.camera_city_name = city_choice.camera_city_name
        self.cities_list = city_choice.cities_list
        self.career = city_choice.career

        progress("world")
        self.world = load_world(
            city_choice.chosen_city, city_choice.camera_city_name, city_choice.bbox,
            city_choice.city_centers, args, city_choice.force_refresh, overpass_endpoints,
            bus_stops_enabled, roadworks_enabled, city_choice.career, self.career_file,
            self.gig_odometer_file, self.language,
            progress=lambda fraction, message: progress("world", message),
        )
        self.initial_map_preparation = (
            prepare_initial_window(self.world, progress=progress) if self._auto_fetch
            else {"started": False, "integrated_tiles": 0, "elapsed_s": 0.0}
        )
        from ..protests import ProtestManager, ProtestSettings
        self.world.protests = ProtestManager(ProtestSettings.from_config(config), self.chosen_city)
        self.world.npc_manager.protests = self.world.protests
        progress("weather")
        self.car = self.world.car
        self._set_fares_open(False)  # opened when the first client connects
        # weather is per-session state constructed fresh alongside
        # `world` rather than something load_world itself returns -
        # attached onto `world` here so protocol.py's state builder (which
        # reads world.weather, matching how it reads every other manager)
        # doesn't need a separate parameter for it.
        # The launcher supplies the user's selected start time. Direct server
        # launches without --start-time retain the legacy 18:00 fallback.
        start = getattr(args, "start_time", None)  # the gig start picker's, a year back at most
        if start is not None:
            start = clamp_start_datetime(start.replace(second=0, microsecond=0), date.today())
        if saved.get("game_time"):  # a continued game resumes at its own time, unclamped
            start = datetime.fromisoformat(saved["game_time"])
        self.calendar = GameCalendar(start or datetime.combine(date.today(), datetime.min.time()) + timedelta(hours=18),
                                     latitude=getattr(self.world, "sun_latitude", 65.01))
        if saved:  # odometer, fuel and money came with the gig car file
            from ..save_slots import restore_fare
            pose = saved.get("car") or {}
            if all(isinstance(pose.get(key), (int, float)) for key in ("x", "y", "heading")):
                self.car.x, self.car.y, self.car.heading = pose["x"], pose["y"], pose["heading"]
                self.car.speed = 0.0
            taxi_mgr = self.world.taxi_mgr
            taxi_mgr.total_score = int(saved.get("total_score", 0))
            taxi_mgr.completed_fares = int(saved.get("completed_fares", 0))
            if restore_fare(taxi_mgr, saved.get("fare")):
                logger.info("Save slot %s: fare to %s continues", self.save_slot_file.stem,
                            taxi_mgr.current_passenger.dropoff.address)
        moon_latitude = getattr(self.world, "sun_latitude", 65.01)
        moon_longitude = getattr(self.world, "sun_longitude", 25.47)
        self.moon_info = moon_info_on(self.calendar.date, moon_latitude, moon_longitude)
        moon_time = lambda value: value.strftime("%H:%M") if value is not None else "none"
        logger.info(
            "Moon %s: rise=%s transit=%s set=%s phase=%s illumination=%.1f%% age=%.1f days",
            self.calendar.date, moon_time(self.moon_info.rise), moon_time(self.moon_info.transit),
            moon_time(self.moon_info.set), self.moon_info.phase, self.moon_info.illumination * 100.0,
            self.moon_info.age_days,
        )
        self.world.weather = WeatherSystem(season=self.calendar.season)
        # Historical weather (opt-in): FMI observations/forecast for
        # this city and game time where known, generated weather otherwise.
        historical = getattr(args, "historical_weather", None)
        if historical is None:
            historical = config.getboolean("game", "historical_weather", fallback=False)
        self.weather_history = None
        self._historical_weather = historical
        self.weather_city = self.chosen_city
        self._weather_latitude = self.calendar.latitude
        self._weather_check_position = None
        self._weather_centre = None
        self._update_weather_location()
        if self.weather_history is not None:
            self.weather_history.request(self.calendar.current - timedelta(hours=6), self.calendar.current + timedelta(hours=48))
            self.weather_history.wait_idle(3.0)  # brief: the first hour can be the real weather
        observed = self._update_outside()
        if observed is not None:  # the first tick follows it; the start's weather is it already
            self.world.weather.update(0.001, 0.0, outside_temperature_c=self.world.weather.outside_temperature_c,
                                      observed=observed)
        self.world.weather.settle_initial_wetness(self._raining_last_hour())
        self._on_foot = True
        self._camx, self._camy = self.car.x, self.car.y
        self._px_per_m = _DEFAULT_PX_PER_M
        self._current_way = None
        self._time_scale = 60.0
        self._bridge_edge_crash_cooldown = 0.0
        self._rage_power = 0.0
        self._water_elapsed = 0.0
        self._slow_check_elapsed = 0.0
        self._taxi_waiter_elapsed = 0.0
        self._saved_gig_fares = self.world.taxi_mgr.completed_fares
        self._tick = 0
        self._tire_mark = None  # this tick's tyre mark under the taxi (godot-16), or None
        self._lightning_event_id = self.world.weather.lightning_event_id

        self._command_lock = threading.Lock()
        self._latest_command = PlayerCommand()
        self._pending_interacts = 0
        from ..station_announcer import StationAnnouncer
        self.announcer = StationAnnouncer(platforms=[way for way in self.world.ways
                                                     if way.highway == "platform" and not getattr(way, "is_busway", False)])
        self.navigation = NavigationRoute()  # the player's route to the taxi target (godot-final-04)
        self._pending_refuels = 0  # edge-triggered too: one press buys fuel once, never again each tick
        self._pending_road_rages = 0  # SPACE presses, likewise
        self._pending_respawns = 0
        self._pending_homes = 0
        self._homes_in_save = self.save_slot_file is not None
        self.homes_file = self.save_slot_file if self._homes_in_save else (
            homes_path(CONFIG_PATH) if getattr(args, "game_mode", "gig_driver") == "career" else None)
        self._home = load_home(self.homes_file, str(self.chosen_city or ""), in_save=self._homes_in_save) if self.homes_file else None
        self._home_confirm_s = 0.0  # a second H within this: the new yard becomes home
        self._prepared_home = None  # the home whose map was last handed to the background preparation
        self._home_preparation = None  # its future (cancelled if home moves before it starts)
        self._pending_cancels = 0
        self._pending_trip_resets = 0
        self._road_rage = None  # the active shout: {"text", "timer"}
        self._debug_snapshots: list = []  # F12: JSON paths to write on the next tick
        self._phone_requests: list = []  # edge-triggered like interacts: each one is applied once

        self._clients_lock = threading.Lock()
        self._clients: list = []
        self._client_views = {}  # connection -> (last simulation time, world camera bounds)
        # Per connection: the map chunks it has, and the player cell they were planned for.
        progress("lights", f"{len(self.world.ways)} roads")
        self.world.street_light_points = place_street_lights(self.world)  # before the chunks carry them
        # Build the index now, but encode only the nearby chunks a client asks
        # for. Some rural maps contain far-flung geometry in thousands of
        # irrelevant buckets; eagerly encoding all of them delayed startup.
        progress("chunks", f"{len(self.world.buildings)} buildings; {len(self.world.street_light_points)} lights")
        self._chunks_index = ChunkIndex(self.world)
        self._camera_spawner = SpeedCameraSpawner()
        self._client_chunks: dict = {}
        self._map_streamer = MapStreamer(self.world, self._map_grew) if self._auto_fetch else None
        # The tiles the chunk index was built with (None: the map never grows). A chunk
        # beyond them would reach the client half-built and be resent when its tile merges.
        self._indexed_tiles = set(self._map_streamer.manager.loaded_tiles) if self._map_streamer is not None else None
        self._map_growth: list = []  # the background rebuild's results, swapped in by ticks in order
        self._server_time = 0.0
        self._game_day_notice_shown = False

        self._listener: Optional[Listener] = None
        self._running = False

    def _raining_last_hour(self) -> list:
        if self.weather_history is None:
            return []
        return raining_last_hour(self.weather_history, self.calendar.current,
                                 lambda moment: typical_temperature(moment, self._weather_latitude), self.chosen_city)

    def _forecast(self) -> list:
        """The start-screen forecast: now and every 6 h for 24 h - the
        temperature (observed/forecast, else typical), the weather (FMI's
        precipitation where known, else the generator's prediction) and
        where it came from."""
        first_hour = self.calendar.current.replace(minute=0, second=0, microsecond=0)
        moments = [first_hour + timedelta(hours=offset) for offset in range(0, 25, 6)]
        history = self.weather_history
        observed = [history.get(moment) if history is not None else None for moment in moments]
        temperatures = [o.temperature_c if o is not None and o.temperature_c is not None
                        else typical_temperature(moment, self._weather_latitude) for moment, o in zip(moments, observed)]
        conditions = self.world.weather.forecast(temperatures, 6.0 * 60.0 * 60.0)
        lines = []
        for moment, temperature, (condition, thunder), seen in zip(moments, temperatures, conditions, observed):
            kind, seen_thunder = precipitation_from_observation(seen) if seen is not None else (None, False)
            if kind is not None:
                condition = weather_type_for_observation(kind, temperature)
                thunder = seen_thunder and condition.value == "rain"
            source = seen.source if seen is not None else "generated"
            lines.append({"time": f"{moment:%d.%m. %H:%M}", "temperature_c": round(temperature, 1),
                          "weather": "thunderstorm" if thunder else condition.value, "source": source,
                          "wind_speed_mps": seen.wind_speed_mps if seen is not None else None,
                          "wind_from_deg": seen.wind_from_deg if seen is not None else None,
                          "snow_depth_cm": seen.snow_depth_cm if seen is not None else None})
            if source in ("observed", "forecast"):
                logger.info("FMI weather %s: %s", f"{moment:%d.%m. %H:%M}", source)
        return lines

    def _update_weather_location(self):
        """Follow the taxi's nearest municipality, including a restored position."""
        position = (self.car.x, self.car.y)
        previous = self._weather_check_position
        if previous is not None and math.hypot(position[0] - previous[0], position[1] - previous[1]) < 1000.0:
            return
        self._weather_check_position = position
        from ..taxi import municipality_points
        from ..geo import meters_to_latlon
        nearest = min((point for point in municipality_points() if point[4] is None),
                      key=lambda point: math.hypot(point[1] - position[0], point[2] - position[1]), default=None)
        if nearest is None:
            return
        city, x, y = nearest[:3]
        if self._weather_centre is not None:
            old_distance = math.hypot(self._weather_centre[0] - position[0], self._weather_centre[1] - position[1])
            new_distance = math.hypot(x - position[0], y - position[1])
            if city == self.weather_city or old_distance - new_distance < 2000.0:
                return  # avoid switching repeatedly along a nearest-centre boundary
        lat, lon = meters_to_latlon(x, y)
        if lat is None or lon is None:
            return
        self.weather_city, self._weather_centre = city, (x, y)
        self._weather_latitude = lat
        if self._historical_weather:
            self.weather_history = WeatherHistory(lat, lon, cache_path=Path(CACHE_DIR) / "weather_history.db")
        self._fallback_weather_hour = self._fallback_weather = None
        logger.info("Weather location: %s (%.3f, %.3f)", city, lat, lon)

    def _update_outside(self):
        """Gradually sampled FMI weather (None: generated) and temperature."""
        self._update_weather_location()
        moment, weather = self.calendar.current, self.world.weather
        fmi_moment = moment.replace(minute=0, second=0, microsecond=0)
        observed = None
        if self.weather_history is not None:
            previous_moment = fmi_moment - timedelta(hours=1)
            next_moment = fmi_moment + timedelta(hours=1)
            self.weather_history.request(previous_moment, fmi_moment + timedelta(hours=48))
            observed = gradual_weather(self.weather_history, moment, self.chosen_city)
            if observed is None or precipitation_from_observation(observed)[0] is None:
                if getattr(self, "_fallback_weather_hour", None) != fmi_moment:
                    self._fallback_weather_hour = fmi_moment
                    self._fallback_weather = self.weather_history.previous(fmi_moment)
                    if self._fallback_weather is not None:
                        hour, previous = self._fallback_weather
                        logger.warning("FMI precipitation unavailable for %s; using cached %s from %s UTC (%.1f h old)",
                                       fmi_moment.isoformat(), previous.source,
                                       datetime.fromtimestamp(hour * 3600, timezone.utc).isoformat(),
                                       game_time_to_utc_hour(fmi_moment) - hour)
                if self._fallback_weather is not None:
                    observed = self._fallback_weather[1]
        source = observed.source if observed is not None else "generated"
        if source in ("observed", "forecast") and source != getattr(weather, "weather_source", None):
            logger.info("FMI weather now %s: %s", f"{fmi_moment:%d.%m. %H:%M}", source)
        weather.weather_source = source
        weather.outside_temperature_c = (observed.temperature_c if observed is not None and observed.temperature_c is not None
                                         else typical_temperature(moment, self._weather_latitude))
        return observed

    def _tyre_mark(self, previous, throttle: float = 0.0) -> Optional[dict]:
        """Return this tick's transient tyre mark, or None.

        Hard surfaces retain only full-black braking skids. Soft ground and
        snowy roads retain their material-specific tracks while moving. The
        client keeps recent points in memory; render-cache files do not.
        """
        from ..calendar import Season
        from ..map_level import SURFACE_LEVEL
        from ..physics import (get_current_road_at_car, is_point_in_parking_lot, is_point_on_parking_space,
                               off_road_ground_kind, skidmark_intensity, skidmark_should_mark,
                               tire_tracks_include_front_wheels)

        car, world = self.car, self.world
        if self._on_foot or (car.x, car.y) == previous:
            return None
        on_surface = getattr(car, "map_level", SURFACE_LEVEL) == SURFACE_LEVEL
        surface_way = get_current_road_at_car(car, ways=world.ways, spatial_grid=world.spatial_grid, car_roads_only=False) \
            if on_surface else None
        snow = world.weather.road_snow_at(car.x, car.y) if surface_way is not None else 0.0
        if snow >= 0.1 and abs(car.speed) > 0.1:
            return {"kind": "snow", "intensity": round(min(1.0, snow / 3.0), 2), "front": True}
        ground = (
            off_road_ground_kind(car.x, car.y, scenery_grid=world.scenery_grid, frozen=getattr(world, "fields_frozen", False))
            if on_surface and surface_way is None
            and not is_point_on_parking_space(car.x, car.y, world.parking_spaces)
            and not is_point_in_parking_lot(car.x, car.y, scenery_grid=world.scenery_grid)
            else "hard"
        )
        soft = ground in ("soft", "sand")
        skidding = skidmark_should_mark(car.skid_amount, wetness=world.weather.wetness, hard_surface=not soft)
        if not soft and not car.braking:
            skidding = False  # hard surfaces keep only black braking marks, not gray slip trails
        if not (skidding or (soft and abs(car.speed) > 1.0)):
            return None
        # Skidding on a frozen field scratches the ice pale, never black.
        kind = ("snow" if self.calendar.season == Season.WINTER else "sand" if ground == "sand" else "dirt") if soft else "snow" if ground == "ice" else "rubber"
        intensity = skidmark_intensity(car.skid_amount) if soft and skidding else 1.0
        mark = {"kind": kind, "intensity": round(intensity, 2),
                "front": bool(tire_tracks_include_front_wheels(soft, skidding, getattr(car, "front_lockup", False)))}
        if ground == "sand" and kind == "sand":
            mark["spray"] = round(min(1.0, abs(car.speed) / 6.0), 2)
        if ground == "soft" and kind == "dirt" and throttle >= 0.7 and car.engine_on and car.fuel_l > 0 and not car.braking:
            mark["spray"] = round(min(1.0, throttle), 2)
        return mark

    @property
    def _game_time_seconds(self) -> float:
        """Seconds since local midnight on the calendar (not a clock of its own)."""
        return self.calendar.time_seconds

    def season_weights(self) -> list:
        """[winter, spring, summer, autumn] the client blends, at 0.05 steps;
        also sets world.fields_frozen (physics) from the same winter weight
        the client freezes the fields by, so look and grip agree."""
        look = self.calendar.seasonal_appearance  # continuous weights, for the client to blend
        observed = self.weather_history.get(self.calendar.current) if self.weather_history is not None else None
        if observed is not None and observed.snow_depth_cm is not None:  # FMI's measured snow, over the date's guess
            look = appearance_with_snow_depth(look, observed.snow_depth_cm)
        season = [round(w * 20.0) / 20.0 for w in (look.winter, look.spring, look.summer, look.autumn)]
        self.world.fields_frozen = season[0] >= FIELDS_FROZEN_WINTER_WEIGHT
        return season

    def _sun_altitude(self) -> float:
        return self._sun_position()[0]

    def _sun_position(self) -> tuple:
        """(altitude, azimuth) in degrees; the azimuth clockwise from the
        map's grid north (EPSG:3067 +y), which the client's 3D view uses."""
        latitude = getattr(self.world, "sun_latitude", self.calendar.latitude)
        longitude = getattr(self.world, "sun_longitude", 25.47)
        altitude, azimuth = solar_position_on(
            self.calendar.date, self.calendar.time_seconds, latitude, longitude,
            finnish_utc_offset_hours(self.calendar.current),
        )
        return altitude, grid_azimuth(azimuth, latitude, longitude)

    def _moon_position(self) -> tuple:
        latitude = getattr(self.world, "sun_latitude", self.calendar.latitude)
        longitude = getattr(self.world, "sun_longitude", 25.47)
        altitude, azimuth, illumination = moon_position_at(self.calendar.current, latitude, longitude)
        return altitude, grid_azimuth(azimuth, latitude, longitude), illumination

    def _update_sports(self) -> None:
        """What may be played on the sports fields (the pedestrians' sports
        activities): ice when the fields are frozen, soccer when the pitches
        are bare - and only when light: daylight, or the floodlights' hours.
        Also world.fields_frozen, for this tick's physics."""
        season = self.season_weights()
        lit = darkness_for_sun_altitude(self._sun_altitude()) < SPORTS_ICE_DARKNESS or sports_lights_hours(self.calendar.current)
        self.world.pedestrian_mgr.sports_ice_open = self.world.fields_frozen and lit
        # Soccer: no snow on the pitch at all (godot chunk_detail.gd draws its lines by the same weight).
        self.world.pedestrian_mgr.soccer_open = season[0] < SOCCER_SNOW_WEIGHT and lit
        weather = self.world.weather
        temperature = weather.outside_temperature_c
        self.world.pedestrian_mgr.tennis_open = (
            temperature is not None and temperature > 10 and weather.weather_type == "clear"
            and not weather.is_thunderstorm and weather.cloud_cover <= .6
            and self._sun_altitude() > 5 and season[0] < SOCCER_SNOW_WEIGHT and not self.world.fields_frozen)
        self.world.pedestrian_mgr.beach_open = (
            self.calendar.current.month in (6, 7, 8) and temperature is not None and temperature > 15.0
            and weather.weather_type == "clear" and not weather.is_thunderstorm
            and weather.cloud_cover <= 0.25 and self._sun_altitude() > 5.0 and not self.world.fields_frozen)


    def calendar_state(self) -> dict:
        """What a client needs of the calendar (state "calendar"): the date,
        how fast game time runs, and the Sun and Moon - computed here, never
        by the client, at the city's latitude and longitude."""
        altitude, azimuth = self._sun_position()
        moon_altitude, moon_azimuth, moon_illumination = self._moon_position()
        season = self.season_weights()
        arena_crowds = getattr(self.world, "arena_crowds", None)
        from ..holiday_events import holiday_events
        return {"date": self.calendar.date.isoformat(), "time_scale": self._time_scale,
                "season": season,
                "sun_altitude_deg": round(altitude, 2), "sun_azimuth_deg": round(azimuth, 2), "darkness": round(darkness_for_sun_altitude(altitude), 3),
                "moon_altitude_deg": round(moon_altitude, 2), "moon_azimuth_deg": round(moon_azimuth, 2),
                "moon_illumination": round(moon_illumination, 3),
                "sports_lights": sports_lights_hours(self.calendar.current),
                "holidays": holiday_events(self.calendar.current),
                "arena_lights": bool(arena_crowds and arena_crowds.lights_on(self.calendar.current)),
                "arena_games": [[round(x, 1), round(y, 1)] for x, y in arena_crowds.games_in_progress(self.calendar.current)]
                if arena_crowds else []}

    def start(self, host: str, port: int) -> None:
        self._listener = Listener(host, port, self._on_client_connect)
        self.host, self.port = self._listener.host, self._listener.port
        logger.info("Simulation server listening on %s:%d", self.host, self.port)
        self._running = True

    def close(self) -> None:
        """Stop listening and drop every client (tests; an embedding host).
        The process exit does this for the standalone server."""
        self._running = False
        self.navigation.close()
        if self._listener is not None:
            self._listener.close()
        with self._clients_lock:
            clients, self._clients = list(self._clients), []
        for connection in clients:
            connection.close()

    def _place_name(self) -> str:
        """The start sign's name: the catalog city, or for a custom start
        (--bbox) the nearest town/village on the loaded map."""
        if getattr(self.args, "bbox", None):
            if getattr(self.args, "place_name", None):  # the map picker's reverse geocode
                return self.args.place_name
            towns = [p for p in self.world.places if p.kind in ("city", "town", "village")]
            if towns:
                return min(towns, key=lambda p: (p.x - self.car.x) ** 2 + (p.y - self.car.y) ** 2).name
        return str(self.chosen_city or "")

    def _set_fares_open(self, open_: bool) -> None:
        taxi_mgr = self.world.taxi_mgr
        taxi_mgr.fares_open = open_
        bookings = getattr(taxi_mgr, "rail_bookings", None)
        if bookings is not None:
            bookings.enabled = open_
            bookings.min_gap_s = 30.0
        if open_:  # the first request a little after the start, not in the same instant
            taxi_mgr.next_offer_timer = min(taxi_mgr.next_offer_timer, 5.0)

    def _on_client_connect(self, connection) -> None:
        logger.info("Client connected")
        # Who it is and the map origin first; the map chunks around the
        # player and every tick's state follow from the tick loop.
        message = protocol.build_world_message((self.car.x, self.car.y), CHUNK_SIZE_M, LOCAL_PLAYER_ID,
                                               self._place_name(), self._forecast())
        message["weather_city"] = self.weather_city
        connection.send(message)
        with self._clients_lock:
            self._client_chunks[connection] = (set(), None)
            self._clients.append(connection)
        if not self._fares_opened:  # the game has started: fares and pre-bookings from now on
            self._fares_opened = True
            self._set_fares_open(True)
        if not self._game_day_notice_shown:
            games = [game for game in self.world.arena_crowds.schedule_on(self.calendar.date)
                     if self.calendar.current < game.start + GAME_DURATION]
            if games:
                schedule = "; ".join(
                    f"{game.home_team}–{game.away_team} {game.start:%H:%M} ({game.venue_name})"
                    for game in games
                )
                self._notify(tr(self.language, "game_day_schedule", schedule=schedule), 10.0)
            self._game_day_notice_shown = True

    def _apply_incoming_messages(self) -> None:
        with self._clients_lock:
            clients = list(self._clients)
        for connection in clients:
            for message in connection.try_recv_all():
                if message.get("type") != "command":
                    continue
                if protocol.command_player_id(message) != LOCAL_PLAYER_ID:
                    logger.warning("Ignoring a command for unknown player %r", message.get("player_id"))
                    continue
                command, interact = protocol.command_from_message(message)
                from ..viewport import client_view_bounds
                view = client_view_bounds(message)
                if view is not None and max(abs((view[0] + view[2]) / 2 - self.car.x),
                                            abs((view[1] + view[3]) / 2 - self.car.y)) <= 2000:
                    self._client_views[connection] = (self._server_time, view)
                phone = protocol.phone_request_from_message(message)
                requested_language = message.get("command", {}).get("language") if isinstance(message.get("command"), dict) else None
                if isinstance(requested_language, str) and requested_language in SUPPORTED_LANGUAGES and requested_language != self.language:
                    self.language = requested_language
                    self.world.taxi_mgr.set_language(requested_language)
                with self._command_lock:
                    self._latest_command = replace(command, refuel=False, road_rage=False, respawn=False, home=False,
                                                   cancel_ride=False, reset_trip=False)  # the held part only
                    if interact:
                        self._pending_interacts += 1
                    if command.refuel:
                        self._pending_refuels += 1
                    if command.road_rage:
                        self._pending_road_rages += 1
                    if command.respawn:
                        self._pending_respawns += 1
                    if command.home:
                        self._pending_homes += 1
                    if command.cancel_ride:
                        self._pending_cancels += 1
                    if command.reset_trip:
                        self._pending_trip_resets += 1
                    if phone is not None:
                        self._phone_requests.append(phone)
                    if message.get("clear_home") is True:
                        self._clear_home()
                    if message.get("save_game") is True:  # the pause menu's Save / Quit
                        self._pending_save = True
                    snapshot = message.get("debug_snapshot")  # F12 in the client: the screenshot's JSON
                    if isinstance(snapshot, str) and snapshot.endswith(".json"):
                        self._debug_snapshots.append(snapshot)
        with self._clients_lock:
            before = len(self._clients)
            self._clients = [c for c in self._clients if not c.is_closed]
            for connection in [c for c in self._client_chunks if c.is_closed]:
                if connection.error is not None:
                    logger.info("Client dropped: %s", connection.error)
                del self._client_chunks[connection]
                self._client_views.pop(connection, None)
            gone = len(self._clients) != before
            if gone:
                logger.info("Client disconnected (%d remaining)", len(self._clients))
        if gone:
            # A departed client's last input must not keep driving the taxi
            # (held throttle into a wall): back to no input.
            with self._command_lock:
                self._latest_command = PlayerCommand()

    def write_debug_snapshot(self, path: str) -> None:
        """The F12 JSON (debug_snapshot.py) for the
        client's screenshot, from the server's world; the client's view is
        the server's camera at its zoom."""
        from ..viewport import get_viewport_bounds
        from ..debug_snapshot import _write_debug_snapshot

        w = self.world
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            _write_debug_snapshot(
                path, self.car, w.taxi_mgr, w.auto_fetch_manager, self.args, self.bbox or w.auto_fetch_manager.get_bounds(),
                self._visible_bounds() or get_viewport_bounds(self._camx, self._camy, px_per_m=self._px_per_m, margin_m=30.0),
                self._camx, self._camy, self._px_per_m, self._current_way, w.ways, w.waters, w.buildings,
                w.sceneries, w.places, w.taxi_stops, w.traffic_lights, w.crossings, w.elements_count,
                w.traffic_mgr, w.pedestrian_mgr, w.spatial_grid, 0, self.chosen_city,
                getattr(self, "camera_city_name", self.chosen_city), getattr(self.args, "game_mode", "gig_driver"),
                self._on_foot, scenery_objects=w.scenery_objects, speed_bumps=w.speed_bumps, railways=w.railways,
                railings=w.railings, npcs=w.npcs, npc_drivers=w.npc_drivers, npc_manager=w.npc_manager,
            )
            logger.info("Debug snapshot %s", path)
        except Exception:  # a debugging aid: never take the game down
            logger.exception("Debug snapshot %s failed", path)

    def save_game(self) -> bool:
        """Write the gig save slot (False without one, e.g. career)."""
        if self.save_slot_file is None:
            return False
        from ..geo import meters_to_latlon
        from ..save_slots import write_slot
        latitude, longitude = meters_to_latlon(self.car.x, self.car.y)
        if latitude is None:
            logger.warning("Save slot not written: no coordinate conversion")
            return False
        write_slot(self.save_slot_file, car=self.car, taxi_mgr=self.world.taxi_mgr, calendar=self.calendar,
                   city=self.chosen_city, place_name=getattr(self.args, "place_name", None) or "",
                   latlon=(latitude, longitude))
        logger.info("Saved to slot %s", self.save_slot_file.stem)
        return True

    def tick(self, dt: float) -> None:
        while self._debug_snapshots:
            self.write_debug_snapshot(self._debug_snapshots.pop(0))
        if self._pending_save:
            self._pending_save = False
            if self.save_game():
                self.save_count += 1
        self._apply_incoming_messages()
        self.audio.advance(dt)

        with self._command_lock:
            command = self._latest_command
            interact = self._pending_interacts > 0
            if interact:
                self._pending_interacts -= 1
            if self._pending_refuels > 0:
                self._pending_refuels -= 1
                command = replace(command, refuel=True)
            if self._pending_road_rages > 0:
                self._pending_road_rages -= 1
                command = replace(command, road_rage=True)
            respawn = self._pending_respawns > 0
            home = self._pending_homes > 0
            self._pending_homes -= int(home)
            cancel_ride = self._pending_cancels > 0
            reset_trip_meter = self._pending_trip_resets > 0
            self._pending_respawns -= int(respawn)
            self._pending_cancels -= int(cancel_ride)
            self._pending_trip_resets -= int(reset_trip_meter)

        with self._command_lock:
            phone_requests, self._phone_requests = self._phone_requests, []
        phone_results = [self._apply_phone_request(request) for request in phone_requests]

        if interact:
            command = replace(command, engine_on=None)
            self._on_foot = apply_enter_exit_vehicle(
                self.car, self.world.player_pedestrian, self._on_foot, self.audio, self.world.taxi_mgr,
                self.world.pedestrian_mgr.pedestrians,
            )

        self.car.lane_assist_enabled = command.lane_assist_enabled
        if respawn and not self._on_foot:
            respawn_car(self.car, self.world.ways, waters=self.world.waters, taxi_stops=self.world.taxi_stops)
            self.world.taxi_mgr.handle_respawn(self.car.x, self.car.y)
            self._camx, self._camy = self.car.x, self.car.y
        self._home_confirm_s = max(0.0, self._home_confirm_s - dt)
        if home:
            self._home_pressed()
        if cancel_ride:
            self.world.taxi_mgr.discard_mission(self.car.x, self.car.y)
        if reset_trip_meter:
            reset_trip(self.car)

        # Game time runs 60x while there is no fare, 1:1 during one.
        time_scale = self._time_scale = 1.0 if self.world.taxi_mgr.has_active_job() else 60.0
        previous_date = self.calendar.date
        self.calendar.advance(dt * time_scale)
        if self.calendar.date != previous_date:
            self.world.weather.season = self.calendar.season  # the thermal season follows the calendar
        observed = self._update_outside()
        self.world.weather.update(dt * time_scale, dt, outside_temperature_c=self.world.weather.outside_temperature_c,
                                  observed=observed)
        self._update_sports()
        if self.world.weather.lightning_event_id != self._lightning_event_id:  # a strike: thunder, once
            self.audio.play_group("weather.thunder", 0.8)
            self._lightning_event_id = self.world.weather.lightning_event_id

        car_x, car_y = self.car.x, self.car.y
        result = advance_simulation(
            dt, command, self.car, self.world,
            on_foot=self._on_foot,
            player_pedestrian=self.world.player_pedestrian,
            camx=self._camx, camy=self._camy, px_per_m=self._px_per_m,
            current_way=self._current_way,
            game_time_seconds=self._game_time_seconds,
            speed_limiter_enabled=command.speed_limiter_enabled,
            red_light_assist_enabled=command.red_light_assist_enabled,
            npc_follow=False,
            screen_w=SCREEN_W, screen_h=SCREEN_H,
            physics_mode=self.physics_mode,
            weather=self.world.weather,
            bridge_edge_crash_cooldown=self._bridge_edge_crash_cooldown,
            rage_power=self._rage_power,
            water_elapsed=self._water_elapsed,
            language=self.language,
            audio=self.audio,
            frame_profiler=_NullFrameProfiler.INSTANCE,
            slow_check_elapsed=self._slow_check_elapsed,
            taxi_waiter_elapsed=self._taxi_waiter_elapsed,
            saved_gig_fares=self._saved_gig_fares,
            career=self.career,
            career_file=self.career_file,
            gig_odometer_file=self.gig_odometer_file,
            chosen_city=self.chosen_city,
            cities_list=self.cities_list,
            outside_temperature_c=self.world.weather.outside_temperature_c,
            now=self.calendar.current,
            view_bounds=self._visible_bounds(),
        )
        self._tire_mark = self._tyre_mark(previous=(car_x, car_y), throttle=command.throttle)
        for npc in self.world.npc_manager.vehicles:  # brake lamps
            npc.braking = npc_braking(npc, getattr(npc, "_last_speed", npc.speed), dt)
            npc._last_speed = npc.speed
        if self._road_rage is not None:  # the shout counts down in real time
            timer = max(0.0, self._road_rage["timer"] - dt)
            self._road_rage = {"text": self._road_rage["text"], "timer": round(timer, 3)} if timer > 0.0 else None
        if result.rage_shout:
            self._road_rage = {"text": result.rage_shout, "timer": RAGE_SHOUT_DURATION_S}
        self._camx, self._camy = result.camx, result.camy
        self._current_way = result.current_way
        self._bridge_edge_crash_cooldown = result.bridge_edge_crash_cooldown
        self._rage_power = result.rage_power
        self._water_elapsed = result.water_elapsed
        self._slow_check_elapsed = result.slow_check_elapsed
        self._taxi_waiter_elapsed = result.taxi_waiter_elapsed
        self._saved_gig_fares = result.saved_gig_fares
        self._tick += 1
        self._server_time += dt

        events = phone_results + self.audio.take_events()
        railway_mgr = getattr(self.world, "railway_mgr", None)
        if railway_mgr is not None:
            for kind, x, y, train, stop in railway_mgr.sound_events:
                if stop is not None:  # the station's announcement, from its platform
                    platform = stop[5] if len(stop) > 5 and stop[5] is not None else (x, y)
                    announcement = self.announcer.event(kind, train, stop, platform, (self.car.x, self.car.y))
                    if announcement is not None:
                        events.append(announcement)
                events.append({
                    "type": f"train_{kind}", "at": [x, y], "station": stop[2] if stop else None,
                    "train": f"{train.service.train_type} {train.service.number}" if train.service else None,
                })
            railway_mgr.sound_events.clear()
        if self._map_growth:
            self._apply_map_growth()
        if self._map_streamer is not None:  # auto-fetch near the edge, then map sync
            self._map_streamer.tick(self.car.x, self.car.y, math.cos(self.car.heading) * self.car.speed,
                                    math.sin(self.car.heading) * self.car.speed, urgent=not self.central_chunk_ready())
        self._prepare_home_map()
        self._update_speed_cameras(dt)
        self._stream_map_chunks()
        self.navigation.update(self.world, self.car, self._current_way)
        self._broadcast_state(should_stop=result.should_stop, city_summary=result.city_summary, events=events)

    def _update_speed_cameras(self, dt: float) -> None:
        # Do not mutate an index while map growth is copying/replacing it.
        if self._map_streamer is not None and self._map_streamer.hold:
            return
        camera = self._camera_spawner.update(dt, self.car, self.world.spatial_grid, self.world.speed_cameras)
        if camera is None:
            return
        cid = self._chunks_index.add_speed_camera(camera, len(self.world.speed_cameras) - 1)
        with self._clients_lock:
            for connection, (loaded, _) in list(self._client_chunks.items()):
                if cid in loaded:
                    connection.send(self._chunks_index.encoded(cid))

    def _prepare_home_map(self) -> None:
        """Once per home, while the map is idle: warm the cache for the area
        an H jump will load (AutoFetchManager.prepare_window). Optional - a
        failure only means the jump loads it then."""
        streamer = self._map_streamer
        if streamer is None or self._home is None or self._prepared_home == self._home[:2] or streamer.status():
            return
        if self._home_preparation is not None:
            self._home_preparation.cancel()  # an older home's, not started yet: no longer wanted
        self._prepared_home = self._home[:2]
        try:
            self._home_preparation = streamer.manager.prepare_window(*self._home[:2])
        except Exception:
            logger.exception("Home map preparation failed to start")
            self._home_preparation = None

    def central_chunk_ready(self) -> bool:
        """Whether the map chunk under the player has roads - what the client
        needs first; False right after a jump into an unloaded area."""
        player = self.world.player_pedestrian if self._on_foot else self.car
        chunk = self._chunks_index._chunks.get(chunk_id(*cell_of(player.x, player.y)))
        return bool(chunk and chunk.get("roads"))

    def _clear_home(self) -> None:
        if self.homes_file is not None:
            clear_homes(self.homes_file, in_save=self._homes_in_save)
        self._home = None
        self._home_confirm_s = 0.0
        self._prepared_home = None
        if self._home_preparation is not None:
            self._home_preparation.cancel()
            self._home_preparation = None

    def _home_pressed(self) -> None:
        """H: in a house yard, make it home (a new one asks first: H
        again); anywhere else, the taxi respawns at home."""
        from ..physics import get_current_road_at_car

        car, w, language = self.car, self.world, self.language
        if self._on_foot:
            return self._notify(tr(language, "home_on_foot"))
        way = get_current_road_at_car(car, ways=w.ways, spatial_grid=w.spatial_grid, car_roads_only=False)
        in_yard = at_house_yard(car.x, car.y, way, w.parking_spaces, getattr(w, "building_grid", None))
        if in_yard and not is_same_home(self._home, car.x, car.y):
            if abs(car.speed) > 0.5:
                return self._notify(tr(language, "home_stop"))
            if self._home is not None and self._home_confirm_s <= 0.0:
                self._home_confirm_s = CONFIRM_S
                return self._notify(tr(language, "home_confirm"), CONFIRM_S)
            self._home, self._home_confirm_s = (car.x, car.y, car.heading), 0.0
            if self.homes_file is not None:
                save_home(self.homes_file, str(self.chosen_city or ""), self._home, in_save=self._homes_in_save)
            return self._notify(tr(language, "home_saved"))
        if self._home is None:
            return self._notify(tr(language, "home_not_yard"))
        respawn_car(car, w.ways, waters=w.waters, taxi_stops=w.taxi_stops)  # the usual respawn's resets (fuel, engine)
        car.x, car.y, car.heading = self._home
        car.speed, car.layer, car.map_level = 0.0, 0, 0
        self._notify(tr(language, "home_arrived"))  # a lost fare's notice (handle_respawn) wins
        w.taxi_mgr.handle_respawn(car.x, car.y)
        self._camx, self._camy = car.x, car.y

    def _notify(self, message: str, seconds: float = 3.0) -> None:
        self.world.taxi_mgr.notification_msg, self.world.taxi_mgr.notification_timer = message, seconds

    def _apply_phone_request(self, request: dict) -> dict:
        """Accept or reject a phone row by id through the taxi manager - and say how it went."""
        taxi_mgr = self.world.taxi_mgr
        index = taxi_mgr.phone_item_index(request["item_id"])
        ok, reason = False, "gone"  # expired, taken or declined meanwhile
        if index is not None and getattr(taxi_mgr.phone_items()[index][1], "status", "PENDING") != "PENDING":
            index, reason = None, "refused"  # an accepted booking can't be answered again (reject_offer(0) would pick another)
        if index is not None:
            if request["action"] == "accept":
                ok = taxi_mgr.accept_offer(index, self.car.x, self.car.y)
            else:
                ok = taxi_mgr.reject_offer(index, self.car.x, self.car.y)
            reason = "" if ok else "refused"
        if ok:
            self.audio.play_group("ui.accept" if request["action"] == "accept" else "ui.reject", 0.6)
        return {"type": "phone_result", "action": request["action"], "item_id": request["item_id"],
                "request_id": request["request_id"], "ok": ok, "reason": reason}

    def _map_grew(self, old_bounds, new_bounds, dirty=None) -> None:
        """A map sync finished: light the new roads and rebuild the chunks the
        merges changed (`dirty`, metres; ChunkIndex.updated - the rest are
        kept) in the background, the streamer holding further merges
        meanwhile so the world stays as synced; _apply_map_growth swaps them
        in on a later tick. The chunks around the player come first, as their
        own result (after a Home jump: the destination drawn seconds before
        the rest of the area is rebuilt)."""
        covered = set(self._map_streamer.sync_tiles)

        def build():
            started = time.perf_counter()
            index, previous = self._chunks_index, self.world.street_light_points
            if dirty is None:
                self._map_growth.append((previous, index, set(), old_bounds, new_bounds, 0.0, True, covered))
                return
            margin = CHANGED_AREA_MARGIN_M
            area = (dirty[0] - margin, dirty[1] - margin, dirty[2] + margin, dirty[3] + margin)
            ix, iy = cell_of(self.car.x, self.car.y)
            near = (max(area[0], (ix - 1) * CHUNK_SIZE_M), max(area[1], (iy - 1) * CHUNK_SIZE_M),
                    min(area[2], (ix + 2) * CHUNK_SIZE_M), min(area[3], (iy + 2) * CHUNK_SIZE_M))

            def encode_in_reach(index, changed):
                # What the next ticks send (resends, the new tiles' chunks) is encoded
                # here rather than in a tick: 2-20 ms a chunk.
                for cid in changed:
                    cx, cy = (int(part) for part in cid.split("_"))
                    if max(abs(cx - ix), abs(cy - iy)) <= LOAD_RADIUS:
                        index.encoded(cid)

            if near[0] < near[2] and near[1] < near[3]:
                # The player's 3x3 chunks changed: those first, with the street
                # lights known so far (after a Home jump the destination is drawn
                # a second or more sooner; its new lamps come with the next pass).
                index, changed = ChunkIndex.updated(index, self.world, near)
                encode_in_reach(index, changed)
                self._map_growth.append((previous, index, changed, old_bounds, new_bounds,
                                         time.perf_counter() - started, False, covered))
            lights_started = time.perf_counter()
            # A merged tile can fill a hole inside old_bounds, not just extend it.
            # Rebuild its dirty area, retaining lamps elsewhere unchanged.
            lights = [lamp for lamp in previous
                      if not (area[0] <= lamp[0] <= area[2] and area[1] <= lamp[1] <= area[3])]
            lights.extend(place_street_lights(self.world, region=area))
            lights_s = time.perf_counter() - lights_started
            self.world.street_light_points = lights
            try:
                index, changed = ChunkIndex.updated(index, self.world, area)
            finally:
                self.world.street_light_points = previous  # the tick's own until the swap
            encode_in_reach(index, changed)
            self._map_growth.append((lights, index, changed, old_bounds, new_bounds, time.perf_counter() - started, True,
                                     covered))
            logger.info("Map chunks rebuilt for %.0f x %.0f m (lights %.0f ms)", area[2] - area[0], area[3] - area[1],
                        lights_s * 1000.0)

        self._map_streamer.hold = True
        threading.Thread(target=build, name="map-growth", daemon=True).start()

    def _apply_map_growth(self) -> None:
        """Swap in the grown map's lamps and chunks (the next result of the
        background rebuild); resend every chunk a client has whose content
        changed (new roads across the old edge, lamps, buildings...)."""
        lights, index, changed, old_bounds, new_bounds, build_s, final, covered = self._map_growth.pop(0)
        self._chunks_index = index
        self.world.street_light_points = lights
        self._map_streamer.hold = not final
        if final and self._indexed_tiles is not None:
            self._indexed_tiles = covered
        player = self.world.player_pedestrian if self._on_foot else self.car
        px, py = cell_of(player.x, player.y)

        def distance(cid: str) -> int:
            ix, iy = (int(part) for part in cid.split("_"))
            return max(abs(ix - px), abs(iy - py))

        with self._clients_lock:
            for connection, (loaded, _) in list(self._client_chunks.items()):
                # Nearest first; a resent chunk replaces the client's copy as it is drawn (no unload, no hole).
                for cid in sorted(loaded & changed, key=distance):
                    connection.send(self._chunks_index.encoded(cid))
                self._client_chunks[connection] = (loaded, None)  # replan: the new area may be in reach
        logger.info("Map grew %s -> %s: %d chunks changed%s, built in %.0f ms", old_bounds, new_bounds, len(changed),
                    "" if final else " around the player", build_s * 1000.0)

    def _stream_map_chunks(self) -> None:
        """Each client gets the map chunks around the player it doesn't have
        yet and is told to drop far ones - replanned when the player enters
        another chunk and after every map growth. Beyond the player's own 3x3
        a chunk waits until the chunk index has its tile (_indexed_tiles);
        the player's own are sent at once (after a Home jump the destination
        is drawn as it arrives)."""
        with self._clients_lock:
            clients = list(self._clients)
        if not clients:
            return
        player = self.world.player_pedestrian if self._on_foot else self.car
        cell = cell_of(player.x, player.y)
        indexed = self._indexed_tiles
        for connection in clients:
            loaded, planned_for = self._client_chunks.get(connection, (set(), None))
            if planned_for == cell:
                continue
            to_load, to_drop = plan(loaded, cell)
            for cid in to_drop:
                connection.send({"type": "chunk_unload", "version": protocol.PROTOCOL_VERSION, "chunk_id": cid})
                loaded.discard(cid)
            for cid in to_load:
                ix, iy = (int(part) for part in cid.split("_"))
                if indexed is not None and max(abs(ix - cell[0]), abs(iy - cell[1])) > 1 \
                        and world_to_tile((ix + 0.5) * CHUNK_SIZE_M, (iy + 0.5) * CHUNK_SIZE_M) not in indexed:
                    continue
                connection.send(self._chunks_index.encoded(cid))
                loaded.add(cid)
            self._client_chunks[connection] = (loaded, cell)

    def _visible_bounds(self):
        views = [bounds for connection, (at, bounds) in self._client_views.items()
                 if not connection.is_closed and self._server_time - at <= 2.0]
        if not views:
            return None  # legacy clients and headless tests retain the nominal viewport
        return (min(v[0] for v in views), min(v[1] for v in views),
                max(v[2] for v in views), max(v[3] for v in views))

    def _broadcast_state(self, *, should_stop: bool = False, city_summary=None, events=None) -> None:
        message = protocol.build_state_message(
            tick=self._tick, world=self.world, car=self.car, on_foot=self._on_foot,
            player_pedestrian=self.world.player_pedestrian, game_time_seconds=self._game_time_seconds,
            camx=self._camx, camy=self._camy,
            rage_power=self._rage_power, water_elapsed=self._water_elapsed,
            should_stop=should_stop, city_summary=city_summary, events=events,
            server_time=self._server_time,
            current_way=self._current_way, language=self.language, calendar=self.calendar_state(), tire_mark=self._tire_mark,
            navigation={"points": self.navigation.points, "instruction": self.navigation.instruction}, road_rage=self._road_rage,
            map_loading=self._map_streamer.status() if self._map_streamer is not None else "",
            map_loading_detail=self._map_streamer.manager.get_progress_message() if self._map_streamer is not None else "",
            railway=protocol.railway_state(getattr(self.world, "railway_mgr", None), self.car.x, self.car.y, self.calendar.current),
        )
        message["state"]["save_count"] = self.save_count  # the pause menu waits for its save
        with self._clients_lock:
            clients = list(self._clients)
        for connection in clients:
            connection.send_state(message)  # never waits: a behind client gets the newest state

    def run_forever(self) -> None:
        """Blocking tick loop - the body of `python -m theroadragetrip.server`."""
        interval = 1.0 / self.tick_rate
        next_tick = time.monotonic()
        while True:
            self.tick(interval)
            next_tick += interval
            sleep_for = next_tick - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)
            else:
                next_tick = time.monotonic()  # fell behind; don't try to catch up in a burst


def place_street_lights(world, region=None) -> list:
    """Street lights for the whole map or a changed world-metre rectangle.

    Keep surrounding roads/buildings as placement context, including when
    a streamed tile fills a previously unloaded hole inside the map bounds.
    Uses street_lights.py:
    explicit OSM lamps first, then lit roads at fixed spacing, clear of
    junctions and buildings (Oulu: ~21,500 lights, ~1.7 s at startup).
    [(x, y, road direction, pool radius m)]."""
    from .. import street_lights as roads

    bounded = region is not None
    ways = world.ways
    if region is None:
        points = [p for way in ways for p in way.points_m]
        if not points:
            return []
        region = (min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points))
    work = roads._snapshot_street_light_job(
        "server", region, ways, getattr(world, "spatial_grid", None) if bounded else None,
        world.buildings, getattr(world, "building_grid", None) if bounded else None,
        getattr(world, "street_lamps", None), getattr(world, "street_lamp_grid", None),
        getattr(world, "parking_spaces", None),
    )
    while not roads._advance_street_light_prep(work):
        pass
    while not roads._advance_street_light_placement(work):
        pass
    lamps = list(work["lamps"])
    # Parking lots with mapped spots: the poles stand where two back-to-back
    # rows meet, at the spots' shared corners; the aisle-guessed lamps around
    # them go. Lots without mapped spots keep the aisle placement.
    spaces = work["parking_spaces"] if bounded else (getattr(world, "parking_spaces", None) or [])
    poles = roads.parking_row_lamps(spaces)
    if poles:
        near_pole = roads.PARKING_POLE_CLEARANCE_M ** 2
        cell = roads.PARKING_LIGHT_SPACING_M
        grid: dict = {}
        for pole in poles:
            grid.setdefault((math.floor(pole[0] / cell), math.floor(pole[1] / cell)), []).append(pole)

        def by_a_pole(x, y):
            cx, cy = math.floor(x / cell), math.floor(y / cell)
            return any((x - p[0]) ** 2 + (y - p[1]) ** 2 < near_pole
                       for gx in (cx - 1, cx, cx + 1) for gy in (cy - 1, cy, cy + 1) for p in grid.get((gx, gy), ()))
        lamps = [lamp for lamp in lamps if not by_a_pole(lamp[0], lamp[1])] + poles
    if bounded:
        lamps = [lamp for lamp in lamps if region[0] <= lamp[0] <= region[2] and region[1] <= lamp[1] <= region[3]]
    return lamps


class _NullFrameProfiler:
    """No-op stand-in: the server has no debug HUD to feed."""

    def section(self, _name):
        return nullcontext()

    def set_metric(self, *_args, **_kwargs):
        pass


_NullFrameProfiler.INSTANCE = _NullFrameProfiler()


def run_server(args, config) -> SimulationServer:
    from .startup_progress import StartupProgress

    progress = StartupProgress(getattr(args, "startup_progress", None))
    try:
        server = SimulationServer(args, config, startup_progress=progress)
        progress("connecting")
        server.start(args.host, args.port)
        progress("ready")
    except Exception as exc:
        progress("error", f"{type(exc).__name__}: {exc}")
        raise
    return server
