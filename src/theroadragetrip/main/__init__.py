import cProfile
import concurrent.futures
import gc
import logging
import math
import os
import random
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pygame

from ..geo import angle_diff, dist_point_to_segment, meters_to_latlon
from ..audio import AudioManager
from ..config import (
    CONFIG_PATH,
    cities_from_config,
    default_city_configuration,
    get_overpass_endpoints,
    load_config,
    reset_config,
    save_config,
)
from ..career import (
    career_path,
    gig_odometer_path,
    load_career,
    load_career_balance,
    load_career_distance,
    load_gig_balance,
    load_gig_fuel,
    load_gig_odometer,
    save_career,
    save_gig_odometer,
)
from ..localization import SUPPORTED_LANGUAGES, normalize_language, tr
from ..calendar import GameCalendar, Season
from ..climate import appearance_with_snow_depth, typical_temperature
from ..fuel import fuel_station_price_cents, nearest_fuel_station
from .. import protocol, transport
from ..simulation import PlayerCommand, advance_simulation, apply_enter_exit_vehicle
from ..osm import (
    CACHE_DIR,
    DEFAULT_BBOX,
    AutoFetchManager,
    TILE_MERGE_BUDGET_S,
    build_ways,
    city_bin_available,
    city_bin_path,
    clear_osm_cache,
    configure_user_agent,
    fetch_osm_ways,
    fetch_osm_ways_from_pbf,
    has_outdated_osm_cache,
    load_city_ways,
    local_pbf_available,
    load_local_sample,
    remove_trees_under_roads,
    remove_trees_under_roads_steps,
)
from ..physics import (
    Car,
    SpatialWayGrid,
    get_current_road_at_car,
    is_point_in_parking_lot,
    off_road_ground_kind,
    is_point_on_parking_space,
    reset_trip,
    respawn_car,
    skidmark_intensity,
    skidmark_should_mark,
    tire_tracks_include_front_wheels,
)
from ..render import (
    FPS,
    SCREEN_H,
    SCREEN_W,
    TireTrail,
    draw_buildings,
    draw_bus_stops,
    draw_car,
    draw_city_selection_menu,
    draw_game_start_hint,
    draw_game_start_overlay,
    draw_city_summary,
    draw_mode_selection_menu,
    draw_compass,
    draw_crossings,
    draw_speed_bumps,
    draw_construction_fences,
    draw_curbs,
    draw_railings,
    draw_railways,
    draw_day_night_overlay,
    draw_illuminated_windows,
    generate_detached_house_parking,
    generate_detached_house_parking_chunk,
    draw_grass_texture,
    draw_headlight_beams,
    draw_hud,
    draw_frame_profiler,
    draw_g_force_meter,
    begin_static_cache_frame,
    invalidate_static_caches,
    invalidate_static_caches_for_camera_jump,
    default_hud_layout,
    draw_tutorial_screen,
    draw_labels,
    draw_loading_screen,
    draw_navigation_route,
    draw_logical_intersections,
    draw_activity_debug_panel,
    draw_npc_cars,
    draw_trains,
    draw_next_train,
    draw_npc_spatial_grid,
    draw_npc_debug_overlay,
    draw_npc_debug_panel,
    draw_npc_population_panel,
    draw_feature_inspector_panel,
    screen_to_world,
    set_game_date,
    draw_pause_menu,
    draw_parking_spaces,
    draw_settings_menu,
    draw_pedestrians,
    draw_pedestrian_reflectors,
    draw_puddles,
    draw_lightning_flash,
    draw_rain,
    draw_splashes,
    draw_wet_roads,
    find_puddle_overlap,
    draw_resident_popup,
    resident_at_screen_position,
    draw_phone_offers,
    draw_scenery,
    draw_scenery_objects,
    draw_traffic_islands,
    draw_fuel_station_signs,
    draw_open_roof_overlays,
    draw_trees,
    draw_street_lights,
    draw_taxi_smoke,
    draw_passenger_nausea_bubble,
    draw_taxi_exhaust,
    draw_speed_cameras,
    draw_stop_signs,
    draw_yield_signs,
    draw_taxi_stops,
    draw_taxi_target,
    draw_tire_tracks,
    draw_vehicle_lights,
    draw_vomit_puddles,
    draw_traffic_lights,
    draw_waters,
    draw_ways,
    draw_roadworks,
    get_viewport_bounds,
    minimum_px_per_m_for_viewport_width,
    solar_altitude_and_events,
)
from ..activities import ActivityContext, ActivityInstance
from ..npc import NPCVehicleManager, npc_target_count_for_population
from ..pedestrian import PedestrianManager, PlayerPedestrian
from ..residents import ResidentManager
from ..police import place_speed_cameras
from ..roadworks import create_roadworks
from ..taxi import TaxiManager
from ..tile_streaming import PBF_TILE_SIZE_M, set_tile_size_m
from ..traffic_world import TrafficWorld
from ..world_cache import WorldCacheManager, clear_world_cache
from ..performance import MAP_SYNC_BUDGET_S, FrameProfiler
from ..weather import SPLASH_MIN_SPEED_MPS, WeatherSystem, weather_type_for_observation
from ..train_timetable import load_timetable
from ..trains import RailwayManager
from ..world_places import load_places
from ..weather_history import WeatherHistory, precipitation_from_observation

from .cli import configure_logging, parse_args
from .menu_input import (
    _city_edit_at,
    _city_horizontal_index,
    _city_item_at,
    _city_menu_index,
    _city_refresh_at,
    _menu_item_at_y,
    _mode_menu_navigate,
    MODE_MENU_OPTION_COUNT,
    _pause_item_at,
    _respawn_allowed,
)
from .startup_screens import choose_language, choose_start_datetime, confirm_outdated_cache, edit_city_list
from .debug_tools import _screenshot_directory, _write_debug_snapshot, find_feature_at

# Maintain BBOX constant for backward compatibility
BBOX = DEFAULT_BBOX

logger = logging.getLogger(__name__)
RAGE_SHOUTS = ("PRKL!", "STNA!", "VTTU!", "HLVT!", "KRPÄ!", "KSPÄ!", "PSKA!")
RAGE_SHOUT_COST = 0.25
NEARBY_PLACES_RADIUS_M = 50_000.0  # airports/stations logged at city start
# F5 activity debug panel's force-an-activity testing keys (residents-
# live.md section 18) - number key N forces the Nth plugin listed in the
# panel (registry.all_plugins() order) onto the selected resident.
ACTIVITY_DEBUG_FORCE_KEYS = (
    pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5,
    pygame.K_6, pygame.K_7, pygame.K_8, pygame.K_9,
)


def _reset_runtime_settings(config, audio, taxi_mgr):
    reset_config(config)
    language = normalize_language(config.get("game", "language", fallback=""))
    physics_mode = config.get("game", "physics_realism", fallback="arcade")
    endpoint_text = config.get("map", "overpass_endpoints", fallback="")
    for key in ("master", "music", "effects"):
        audio.set_volume(key, config.getfloat("audio", f"{key}_volume"))
    audio.set_comments_enabled(config.getboolean("audio", "comments_enabled"))
    taxi_mgr.set_language(language)
    save_config(config)
    return language, physics_mode, endpoint_text, get_overpass_endpoints(config)


def _weather_status(weather) -> str:
    remaining = weather.seconds_until_weather_change
    timing = "manual" if remaining is None else (
        f"current_period_ends_in={int(remaining // 3600):02d}:"
        f"{int(remaining % 3600 // 60):02d}:{int(remaining % 60):02d}"
    )
    thunder = " thunderstorm" if weather.is_thunderstorm else ""
    black_ice = (
        f" black_ice={weather.road_ice_fraction:.0%}"
        if weather.road_ice_fraction > 0.0
        else ""
    )
    return (
        f"condition={weather.weather_type.value}{thunder} "
        f"wetness={weather.wetness:.0%}{black_ice} {timing}"
    )


def _sync_thermal_season(game_calendar, weather, logged_season):
    """Apply the calendar season to weather and log actual transitions."""
    season = game_calendar.season
    weather.season = season
    if season != logged_season:
        logger.info(
            "Thermal season: %s (date=%s latitude=%.4f)",
            season.value,
            game_calendar.date,
            game_calendar.latitude,
        )
    return season


def _map_sync_should_start(revision_changed: bool, any_grid_stale: bool, map_sync_stage: int) -> bool:
    """Whether the multi-frame map-sync pipeline should (re)start this frame.

    Must require map_sync_stage == 0 regardless of which trigger fired.
    The pipeline advances exactly one stage per frame across many frames
    (spreading an O(total ways/buildings) rebuild out so it isn't one big
    stall) - restarting it back to stage 1 every time a new revision
    arrives mid-flight, which used to happen here because `or` binds
    looser than `and` so `revision_changed or (any_grid_stale and stage ==
    0)` let a bare revision change reset progress regardless of stage,
    means a late stage (e.g. the traffic-light grid rebuild) can starve
    forever under sustained tile streaming, even though it always looks
    like it's "syncing".
    """
    return map_sync_stage == 0 and (revision_changed or any_grid_stale)


def _run_headless_ticks(
    tick_count, car, world, audio, frame_profiler, weather,
    camx, camy, px_per_m, current_way, game_time_seconds,
    speed_limiter_enabled, red_light_assist_enabled, npc_follow,
    physics_mode, bridge_edge_crash_cooldown, rage_power, water_elapsed,
    language, slow_check_elapsed, taxi_waiter_elapsed, saved_gig_fares,
    career, career_file, gig_odometer_file, chosen_city, cities_list,
) -> None:
    """Run `tick_count` simulation ticks with no display, no rendering, and
    no player input - a runnable proof that `advance_simulation` works
    without Pygame, standing in for the real headless server this game
    doesn't have yet (client-server-01.md step 9)."""
    dt = 1.0 / FPS
    no_input = PlayerCommand()
    start = time.perf_counter()
    for _ in range(tick_count):
        result = advance_simulation(
            dt, no_input, car, world,
            on_foot=False,
            player_pedestrian=world.player_pedestrian,
            camx=camx, camy=camy, px_per_m=px_per_m,
            current_way=current_way,
            game_time_seconds=game_time_seconds,
            speed_limiter_enabled=speed_limiter_enabled,
            red_light_assist_enabled=red_light_assist_enabled,
            npc_follow=npc_follow,
            screen_w=SCREEN_W, screen_h=SCREEN_H,
            physics_mode=physics_mode,
            weather=weather,
            bridge_edge_crash_cooldown=bridge_edge_crash_cooldown,
            rage_power=rage_power,
            water_elapsed=water_elapsed,
            language=language,
            audio=audio,
            frame_profiler=frame_profiler,
            slow_check_elapsed=slow_check_elapsed,
            taxi_waiter_elapsed=taxi_waiter_elapsed,
            saved_gig_fares=saved_gig_fares,
            career=career,
            career_file=career_file,
            gig_odometer_file=gig_odometer_file,
            chosen_city=chosen_city,
            cities_list=cities_list,
        )
        camx, camy = result.camx, result.camy
        current_way = result.current_way
        water_elapsed = result.water_elapsed
        rage_power = result.rage_power
        bridge_edge_crash_cooldown = result.bridge_edge_crash_cooldown
        slow_check_elapsed = result.slow_check_elapsed
        taxi_waiter_elapsed = result.taxi_waiter_elapsed
        saved_gig_fares = result.saved_gig_fares
        game_time_seconds = (game_time_seconds + dt * 60.0) % (24.0 * 60.0 * 60.0)
        if result.should_stop:
            break
    elapsed = time.perf_counter() - start
    print(
        f"Headless run: {tick_count} ticks in {elapsed:.3f}s "
        f"({tick_count / max(elapsed, 1e-9):.0f} ticks/s), car at "
        f"({car.x:.1f}, {car.y:.1f})"
    )


def _resolve_osm_fetch_func(args, overpass_endpoints, progress_callback=None):
    """Pick where OSM data comes from: live Overpass, or a local .osm.pbf
    extract via osmium-tool (osm_source=pbf) - no downloads, no rate
    limits, works offline. Falls back to Overpass with a warning if "pbf"
    was requested but the local file or the `osmium` tool aren't actually
    usable, so a missing extract doesn't just crash map loading outright.
    """
    def _use_overpass(fetch_bbox, **fetch_kwargs):
        if progress_callback is not None:
            fetch_kwargs.setdefault("progress_callback", progress_callback)
        return fetch_osm_ways(fetch_bbox, endpoints=overpass_endpoints, **fetch_kwargs)

    if getattr(args, "osm_source", "overpass") == "pbf":
        pbf_path = getattr(args, "osm_pbf_path", None)
        if local_pbf_available(pbf_path):
            def _use_pbf(fetch_bbox, **fetch_kwargs):
                if progress_callback is not None:
                    fetch_kwargs.setdefault("progress_callback", progress_callback)
                return fetch_osm_ways_from_pbf(fetch_bbox, pbf_path=pbf_path, **fetch_kwargs)

            return _use_pbf
        logger.warning(
            "osm_source=pbf requested but no usable local .osm.pbf/osmium-tool "
            "found (path=%s) - falling back to the Overpass API",
            pbf_path or "assets/osm/finland-latest.osm.pbf",
        )
    return _use_overpass


def _choose_city(
    active_city_name,
    game_mode: str,
    city_centers,
    bbox_presets,
    career_file,
    career,
    screen,
    font,
    clock,
    config,
    language: str,
    args,
    force_refresh: bool,
    return_to_main_menu: bool,
):
    """Run the mode/city selection menus (or resolve --preset/--bbox) for one
    outer app_running iteration of main(), and return the chosen starting
    point plus whatever menu state the gameplay loop still needs afterward.
    """
    cities_list = list(city_centers.keys())
    selected_city_idx = 0

    # Show city selection menu if no explicit CLI override or when requested from pause menu
    if active_city_name is not None or (
        not args.bbox
        and not args.preset
        and not args.use_sample
        and not args.no_menu
        or return_to_main_menu
    ):
        return_to_main_menu = False
        if active_city_name is None:
            mode_selected = 0 if game_mode == "career" else 1
            choosing_mode = True
            while choosing_mode:
                clock.tick(30)
                for ev in pygame.event.get():
                    if ev.type == pygame.QUIT:
                        pygame.quit()
                        sys.exit(0)
                    if ev.type == pygame.MOUSEMOTION:
                        hovered = _menu_item_at_y(ev.pos[1], 270, 30, 30, MODE_MENU_OPTION_COUNT)
                        if hovered is not None:
                            mode_selected = hovered
                        continue
                    if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                        hovered = _menu_item_at_y(ev.pos[1], 270, 30, 30, MODE_MENU_OPTION_COUNT)
                        if hovered is not None:
                            mode_selected = hovered
                            if mode_selected == 2:
                                completed = bool(load_career(career_file, len(cities_list))["completed"])
                                save_career(career_file, 0, completed=completed)
                                mode_selected = 0
                            elif mode_selected == 3:
                                clear_osm_cache()
                                clear_world_cache()
                                mode_selected = 0
                            else:
                                choosing_mode = False
                        continue
                    if ev.type != pygame.KEYDOWN:
                        continue
                    if ev.key == pygame.K_ESCAPE:
                        pygame.quit()
                        sys.exit(0)
                    if ev.key in (pygame.K_UP, pygame.K_LEFT):
                        mode_selected = _mode_menu_navigate(mode_selected, -1)
                    elif ev.key in (pygame.K_DOWN, pygame.K_RIGHT):
                        mode_selected = _mode_menu_navigate(mode_selected, 1)
                    elif ev.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
                        if mode_selected == 2:
                            completed = bool(load_career(career_file, len(cities_list))["completed"])
                            save_career(career_file, 0, completed=completed)
                            mode_selected = 0
                        elif mode_selected == 3:
                            clear_osm_cache()
                            clear_world_cache()
                            mode_selected = 0
                        else:
                            choosing_mode = False
                    elif ev.key in (pygame.K_1, pygame.K_KP1):
                        mode_selected = 0
                        choosing_mode = False
                    elif ev.key in (pygame.K_2, pygame.K_KP2):
                        mode_selected = 1
                        choosing_mode = False
                    elif ev.key in (pygame.K_3, pygame.K_KP3):
                        completed = bool(load_career(career_file, len(cities_list))["completed"])
                        save_career(career_file, 0, completed=completed)
                        mode_selected = 0
                    elif ev.key in (pygame.K_4, pygame.K_KP4):
                        clear_osm_cache()
                        clear_world_cache()
                        mode_selected = 0
                draw_mode_selection_menu(screen, font, mode_selected, SCREEN_W, SCREEN_H, language)
                pygame.display.flip()
            game_mode = "career" if mode_selected == 0 else "gig_driver"

        career = load_career(career_file, len(cities_list)) if game_mode == "career" else None
        if career is not None and not career["completed"]:
            city_centers, bbox_presets = default_city_configuration()
            cities_list = list(city_centers)
            career = load_career(career_file, len(cities_list))
        if career is not None:
            selected_city_idx = len(cities_list) - 1 - int(career["city_index"])
        if active_city_name is not None and active_city_name in cities_list:
            selected_city_idx = cities_list.index(active_city_name)
        in_menu = game_mode != "career"
        intro_until = pygame.time.get_ticks() + 1000
        while in_menu:
            clock.tick(30)
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit(0)
                elif ev.type == pygame.MOUSEMOTION:
                    hovered = _city_item_at(ev.pos, len(cities_list), SCREEN_W)
                    if hovered is not None:
                        selected_city_idx = hovered
                elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    if _city_refresh_at(ev.pos, SCREEN_W, SCREEN_H, len(cities_list)):
                        force_refresh = not force_refresh
                        continue
                    if _city_edit_at(ev.pos, SCREEN_W, SCREEN_H, len(cities_list)):
                        cities_list, selected_city_idx = edit_city_list(
                            screen, font, clock, config, cities_list,
                            selected_city_idx, language,
                        )
                        city_centers, bbox_presets = cities_from_config(config)
                        continue
                    hovered = _city_item_at(ev.pos, len(cities_list), SCREEN_W)
                    if hovered is not None:
                        selected_city_idx = hovered
                        in_menu = False
                elif ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        pygame.quit()
                        sys.exit(0)
                    elif ev.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
                        in_menu = False
                    elif ev.key == pygame.K_UP:
                        selected_city_idx = (selected_city_idx - 1) % len(cities_list)
                    elif ev.key == pygame.K_DOWN:
                        selected_city_idx = (selected_city_idx + 1) % len(cities_list)
                    elif ev.key == pygame.K_f:
                        force_refresh = not force_refresh
                    elif ev.key == pygame.K_e:
                        cities_list, selected_city_idx = edit_city_list(
                            screen, font, clock, config, cities_list,
                            selected_city_idx, language,
                        )
                        city_centers, bbox_presets = cities_from_config(config)
                    elif ev.key in (pygame.K_LEFT, pygame.K_RIGHT):
                        direction = 1 if ev.key == pygame.K_RIGHT else -1
                        selected_city_idx = _city_horizontal_index(
                            selected_city_idx, direction, len(cities_list)
                        )
                    else:
                        idx = _city_menu_index(ev.key, len(cities_list))
                        if idx is not None:
                            selected_city_idx = idx
                            in_menu = False

            if pygame.time.get_ticks() < intro_until:
                draw_loading_screen(screen, font, 1.0, "Ready", SCREEN_W, SCREEN_H, show_details=False)
            else:
                draw_city_selection_menu(
                    screen, font, cities_list, selected_city_idx, SCREEN_W, SCREEN_H, language,
                    force_refresh=force_refresh,
                )
            pygame.display.flip()

        chosen_city = cities_list[selected_city_idx]
        camera_city_name = chosen_city
        bbox = bbox_presets.get(chosen_city.lower(), DEFAULT_BBOX)
        logger.info("Selected starting city: %s (bbox: %s)", chosen_city, bbox)
    else:
        preset_key = args.preset.lower() if args.preset else "oulu"
        chosen_city = args.preset or preset_key
        camera_city_name = chosen_city
        bbox = bbox_presets.get(preset_key, DEFAULT_BBOX)
        if args.bbox:
            try:
                parts = [float(p.strip()) for p in args.bbox.split(",")]
                if len(parts) == 4:
                    bbox = (parts[0], parts[1], parts[2], parts[3])
            except Exception:
                logger.warning("Invalid bbox provided, using default preset (%s)", preset_key)

    return SimpleNamespace(
        chosen_city=chosen_city,
        camera_city_name=camera_city_name,
        bbox=bbox,
        city_centers=city_centers,
        bbox_presets=bbox_presets,
        game_mode=game_mode,
        career=career,
        force_refresh=force_refresh,
        cities_list=cities_list,
        selected_city_idx=selected_city_idx,
    )


