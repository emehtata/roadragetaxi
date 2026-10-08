"""The headless simulation server (client-server-02.md).

Owns the one authoritative `world`/`car`, runs `simulation.advance_simulation`
at a fixed rate, and publishes a state snapshot to every connected client
after each tick. Never opens a Pygame display - see
docs/architecture/simulation-rendering.md for the full boundary writeup,
including the one remaining (display-free) Pygame touchpoint here:
`pygame.time.Clock` for tick pacing.

Scope note: auto-fetch (live map expansion as the car nears the loaded
bbox's edge) is disabled in server mode for this phase - the map-sync/
tile-streaming pipeline still calls a loading-screen helper that assumes
a Pygame display, and replicating that headlessly is left to a later
pass. The server runs the same `advance_simulation` tick as the old
single-process game otherwise; see the architecture doc's "Known
limitations".
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace

import logging
import threading
import time
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Optional

import pygame

from .. import protocol
from ..navigation_route import NavigationRoute
from ..map_chunks import CHUNK_SIZE_M, ChunkIndex, cell_of, plan
from ..protocol import LOCAL_PLAYER_ID
from ..calendar import GameCalendar, darkness_for_sun_altitude, solar_altitude_and_events_on
from ..career import career_path, gig_odometer_path, load_career
from ..config import CONFIG_PATH, cities_from_config, default_city_configuration, get_overpass_endpoints
from ..main import _choose_city, _load_world
from ..render import SCREEN_H, SCREEN_W
from ..simulation import RAGE_SHOUT_DURATION_S, PlayerCommand, advance_simulation, apply_enter_exit_vehicle
from ..physics import reset_trip, respawn_car
from ..transport import Listener
from ..weather import WeatherSystem

logger = logging.getLogger(__name__)

# Nominal viewport used only for NPC/pedestrian spawn-despawn culling
# (advance_simulation's viewport_bounds) - the server has no real screen
# or zoom level, so it assumes the client's default zoom rather than
# tracking each connected client's actual one. See architecture doc.
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
        # Speech (godot-final-07): speech.py chooses as Pygame does; a line
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


class SimulationServer:
    def __init__(self, args, config, city_choice=None):
        """`city_choice` (a `_choose_city`-shaped SimpleNamespace) lets an
        embedding client that already ran its own interactive city menu
        hand the resolved choice straight to the server, instead of the
        server independently re-resolving one from raw CLI args - the two
        must never disagree about which city/bbox is being played. The
        standalone `python -m theroadragetrip.server` process (no client
        menu involved) resolves it here instead, CLI-driven, no menu."""
        self.args = args
        self.tick_rate = max(1.0, float(getattr(args, "tick_rate", 30.0)))
        self.audio = EventAudio()
        self.language = getattr(args, "language", None) or config.get("game", "language", fallback="") or "en"
        self.physics_mode = config.get("game", "physics_realism", fallback="arcade")
        self.career_file = career_path(CONFIG_PATH)
        self.gig_odometer_file = gig_odometer_path(CONFIG_PATH)

        overpass_endpoints = get_overpass_endpoints(config)
        bus_stops_enabled = config.getboolean("game", "bus_stops", fallback=False)
        roadworks_enabled = config.getboolean("game", "roadworks_enabled", fallback=False)
        args.auto_fetch = False  # see module docstring's scope note

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
                city_choice = _choose_city(
                    None, "gig_driver", city_centers, bbox_presets, self.career_file, None,
                    None, None, pygame.time.Clock(), config, self.language, args,
                    args.force_refresh, False,
                )
        self.chosen_city = city_choice.chosen_city
        self.cities_list = city_choice.cities_list
        self.career = city_choice.career

        self.world = _load_world(
            city_choice.chosen_city, city_choice.camera_city_name, city_choice.bbox,
            city_choice.city_centers, None, None, pygame.time.Clock(), args,
            city_choice.force_refresh, overpass_endpoints, bus_stops_enabled,
            roadworks_enabled, city_choice.career, self.career_file, self.gig_odometer_file,
            self.language, headless=True,
        )
        self.car = self.world.car
        # weather is per-session state main() constructs fresh alongside
        # `world` rather than something _load_world itself returns -
        # attached onto `world` here so protocol.py's state builder (which
        # reads world.weather, matching how it reads every other manager)
        # doesn't need a separate parameter for it.
        # The game's one calendar (godot-14), as main() keeps it: game time,
        # date and the weather's season follow from it. The server starts
        # today at 18:00, as it always has; Pygame's career default is
        # another date, chosen on its start screen.
        self.calendar = GameCalendar(datetime.combine(date.today(), datetime.min.time()) + timedelta(hours=18),
                                     latitude=getattr(self.world, "sun_latitude", 65.01))
        self.world.weather = WeatherSystem(season=self.calendar.season)

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
        self._pending_cancels = 0
        self._pending_trip_resets = 0
        self._road_rage = None  # the active shout: {"text", "timer"}
        self._phone_requests: list = []  # edge-triggered like interacts: each one is applied once

        self._clients_lock = threading.Lock()
        self._clients: list = []
        # Per connection: the map chunks it has, and the player cell they were planned for.
        self.world.street_light_points = place_street_lights(self.world)  # before the chunks carry them
        # Build the index now, but encode only the nearby chunks a client asks
        # for. Some rural maps contain far-flung geometry in thousands of
        # irrelevant buckets; eagerly encoding all of them delayed startup.
        self._chunks_index = ChunkIndex(self.world)
        self._client_chunks: dict = {}
        self._server_time = 0.0

        self._listener: Optional[Listener] = None
        self._running = False

    def _tyre_mark(self, previous) -> Optional[dict]:
        """Whether the taxi lays a tyre mark this tick, and which, decided as
        Pygame's main() decides it (SKIDMARK.md): rubber on a hard surface
        when the tyres slip enough, a dirt (sand, snow) trail off-road on
        soft ground whenever moving. None when nothing is laid. The client
        keeps the trail."""
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
        ground = (
            off_road_ground_kind(car.x, car.y, scenery_grid=world.scenery_grid)
            if on_surface and surface_way is None
            and not is_point_on_parking_space(car.x, car.y, world.parking_spaces)
            and not is_point_in_parking_lot(car.x, car.y, scenery_grid=world.scenery_grid)
            else "hard"
        )
        soft = ground in ("soft", "sand")
        skidding = skidmark_should_mark(car.skid_amount, wetness=world.weather.wetness, hard_surface=not soft)
        if not (skidding or (soft and abs(car.speed) > 1.0)):
            return None
        kind = ("snow" if self.calendar.season == Season.WINTER else "sand" if ground == "sand" else "dirt") if soft else "rubber"
        return {"kind": kind, "intensity": round(skidmark_intensity(car.skid_amount) if skidding else 1.0, 2),
                "front": bool(tire_tracks_include_front_wheels(soft, skidding, getattr(car, "front_lockup", False)))}

    @property
    def _game_time_seconds(self) -> float:
        """Seconds since local midnight on the calendar (not a clock of its own)."""
        return self.calendar.time_seconds

    def calendar_state(self) -> dict:
        """What a client needs of the calendar (state "calendar"): the date,
        how fast game time runs, and the sun - computed here, never by the
        client. The sun is at the city's latitude and longitude."""
        altitude, _, _ = solar_altitude_and_events_on(
            self.calendar.date, self.calendar.time_seconds,
            getattr(self.world, "sun_latitude", self.calendar.latitude), getattr(self.world, "sun_longitude", 25.47),
        )
        look = self.calendar.seasonal_appearance  # continuous weights, as Pygame's renderers blend them
        return {"date": self.calendar.date.isoformat(), "time_scale": self._time_scale,
                "season": [round(w * 20.0) / 20.0 for w in (look.winter, look.spring, look.summer, look.autumn)],
                "sun_altitude_deg": round(altitude, 2), "darkness": round(darkness_for_sun_altitude(altitude), 3)}

    def start(self, host: str, port: int) -> None:
        self._listener = Listener(host, port, self._on_client_connect)
        self.host, self.port = self._listener.host, self._listener.port
        logger.info("Simulation server listening on %s:%d", self.host, self.port)
        self._running = True

    def _on_client_connect(self, connection) -> None:
        logger.info("Client connected")
        # Who it is and the map origin first; the map chunks around the
        # player and every tick's state follow from the tick loop.
        connection.send(protocol.build_world_message((self.car.x, self.car.y), CHUNK_SIZE_M, LOCAL_PLAYER_ID))
        with self._clients_lock:
            self._client_chunks[connection] = (set(), None)
            self._clients.append(connection)

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
                phone = protocol.phone_request_from_message(message)
                with self._command_lock:
                    self._latest_command = replace(command, refuel=False, road_rage=False, respawn=False,
                                                   cancel_ride=False, reset_trip=False)  # the held part only
                    if interact:
                        self._pending_interacts += 1
                    if command.refuel:
                        self._pending_refuels += 1
                    if command.road_rage:
                        self._pending_road_rages += 1
                    if command.respawn:
                        self._pending_respawns += 1
                    if command.cancel_ride:
                        self._pending_cancels += 1
                    if command.reset_trip:
                        self._pending_trip_resets += 1
                    if phone is not None:
                        self._phone_requests.append(phone)
        with self._clients_lock:
            before = len(self._clients)
            self._clients = [c for c in self._clients if not c.is_closed]
            for connection in [c for c in self._client_chunks if c.is_closed]:
                if connection.error is not None:
                    logger.info("Client dropped: %s", connection.error)
                del self._client_chunks[connection]
            gone = len(self._clients) != before
            if gone:
                logger.info("Client disconnected (%d remaining)", len(self._clients))
        if gone:
            # A departed client's last input must not keep driving the taxi
            # (held throttle into a wall): back to no input.
            with self._command_lock:
                self._latest_command = PlayerCommand()

    def tick(self, dt: float) -> None:
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
            cancel_ride = self._pending_cancels > 0
            reset_trip_meter = self._pending_trip_resets > 0
            self._pending_respawns -= int(respawn)
            self._pending_cancels -= int(cancel_ride)
            self._pending_trip_resets -= int(reset_trip_meter)

        with self._command_lock:
            phone_requests, self._phone_requests = self._phone_requests, []
        phone_results = [self._apply_phone_request(request) for request in phone_requests]

        if interact:
            self._on_foot = apply_enter_exit_vehicle(
                self.car, self.world.player_pedestrian, self._on_foot, self.audio, self.world.taxi_mgr,
            )

        self.car.lane_assist_enabled = command.lane_assist_enabled
        if respawn and not self._on_foot:
            respawn_car(self.car, self.world.ways, waters=self.world.waters, taxi_stops=self.world.taxi_stops)
            self.world.taxi_mgr.handle_respawn(self.car.x, self.car.y)
            self._camx, self._camy = self.car.x, self.car.y
        if cancel_ride:
            self.world.taxi_mgr.discard_mission(self.car.x, self.car.y)
        if reset_trip_meter:
            reset_trip(self.car)

        # Game time runs 60x while there is no fare, 1:1 during one (main()).
        time_scale = self._time_scale = 1.0 if self.world.taxi_mgr.has_active_job() else 60.0
        previous_date = self.calendar.date
        self.calendar.advance(dt * time_scale)
        if self.calendar.date != previous_date:
            self.world.weather.season = self.calendar.season  # main()'s _sync_thermal_season
        self.world.weather.update(dt * time_scale, dt)
        if self.world.weather.lightning_event_id != self._lightning_event_id:  # a strike: thunder, once (as main())
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
            now=self.calendar.current,
        )
        self._tire_mark = self._tyre_mark(previous=(car_x, car_y))
        if self._road_rage is not None:  # main(): the shout counts down in real time
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
                if stop is not None:  # main()'s _play_rail_sounds: the station's announcement, from its platform
                    platform = stop[5] if len(stop) > 5 and stop[5] is not None else (x, y)
                    announcement = self.announcer.event(kind, train, stop, platform, (self.car.x, self.car.y))
                    if announcement is not None:
                        events.append(announcement)
                events.append({
                    "type": f"train_{kind}", "at": [x, y], "station": stop[2] if stop else None,
                    "train": f"{train.service.train_type} {train.service.number}" if train.service else None,
                })
            railway_mgr.sound_events.clear()
        self._stream_map_chunks()
        self.navigation.update(self.world, self.car, self._current_way)
        self._broadcast_state(should_stop=result.should_stop, city_summary=result.city_summary, events=events)

    def _apply_phone_request(self, request: dict) -> dict:
        """Accept or reject a phone row by id through the taxi manager - the
        same calls (and sounds) as the Pygame phone - and say how it went."""
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

    def _stream_map_chunks(self) -> None:
        """Each client gets the map chunks around the player it doesn't have
        yet and is told to drop far ones - replanned only when the player
        enters another chunk."""
        with self._clients_lock:
            clients = list(self._clients)
        if not clients:
            return
        player = self.world.player_pedestrian if self._on_foot else self.car
        cell = cell_of(player.x, player.y)
        for connection in clients:
            loaded, planned_for = self._client_chunks.get(connection, (set(), None))
            if planned_for == cell:
                continue
            to_load, to_drop = plan(loaded, cell)
            for cid in to_drop:
                connection.send({"type": "chunk_unload", "version": protocol.PROTOCOL_VERSION, "chunk_id": cid})
                loaded.discard(cid)
            for cid in to_load:
                connection.send(self._chunks_index.encoded(cid))
                loaded.add(cid)
            self._client_chunks[connection] = (loaded, cell)

    def _broadcast_state(self, *, should_stop: bool = False, city_summary=None, events=None) -> None:
        message = protocol.build_state_message(
            tick=self._tick, world=self.world, car=self.car, on_foot=self._on_foot,
            player_pedestrian=self.world.player_pedestrian, game_time_seconds=self._game_time_seconds,
            camx=self._camx, camy=self._camy,
            rage_power=self._rage_power, water_elapsed=self._water_elapsed,
            should_stop=should_stop, city_summary=city_summary, events=events,
            server_time=self._server_time,
            current_way=self._current_way, language=self.language, calendar=self.calendar_state(), tire_mark=self._tire_mark,
            navigation={"points": self.navigation.points}, road_rage=self._road_rage,
            railway=protocol.railway_state(getattr(self.world, "railway_mgr", None), self.car.x, self.car.y, self.calendar.current),
        )
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


