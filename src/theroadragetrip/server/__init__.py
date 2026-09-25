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

import logging
import threading
import time
from typing import Optional

import pygame

from .. import protocol
from ..career import career_path, gig_odometer_path
from ..config import CONFIG_PATH, cities_from_config, get_overpass_endpoints
from ..main import _choose_city, _load_world
from ..render import SCREEN_H, SCREEN_W
from ..simulation import PlayerCommand, advance_simulation, apply_enter_exit_vehicle
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
        self.audio = NullAudio()
        self.language = config.get("game", "language", fallback="") or "en"
        self.physics_mode = config.get("game", "physics_realism", fallback="arcade")
        self.career_file = career_path(CONFIG_PATH)
        self.gig_odometer_file = gig_odometer_path(CONFIG_PATH)

        overpass_endpoints = get_overpass_endpoints(config)
        bus_stops_enabled = config.getboolean("game", "bus_stops", fallback=False)
        roadworks_enabled = config.getboolean("game", "roadworks_enabled", fallback=False)
        args.auto_fetch = False  # see module docstring's scope note

        if city_choice is None:
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
        self.world.weather = WeatherSystem()

        self._on_foot = True
        self._camx, self._camy = self.car.x, self.car.y
        self._px_per_m = _DEFAULT_PX_PER_M
        self._current_way = None
        self._game_time_seconds = 18.0 * 60.0 * 60.0
        self._bridge_edge_crash_cooldown = 0.0
        self._rage_power = 0.0
        self._water_elapsed = 0.0
        self._slow_check_elapsed = 0.0
        self._taxi_waiter_elapsed = 0.0
        self._saved_gig_fares = self.world.taxi_mgr.completed_fares
        self._tick = 0

        self._command_lock = threading.Lock()
        self._latest_command = PlayerCommand()
        self._pending_interacts = 0

        self._clients_lock = threading.Lock()
        self._clients: list = []

        self._listener: Optional[Listener] = None
        self._running = False

    def start(self, host: str, port: int) -> None:
        self._listener = Listener(host, port, self._on_client_connect)
        self.host, self.port = self._listener.host, self._listener.port
        logger.info("Simulation server listening on %s:%d", self.host, self.port)
        self._running = True

    def _on_client_connect(self, connection) -> None:
        logger.info("Client connected")
        with self._clients_lock:
            self._clients.append(connection)

    def _apply_incoming_messages(self) -> None:
        with self._clients_lock:
            clients = list(self._clients)
        for connection in clients:
            for message in connection.try_recv_all():
                if message.get("type") != "command":
                    continue
                command, interact = protocol.command_from_message(message)
                with self._command_lock:
                    self._latest_command = command
                    if interact:
                        self._pending_interacts += 1
        with self._clients_lock:
            before = len(self._clients)
            self._clients = [c for c in self._clients if not c.is_closed]
            if len(self._clients) != before:
                logger.info("Client disconnected (%d remaining)", len(self._clients))

    def tick(self, dt: float) -> None:
        self._apply_incoming_messages()

        with self._command_lock:
            command = self._latest_command
            interact = self._pending_interacts > 0
            if interact:
                self._pending_interacts -= 1

        if interact:
            self._on_foot = apply_enter_exit_vehicle(
                self.car, self.world.player_pedestrian, self._on_foot, self.audio,
                self.world.taxi_mgr, self.world.pedestrian_mgr,
            )

        time_scale = 1.0 if self.world.taxi_mgr.current_passenger else 60.0
        self._game_time_seconds = (self._game_time_seconds + dt * time_scale) % (24.0 * 60.0 * 60.0)
        self.world.weather.update(dt * time_scale, dt)

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
        )
        self._camx, self._camy = result.camx, result.camy
        self._current_way = result.current_way
        self._bridge_edge_crash_cooldown = result.bridge_edge_crash_cooldown
        self._rage_power = result.rage_power
        self._water_elapsed = result.water_elapsed
        self._slow_check_elapsed = result.slow_check_elapsed
        self._taxi_waiter_elapsed = result.taxi_waiter_elapsed
        self._saved_gig_fares = result.saved_gig_fares
        self._tick += 1

        self._broadcast_state(should_stop=result.should_stop, city_summary=result.city_summary)

    def _broadcast_state(self, *, should_stop: bool = False, city_summary=None) -> None:
        message = protocol.build_state_message(
            tick=self._tick, world=self.world, car=self.car, on_foot=self._on_foot,
            player_pedestrian=self.world.player_pedestrian, game_time_seconds=self._game_time_seconds,
            camx=self._camx, camy=self._camy,
            rage_power=self._rage_power, water_elapsed=self._water_elapsed,
            should_stop=should_stop, city_summary=city_summary,
        )
        with self._clients_lock:
            clients = list(self._clients)
        for connection in clients:
            connection.send(message)

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