def _latlon_to_world_metres():
    """(lat, lon) -> world metres (EPSG:3067, x east / y north), or None
    without pyproj (trains then fall back to the fixed interval)."""
    try:
        from pyproj import Transformer
    except ImportError:
        return None
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3067", always_xy=True)
    return lambda lat, lon: transformer.transform(lon, lat)


def _load_world(
    chosen_city: str,
    camera_city_name: str,
    bbox,
    city_centers,
    screen,
    font,
    clock,
    args,
    force_refresh: bool,
    overpass_endpoints,
    bus_stops_enabled: bool,
    roadworks_enabled: bool,
    career,
    career_file,
    gig_odometer_file,
    language: str,
    headless: bool = False,
):
    """Load OSM data for `bbox` and build every world/gameplay-manager object
    the gameplay loop needs, showing loading-screen progress as it goes.

    Exits the process (matching main()'s prior inline behavior) if the OSM
    data fails to load or the bbox contains no map features.

    `headless=True` (the simulation server's case) skips every Pygame
    display call in the progress path below - `screen`/`font` may be
    None - so this can run on a machine with no graphical environment.
    """
    sun_latitude, sun_longitude = city_centers.get(
        chosen_city,
        ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0),
    )

    last_progress_draw = 0.0

    def on_load_progress(fraction: float, message: str) -> None:
        nonlocal last_progress_draw
        loading_state[0] = max(0.0, min(1.0, fraction))
        loading_state[1] = message
        if headless or threading.current_thread() is not threading.main_thread():
            return
        now = time.monotonic()
        if fraction < 1.0 and now - last_progress_draw < 0.1:
            return
        draw_loading_screen(screen, font, fraction, message)
        pygame.display.flip()
        last_progress_draw = now
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                sys.exit(0)

    loading_state = [0.05, "Initializing scenery engine..."]
    on_load_progress(0.05, "Initializing scenery engine...")

    def on_build_progress(fraction: float, message: str) -> None:
        on_load_progress(0.05 + min(1.0, fraction) * 0.65, message)

    # Load map
    try:
        elements_count = 0
        world_cache = WorldCacheManager(
            cache_ttl=float(os.getenv("OSM_CACHE_TTL", 24 * 3600)),
            fetch_func=_resolve_osm_fetch_func(args, overpass_endpoints, progress_callback=on_load_progress),
            build_func=lambda raw: build_ways(
                raw, progress_callback=on_build_progress, include_bus_stops=bus_stops_enabled
            ),
        )
        area_id = world_cache.area_id(bbox)

        def load_map_data():
            if args.use_sample:
                on_load_progress(0.2, "Loading bundled offline sample data...")
                elements = load_local_sample()
                if elements is None:
                    raise Exception("No local sample file found")
                logger.info("Using local sample (via --use-sample)")
                on_load_progress(0.5, f"Loaded {len(elements)} sample elements")
                result = build_ways(
                    elements, progress_callback=on_build_progress, include_bus_stops=bus_stops_enabled
                )
                return result, len(elements)
            return world_cache.load_area(
                area_id, bbox, force_refresh=force_refresh or args.no_cache,
            ), 0

        load_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="startup-map")
        load_future = load_executor.submit(load_map_data)
        while not load_future.done():
            on_load_progress(loading_state[0], loading_state[1])
            clock.tick(30)
        res, elements_count = load_future.result()
        load_executor.shutdown(wait=True)
        crossings = getattr(res, "crossings", [])
        stop_signs = getattr(res, "stop_signs", [])
        yield_signs = getattr(res, "yield_signs", [])
        logical_intersections = getattr(res, "logical_intersections", [])
        curbs = getattr(res, "curbs", [])
        if len(res) == 8:
            ways, waters, buildings, sceneries, places, bounds, traffic_lights, crossings = res
        elif len(res) == 7:
            ways, waters, buildings, sceneries, places, bounds, traffic_lights = res
        else:
            ways, waters, buildings, sceneries, places, bounds = res[:6]
            traffic_lights = getattr(res, "traffic_lights", [])
            yield_signs = getattr(res, "yield_signs", [])
    except Exception as e:
        logger.error("Failed to load OSM data: %s", e)
        sys.exit(1)

    # Predefined cities may ship a prebuilt V2 road binary (tools/osm/
    # build_finland_roads.py, benchmark_oulu.py, benchmark_cities.py):
    # fast, deterministic road ways in place of the ones just parsed out
    # of the OSM/PBF/Overpass fetch above. Buildings/water/scenery/etc.
    # from that fetch are kept unchanged - only `ways` is replaced, and
    # only on success. A missing or broken binary is not an error: it
    # just means this city keeps using the road ways already fetched.
    if args.use_prebuilt_roads and city_bin_available(chosen_city):
        try:
            bin_ways, bin_nodes, bin_geometry_points, bin_load_seconds = load_city_ways(chosen_city)
        except Exception as exc:  # noqa: BLE001 - a broken BIN must never block city loading, see osm/bin_source.py
            logger.warning(
                "Failed to load prebuilt road network for %s; "
                "falling back to existing OSM/PBF road loading: %s",
                chosen_city, exc,
            )
        else:
            # The binary holds drivable roads only: keep the fetch's own
            # footways/cycleways/paths/pedestrian streets (sidewalks,
            # pedestrian routing, street-verge paving) instead of losing
            # every one of them.
            ways = bin_ways + [way for way in ways if not way.is_drivable]
            logger.info(
                "Road network source: prebuilt binary | City: %s | File: %s | "
                "Load time: %.1f ms | Ways: %d | Nodes: %d | Geometry points: %d",
                chosen_city, city_bin_path(chosen_city), bin_load_seconds * 1000.0,
                len(bin_ways), bin_nodes, bin_geometry_points,
            )
    else:
        logger.info(
            "Road network source: existing OSM/PBF fallback | City: %s | "
            "Reason: %s", chosen_city,
            "no prebuilt binary" if not city_bin_available(chosen_city)
            else "prebuilt binary disabled (map.use_prebuilt_roads)",
        )

    if not ways and not waters and not buildings and not sceneries and not places:
        logger.error("No map features found in bbox. Try a different bbox.")
        sys.exit(1)

    minx, miny, maxx, maxy = bounds
    taxi_stops = getattr(res, "taxi_stops", [])
    bus_stops = getattr(res, "bus_stops", [])
    parking_spaces = getattr(res, "parking_spaces", [])
    scenery_objects = getattr(res, "scenery_objects", [])
    # lights.md: explicit OSM lamp-pole positions (highway=street_lamp),
    # when mapped, are the primary source draw_street_lights uses instead
    # of its own lit=*-driven fixed-spacing synthesis - see osm/build.py's
    # _scenery_object_kind.
    street_lamps = [obj for obj in scenery_objects if obj.kind == "street_lamp"]
    speed_bumps = getattr(res, "speed_bumps", [])
    railways = getattr(res, "railways", [])
    railings = getattr(res, "railings", [])
    roadworks, roadwork_lights = create_roadworks(ways) if roadworks_enabled else ([], [])
    traffic_lights.extend(roadwork_lights)
    logger.info(
        "Created %d random roadworks (%d temporary lights), enabled=%s",
        len(roadworks),
        len(roadwork_lights),
        roadworks_enabled,
    )
    on_load_progress(0.70, "Preparing road index...")
    remove_trees_under_roads(sceneries, ways)
    # Spatial index for fast O(1) road collision detection
    spatial_grid = SpatialWayGrid()
    spatial_grid.rebuild(ways)
    generated_house_bays = generate_detached_house_parking(
        buildings, ways, parking_spaces, spatial_grid
    )
    if generated_house_bays:
        logger.info("Generated %d detached-house residential parking bays", generated_house_bays)
    building_grid = SpatialWayGrid()
    building_grid.rebuild(buildings)
    scenery_grid = SpatialWayGrid()
    scenery_grid.rebuild(sceneries)
    street_lamp_grid = SpatialWayGrid()
    street_lamp_grid.rebuild(street_lamps)
    water_grid = SpatialWayGrid()
    water_grid.rebuild(waters)
    crossing_grid = SpatialWayGrid()
    crossing_grid.rebuild(crossings)
    traffic_light_grid = SpatialWayGrid()
    traffic_light_grid.rebuild(traffic_lights)
    curb_grid = SpatialWayGrid()
    curb_grid.rebuild(curbs)
    railway_grid = SpatialWayGrid()
    railway_grid.rebuild(railways)
    railing_grid = SpatialWayGrid()
    railing_grid.rebuild(railings)

    # Spawn car on a road near center (avoiding water)
    car = Car(x=(minx + maxx) / 2, y=(miny + maxy) / 2, heading=0.0, speed=0.0)
    if ways:
        respawn_car(car, ways, near_center=True, bounds=bounds, waters=waters, taxi_stops=taxi_stops)
        car.engine_on = False  # the driver starts on foot; E starts it after getting in
    career_total_distance_m = None
    if career is not None:
        career_total_distance_m = load_career_distance(career_file)
        car.odometer_m = career_total_distance_m
    else:
        car.odometer_m = load_gig_odometer(gig_odometer_file)
        saved_fuel_l = load_gig_fuel(gig_odometer_file)
        if saved_fuel_l is not None:
            # The gig car keeps whatever was left in the tank last session.
            car.fuel_l = min(car.fuel_capacity_l, saved_fuel_l)
        if car.odometer_m == 0.0:
            car.odometer_m = float(random.randint(100000, 600000))
            save_gig_odometer(gig_odometer_file, car.odometer_m, car.fuel_l)

    # Initialize Taxi Manager for game mode
    on_load_progress(0.80, "Preparing taxi missions...")
    residents = ResidentManager(city_name=chosen_city)
    residents.set_city_center_m((minx + maxx) / 2.0, (miny + maxy) / 2.0)
    city_center = city_centers.get(chosen_city)
    if city_center is not None:
        residents.set_city_center_latlon(*city_center)
    # Build-time dataset (tools/osm/extract_places.py), not the PBF.
    nearby_places = load_places().within(sun_latitude, sun_longitude, NEARBY_PLACES_RADIUS_M)
    logger.info(
        "World places within %.0f km: %s", NEARBY_PLACES_RADIUS_M / 1000.0,
        ", ".join(f"{place.name} ({place.type})" for place in nearby_places) or "none",
    )
    taxi_mgr = TaxiManager(
        ways,
        places=places,
        buildings=buildings,
        taxi_stops=taxi_stops,
        language=language,
        resident_manager=residents,
    )
    if career is None:
        saved_balance_cents = load_gig_balance(gig_odometer_file)
        if saved_balance_cents is not None:
            taxi_mgr.balance_cents = saved_balance_cents
    else:
        taxi_mgr.balance_cents = load_career_balance(career_file)
    speed_cameras = place_speed_cameras(
        ways,
        bounds,
        camera_city_name,
        seed=random.randrange(2**32),
    )
    logger.info("Placed %d hidden speed cameras", len(speed_cameras))
    # Keep road, signal, and resident services for taxi missions.
    on_load_progress(0.86, "Preparing taxi world...")
    traffic_mgr = TrafficWorld(
        ways,
        traffic_lights=traffic_lights,
        crossings=crossings,
        parking_spaces=parking_spaces,
        residents=residents,
        logical_intersections=logical_intersections,
    )
    # NPC-003: a real, persistent, gradually-filled NPC vehicle
    # population (replaces NPC-001's single deterministic demo car).
    # Filled here, during loading, so an initial population exists the
    # moment gameplay starts - see NPCVehicleManager.populate_initial's
    # own docstring for why a plain loop is fine at load time even though
    # ongoing top-up during play is deliberately staggered.
    on_load_progress(0.88, "Preparing NPC traffic...")
    npc_manager = NPCVehicleManager(
        target_count=args.npc_vehicle_count or npc_target_count_for_population(
            (residents.city_data or {}).get("väkiluku")
        ),
        min_count=args.npc_vehicle_min,
        max_count=args.npc_vehicle_max,
        vehicle_distribution=args.vehicle_distribution,
        include_experimental=args.enable_two_wheelers,
    )
    npc_manager.populate_initial(
        car.x, car.y, residents, ways, spatial_grid=spatial_grid,
        parking_spaces=parking_spaces, sceneries=sceneries, buildings=buildings,
        curbs=curbs, curb_grid=curb_grid, building_grid=building_grid,
        progress_callback=lambda fraction: on_load_progress(0.88 + 0.06 * fraction, "Preparing NPC traffic..."),
    )
    logger.info(
        "NPC-003: populated %d/%d NPC vehicles (%d household, %d autonomous), by type: %s",
        len(npc_manager.vehicles), npc_manager.target_count,
        npc_manager.population_counts()["household"], npc_manager.population_counts()["autonomous"],
        npc_manager.population_counts_by_type(),
    )
    # Same list/dict objects for the life of the session - npc_manager's
    # own population-tick spawns/despawns stay visible through
    # traffic_mgr.npcs without needing to re-set this on every change.
    npcs = npc_manager.vehicles
    npc_drivers = npc_manager.drivers
    traffic_mgr.npcs = npcs
    # Initialize autonomous Pedestrian Manager
    on_load_progress(0.92, "Preparing pedestrians...")
    pedestrian_mgr = PedestrianManager(
        ways,
        target_count=args.pedestrian_count,
        traffic_lights=traffic_lights,
        crossings=crossings,
        logical_intersections=logical_intersections,
        traffic_manager=traffic_mgr,
        residents=residents,
        venue_buildings=buildings,
        scenery_objects=scenery_objects,
        sceneries=sceneries,
        bus_stops=bus_stops,
    )
    # Cyclists are disabled until their traffic interactions are complete.
    player_pedestrian = PlayerPedestrian(
        car.x - math.sin(car.heading) * getattr(car, "width_m", 1.8) * 0.85
        + math.cos(car.heading) * getattr(car, "length_m", 4.0) * 0.2,
        car.y + math.cos(car.heading) * getattr(car, "width_m", 1.8) * 0.85
        + math.sin(car.heading) * getattr(car, "length_m", 4.0) * 0.2,
        heading=car.heading,
    )
    player_pedestrian.is_player = True
    base_pedestrian_count = pedestrian_mgr.target_count

    # Prepare transformer for meters->latlon display
    try:
        from pyproj import Transformer

        transformer_to_ll = Transformer.from_crs("EPSG:3067", "EPSG:4326", always_xy=True)
    except Exception:
        transformer_to_ll = None
        logger.debug("pyproj not available; lat/lon display disabled")

    # Auto fetch manager (background)
    on_load_progress(0.97, "Starting game...")
    auto_fetch_manager = AutoFetchManager(
        ways,
        bounds,
        transformer_to_ll,
        waters=waters,
        buildings=buildings,
        sceneries=sceneries,
        places=places,
        traffic_lights=traffic_lights,
        stop_signs=stop_signs,
        crossings=crossings,
        parking_spaces=parking_spaces,
        logical_intersections=logical_intersections,
        yield_signs=yield_signs,
        curbs=curbs,
        scenery_objects=scenery_objects,
        speed_bumps=speed_bumps,
        railways=railways,
        railings=railings,
        fetch_func=_resolve_osm_fetch_func(args, overpass_endpoints),
        build_func=build_ways,
        build_in_process=args.build_in_process,
        world_cache_manager=world_cache,
    )
    auto_fetch_manager.initialize_player_tile(car.x, car.y)
    on_load_progress(1.0, "Ready")
    logger.info("Entering gameplay loop")

    return SimpleNamespace(
        auto_fetch_manager=auto_fetch_manager,
        base_pedestrian_count=base_pedestrian_count,
        bounds=bounds,
        building_grid=building_grid,
        buildings=buildings,
        bus_stops=bus_stops,
        car=car,
        career_total_distance_m=career_total_distance_m,
        crossing_grid=crossing_grid,
        crossings=crossings,
        curb_grid=curb_grid,
        curbs=curbs,
        railway_grid=railway_grid,
        railways=railways,
        railing_grid=railing_grid,
        railings=railings,
        elements_count=elements_count,
        logical_intersections=logical_intersections,
        npc_drivers=npc_drivers,
        npcs=npcs,
        npc_manager=npc_manager,
        parking_spaces=parking_spaces,
        pedestrian_mgr=pedestrian_mgr,
        places=places,
        player_pedestrian=player_pedestrian,
        residents=residents,
        roadworks=roadworks,
        sceneries=sceneries,
        scenery_grid=scenery_grid,
        scenery_objects=scenery_objects,
        street_lamps=street_lamps,
        street_lamp_grid=street_lamp_grid,
        spatial_grid=spatial_grid,
        speed_bumps=speed_bumps,
        speed_cameras=speed_cameras,
        stop_signs=stop_signs,
        yield_signs=yield_signs,
        sun_latitude=sun_latitude,
        sun_longitude=sun_longitude,
        taxi_mgr=taxi_mgr,
        taxi_stops=taxi_stops,
        traffic_light_grid=traffic_light_grid,
        traffic_lights=traffic_lights,
        traffic_mgr=traffic_mgr,
        transformer_to_ll=transformer_to_ll,
        water_grid=water_grid,
        waters=waters,
        ways=ways,
        world_cache=world_cache,
    )