def place_street_lights(world) -> list:
    """Every street light of the map, placed once with Pygame's own
    placement (render/roads.py: explicit OSM lamps first, then lit roads at
    fixed spacing, clear of junctions and buildings) - Pygame runs it per
    view region in frame-budgeted steps; here it runs to the end over the
    whole map (Oulu: ~21,500 lights, ~1.7 s at startup).
    [(x, y, road direction, pool radius m)]."""
    from ..render import roads

    points = [p for way in world.ways for p in way.points_m]
    if not points:
        return []
    region = (min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points))
    work = roads._snapshot_street_light_job(
        "server", region, world.ways, None, world.buildings, None,
        getattr(world, "street_lamps", None), getattr(world, "street_lamp_grid", None),
    )
    while not roads._advance_street_light_prep(work):
        pass
    while not roads._advance_street_light_placement(work):
        pass
    return list(work["lamps"])


class _NullFrameProfiler:
    """No-op stand-in: the server has no debug HUD to feed."""

    def section(self, _name):
        return nullcontext()

    def set_metric(self, *_args, **_kwargs):
        pass


_NullFrameProfiler.INSTANCE = _NullFrameProfiler()


def run_server(args, config) -> SimulationServer:
    server = SimulationServer(args, config)
    server.start(args.host, args.port)
    return server