def _wait_for_active_tile_fetch(
    auto_fetch_manager,
    clock,
    screen,
    font,
    language: str,
) -> None:
    """Block behind a full loading screen for as long as a tile fetch is in
    flight - no small in-HUD progress bar, no gameplay resuming mid-fetch.

    Called right after triggering a background tile fetch, instead of
    letting the player keep driving and potentially cross into yet another
    tile before this one even lands - stacking up simultaneous Overpass
    requests is exactly what draws rate limits. Waits for as long as it
    takes: the underlying HTTP request already carries its own 60s-per-
    attempt timeout (osm/overpass.py), so this can't hang forever even
    without its own deadline - and cutting it off early here would be
    exactly the "resume with an incomplete fetch, show a small bar
    instead" behavior this replaces.
    """
    while auto_fetch_manager.get_fetching():
        clock.tick(30)
        for wait_event in pygame.event.get():
            if wait_event.type == pygame.QUIT:
                pygame.quit()
                sys.exit(0)
        draw_loading_screen(
            screen, font, auto_fetch_manager.get_progress(),
            auto_fetch_manager.get_progress_message() or tr(language, "loading_osm"),
            language=language,
        )
        pygame.display.flip()
    clock.tick()  # Don't let dt jump on the frame after waiting.


# bin-loader-v10.md: the world is ~0.8-1.3M long-lived, acyclic tracked
# objects, so every default-threshold generation-2 pass (39 per benchmark
# run, up to ~500 ms each) found nothing to free. These thresholds keep
# young-generation passes small (max ~30 ms measured) and push full passes
# out to ~100M allocations; reference counting still frees unloaded tiles.
GC_THRESHOLDS = (10000, 10, 1000)


def main() -> None:
    gc.set_threshold(*GC_THRESHOLDS)
    config = load_config()
    overpass_endpoints = get_overpass_endpoints(config)
    configure_user_agent(config.get("game", "user_agent_id"))
    city_centers, bbox_presets = cities_from_config(config)
    args = parse_args(config, city_names=list(bbox_presets))
    if args.osm_source == "pbf":
        # A local extract's cost is dominated by the fixed full-file scan,
        # not by how much area is cut out (see PBF_TILE_SIZE_M) - bigger,
        # less frequent tiles trade that fixed cost against fewer fetches
        # overall. Only safe here: an Overpass query this large risks
        # timing out or tripping a public instance's response-size limit.
        set_tile_size_m(PBF_TILE_SIZE_M)
    configure_logging(args.log_level, file_logging=config.getboolean("game", "file_logging", fallback=False))
    roadworks_enabled = config.getboolean("game", "roadworks_enabled", fallback=False)
    bus_stops_enabled = config.getboolean("game", "bus_stops", fallback=False)

    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    try:
        icon_path = os.path.join(os.path.dirname(__file__), "..", "assets", "rrt-taxi.png")
        pygame.display.set_icon(pygame.image.load(icon_path).convert_alpha())
    except (OSError, pygame.error):
        logger.warning("Game icon could not be loaded")
    pygame.display.set_caption("The Road Rage Trip (OSM PoC)")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont(None, 24)
    small_font = pygame.font.SysFont(None, 18)

    # A freshly created window doesn't always have OS keyboard focus on its
    # very first frame (most noticeable on Windows) - the window manager
    # grants focus shortly after creation, not necessarily before the first
    # blocking screen (choose_language / confirm_outdated_cache below)
    # starts reading input. A mouse click both hits a button AND happens to
    # grant focus, which is why an early screen can look like it only
    # responds to the mouse. Give the window manager a brief, bounded
    # window to hand over focus first. Skipped under the dummy driver
    # (tests) where there's no real window manager to grant it.
    if os.environ.get("SDL_VIDEODRIVER") != "dummy":
        focus_deadline = time.monotonic() + 1.0
        while not pygame.key.get_focused() and time.monotonic() < focus_deadline:
            pygame.event.pump()
            clock.tick(60)

    language = normalize_language(config.get("game", "language", fallback=""))
    # Headless runs have nobody to answer the picker: keep the default.
    if not config.get("game", "language", fallback="").strip() and not args.headless:
        language = choose_language(screen, font, clock)
        config.set("game", "language", language)
        save_config(config)

    if has_outdated_osm_cache():
        confirm_outdated_cache(screen, font, clock, language)
        clear_osm_cache()
        clear_world_cache()

    audio = AudioManager(
        master_volume=config.getfloat("audio", "master_volume", fallback=1.0),
        music_volume=config.getfloat("audio", "music_volume", fallback=0.2),
        effects_volume=config.getfloat("audio", "effects_volume", fallback=1.0),
        comments_enabled=config.getboolean("audio", "comments_enabled", fallback=True),
        speech_min_interval=config.getfloat("speech", "min_interval", fallback=5.0),
        speech_max_interval=config.getfloat("speech", "max_interval", fallback=20.0),
    )

    # Outer game loop to support picking new starting city without restarting process
    app_running = True
    active_city_name = None
    game_mode = "gig_driver"
    career_file = career_path(CONFIG_PATH)
    gig_odometer_file = gig_odometer_path(CONFIG_PATH)
    career = None
    return_to_main_menu = False
    force_refresh = args.force_refresh
    connection = None
    # Gig-driver mode starts from the machine's current local calendar by
    # default. The picker may override any field; seconds are omitted from
    # the UI, so begin cleanly at the current minute.
    selected_start_datetime = datetime.now().replace(second=0, microsecond=0)

    while app_running:
        city_summary = None

        if connection is not None:
            connection.close()

        # Show city selection menu if no explicit CLI override or when requested from pause menu
        # (--connect skips it: a separately-started server has already
        # fixed the world being played, so this client's own menu could
        # otherwise disagree with it - see the architecture doc's known
        # limitations on matching world-selection args between processes).
        if args.connect:
            args.no_menu = True
        city_choice = _choose_city(
            active_city_name, game_mode, city_centers, bbox_presets, career_file, career,
            screen, font, clock, config, language, args, force_refresh, return_to_main_menu,
        )
        return_to_main_menu = False
        chosen_city = city_choice.chosen_city
        camera_city_name = city_choice.camera_city_name
        bbox = city_choice.bbox
        city_centers = city_choice.city_centers
        bbox_presets = city_choice.bbox_presets
        game_mode = city_choice.game_mode
        career = city_choice.career
        force_refresh = city_choice.force_refresh
        cities_list = city_choice.cities_list
        selected_city_idx = city_choice.selected_city_idx

        if (
            game_mode == "gig_driver"
            and not args.connect
            and not args.no_menu
            and not args.preset
            and not args.bbox
            and not args.use_sample
        ):
            selected_start_datetime = choose_start_datetime(
                screen, font, clock, language, selected_start_datetime
            )

        if args.connect:
            # Explicit opt-in to the experimental client/server
            # architecture (client-server-015.md STEP 4/13) - talks to a
            # separately-started `python -m theroadragetrip.server`
            # process over a real socket. Never used by normal
            # single-player launches.
            connect_host, _, connect_port = args.connect.partition(":")
            try:
                connection = transport.connect(connect_host, int(connect_port))
            except (OSError, ValueError) as exc:
                logger.error("Could not connect to simulation server at %s: %s", args.connect, exc)
                sys.exit(1)
            logger.info("Connected to simulation server at %s", args.connect)
        else:
            # Normal single-player: no SimulationServer, no thread, no
            # socket, no JSON - advance_simulation() is called directly,
            # in-process, every frame below (client-server-015.md Phase
            # 1.5). `connection` stays None throughout.
            connection = None

        world = _load_world(
            chosen_city, camera_city_name, bbox, city_centers, screen, font, clock,
            args, force_refresh, overpass_endpoints, bus_stops_enabled, roadworks_enabled,
            career, career_file, gig_odometer_file, language,
        )
        if connection is not None:
            # --connect mode only: this client never runs NPC/pedestrian/
            # traffic AI itself - the locally auto-populated starting
            # entities _load_world just built are discarded immediately;
            # from here on they only ever appear via
            # protocol.apply_server_state's reconciliation against the
            # server's authoritative snapshots.
            world.npc_manager.vehicles.clear()
            world.pedestrian_mgr.pedestrians.clear()
            # Otherwise a client-numbered driver could coincidentally
            # share a vehicle_id with a same-numbered server vehicle
            # (both number from 1) and get looked up against the wrong
            # ShadowVehicle by the F7 single-vehicle debug panel.
            world.npc_drivers.clear()
        auto_fetch_manager = world.auto_fetch_manager
        base_pedestrian_count = world.base_pedestrian_count
        bounds = world.bounds
        building_grid = world.building_grid
        buildings = world.buildings
        bus_stops = world.bus_stops
        car = world.car
        career_total_distance_m = world.career_total_distance_m
        crossing_grid = world.crossing_grid
        crossings = world.crossings
        curb_grid = world.curb_grid
        curbs = world.curbs
        railway_grid = world.railway_grid
        railways = world.railways
        railway_mgr = RailwayManager(railways, load_timetable(), _latlon_to_world_metres())
        railway_mgr_source_count = len(railways)
        railing_grid = world.railing_grid
        railings = world.railings
        elements_count = world.elements_count
        logical_intersections = world.logical_intersections
        npc_drivers = world.npc_drivers
        npcs = world.npcs
        npc_manager = world.npc_manager
        parking_spaces = world.parking_spaces
        pedestrian_mgr = world.pedestrian_mgr
        places = world.places
        player_pedestrian = world.player_pedestrian
        residents = world.residents
        roadworks = world.roadworks
        sceneries = world.sceneries
        scenery_grid = world.scenery_grid
        scenery_objects = world.scenery_objects
        street_lamps = world.street_lamps
        street_lamp_grid = world.street_lamp_grid
        spatial_grid = world.spatial_grid
        speed_bumps = world.speed_bumps
        speed_cameras = world.speed_cameras
        stop_signs = world.stop_signs
        yield_signs = world.yield_signs
        sun_latitude = world.sun_latitude
        sun_longitude = world.sun_longitude
        taxi_mgr = world.taxi_mgr
        taxi_stops = world.taxi_stops
        traffic_light_grid = world.traffic_light_grid
        traffic_lights = world.traffic_lights
        traffic_mgr = world.traffic_mgr
        transformer_to_ll = world.transformer_to_ll
        water_grid = world.water_grid
        waters = world.waters
        ways = world.ways
        world_cache = world.world_cache

        label_mode = 0
        show_debug_hud = False
        npc_follow = False  # F6: camera follows the NPC-001 vehicle
        show_npc_debug = False  # F7: NPC debug overlay (state/route/decision)
        # F5: residents-live.md section 18's activity debug panel - shows
        # the selected resident's current ambient activity plus why every
        # registered plugin would/wouldn't be picked for them right now;
        # while showing, number keys 1-9 force one onto them for testing.
        show_activity_debug = False
        # F4: RENDER-audit.md section 19's feature inspector - click the
        # map to see what OSM feature is there and whether it's rendered.
        show_feature_inspector = False
        inspected_feature = None
        physics_mode = config.get("game", "physics_realism", fallback="arcade")
        speed_limiter_enabled = True
        red_light_assist_enabled = False
        show_compass = False
        show_navigation = False
        show_next_train = False  # J: next arrival at the nearest station
        navigation_route = None
        navigation_target_key = None
        navigation_route_dirty = False
        phone_open = False
        rage_shout_timer = 0.0
        rage_shout_text = RAGE_SHOUTS[0]
        rage_power = 0.0
        hud_layout = default_hud_layout(SCREEN_W, SCREEN_H)
        hud_rects = {}
        hud_dragging = None
        hud_drag_offset = (0, 0)
        selected_resident_id = None
        running = True
        current_way = get_current_road_at_car(car, ways=ways, spatial_grid=spatial_grid, car_roads_only=True)
        min_px_per_m = minimum_px_per_m_for_viewport_width(screen_w=SCREEN_W, margin_m=30.0)
        zoom_target = max(
            min_px_per_m,
            args.px_per_m if args.px_per_m is not None else 9.0,
        )
        px_per_m = max(min_px_per_m, zoom_target * 0.75)
        zoom_elapsed = 0.0
        zoom_duration = 3.0
        start_datetime = selected_start_datetime if game_mode == "gig_driver" else datetime(2026, 8, 31, 18, 0)
        game_calendar = GameCalendar(start_datetime, latitude=sun_latitude)
        game_time_seconds = game_calendar.time_seconds
        set_game_date(game_calendar.date)
        logger.info(
            "Solar model: date=%s city=%s latitude=%.6f longitude=%.6f",
            game_calendar.date,
            chosen_city,
            sun_latitude,
            sun_longitude,
        )
        logged_season = game_calendar.season
        logger.info(
            "Thermal season: %s (date=%s latitude=%.4f)",
            logged_season.value,
            game_calendar.date,
            game_calendar.latitude,
        )
        solar_time_bucket = None
        camx, camy = car.x, car.y
        # A fresh city session's camera lands far from wherever the
        # previous city's static caches were last built (e.g. after
        # "Change city" from the pause menu), so queue a throttled rebuild
        # instead of letting every layer redraw uncached on the same frame.
        invalidate_static_caches_for_camera_jump()
        first_gameplay_frame = True
        awaiting_start = True
        start_warmup_remaining = 1.5
        start_hint_remaining = 0.0
        slow_check_elapsed = 0.0
        taxi_waiter_elapsed = 0.0
        last_zoom_scale = None
        tire_tracks: list[TireTrail] = []
        tire_track_point_count = 0
        last_track_position = None
        last_track_surface = None
        car_was_in_puddle = False
        map_sync_stage = 0
        tree_sweep = None
        # map_sync_stage 2's own sub-stage (bin-loader-v3.md): the road
        # spatial grid rebuild and detached-house parking generation are
        # each budgeted separately - "grid" then "parking" then "done" -
        # since parking generation alone measured up to ~1.9s in one frame
        # against a dense real city load (2376 bays over 20k buildings).
        spatial_grid_sub_stage = "grid"
        house_parking_index = 0
        last_map_revision = auto_fetch_manager.get_map_revision()
        # street_lamps is filtered from scenery_objects, not a list
        # AutoFetchManager grows directly (unlike buildings/ways) - this
        # tracks how many scenery_objects it was last filtered from, so
        # the map-sync stage below only re-filters/rebuilds when autofetch
        # has actually added new ones.
        street_lamps_synced_count = len(scenery_objects)
        water_elapsed = 0.0
        bridge_edge_crash_cooldown = 0.0
        visible_road_count_elapsed = 0.0
        visible_road_count = 0
        on_foot = True
        interact_pending = False
        refuel_pending = False
        engine_on_pending = None
        command_seq = 0
        prev_state_snapshot = None
        prev_snapshot_time = 0.0
        curr_state_snapshot = None
        curr_snapshot_time = 0.0
        saved_gig_fares = taxi_mgr.completed_fares
        render_profile_last_log = time.perf_counter()
        render_profile_times = {}
        runtime_profiler = cProfile.Profile()
        runtime_profile_active = False
        frame_profiler = FrameProfiler()
        pedestrian_mgr.profiler = frame_profiler
        weather = WeatherSystem(season=game_calendar.season)
        # Historical weather (Settings, opt-in): FMI observations for this
        # city and game time where known, generated weather otherwise.
        historical_weather = config.getboolean("game", "historical_weather", fallback=False)
        weather_history = WeatherHistory(
            sun_latitude, sun_longitude, cache_path=Path(CACHE_DIR) / "weather_history.db",
        )

        def observed_weather(moment):
            return weather_history.get(moment) if historical_weather else None

        def outside_temperature(moment):
            observed = observed_weather(moment)
            if observed is not None and observed.temperature_c is not None:
                return observed.temperature_c
            return typical_temperature(moment, sun_latitude)

        if historical_weather:
            weather_history.request(game_calendar.current - timedelta(hours=6), game_calendar.current + timedelta(hours=48))
            weather_history.wait_idle(3.0)  # brief: the start forecast can show real weather
        forecast_moments = [game_calendar.current + timedelta(hours=offset) for offset in range(0, 25, 6)]
        forecast_temperatures = [outside_temperature(moment) for moment in forecast_moments]
        forecast_conditions = weather.forecast(forecast_temperatures, 6.0 * 60.0 * 60.0)
        for index, (moment, temperature) in enumerate(zip(forecast_moments, forecast_temperatures)):
            observed = observed_weather(moment)
            kind, thunder = precipitation_from_observation(observed) if observed is not None else (None, False)
            if kind is not None:
                observed_type = weather_type_for_observation(kind, temperature)
                forecast_conditions[index] = (observed_type, thunder and observed_type.value == "rain")
        forecast_sources = [
            weather_history.source_at(moment) if historical_weather else "generated" for moment in forecast_moments
        ]
        weather_forecast_lines = [
            f"{moment:%d.%m. %H:%M}   {temperature:+.0f} °C   "
            f"{tr(language, 'weather_thunderstorm' if thunder else 'weather_' + condition.value)}"
            + (f"   ({tr(language, 'weather_source_' + source)})" if historical_weather else "")
            for moment, temperature, (condition, thunder), source in zip(
                forecast_moments, forecast_temperatures, forecast_conditions, forecast_sources
            )
        ]
        for moment, temperature, (condition, thunder), source in zip(
            forecast_moments, forecast_temperatures, forecast_conditions, forecast_sources
        ):
            logger.info(
                "Weather forecast %s: %+.1f C %s%s [%s]", f"{moment:%d.%m. %H:%M}", temperature,
                condition.value, " thunderstorm" if thunder else "", source,
            )
        last_lightning_event_id = weather.lightning_event_id
        logger.info("Weather: %s", _weather_status(weather))
        last_logged_weather = None  # (type, thunder, source): log each change once
        world.weather = weather  # protocol.apply_server_state reads world.weather, matching the server's own convention
        clock.tick()  # Reset clock timer to avoid large dt on first frame

        if args.headless:
            _run_headless_ticks(
                args.headless, car, world, audio, frame_profiler, weather,
                camx, camy, px_per_m, current_way, game_time_seconds,
                speed_limiter_enabled, red_light_assist_enabled, npc_follow,
                physics_mode, bridge_edge_crash_cooldown, rage_power, water_elapsed,
                language, slow_check_elapsed, taxi_waiter_elapsed, saved_gig_fares,
                career, career_file, gig_odometer_file, chosen_city, cities_list,
            )
            return

        last_saved_balance_cents = taxi_mgr.balance_cents
        while running:
            raw_frame_ms = clock.tick_busy_loop(FPS)  # Precise pacing; real per-frame duration for the debug HUD
            if taxi_mgr.balance_cents != last_saved_balance_cents:
                # Money must survive any exit, including the sys.exit()
                # quit paths that skip the end-of-session save below.
                last_saved_balance_cents = taxi_mgr.balance_cents
                if career is None:
                    save_gig_odometer(gig_odometer_file, car.odometer_m, car.fuel_l, taxi_mgr.balance_cents)
                elif city_summary is None:
                    save_career(
                        career_file, int(career["city_index"]), int(career["total_score"]),
                        bool(career["completed"]), total_distance_m=car.odometer_m,
                        balance_cents=taxi_mgr.balance_cents,
                    )
            # advance() (not begin_frame() + a later end_frame()) - raw_frame_ms
            # describes the iteration that just finished, so it must be paired
            # with that iteration's sections before begin_frame() clears them
            # for this one. See FrameProfiler.advance()'s docstring.
            frame_profiler.advance(raw_frame_ms)
            dt = min(raw_frame_ms / 1000.0, 0.1)  # clamp lag spikes for physics safety
            if awaiting_start:
                start_warmup_remaining = max(0.0, start_warmup_remaining - dt)
            elif start_hint_remaining > 0.0:
                start_hint_remaining = max(0.0, start_hint_remaining - dt)
            time_scale = 1.0 if taxi_mgr.current_passenger else 60.0
            previous_date = game_calendar.date
            game_calendar.advance(dt * time_scale)
            game_time_seconds = game_calendar.time_seconds
            if game_calendar.date != previous_date:
                set_game_date(game_calendar.date)
                logged_season = _sync_thermal_season(game_calendar, weather, logged_season)
            weather.update(
                dt * time_scale,
                dt,
                outside_temperature_c=outside_temperature(game_calendar.current),
                observed=observed_weather(game_calendar.current),
            )
            if weather.lightning_event_id != last_lightning_event_id:
                audio.play("thunder", volume=0.8)
                last_lightning_event_id = weather.lightning_event_id
            frame_profiler.set_metric(
                "weather", f"{weather.weather_type.value} wetness={weather.wetness:.0%}"
            )
            if historical_weather:
                # Cheap when already loaded; queues the next observation chunk
                # or a stale forecast refresh in the background otherwise.
                weather_history.request(game_calendar.current, game_calendar.current + timedelta(hours=48))
            current_weather_key = (
                weather.weather_type.value, weather.is_thunderstorm,
                weather_history.source_at(game_calendar.current) if historical_weather else "generated",
            )
            if current_weather_key != last_logged_weather:
                last_logged_weather = current_weather_key
                observed_now = observed_weather(game_calendar.current)
                logger.info(
                    "Weather now %s: %s%s %+.1f C, wind %.0f m/s from %03.0f%s [%s]",
                    f"{game_calendar.current:%d.%m. %H:%M}",
                    current_weather_key[0], " thunderstorm" if current_weather_key[1] else "",
                    outside_temperature(game_calendar.current),
                    weather.wind_speed_mps, weather.wind_from_deg,
                    f" snow {observed_now.snow_depth_cm:.0f} cm"
                    if observed_now is not None and observed_now.snow_depth_cm is not None else "",
                    current_weather_key[2],
                )
            current_solar_bucket = int(game_time_seconds // (15.0 * 60.0))
            if current_solar_bucket != solar_time_bucket:
                car_latitude, car_longitude = meters_to_latlon(car.x, car.y, transformer_to_ll)
                if car_latitude is not None and car_longitude is not None:
                    sun_latitude, sun_longitude = car_latitude, car_longitude
                    game_calendar.latitude = car_latitude
                    logged_season = _sync_thermal_season(game_calendar, weather, logged_season)
                solar_time_bucket = current_solar_bucket
                logger.debug(
                    "Solar position updated: time=%02d:%02d latitude=%.6f longitude=%.6f",
                    int(game_time_seconds // 3600.0),
                    int((game_time_seconds % 3600.0) // 60.0),
                    sun_latitude,
                    sun_longitude,
                )
            if first_gameplay_frame:
                logger.info("Gameplay frame: start")

            frame_events = pygame.event.get()
            frame_profiler.set_metric("events", len(frame_events))
            for event in frame_events:
                if event.type == pygame.QUIT:
                    running = False
                    app_running = False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    clicked_hud = False
                    for element_name in ("rage", "speedometer", "meters"):
                        element_rect = hud_rects.get(element_name)
                        if element_rect and element_rect.collidepoint(event.pos):
                            element_x, element_y = hud_layout[element_name]
                            hud_dragging = element_name
                            hud_drag_offset = (event.pos[0] - element_x, event.pos[1] - element_y)
                            clicked_hud = True
                            break
                    if not clicked_hud:
                        visible_pedestrians = pedestrian_mgr.pedestrians + ([player_pedestrian] if on_foot else [])
                        selected_resident_id = resident_at_screen_position(
                            visible_pedestrians,
                            traffic_mgr.residents,
                            event.pos,
                            camx,
                            camy,
                            px_per_m=px_per_m,
                            screen_w=SCREEN_W,
                            screen_h=SCREEN_H,
                        )
                        if show_feature_inspector:
                            # RENDER-audit.md section 19.
                            world_x, world_y = screen_to_world(
                                event.pos[0], event.pos[1], camx, camy,
                                px_per_m=px_per_m, screen_w=SCREEN_W, screen_h=SCREEN_H,
                            )
                            inspected_feature = find_feature_at(
                                world_x, world_y,
                                ways=ways, curbs=curbs, railings=railings, buildings=buildings,
                                sceneries=sceneries, parking_spaces=parking_spaces,
                                waters=waters, railways=railways,
                            )
                elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    hud_dragging = None
                elif event.type == pygame.MOUSEMOTION and hud_dragging:
                    hud_layout[hud_dragging] = (
                        event.pos[0] - hud_drag_offset[0],
                        event.pos[1] - hud_drag_offset[1],
                    )
                elif event.type == pygame.KEYDOWN:
                    if awaiting_start:
                        if start_warmup_remaining > 0.0:
                            continue
                        awaiting_start = False
                        # Shown until the driver first gets in (reset on entry).
                        start_hint_remaining = math.inf
                        continue
                    if event.key in (pygame.K_PAGEUP, pygame.K_PAGEDOWN):
                        time_delta = 60.0 * 60.0 if event.key == pygame.K_PAGEUP else -60.0 * 60.0
                        previous_date = game_calendar.date
                        game_calendar.advance(time_delta)
                        game_time_seconds = game_calendar.time_seconds
                        if game_calendar.date != previous_date:
                            set_game_date(game_calendar.date)
                            logged_season = _sync_thermal_season(game_calendar, weather, logged_season)
                        logger.debug(
                            "Game time adjusted: delta=%+.1fh time=%02d:%02d",
                            time_delta / 3600.0,
                            int(game_time_seconds // 3600.0),
                            int((game_time_seconds % 3600.0) // 60.0),
                        )
                    elif event.key == pygame.K_F12:
                        screenshot_dir = _screenshot_directory()
                        os.makedirs(screenshot_dir, exist_ok=True)
                        screenshot_id = time.time_ns()
                        screenshot_path = os.path.join(screenshot_dir, f"screenshot_{screenshot_id}.png")
                        pygame.image.save(screen, screenshot_path)
                        debug_path = os.path.join(screenshot_dir, f"screenshot_{screenshot_id}.json")
                        screenshot_viewport = get_viewport_bounds(
                            camx, camy, px_per_m=px_per_m, margin_m=30.0
                        )
                        _write_debug_snapshot(
                            debug_path, car, taxi_mgr, auto_fetch_manager, args, bbox,
                            screenshot_viewport, camx, camy, px_per_m, current_way, ways,
                            waters, buildings, sceneries, places, taxi_stops,
                            traffic_lights, crossings, elements_count, traffic_mgr,
                            pedestrian_mgr, spatial_grid, map_sync_stage,
                            chosen_city, camera_city_name, game_mode, on_foot,
                            scenery_objects=scenery_objects,
                            speed_bumps=speed_bumps,
                            railways=railways,
                            railings=railings,
                            npcs=npcs,
                            npc_drivers=npc_drivers,
                            npc_manager=npc_manager,
                            frame_profiler=frame_profiler,
                        )
                        logger.info("Screenshot saved to %s", screenshot_path)
                        logger.info("Runtime debug snapshot saved to %s", debug_path)
                    elif event.key == pygame.K_F9:
                        if runtime_profile_active:
                            runtime_profiler.disable()
                            runtime_profile_active = False
                            logger.info("Runtime profiler stopped; press F10 to save profile")
                        else:
                            runtime_profiler.enable()
                            runtime_profile_active = True
                            logger.info("Runtime profiler started")
                    elif event.key == pygame.K_F10:
                        if runtime_profile_active:
                            runtime_profiler.disable()
                            runtime_profile_active = False
                        profile_dir = _screenshot_directory()
                        os.makedirs(profile_dir, exist_ok=True)
                        profile_path = os.path.join(profile_dir, f"profile_{time.time_ns()}.prof")
                        runtime_profiler.dump_stats(profile_path)
                        logger.info("Runtime profile saved to %s", profile_path)
                    elif event.key == pygame.K_p:
                        phone_open = not phone_open
                    elif event.key == pygame.K_c:
                        show_compass = not show_compass
                    elif event.key == pygame.K_j:
                        show_next_train = not show_next_train
                    elif event.key == pygame.K_n:
                        show_navigation = not show_navigation
                        logger.info(
                            "Navigation toggled: enabled=%s target=%s route_points=%s",
                            show_navigation,
                            bool(taxi_mgr.get_current_target()),
                            len(navigation_route) if navigation_route else 0,
                        )
                        if not show_navigation:
                            navigation_route = None
                            navigation_target_key = None
                    elif event.key == pygame.K_f:
                        # The distance check that gates re-entry is
                        # authoritative gameplay logic
                        # (simulation.apply_enter_exit_vehicle), so this
                        # just queues the edge-triggered action rather
                        # than flipping on_foot here directly - applied
                        # once per frame below (in-process, or via
                        # --connect's server round-trip); a lingering
                        # start_hint_remaining is reset once on_foot
                        # actually flips to False.
                        interact_pending = True
                    elif event.key == pygame.K_g:
                        refuel_pending = True
                    elif event.key == pygame.K_e and not on_foot:
                        engine_on_pending = not car.engine_on
                    elif event.key == pygame.K_SPACE and not phone_open:
                        if rage_power >= RAGE_SHOUT_COST:
                            audio.play_driver_line("rage", language)
                            audio.play("carhorn_takes", volume=0.45)
                            rage_power -= RAGE_SHOUT_COST
                            rage_shout_timer = 5.0
                            rage_shout_text = random.choice(RAGE_SHOUTS)
                            # NPC-005: Road Rage reaches exactly one real
                            # NPC driver - whichever is nearest ahead of
                            # the player right now - not a whole area; see
                            # NPCVehicleManager.trigger_road_rage's own
                            # docstring for why that's enough to produce
                            # an emergent queue behind it.
                            npc_manager.trigger_road_rage(car.x, car.y, car.heading, sim_time=traffic_mgr.sim_time)
                    elif phone_open:
                        if event.key == pygame.K_ESCAPE:
                            phone_open = False
                        elif event.key == pygame.K_x:
                            taxi_mgr.reject_offer()
                        elif event.key in (pygame.K_1, pygame.K_KP1, pygame.K_2, pygame.K_KP2, pygame.K_3, pygame.K_KP3):
                            offer_index = {
                                pygame.K_1: 0, pygame.K_KP1: 0,
                                pygame.K_2: 1, pygame.K_KP2: 1,
                                pygame.K_3: 2, pygame.K_KP3: 2,
                            }[event.key]
                            if taxi_mgr.accept_offer(offer_index, car.x, car.y):
                                phone_open = False
                    elif event.key == pygame.K_ESCAPE:
                        if selected_resident_id is not None:
                            selected_resident_id = None
                            continue
                        # Pause menu with options: Continue Game, Change City, Exit Game
                        pause_options = [
                            tr(language, "continue"), tr(language, "help"), tr(language, "settings_menu"),
                            tr(language, "change_city"), tr(language, "main_menu"), tr(language, "exit"),
                        ]
                        pause_selected = 0
                        is_paused = True

                        while is_paused:
                            clock.tick(30)
                            for p_ev in pygame.event.get():
                                if p_ev.type == pygame.QUIT:
                                    pygame.quit()
                                    sys.exit(0)
                                elif p_ev.type == pygame.MOUSEMOTION:
                                    hovered = _pause_item_at(p_ev.pos, len(pause_options), SCREEN_W, SCREEN_H)
                                    if hovered is not None:
                                        pause_selected = hovered
                                elif p_ev.type == pygame.MOUSEBUTTONDOWN and p_ev.button == 1:
                                    hovered = _pause_item_at(p_ev.pos, len(pause_options), SCREEN_W, SCREEN_H)
                                    if hovered is not None:
                                        pause_selected = hovered
                                        p_ev = pygame.event.Event(
                                            pygame.KEYDOWN,
                                            {"key": pygame.K_RETURN},
                                        )
                                    else:
                                        continue
                                if p_ev.type == pygame.KEYDOWN:
                                    if p_ev.key == pygame.K_ESCAPE:
                                        is_paused = False
                                    elif p_ev.key == pygame.K_UP:
                                        pause_selected = (pause_selected - 1) % len(pause_options)
                                    elif p_ev.key == pygame.K_DOWN:
                                        pause_selected = (pause_selected + 1) % len(pause_options)
                                    elif p_ev.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
                                        if pause_selected == 0:
                                            # Continue Game
                                            is_paused = False
                                        elif pause_selected == 1:
                                            show_help = True
                                            while show_help:
                                                clock.tick(30)
                                                for h_ev in pygame.event.get():
                                                    if h_ev.type == pygame.QUIT:
                                                        pygame.quit()
                                                        sys.exit(0)
                                                    if h_ev.type == pygame.KEYDOWN and h_ev.key in (pygame.K_ESCAPE, pygame.K_F1):
                                                        show_help = False
                                                draw_tutorial_screen(screen, font, SCREEN_W, SCREEN_H, language)
                                                pygame.display.flip()
                                        elif pause_selected == 2:
                                            settings_selected = 0
                                            endpoint_text = config.get("map", "overpass_endpoints", fallback="")
                                            in_settings = True
                                            while in_settings:
                                                clock.tick(30)
                                                for s_ev in pygame.event.get():
                                                    if s_ev.type == pygame.QUIT:
                                                        pygame.quit()
                                                        sys.exit(0)
                                                    if s_ev.type == pygame.MOUSEMOTION:
                                                        hovered = _menu_item_at_y(s_ev.pos[1], 170, 32, 18, 10)
                                                        if hovered is not None:
                                                            settings_selected = hovered
                                                        continue
                                                    if s_ev.type == pygame.MOUSEBUTTONDOWN and s_ev.button == 1:
                                                        hovered = _menu_item_at_y(s_ev.pos[1], 170, 32, 18, 10)
                                                        if hovered is not None:
                                                            settings_selected = hovered
                                                            if hovered == 9:
                                                                language, physics_mode, endpoint_text, overpass_endpoints = _reset_runtime_settings(config, audio, taxi_mgr); historical_weather = config.getboolean("game", "historical_weather", fallback=False)
                                                        continue
                                                    if s_ev.type != pygame.KEYDOWN:
                                                        continue
                                                    if s_ev.key == pygame.K_ESCAPE:
                                                        in_settings = False
                                                    elif settings_selected == 6 and s_ev.key == pygame.K_BACKSPACE:
                                                        endpoint_text = endpoint_text[:-1]
                                                        config.set("map", "overpass_endpoints", endpoint_text)
                                                        overpass_endpoints = get_overpass_endpoints(config)
                                                        save_config(config)
                                                    elif settings_selected == 6 and s_ev.key == pygame.K_DELETE:
                                                        endpoint_text = ""
                                                        config.set("map", "overpass_endpoints", endpoint_text)
                                                        overpass_endpoints = get_overpass_endpoints(config)
                                                        save_config(config)
                                                    elif settings_selected == 6 and s_ev.key == pygame.K_RETURN:
                                                        save_config(config)
                                                    elif settings_selected == 9 and s_ev.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
                                                        language, physics_mode, endpoint_text, overpass_endpoints = _reset_runtime_settings(config, audio, taxi_mgr); historical_weather = config.getboolean("game", "historical_weather", fallback=False)
                                                    elif settings_selected == 6 and s_ev.unicode and s_ev.unicode.isprintable():
                                                        endpoint_text += s_ev.unicode
                                                        config.set("map", "overpass_endpoints", endpoint_text)
                                                        overpass_endpoints = get_overpass_endpoints(config)
                                                        save_config(config)
                                                    elif s_ev.key == pygame.K_UP:
                                                        settings_selected = (settings_selected - 1) % 10
                                                    elif s_ev.key == pygame.K_DOWN:
                                                        settings_selected = (settings_selected + 1) % 10
                                                    elif s_ev.key in (pygame.K_LEFT, pygame.K_RIGHT):
                                                        delta = 0.05 if s_ev.key == pygame.K_RIGHT else -0.05
                                                        if settings_selected == 0:
                                                            language = SUPPORTED_LANGUAGES[(SUPPORTED_LANGUAGES.index(language) + (1 if delta > 0 else -1)) % 2]
                                                        elif settings_selected in (1, 2, 3):
                                                            key = ("master_volume", "music_volume", "effects_volume")[settings_selected - 1]
                                                            value = max(0.0, min(1.0, config.getfloat("audio", key) + delta))
                                                            config.set("audio", key, f"{value:.2f}")
                                                            audio.set_volume(key.removesuffix("_volume"), value)
                                                        elif settings_selected == 4:
                                                            enabled = not config.getboolean("audio", "comments_enabled", fallback=True)
                                                            config.set("audio", "comments_enabled", str(enabled).lower())
                                                            audio.set_comments_enabled(enabled)
                                                        elif settings_selected == 5:
                                                            enabled = not config.getboolean("audio", "subtitles_enabled", fallback=True)
                                                            config.set("audio", "subtitles_enabled", str(enabled).lower())
                                                        elif settings_selected == 7:
                                                            physics_mode = "simulation" if physics_mode == "arcade" else "arcade"
                                                            config.set("game", "physics_realism", physics_mode)
                                                        elif settings_selected == 8:
                                                            historical_weather = not historical_weather
                                                            config.set("game", "historical_weather", str(historical_weather).lower())
                                                            if historical_weather:
                                                                weather_history.request(
                                                                    game_calendar.current - timedelta(hours=6),
                                                                    game_calendar.current + timedelta(hours=48),
                                                                )
                                                        config.set("game", "language", language)
                                                        taxi_mgr.set_language(language)
                                                        save_config(config)
                                                draw_settings_menu(screen, font, language, config.getfloat("audio", "master_volume"), config.getfloat("audio", "music_volume"), config.getfloat("audio", "effects_volume"), config.getboolean("audio", "comments_enabled", fallback=True), config.getboolean("audio", "subtitles_enabled", fallback=True), endpoint_text, settings_selected, SCREEN_W, SCREEN_H, physics_mode=physics_mode, historical_weather=historical_weather)
                                                pygame.display.flip()
                                        elif pause_selected == 3:
                                            # Change City
                                            is_paused = False
                                            running = False
                                            active_city_name = cities_list[selected_city_idx]
                                        elif pause_selected == 4:
                                            # Return to main menu
                                            is_paused = False
                                            running = False
                                            active_city_name = None
                                            return_to_main_menu = True
                                        elif pause_selected == 5:
                                            # Exit Game
                                            pygame.quit()
                                            sys.exit(0)

                            # Redraw current frame beneath pause overlay
                            draw_pause_menu(screen, font, pause_options, pause_selected, SCREEN_W, SCREEN_H, language)
                            pygame.display.flip()

                        # Reset clock after unpausing to prevent sudden dt physics jumps
                        clock.tick()
                    elif event.key == pygame.K_F1:
                        show_help = True
                        while show_help:
                            clock.tick(30)
                            for h_ev in pygame.event.get():
                                if h_ev.type == pygame.QUIT:
                                    pygame.quit()
                                    sys.exit(0)
                                if h_ev.type == pygame.KEYDOWN and h_ev.key in (pygame.K_ESCAPE, pygame.K_F1):
                                    show_help = False
                            draw_tutorial_screen(screen, font, SCREEN_W, SCREEN_H, language)
                            pygame.display.flip()
                        clock.tick()
                    elif event.key == pygame.K_F2:
                        hud_layout = default_hud_layout(screen.get_width(), screen.get_height())
                    elif event.key == pygame.K_F3:
                        show_debug_hud = not show_debug_hud
                        frame_profiler.enabled = show_debug_hud
                        logger.info("Debug HUD %s", "enabled" if show_debug_hud else "disabled")
                    elif event.key == pygame.K_F4:
                        show_feature_inspector = not show_feature_inspector
                        inspected_feature = None
                        logger.info("Feature inspector %s", "enabled" if show_feature_inspector else "disabled")
                    elif event.key == pygame.K_F5:
                        show_activity_debug = not show_activity_debug
                        logger.info("Activity debug panel %s", "enabled" if show_activity_debug else "disabled")
                    elif event.key == pygame.K_F6:
                        npc_follow = bool(npcs) and not npc_follow
                        logger.info("NPC camera follow %s", "enabled" if npc_follow else "disabled")
                    elif event.key == pygame.K_F7:
                        show_npc_debug = not show_npc_debug
                        logger.info("NPC debug overlay %s", "enabled" if show_npc_debug else "disabled")
                    elif event.key == pygame.K_F8:
                        weather.toggle_rain()
                        logger.info("Weather toggled: %s", weather.weather_type.value)
                    elif (
                        show_activity_debug
                        and selected_resident_id is not None
                        and event.key in ACTIVITY_DEBUG_FORCE_KEYS
                    ):
                        # residents-live.md section 18: "provide a way to
                        # force an activity for testing" - number keys
                        # 1-9 force the Nth plugin listed in the F5 panel
                        # (same registry.all_plugins() order) directly
                        # onto the selected resident, bypassing scoring/
                        # cooldown entirely - this is a testing shortcut,
                        # never called from the real per-tick selection.
                        forced_pedestrian = next(
                            (p for p in pedestrian_mgr.pedestrians if p.resident_id == selected_resident_id), None,
                        )
                        plugins = pedestrian_mgr.activity_manager.registry.all_plugins()
                        plugin_index = ACTIVITY_DEBUG_FORCE_KEYS.index(event.key)
                        if forced_pedestrian is not None and plugin_index < len(plugins):
                            plugin = plugins[plugin_index]
                            force_context = ActivityContext(
                                pedestrian=forced_pedestrian, pedestrian_manager=pedestrian_mgr,
                                residents=residents, sim_time=pedestrian_mgr.sim_time,
                            )
                            location = plugin.find_location(force_context) if plugin.definition.requires_location else None
                            if not plugin.definition.requires_location or location is not None:
                                forced_pedestrian.activity = ActivityInstance(
                                    plugin_id=plugin.definition.id, location=location,
                                    started_sim_time=pedestrian_mgr.sim_time,
                                )
                                forced_pedestrian.state = "walking_to_activity"
                                forced_pedestrian.route = None
                                logger.info("Forced activity %s onto resident %s", plugin.definition.id, selected_resident_id)
                            else:
                                logger.info("Could not force activity %s: no suitable location nearby", plugin.definition.id)
                    elif event.key == pygame.K_r:
                        if not _respawn_allowed(on_foot):
                            logger.info("Respawn ignored while driver is walking outside taxi")
                        else:
                            respawn_car(car, ways, waters=waters, taxi_stops=taxi_stops)
                            camx, camy = car.x, car.y
                            invalidate_static_caches_for_camera_jump()
                            taxi_mgr.handle_respawn(car.x, car.y)
                            # Don't let the next tire-track segment rubber-
                            # band across the teleport (SKIDMARK.md #22.21.13).
                            last_track_position = None
                            last_track_surface = None
                    elif event.key == pygame.K_HOME:
                        if not _respawn_allowed(on_foot):
                            logger.info("Debug respawn ignored while driver is walking outside taxi")
                        else:
                            respawn_car(
                                car,
                                ways,
                                bounds=auto_fetch_manager.get_bounds(),
                                waters=waters,
                                near_edge=True,
                            )
                            camx, camy = car.x, car.y
                            invalidate_static_caches_for_camera_jump()
                            taxi_mgr.handle_respawn(car.x, car.y)
                            last_track_position = None
                            last_track_surface = None
                            logger.info("Debug respawn near bbox edge: car=(%.1f, %.1f)", car.x, car.y)
                    elif event.key == pygame.K_x:
                        taxi_mgr.discard_mission(car.x, car.y)
                        logger.info("Passenger fare discarded by player")
                    elif event.key == pygame.K_t:
                        reset_trip(car)
                        logger.info("Trip meter reset to 0 m")
                    elif event.key == pygame.K_u:
                        hud_layout = default_hud_layout(screen.get_width(), screen.get_height())
                        logger.info("HUD layout reset to default")
                    elif event.key == pygame.K_l:
                        label_mode = (label_mode + 1) % 3
                        logger.info("Label mode %d", label_mode)
                    elif event.key == pygame.K_k:
                        car.lane_assist_enabled = not car.lane_assist_enabled
                        logger.info("Lane assist %s", "enabled" if car.lane_assist_enabled else "disabled")
                    elif event.key == pygame.K_v:
                        speed_limiter_enabled = not speed_limiter_enabled
                        logger.info("Speed limiter %s", "enabled" if speed_limiter_enabled else "disabled")
                    elif event.key == pygame.K_b:
                        red_light_assist_enabled = not red_light_assist_enabled
                        logger.info("Red light assist %s", "enabled" if red_light_assist_enabled else "disabled")
                    elif event.key in (pygame.K_EQUALS, pygame.K_PLUS):
                        px_per_m = max(min_px_per_m, px_per_m * 1.1)
                    elif event.key == pygame.K_MINUS:
                        px_per_m = max(min_px_per_m, px_per_m * 0.9)

            if first_gameplay_frame:
                logger.info("Gameplay frame: events complete")

            if not running:
                break

            if phone_open:
                dt = 0.0
            slow_check_elapsed += dt
            taxi_waiter_elapsed += dt
            visible_road_count_elapsed += dt
            rage_shout_timer = max(0.0, rage_shout_timer - dt)
            bridge_edge_crash_cooldown = max(0.0, bridge_edge_crash_cooldown - dt)

            if zoom_elapsed < zoom_duration:
                zoom_elapsed = min(zoom_duration, zoom_elapsed + dt)
                progress = zoom_elapsed / zoom_duration
                eased = progress * progress * (3.0 - 2.0 * progress)
                px_per_m = max(
                    min_px_per_m,
                    px_per_m + (zoom_target - px_per_m) * eased,
                )

            zoom_scale = max(px_per_m, zoom_target)
            if last_zoom_scale is None or abs(zoom_scale - last_zoom_scale) > 0.001:
                pedestrian_mgr.set_target_count(base_pedestrian_count, car)
                last_zoom_scale = zoom_scale

            keys = pygame.key.get_pressed()
            command = PlayerCommand(
                throttle=1.0 if not on_foot and (keys[pygame.K_w] or keys[pygame.K_UP]) else 0.0,
                brake=1.0 if not on_foot and (keys[pygame.K_s] or keys[pygame.K_DOWN]) else 0.0,
                steer_left=1.0 if not on_foot and (keys[pygame.K_a] or keys[pygame.K_LEFT]) else 0.0,
                steer_right=1.0 if not on_foot and (keys[pygame.K_d] or keys[pygame.K_RIGHT]) else 0.0,
                forward=(
                    float(keys[pygame.K_w] or keys[pygame.K_UP]) - float(keys[pygame.K_s] or keys[pygame.K_DOWN])
                    if on_foot else 0.0
                ),
                turn=(
                    float(keys[pygame.K_a] or keys[pygame.K_LEFT]) - float(keys[pygame.K_d] or keys[pygame.K_RIGHT])
                    if on_foot else 0.0
                ),
                sprint=bool(on_foot and (keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT])),
                speed_limiter_enabled=speed_limiter_enabled,
                red_light_assist_enabled=red_light_assist_enabled,
                refuel=refuel_pending,
                engine_on=engine_on_pending,
            )
            refuel_pending = False
            engine_on_pending = None
            previous_car_position = (car.x, car.y)

            if connection is not None:
                # --connect mode only (client-server-015.md STEP 3/4):
                # round-trip the command/state through the experimental
                # server protocol. Never exercised by a normal
                # single-player launch - see the `else` branch below.
                connection.send(protocol.build_command_message(command, interact=interact_pending, seq=command_seq))
                command_seq += 1
                interact_pending = False

                new_snapshot = connection.try_recv_latest()
                if new_snapshot is not None:
                    prev_state_snapshot, prev_snapshot_time = curr_state_snapshot, curr_snapshot_time
                    curr_state_snapshot, curr_snapshot_time = new_snapshot["state"], time.monotonic()

                if curr_state_snapshot is not None:
                    # Visual-only interpolation between the last two received
                    # snapshots (client-server-02.md step 10) - alpha stays
                    # in [0, 1], so this never extrapolates past what the
                    # server actually sent.
                    if prev_state_snapshot is not None and curr_snapshot_time > prev_snapshot_time:
                        alpha = (time.monotonic() - curr_snapshot_time) / (curr_snapshot_time - prev_snapshot_time)
                    else:
                        alpha = 1.0
                    blended_state = protocol.interpolate_state(
                        prev_state_snapshot or curr_state_snapshot, curr_state_snapshot, alpha,
                    )
                    previous_on_foot = on_foot
                    applied = protocol.apply_server_state(world, car, blended_state, player_pedestrian=player_pedestrian)
                    on_foot = applied["on_foot"]
                    game_time_seconds = applied["game_time_seconds"]
                    camx, camy = applied["camx"], applied["camy"]
                    rage_power = applied["rage_power"]
                    water_elapsed = applied["water_elapsed"]
                    if previous_on_foot and not on_foot:
                        start_hint_remaining = 0.0
                    if applied["should_stop"]:
                        if applied["city_summary"] is not None:
                            city_summary = tuple(applied["city_summary"])
                        running = False

                # Rain particles animate from local real-time dt (client-only
                # cosmetic); weather_type/wetness stay authoritative from the
                # server, restored right after so update()'s own wetness math
                # never fights the synced value.
                authoritative_weather_type = weather.weather_type
                authoritative_wetness = weather.wetness
                weather.update(dt * (1.0 if taxi_mgr.current_passenger else 60.0), dt)
                weather.weather_type = authoritative_weather_type
                weather.wetness = authoritative_wetness
            else:
                # Normal single-player (client-server-015.md Phase 1.5):
                # advance_simulation() runs directly, in-process - no
                # socket, no JSON, no shadow-object reconciliation, no
                # interpolation. This is the same call SimulationServer.
                # tick() and _run_headless_ticks() already make; it's the
                # one authoritative simulation entry point either way.
                if interact_pending:
                    previous_on_foot = on_foot
                    on_foot = apply_enter_exit_vehicle(car, player_pedestrian, on_foot, audio)
                    if previous_on_foot and not on_foot:
                        start_hint_remaining = 0.0
                interact_pending = False

                time_scale = 1.0 if taxi_mgr.current_passenger else 60.0
                previous_date = game_calendar.date
                game_calendar.advance(dt * time_scale)
                game_time_seconds = game_calendar.time_seconds
                if game_calendar.date != previous_date:
                    set_game_date(game_calendar.date)
                    logged_season = _sync_thermal_season(game_calendar, weather, logged_season)
                weather.update(
                    dt * time_scale,
                    dt,
                    outside_temperature_c=outside_temperature(game_calendar.current),
                    observed=observed_weather(game_calendar.current),
                )
                if weather.lightning_event_id != last_lightning_event_id:
                    audio.play("thunder", volume=0.8)
                    last_lightning_event_id = weather.lightning_event_id
                taxi_mgr.game_date = game_calendar.date

                result = advance_simulation(
                    dt, command, car, world,
                    on_foot=on_foot,
                    player_pedestrian=player_pedestrian,
                    camx=camx, camy=camy, px_per_m=px_per_m,
                    current_way=current_way,
                    game_time_seconds=game_time_seconds,
                    speed_limiter_enabled=speed_limiter_enabled,
                    red_light_assist_enabled=red_light_assist_enabled,
                    npc_follow=npc_follow,
                    screen_w=SCREEN_W, screen_h=SCREEN_H,
                    physics_mode=physics_mode,
                    weather=weather,
                    bridge_edge_crash_cooldown=bridge_edge_crash_cooldown,
                    rage_power=rage_power,
                    water_elapsed=water_elapsed,
                    language=language,
                    audio=audio,
                    frame_profiler=frame_profiler,
                    slow_check_elapsed=slow_check_elapsed,
                    taxi_waiter_elapsed=taxi_waiter_elapsed,
                    saved_gig_fares=saved_gig_fares,
                    career=career,
                    career_file=career_file,
                    gig_odometer_file=gig_odometer_file,
                    chosen_city=chosen_city,
                    cities_list=cities_list,
                    outside_temperature_c=outside_temperature(game_calendar.current),
                )
                camx, camy = result.camx, result.camy
                current_way = result.current_way
                water_elapsed = result.water_elapsed
                rage_power = result.rage_power
                bridge_edge_crash_cooldown = result.bridge_edge_crash_cooldown
                slow_check_elapsed = result.slow_check_elapsed
                taxi_waiter_elapsed = result.taxi_waiter_elapsed
                saved_gig_fares = result.saved_gig_fares
                if result.should_stop:
                    if result.city_summary is not None:
                        city_summary = result.city_summary
                    running = False

            movement_distance = math.hypot(car.x - previous_car_position[0], car.y - previous_car_position[1])
            viewport_bounds = get_viewport_bounds(camx, camy, px_per_m=px_per_m, margin_m=30.0)

            frame_profiler.set_metric("visible_npcs", sum(
                viewport_bounds[0] <= npc.x <= viewport_bounds[2]
                and viewport_bounds[1] <= npc.y <= viewport_bounds[3]
                for npc in npcs
            ))
            frame_profiler.set_metric("visible_pedestrians", sum(
                viewport_bounds[0] <= ped.x <= viewport_bounds[2]
                and viewport_bounds[1] <= ped.y <= viewport_bounds[3]
                for ped in pedestrian_mgr.pedestrians
            ))
            frame_profiler.set_metric("active_residents", len(traffic_mgr.residents.residents))
            frame_profiler.set_metric("car_x", round(car.x, 1))
            frame_profiler.set_metric("car_y", round(car.y, 1))
            frame_profiler.set_metric(
                "world_cache_operations",
                sum(not future.done() for future in getattr(world_cache, "_futures", {}).values()),
            )
            tile_metrics = auto_fetch_manager.get_tile_metrics()
            current_tile = tile_metrics["relative_tile"]
            frame_profiler.set_metric("current_tile_x", current_tile.x if current_tile else 0)
            frame_profiler.set_metric("current_tile_y", current_tile.y if current_tile else 0)
            frame_profiler.set_metric("tiles_in_memory", tile_metrics["tiles_in_memory"])
            frame_profiler.set_metric("tiles_pending", tile_metrics["tiles_pending"])
            frame_profiler.set_metric("tile_load_ms", tile_metrics["tile_load_ms"])
            frame_profiler.set_metric("tile_integration_ms", tile_metrics["tile_integration_ms"])
            frame_profiler.set_metric("tile_unload_ms", tile_metrics["tile_unload_ms"])
            tile_merge_metrics = auto_fetch_manager.get_tile_merge_metrics()
            frame_profiler.set_metric("tile_merge_queue_depth", tile_merge_metrics["tile_merge_queue_depth"])
            frame_profiler.set_metric("tile_merge_remaining_items", tile_merge_metrics["tile_merge_remaining_items"])

            # Keep road logic on car roads, but recognize pedestrian ways as paved surfaces.
            surface_way = get_current_road_at_car(
                car,
                ways=ways,
                spatial_grid=spatial_grid,
                car_roads_only=False,
            )
            current_way = get_current_road_at_car(car, ways=ways, spatial_grid=spatial_grid, car_roads_only=True, current_way=current_way)
            on_road = current_way is not None
            off_road_ground = (
                off_road_ground_kind(car.x, car.y, scenery_grid=scenery_grid)
                if surface_way is None
                and not is_point_on_parking_space(car.x, car.y, parking_spaces)
                and not is_point_in_parking_lot(car.x, car.y, scenery_grid=scenery_grid)
                else "hard"
            )
            # Only soft ground (grass, forest floor, fields...) gets a
            # muddy dirt trail and sand/beach a lighter sand track - not a
            # plaza, forecourt, track, or commercial/industrial ground
            # that just has no road way.
            is_grass = off_road_ground in ("soft", "sand")
            is_sand = off_road_ground == "sand"
            is_snow = is_grass and game_calendar.season == Season.WINTER
            # Tire slip is the source of truth for a skidmark (SKIDMARK.md) -
            # not brake input, not even is_sliding alone (a tire can be
            # visibly slipping before the whole car counts as sliding; see
            # skidmark_should_mark's lower threshold).
            is_skidding = skidmark_should_mark(
                car.skid_amount,
                wetness=weather.wetness,
                hard_surface=not is_grass,
            )
            if movement_distance > 0.0 and (is_skidding or (is_grass and abs(car.speed) > 1.0)):
                start_new_trail = last_track_position is None or (is_grass, is_sand, is_snow) != last_track_surface
                # Sample on distance OR heading change: a car spinning in a
                # donut barely moves but its rear tyres sweep a wide arc, and
                # joining samples a metre of travel apart (with the heading
                # having swung far in between) drew long chords across the
                # circle - a filled, star-shaped blob instead of a ring.
                last_heading = tire_tracks[-1].points[-1][2] if tire_tracks else car.heading
                heading_change = abs(angle_diff(car.heading, last_heading))
                if (
                    start_new_trail
                    or math.hypot(car.x - last_track_position[0], car.y - last_track_position[1]) >= 0.5
                    or heading_change >= math.radians(4.0)
                ):
                    # The grass trail isn't a slip mark - it's a constant-
                    # weight dirt track from driving off-road at all.
                    intensity = skidmark_intensity(car.skid_amount) if is_skidding else 1.0
                    # Soft ground is displaced by every tyre regardless of
                    # slip/lockup. Hard surfaces only receive front marks
                    # when the front tyres actually lock under braking.
                    front_marks = tire_tracks_include_front_wheels(
                        is_grass, is_skidding, car.front_lockup,
                    )
                    if start_new_trail:
                        tire_tracks.append(TireTrail(
                            is_grass, car.x, car.y, car.heading, intensity,
                            is_sand, front_marks, is_snow=is_snow,
                        ))
                    else:
                        tire_tracks[-1].add(car.x, car.y, car.heading, intensity, front_marks)
                    tire_track_point_count += 1
                    last_track_position = (car.x, car.y)
                    last_track_surface = (is_grass, is_sand, is_snow)
                    # Drop the oldest trails (each one a single unbroken
                    # skid/dirt-trail event, see TireTrail) once accumulated
                    # points pass the cap, back down to a lower watermark -
                    # same "evict a chunk, not one at a time" shape as
                    # before, just counted per trail instead of per point.
                    if tire_track_point_count > 4000:
                        while tire_tracks and tire_track_point_count > 3500:
                            tire_track_point_count -= len(tire_tracks.pop(0).points)
            else:
                last_track_position = None
                last_track_surface = None

            # Splash when the car drives into a puddle (WEATHER_RAIN.md #5):
            # visual only, no physics change. Edge-triggered on entering
            # the puddle (not every frame spent inside it) via
            # car_was_in_puddle, same one-event-per-pass-through shape as
            # a real splash.
            puddle_hit = find_puddle_overlap(
                ways, weather, car.x, car.y, max(car.length_m, car.width_m) * 0.5,
                spatial_grid=spatial_grid,
            )
            car_in_puddle_now = puddle_hit is not None and abs(car.speed) >= SPLASH_MIN_SPEED_MPS
            if car_in_puddle_now and not car_was_in_puddle:
                weather.spawn_splash(car.x, car.y, min(1.0, abs(car.speed) * 3.6 / 60.0))
            car_was_in_puddle = car_in_puddle_now

            current_road_name = getattr(current_way, "name", None) if current_way else None
            if not current_road_name and current_way:
                current_road_name = getattr(current_way, "highway", "Road").replace("_", " ").title()

            # Stream the active 3x3 tile region only after a tile transition.
            if args.auto_fetch:
                revision_before_stream = auto_fetch_manager.get_map_revision()
                # Merge newly-completed tile fetches incrementally, budgeted
                # per frame (bin-loader-v5.md) - the merge itself measured up
                # to ~532ms/70% of a whole spike frame as one synchronous
                # call (bin-loader-v4.md), entirely unmeasured before that.
                # No "immediate" spatial_grid/building_grid rebuild follows
                # anymore (see the removed spatial_grid_immediate/
                # building_grid_immediate block this replaces): ways/
                # buildings now grow a little at a time across many frames,
                # so a full rebuild after every partial step would cost far
                # more in aggregate than the stall it used to prevent.
                # any_grid_stale (below) already detects the resulting
                # length mismatch and hands off to the existing V3
                # map_sync_stage pipeline once the merge settles - the same
                # "keep serving the old complete grid until the incremental
                # rebuild finishes" guarantee that pipeline already gives
                # every other stale-until-ready structure.
                with frame_profiler.section("map_sync:tile_integration"):
                    auto_fetch_manager.integrate_completed_tiles(budget_s=TILE_MERGE_BUDGET_S)
                started = auto_fetch_manager.start_tile_streaming(car.x, car.y)
                if auto_fetch_manager.get_map_revision() != revision_before_stream:
                    invalidate_static_caches()
                if started:
                    logger.info(
                        "Triggered background tile streaming at car=(%.1f, %.1f), tile=%s",
                        car.x,
                        car.y,
                        auto_fetch_manager.player_tile,
                    )
                    _wait_for_active_tile_fetch(auto_fetch_manager, clock, screen, font, language)
                any_grid_stale = (
                    len(ways) != spatial_grid.indexed_way_count
                    or len(buildings) != building_grid.indexed_way_count
                    or len(sceneries) != scenery_grid.indexed_way_count
                    or len(scenery_objects) != street_lamps_synced_count
                    or len(waters) != water_grid.indexed_way_count
                    or len(crossings) != crossing_grid.indexed_way_count
                    or len(curbs) != curb_grid.indexed_way_count
                    or len(railways) != railway_grid.indexed_way_count
                    or len(railings) != railing_grid.indexed_way_count
                    or len(traffic_lights) != traffic_light_grid.indexed_way_count
                )
                # Don't start a sync against a world that's still being
                # merged in: it would finish stale and immediately restart
                # (measured: two full passes, re-running the unbudgeted
                # remove_trees/traffic stages), so wait for the merge queue
                # to drain and sync once.
                tile_merge_busy = auto_fetch_manager.get_tile_merge_metrics()["tile_merge_active"]
                if not tile_merge_busy and _map_sync_should_start(
                    auto_fetch_manager.get_map_revision() != last_map_revision,
                    any_grid_stale,
                    map_sync_stage,
                ):
                    logger.info(
                        "Map sync started: revision=%d ways=%d buildings=%d",
                        auto_fetch_manager.get_map_revision(),
                        len(ways),
                        len(buildings),
                    )
                    map_sync_stage = 1

                map_sync_started = time.perf_counter() if map_sync_stage else None
                if map_sync_stage == 1:
                    # Budgeted, resumable across frames: measured ~1.3 s in
                    # one frame on Oulu once footways loaded.
                    with frame_profiler.section("map_sync:remove_trees"):
                        if tree_sweep is None:
                            tree_sweep = remove_trees_under_roads_steps(sceneries, ways)
                        deadline = time.perf_counter() + MAP_SYNC_BUDGET_S
                        for _ in tree_sweep:
                            if time.perf_counter() >= deadline:
                                break
                        else:
                            tree_sweep = None
                            taxi_mgr.invalidate_tree_collision_index()
                            map_sync_stage = 2
                elif map_sync_stage == 2 and (
                    not tile_merge_busy or spatial_grid_sub_stage != "grid" or spatial_grid._pending_ways is not None
                ):
                    # Budgeted, resumable across frames (bin-loader-v3.md):
                    # the road spatial grid rebuild measured up to ~1.7s
                    # and detached-house parking generation up to ~1.9s in
                    # one frame against a dense real city load - each gets
                    # its own sub-stage so neither pays its whole cost in
                    # one frame. spatial_grid keeps serving the OLD
                    # complete grid, unchanged, until its own rebuild
                    # finishes - collision/nearest-road queries are never
                    # served a half-built grid; parking_spaces grows
                    # in place exactly like the synchronous version, so a
                    # partially-generated pass is always valid to query.
                    with frame_profiler.section("map_sync:spatial_grid"):
                        if spatial_grid_sub_stage == "grid":
                            if spatial_grid._pending_ways is None:
                                spatial_grid.start_rebuild(ways)
                            if spatial_grid.advance_rebuild(MAP_SYNC_BUDGET_S):
                                spatial_grid_sub_stage = "parking"
                                house_parking_index = 0
                        if spatial_grid_sub_stage == "parking":
                            house_parking_index, _ = generate_detached_house_parking_chunk(
                                buildings, ways, parking_spaces, spatial_grid,
                                house_parking_index, MAP_SYNC_BUDGET_S,
                            )
                            if house_parking_index >= len(buildings):
                                spatial_grid_sub_stage = "done"
                    if spatial_grid_sub_stage == "done":
                        spatial_grid_sub_stage = "grid"
                        map_sync_stage = 3
                elif map_sync_stage == 3:
                    with frame_profiler.section("map_sync:building_grid"):
                        building_grid.rebuild(buildings)
                    map_sync_stage = 4
                elif map_sync_stage == 4:
                    with frame_profiler.section("map_sync:scenery_grid"):
                        scenery_grid.rebuild(sceneries)
                        # street_lamps is filtered from scenery_objects, not
                        # grown directly by autofetch - re-filter whenever
                        # scenery_objects itself grew (see
                        # street_lamps_synced_count's own comment).
                        street_lamps[:] = [obj for obj in scenery_objects if obj.kind == "street_lamp"]
                        street_lamp_grid.rebuild(street_lamps)
                        street_lamps_synced_count = len(scenery_objects)
                    map_sync_stage = 5
                elif map_sync_stage == 5:
                    with frame_profiler.section("map_sync:water_grid"):
                        water_grid.rebuild(waters)
                    map_sync_stage = 6
                elif map_sync_stage == 6:
                    with frame_profiler.section("map_sync:crossing_grid"):
                        crossing_grid.rebuild(crossings)
                    map_sync_stage = 7
                elif map_sync_stage == 7:
                    with frame_profiler.section("map_sync:curb_grid"):
                        curb_grid.rebuild(curbs)
                    map_sync_stage = 8
                elif map_sync_stage == 8:
                    with frame_profiler.section("map_sync:railway_grid"):
                        railway_grid.rebuild(railways)
                    if len(railways) != railway_mgr_source_count:
                        # ~20 ms on Oulu (routes + timetable match); only when track streamed in.
                        with frame_profiler.section("map_sync:train_routes"):
                            railway_mgr.rebuild(railways)
                        railway_mgr_source_count = len(railways)
                    map_sync_stage = 9
                elif map_sync_stage == 9:
                    with frame_profiler.section("map_sync:railing_grid"):
                        railing_grid.rebuild(railings)
                    map_sync_stage = 10
                elif map_sync_stage == 10:
                    with frame_profiler.section("map_sync:traffic_light_grid"):
                        traffic_light_grid.rebuild(traffic_lights)
                    if args.auto_fetch:
                        with auto_fetch_manager.lock:
                            auto_fetch_manager._attempted_endpoints.clear()
                    map_sync_stage = 11
                elif map_sync_stage == 11:
                    with frame_profiler.section("map_sync:taxi"):
                        taxi_mgr.sync_map_data(ways, places=places, buildings=buildings)
                    map_sync_stage = 12
                elif map_sync_stage == 12:
                    # Budgeted, resumable across frames (bin-loader-v13.md):
                    # the route graph rebuild measured ~190-270 ms in one
                    # frame on Oulu. The previous graph stays authoritative
                    # (queries, NPC route jobs) until the new one commits.
                    with frame_profiler.section("map_sync:traffic"):
                        if getattr(traffic_mgr, "_pending_route_graph", None) is None:
                            traffic_mgr.start_map_sync(
                                ways,
                                traffic_lights=traffic_lights,
                                stop_signs=stop_signs,
                                crossings=crossings,
                                buildings=buildings,
                                sceneries=sceneries,
                                parking_spaces=parking_spaces,
                                logical_intersections=logical_intersections,
                            )
                        traffic_sync_finished = traffic_mgr.advance_map_sync(MAP_SYNC_BUDGET_S)
                    if traffic_sync_finished:
                        map_sync_stage = 13
                elif map_sync_stage == 13:
                    # Budgeted, resumable across frames (bin-loader-v3.md):
                    # measured up to ~3.2s in one frame against a dense
                    # real city load - the single largest map-sync stage.
                    # set_venue_buildings/set_scenery_features now run
                    # FIRST (not after, as originally written): the
                    # original order synced ways once against the *stale*
                    # building grid, then set_venue_buildings rebuilt the
                    # grid and re-ran the entire synchronous sync a SECOND
                    # time against the fresh one - that first pass's
                    # result was always immediately discarded, so this
                    # reordering (resync=False skips that internal
                    # re-sync) does the identical final computation once
                    # instead of twice, not just spreads it out.
                    # pedestrian_mgr.ped_ways/route graph/junction grid
                    # keep serving the OLD complete result, unchanged,
                    # until the incremental job below fully commits.
                    with frame_profiler.section("map_sync:pedestrians"):
                        if pedestrian_mgr._sync_stage in (None, "done"):
                            # bin-loader-v9.md: venue/scenery indexing are
                            # stages of the budgeted job, not synchronous
                            # set_venue_buildings/set_scenery_features calls.
                            with frame_profiler.section("map_sync:pedestrians:start"):
                                pedestrian_mgr.start_incremental_sync(
                                    ways, traffic_lights=traffic_lights, logical_intersections=logical_intersections,
                                    venue_buildings=buildings,
                                    scenery_features=(scenery_objects, sceneries, bus_stops),
                                )
                        pedestrian_sync_finished = pedestrian_mgr.advance_incremental_sync(MAP_SYNC_BUDGET_S)
                    if pedestrian_sync_finished:
                        map_sync_stage = 14
                elif map_sync_stage == 14:
                    with frame_profiler.section("map_sync:finalize"):
                        navigation_route_dirty = True
                        last_map_revision = auto_fetch_manager.get_map_revision()
                        logger.info(
                            "Map sync complete: revision=%d indexed_ways=%d",
                            last_map_revision,
                            spatial_grid.indexed_way_count,
                        )
                    map_sync_stage = 0
                if map_sync_started is not None:
                    frame_profiler.record(
                        "map_sync",
                        (time.perf_counter() - map_sync_started) * 1000.0,
                    )
            current_target = taxi_mgr.get_current_target()
            if show_navigation and current_target:
                target_key = (id(current_target), current_target.x, current_target.y)
                route_deviation = False
                if navigation_route and len(navigation_route) >= 2:
                    route_deviation = min(
                        dist_point_to_segment(car.x, car.y, start[0], start[1], end[0], end[1])
                        for start, end in zip(navigation_route, navigation_route[1:])
                    ) > 35.0
                if target_key != navigation_target_key or navigation_route_dirty or route_deviation:
                    route_layer = getattr(current_way, "layer", None) if current_way else None
                    navigation_route = traffic_mgr.plan_route(
                        (car.x, car.y),
                        (current_target.x, current_target.y),
                        layer=route_layer,
                    )
                    logger.info(
                        "Navigation route planned: start=(%.1f, %.1f) target=(%.1f, %.1f) "
                        "layer=%s points=%s",
                        car.x,
                        car.y,
                        current_target.x,
                        current_target.y,
                        route_layer,
                        len(navigation_route) if navigation_route else 0,
                    )
                    navigation_target_key = target_key
                    navigation_route_dirty = False
            elif not current_target:
                navigation_route = None
                navigation_target_key = None
                show_navigation = False
            if first_gameplay_frame:
                logger.info("Gameplay frame: map update complete")

            # Render background and scene
            begin_static_cache_frame()
            render_profiler_start = time.perf_counter()
            render_profile_frame_start = time.perf_counter()
            render_profile_stage_start = render_profile_frame_start
            map_stage_start = time.perf_counter()
            seasonal_appearance = game_calendar.seasonal_appearance
            observed_now = observed_weather(game_calendar.current)
            if observed_now is not None and observed_now.snow_depth_cm is not None:
                seasonal_appearance = appearance_with_snow_depth(seasonal_appearance, observed_now.snow_depth_cm)
            draw_grass_texture(screen, camx, camy, px_per_m, profiler=frame_profiler, season=game_calendar.season, seasonal_appearance=seasonal_appearance)
            stage_elapsed = time.perf_counter() - map_stage_start
            render_profile_times["map_grass"] = render_profile_times.get("map_grass", 0.0) + stage_elapsed
            frame_profiler.record("render:grass", stage_elapsed * 1000.0)
            if first_gameplay_frame:
                logger.info("Gameplay frame: rendering scenery")
            map_stage_start = time.perf_counter()
            draw_scenery(
                screen,
                sceneries,
                camx,
                camy,
                px_per_m=px_per_m,
                spatial_grid=scenery_grid,
                profiler=frame_profiler,
                season=game_calendar.season,
                seasonal_appearance=seasonal_appearance,
            )
            stage_elapsed = time.perf_counter() - map_stage_start
            render_profile_times["map_scenery"] = render_profile_times.get("map_scenery", 0.0) + stage_elapsed
            frame_profiler.record("render:scenery", stage_elapsed * 1000.0)
            if first_gameplay_frame:
                logger.info("Gameplay frame: rendering water")
            map_stage_start = time.perf_counter()
            draw_waters(
                screen, waters, camx, camy, px_per_m=px_per_m,
                spatial_grid=water_grid, profiler=frame_profiler, season=game_calendar.season,
                seasonal_appearance=seasonal_appearance,
            )
            stage_elapsed = time.perf_counter() - map_stage_start
            render_profile_times["map_water"] = render_profile_times.get("map_water", 0.0) + stage_elapsed
            frame_profiler.record("render:water", stage_elapsed * 1000.0)
            if first_gameplay_frame:
                logger.info("Gameplay frame: rendering roads")
            map_stage_start = time.perf_counter()
            draw_ways(
                screen, ways, camx, camy, px_per_m=px_per_m,
                spatial_grid=spatial_grid, profiler=frame_profiler,
                building_grid=building_grid,
            )
            draw_wet_roads(screen, ways, weather, camx, camy, px_per_m=px_per_m, spatial_grid=spatial_grid)
            draw_puddles(screen, ways, weather, camx, camy, px_per_m=px_per_m, spatial_grid=spatial_grid)
            draw_parking_spaces(
                screen,
                parking_spaces,
                camx,
                camy,
                px_per_m=px_per_m,
                spatial_grid=traffic_mgr._parking_grid,
                grid_cell_size=traffic_mgr._parking_grid_cell_size,
            )
            # Ground-level track only here - a bridge track is drawn again,
            # after the car/pedestrians (see the only_bridges=True call
            # below), so it actually covers whatever's underneath it
            # instead of the car rendering on top of the bridge deck it's
            # really driving under.
            draw_railways(
                screen, railways, camx, camy, px_per_m=px_per_m, spatial_grid=railway_grid, only_bridges=False,
            )
            draw_traffic_islands(
                screen, sceneries, camx, camy, px_per_m=px_per_m,
                spatial_grid=scenery_grid, season=game_calendar.season,
                seasonal_appearance=seasonal_appearance,
            )
            stage_elapsed = time.perf_counter() - map_stage_start
            render_profile_times["map_roads"] = render_profile_times.get("map_roads", 0.0) + stage_elapsed
            frame_profiler.record("render:roads", stage_elapsed * 1000.0)
            # Trees are drawn here, after roads/parking - not inside
            # draw_scenery() above - so a road or parking surface (both
            # just painted) can never end up covering a real tree (see
            # render/scenery.py:draw_trees docstring).
            map_stage_start = time.perf_counter()
            # Wind bends crowns downwind: the whole (cached) tree layer is
            # drawn from a camera shifted upwind - a camera move's cost,
            # not a per-tree redraw.
            tree_lean_x, tree_lean_y = weather.tree_lean_m
            draw_trees(
                screen,
                sceneries,
                camx - tree_lean_x,
                camy - tree_lean_y,
                px_per_m=px_per_m,
                tree_effects=taxi_mgr.tree_effects,
                fallen_trees=taxi_mgr.fallen_trees,
                spatial_grid=scenery_grid,
                ways=ways,
                road_spatial_grid=spatial_grid,
                profiler=frame_profiler,
                season=game_calendar.season,
                seasonal_appearance=seasonal_appearance,
            )
            stage_elapsed = time.perf_counter() - map_stage_start
            render_profile_times["map_trees"] = render_profile_times.get("map_trees", 0.0) + stage_elapsed
            frame_profiler.record("render:trees", stage_elapsed * 1000.0)
            draw_scenery_objects(screen, scenery_objects, camx, camy, px_per_m=px_per_m, profiler=frame_profiler)
            if bus_stops_enabled:
                map_stage_start = time.perf_counter()
                draw_bus_stops(screen, bus_stops, ways, camx, camy, px_per_m=px_per_m, spatial_grid=spatial_grid)
                stage_elapsed = time.perf_counter() - map_stage_start
                render_profile_times["map_bus_stops"] = render_profile_times.get("map_bus_stops", 0.0) + stage_elapsed
                frame_profiler.record("render:bus_stops", stage_elapsed * 1000.0)
            if first_gameplay_frame:
                logger.info("Gameplay frame: rendering buildings")
            map_stage_start = time.perf_counter()
            draw_buildings(
                screen,
                buildings,
                camx,
                camy,
                px_per_m=px_per_m,
                spatial_grid=building_grid,
                road_ways=ways,
                road_spatial_grid=spatial_grid,
                places=places,
                profiler=frame_profiler,
            )
            stage_elapsed = time.perf_counter() - map_stage_start
            render_profile_times["map_buildings"] = render_profile_times.get("map_buildings", 0.0) + stage_elapsed
            frame_profiler.record("render:buildings", stage_elapsed * 1000.0)
            render_profile_times["map"] = render_profile_times.get("map", 0.0) + (
                time.perf_counter() - render_profile_stage_start
            )
            render_profile_stage_start = time.perf_counter()
            map_stage_start = time.perf_counter()
            draw_tire_tracks(
                screen, tire_tracks, camx, camy, grass=False, px_per_m=px_per_m,
                viewport_bounds=viewport_bounds,
            )
            draw_tire_tracks(
                screen, tire_tracks, camx, camy, grass=True, px_per_m=px_per_m,
                viewport_bounds=viewport_bounds,
            )
            draw_tire_tracks(
                screen, tire_tracks, camx, camy, grass=True, sand=True, px_per_m=px_per_m,
                viewport_bounds=viewport_bounds,
            )
            draw_tire_tracks(
                screen, tire_tracks, camx, camy, grass=True, snow=True, px_per_m=px_per_m,
                viewport_bounds=viewport_bounds,
            )
            draw_roadworks(screen, roadworks, camx, camy, px_per_m=px_per_m)
            if first_gameplay_frame:
                logger.info("Gameplay frame: rendering overlays")
            draw_curbs(screen, curbs, camx, camy, px_per_m=px_per_m, spatial_grid=curb_grid)
            draw_railings(screen, railings, camx, camy, px_per_m=px_per_m, spatial_grid=railing_grid)
            draw_construction_fences(screen, sceneries, camx, camy, px_per_m=px_per_m, spatial_grid=scenery_grid)
            draw_crossings(screen, crossings, camx, camy, px_per_m=px_per_m, spatial_grid=crossing_grid)
            draw_speed_bumps(screen, speed_bumps, camx, camy, px_per_m=px_per_m)
            draw_traffic_lights(
                screen,
                traffic_lights,
                traffic_mgr.sim_time,
                camx,
                camy,
                px_per_m=px_per_m,
                spatial_grid=traffic_light_grid,
            )
            draw_taxi_stops(screen, taxi_stops, camx, camy, px_per_m=px_per_m)
            draw_stop_signs(screen, stop_signs, camx, camy, px_per_m=px_per_m)
            draw_yield_signs(screen, yield_signs, camx, camy, px_per_m=px_per_m)
            draw_speed_cameras(
                screen,
                speed_cameras,
                camx,
                camy,
                px_per_m=px_per_m,
                flash_index=taxi_mgr.speed_camera_flash_index,
                flash_active=taxi_mgr.speed_camera_flash_timer > 0.0,
            )
            viewport_minx, viewport_miny, viewport_maxx, viewport_maxy = get_viewport_bounds(
                camx, camy, px_per_m=px_per_m, margin_m=40.0
            )
            light_vehicles = [
                car,
                *(
                    npc for npc in npcs
                    if viewport_minx - 45.0 <= npc.x <= viewport_maxx + 45.0
                    and viewport_miny - 45.0 <= npc.y <= viewport_maxy + 45.0
                ),
            ]
            if visible_road_count_elapsed >= 0.1:
                visible_road_count = sum(
                    1
                    for way in spatial_grid.ways_in_rect(
                        viewport_minx, viewport_miny, viewport_maxx, viewport_maxy
                    )
                    if getattr(way, "is_drivable", True)
                )
                visible_road_count_elapsed = 0.0
            # This whole stretch (tire tracks, roadworks, crossings, traffic
            # lights, taxi stops, speed cameras) used to run between two
            # profiler timestamps whose interval was never actually
            # recorded - the *next* reset below silently discarded it, so a
            # slowdown anywhere in here was invisible to both the frame
            # profiler and the live debug HUD's spike/culprit readout.
            stage_elapsed = time.perf_counter() - map_stage_start
            render_profile_times["map_markings"] = render_profile_times.get("map_markings", 0.0) + stage_elapsed
            frame_profiler.record("render:markings", stage_elapsed * 1000.0)
            render_profile_stage_start = time.perf_counter()
            visible_pedestrians = pedestrian_mgr.pedestrians + [
                npc for npc in npcs if getattr(npc, "is_on_foot", False)
            ] + ([player_pedestrian] if on_foot else [])
            draw_pedestrians(
                screen,
                visible_pedestrians,
                camx,
                camy,
                font=small_font,
                px_per_m=px_per_m,
                ways=ways,
                show_debug=show_debug_hud,
                residents=traffic_mgr.residents,
                spatial_grid=spatial_grid,
            )
            if show_debug_hud:
                draw_logical_intersections(
                    screen,
                    traffic_mgr.logical_intersections,
                    camx,
                    camy,
                    traffic_mgr.sim_time,
                    px_per_m=px_per_m,
                    intersection_manager=traffic_mgr.intersection_manager,
                )
            if show_navigation:
                draw_navigation_route(screen, navigation_route, camx, camy, px_per_m=px_per_m)
            draw_taxi_target(screen, taxi_mgr, camx, camy, font, px_per_m=px_per_m, language=language)
            if car.engine_on:
                draw_taxi_exhaust(screen, car, camx, camy, px_per_m=px_per_m)
            draw_car(
                screen,
                car,
                camx,
                camy,
                font=font,
                px_per_m=px_per_m,
                ways=ways,
                shout_timer=rage_shout_timer,
                shout_text=rage_shout_text,
                spatial_grid=spatial_grid,
                current_way=current_way,
                railways=railways,
                railway_grid=railway_grid,
            )
            visible_npc_count = draw_npc_cars(
                screen, npcs, camx, camy, px_per_m=px_per_m, screen_w=SCREEN_W, screen_h=SCREEN_H,
                ways=ways, spatial_grid=spatial_grid, show_debug=show_npc_debug, residents=residents,
            )
            draw_splashes(screen, weather, camx, camy, px_per_m=px_per_m)
            if not on_foot:
                draw_taxi_smoke(screen, car, camx, camy, px_per_m=px_per_m, timer=taxi_mgr.taxi_smoke_timer)
            draw_passenger_nausea_bubble(
                screen,
                font,
                car,
                taxi_mgr,
                camx,
                camy,
                px_per_m=px_per_m,
                language=language,
            )
            # Open OSM roof structures are canopies rather than solid
            # buildings. Their translucent roof belongs above vehicles and
            # pumps so driving through reads as passing underneath it.
            draw_open_roof_overlays(
                screen,
                buildings,
                camx,
                camy,
                px_per_m=px_per_m,
                spatial_grid=building_grid,
            )
            # Bridge track only here, redrawn after the car/pedestrians
            # above (see the only_bridges=False call near draw_ways) so an
            # elevated railway actually covers whatever's underneath it -
            # matches the bridge the screenshot flagged, where the taxi
            # rendered on top of a rail bridge it was really driving under.
            draw_railways(
                screen, railways, camx, camy, px_per_m=px_per_m, spatial_grid=railway_grid, only_bridges=True,
            )
            # After bridge track, so a train crossing a rail bridge stays
            # visible. Same time scale the game clock uses for the spawn timer.
            railway_mgr.update(dt, dt * (1.0 if taxi_mgr.current_passenger else 60.0), game_calendar.current)
            draw_trains(screen, railway_mgr, camx, camy, px_per_m=px_per_m, show_debug=show_debug_hud, font=font)
            # Price boards are gameplay-critical and must stay above both
            # ordinary buildings and the canopy overlay.
            draw_fuel_station_signs(
                screen,
                scenery_objects,
                camx,
                camy,
                px_per_m=px_per_m,
            )
            stage_elapsed = time.perf_counter() - render_profile_stage_start
            render_profile_times["actors"] = render_profile_times.get("actors", 0.0) + stage_elapsed
            frame_profiler.record("render:actors", stage_elapsed * 1000.0)
            render_profile_stage_start = time.perf_counter()

            lighting_start = time.perf_counter()
            sun_altitude, _, _ = solar_altitude_and_events(
                game_time_seconds, sun_latitude, sun_longitude
            )
            daylight_scene = screen.copy() if sun_altitude < -7.5 else None
            draw_day_night_overlay(
                screen,
                game_time_seconds,
                visible_road_count,
                latitude=sun_latitude,
                longitude=sun_longitude,
            )
            draw_illuminated_windows(
                screen,
                buildings,
                camx,
                camy,
                game_time_seconds,
                px_per_m=px_per_m,
                spatial_grid=building_grid,
                latitude=sun_latitude,
                longitude=sun_longitude,
                profiler=frame_profiler,
            )
            draw_vomit_puddles(screen, taxi_mgr.vomit_puddles, camx, camy, px_per_m=px_per_m)
            draw_vomit_puddles(screen, pedestrian_mgr.vomit_puddles, camx, camy, px_per_m=px_per_m)
            street_light_base = screen.copy()
            draw_headlight_beams(
                screen,
                light_vehicles,
                camx,
                camy,
                game_time_seconds,
                px_per_m=px_per_m,
                daylight_surface=daylight_scene,
                latitude=sun_latitude,
                longitude=sun_longitude,
                npc_vehicles=light_vehicles,
                street_light_positions=None,
                    bicycles=[],
                ways=ways,
                spatial_grid=spatial_grid,
                current_way=current_way,
                buildings=buildings,
                building_spatial_grid=building_grid,
            )
            draw_vehicle_lights(
                screen,
                light_vehicles,
                camx,
                camy,
                px_per_m=px_per_m,
                ways=ways,
                spatial_grid=spatial_grid,
                current_way=current_way,
            )
            with frame_profiler.section("render:lighting:street_lights"):
                draw_street_lights(
                    screen,
                    ways,
                    camx,
                    camy,
                    game_time_seconds,
                    px_per_m=px_per_m,
                    spatial_grid=spatial_grid,
                    visible_road_count=visible_road_count,
                    daylight_surface=daylight_scene,
                    latitude=sun_latitude,
                    longitude=sun_longitude,
                    buildings=buildings,
                    base_surface=street_light_base,
                    building_spatial_grid=building_grid,
                    street_lamps=street_lamps,
                    street_lamp_grid=street_lamp_grid,
                    profiler=frame_profiler,
                )
            if sun_altitude < -7.5:
                draw_pedestrian_reflectors(
                    screen,
                    visible_pedestrians,
                    camx,
                    camy,
                    px_per_m=px_per_m,
                    ways=ways,
                    light_vehicles=[car],
                    street_light_positions=None,
                )
            stage_elapsed = time.perf_counter() - lighting_start
            render_profile_times["lighting"] = render_profile_times.get("lighting", 0.0) + stage_elapsed
            frame_profiler.record("render:lighting", stage_elapsed * 1000.0)

            with frame_profiler.section("render:weather"):
                draw_lightning_flash(screen, weather)
                draw_rain(screen, weather)

            # bin-loader-v4.md: render_profile_stage_start was last set
            # after the "actors" stage (above) and never reset before this
            # point, so "render:labels" below silently measured from the
            # start of the whole lighting block onward - lighting's own
            # cost (which uses its own separately-scoped lighting_start)
            # was being counted a second time, folded into "labels". A
            # profiler-only fix (no gameplay effect): rescope the timer to
            # actually start here.
            render_profile_stage_start = time.perf_counter()

            # Labels overlay (toggled with 'L')
            if label_mode:
                draw_labels(
                    screen,
                    font,
                    ways,
                    waters,
                    buildings,
                    sceneries,
                    places,
                    camx,
                    camy,
                    px_per_m=px_per_m,
                    spatial_grid=spatial_grid,
                    scenery_grid=scenery_grid,
                    building_grid=building_grid,
                    label_mode=label_mode,
                    profiler=frame_profiler,
                )
            stage_elapsed = time.perf_counter() - render_profile_stage_start
            render_profile_times["labels"] = render_profile_times.get("labels", 0.0) + stage_elapsed
            frame_profiler.record("render:labels", stage_elapsed * 1000.0)
            render_profile_stage_start = time.perf_counter()

            render_profile_times["frame"] = render_profile_times.get("frame", 0.0) + (
                time.perf_counter() - render_profile_frame_start
            )
            if logger.isEnabledFor(logging.DEBUG) and time.perf_counter() - render_profile_last_log >= 1.0:
                frame_count = max(1, int(render_profile_times.pop("count", 0)))
                timing_ms = {
                    stage: total * 1000.0 / frame_count
                    for stage, total in render_profile_times.items()
                    if not stage.startswith("map_")
                }
                logger.debug(
                    "Render profile: fps=%.1f avg_ms=%s ways=%d buildings=%d labels=%s",
                    clock.get_fps(),
                    ",".join(f"{stage}={duration:.1f}" for stage, duration in timing_ms.items()),
                    len(ways),
                    len(buildings),
                    label_mode,
                )
                logger.debug(
                    "Map render profile: %s",
                    ",".join(
                        f"{stage.removeprefix('map_')}={duration * 1000.0 / frame_count:.1f}"
                        for stage, duration in render_profile_times.items()
                        if stage.startswith("map_")
                    ),
                )
                logger.debug("Weather: %s", _weather_status(weather))
                render_profile_times.clear()
                render_profile_last_log = time.perf_counter()
            render_profile_times["count"] = render_profile_times.get("count", 0) + 1

            # Draw HUD and compass
            current_target = taxi_mgr.get_current_target()
            target_coords = (current_target.x, current_target.y) if current_target else None
            current_limit_kmh = getattr(current_way, "speed_limit_kmh", None) if current_way else None
            nearby_fuel_station = nearest_fuel_station(scenery_objects, car.x, car.y)
            nearby_fuel_price_cents = (
                fuel_station_price_cents(nearby_fuel_station)
                if nearby_fuel_station is not None
                else None
            )

            with frame_profiler.section("render:hud"):
                draw_hud(
                    screen,
                    font,
                    car,
                    on_road,
                    len(ways),
                    px_per_m,
                    transformer_to_ll,
                    show_labels=bool(label_mode),
                    taxi_mgr=taxi_mgr,
                    current_road_name=current_road_name,
                    speed_limit_kmh=current_limit_kmh,
                    speed_limiter_enabled=speed_limiter_enabled,
                    red_light_assist_enabled=red_light_assist_enabled,
                    show_compass=show_compass,
                    show_navigation=show_navigation,
                    rage_power=rage_power,
                    language=language,
                    career_total_distance_m=car.odometer_m if career is not None else None,
                    water_time_remaining=(10.0 - water_elapsed) if water_elapsed > 0.0 else None,
                    game_time_seconds=game_time_seconds,
                    game_date=game_calendar.date,
                    temperature_c=outside_temperature(game_calendar.current),
                    game_time_realtime=taxi_mgr.current_passenger is not None,
                    comment_text=audio.comment_text,
                    comment_speaker=audio.comment_speaker,
                    comment_speaker_name=audio.comment_speaker_name,
                    subtitles_enabled=config.getboolean("audio", "subtitles_enabled", fallback=True),
                    fps=clock.get_fps(),
                    show_debug_hud=show_debug_hud,
                    hud_layout=hud_layout,
                    hud_rects=hud_rects,
                    fuel_station_price_cents=nearby_fuel_price_cents,
                )
                next_train = railway_mgr.next_arrival(car.x, car.y, game_calendar.current) if show_next_train else None
                if next_train is not None:
                    when, call = next_train
                    draw_next_train(
                        screen, font,
                        f"{tr(language, 'next_train')} {call.station}: {when:%H:%M} {call.train_type} {call.number} "
                        f"{call.origin} – {call.destination}",
                        SCREEN_W,
                    )
            if phone_open:
                draw_phone_offers(screen, taxi_mgr, font, small_font, SCREEN_W, SCREEN_H, language, car=car)
            if show_compass:
                draw_compass(screen, car, SCREEN_W - 64, 145, 28, font, target_pos=target_coords)
            if selected_resident_id is not None:
                selected_pedestrian = next(
                    (
                        pedestrian
                        for pedestrian in pedestrian_mgr.pedestrians
                        if getattr(pedestrian, "resident_id", None) == selected_resident_id
                    ),
                    None,
                )
                selected_resident = traffic_mgr.residents.get(selected_resident_id)
                selected_trip_group_id = getattr(selected_resident, "trip_group_id", None)
                selected_trip_group = next(
                    (
                        one_npc.trip_group
                        for one_npc in npcs
                        if one_npc.trip_group is not None and one_npc.trip_group.group_id == selected_trip_group_id
                    ),
                    None,
                ) if selected_trip_group_id is not None else None
                draw_resident_popup(
                    screen,
                    small_font,
                    selected_resident,
                    traffic_mgr.residents,
                    SCREEN_W,
                    SCREEN_H,
                    pedestrian=selected_pedestrian,
                    trip_group=selected_trip_group,
                )
                if show_activity_debug and selected_pedestrian is not None:
                    activity_context = ActivityContext(
                        pedestrian=selected_pedestrian, pedestrian_manager=pedestrian_mgr,
                        residents=residents, sim_time=pedestrian_mgr.sim_time,
                    )
                    explanations = pedestrian_mgr.activity_manager.explain_candidates(activity_context)
                    draw_activity_debug_panel(screen, selected_pedestrian, explanations, small_font)
            if awaiting_start:
                draw_game_start_overlay(
                    screen, font, chosen_city, SCREEN_W, SCREEN_H,
                    forecast_lines=weather_forecast_lines, language=language,
                )
            elif start_hint_remaining > 0.0 and on_foot:
                draw_game_start_hint(screen, font, SCREEN_W, tr(language, "hint_enter_taxi"))
            elif not on_foot and not car.engine_on and car.fuel_l > 0.0:
                draw_game_start_hint(screen, font, SCREEN_W, tr(language, "hint_start_engine"))

            if first_gameplay_frame:
                logger.info("Gameplay frame: flipping display")
            frame_profiler.record(
                "rendering", (time.perf_counter() - render_profiler_start) * 1000.0
            )
            draw_frame_profiler(
                screen, small_font, frame_profiler,
                0, len(pedestrian_mgr.pedestrians),
            )
            if show_debug_hud:
                draw_g_force_meter(
                    screen, small_font, car.forward_g, car.lateral_g, car.is_sliding,
                    grip_usage=car.grip_usage, max_grip_g=car.max_grip_g,
                )
            if show_npc_debug:
                draw_npc_population_panel(
                    screen, npc_manager.population_counts(), small_font, x=380, y=220,
                    by_type=npc_manager.population_counts_by_type(),
                    visible_count=visible_npc_count,
                )
                draw_npc_spatial_grid(
                    screen, npc_manager.spatial_grid.grid, npc_manager.spatial_grid.cell_size,
                    camx, camy, px_per_m=px_per_m, screen_w=SCREEN_W, screen_h=SCREEN_H,
                )
                if npcs:
                    npc_driver_for_panel = npc_drivers.get(npcs[0].vehicle_id)
                    if npc_driver_for_panel is not None:
                        draw_npc_debug_panel(screen, npcs[0], npc_driver_for_panel, small_font)
                        draw_npc_debug_overlay(screen, npcs[0], npc_driver_for_panel, camx, camy, px_per_m)
            if show_feature_inspector:
                draw_feature_inspector_panel(screen, inspected_feature, small_font)
            pygame.display.flip()
            if first_gameplay_frame:
                logger.info("Gameplay frame: complete")
                first_gameplay_frame = False

        if career is not None and city_summary is None:
            save_career(
                career_file,
                int(career["city_index"]),
                int(career["total_score"]),
                bool(career["completed"]),
                total_distance_m=car.odometer_m,
                balance_cents=taxi_mgr.balance_cents,
            )
        elif career is None:
            save_gig_odometer(gig_odometer_file, car.odometer_m, car.fuel_l, taxi_mgr.balance_cents)

        if city_summary is not None:
            summary_city, summary_score, summary_fares, summary_next_city, summary_career_total = city_summary
            showing_summary = True
            while showing_summary:
                clock.tick(30)
                for summary_event in pygame.event.get():
                    if summary_event.type == pygame.QUIT:
                        pygame.quit()
                        sys.exit(0)
                    if summary_event.type == pygame.KEYDOWN and summary_event.key in (
                        pygame.K_RETURN, pygame.K_KP_ENTER
                    ):
                        showing_summary = False
                draw_city_summary(
                    screen, font, summary_city, summary_score, summary_fares, summary_next_city,
                    summary_career_total, SCREEN_W, SCREEN_H, language,
                )
                pygame.display.flip()
            if summary_next_city is None:
                app_running = False

    auto_fetch_manager.shutdown()
    audio.close()
    pygame.quit()


if __name__ == "__main__":
    main()
