import cProfile
import concurrent.futures
import logging
import math
import os
import random
import sys
import threading
import time
from types import SimpleNamespace
from typing import Optional

import pygame

from ..geo import dist_point_to_segment, meters_to_latlon
from ..audio import AudioManager
from ..config import (
    CONFIG_PATH,
    cities_from_config,
    default_city_configuration,
    get_overpass_endpoints,
    load_config,
    save_config,
)
from ..career import (
    CAREER_SCORE_LIMIT,
    career_path,
    gig_odometer_path,
    load_career,
    load_career_distance,
    load_gig_odometer,
    save_career,
    save_gig_odometer,
)
from ..localization import SUPPORTED_LANGUAGES, normalize_language, tr
from ..osm import (
    DEFAULT_BBOX,
    AutoFetchManager,
    build_ways,
    clear_osm_cache,
    configure_user_agent,
    fetch_osm_ways,
    fetch_osm_ways_from_pbf,
    has_outdated_osm_cache,
    local_pbf_available,
    load_local_sample,
    remove_trees_under_roads,
)
from ..physics import (
    ACCEL,
    BRAKE,
    FRICTION,
    STEER_RATE,
    STEER_SPEED_FACTOR,
    Car,
    SpatialWayGrid,
    get_current_road_at_car,
    is_car_colliding_with_bridge_edge,
    is_car_fully_in_water,
    is_point_in_parking_lot,
    is_point_on_parking_space,
    reset_trip,
    respawn_car,
    pull_car_inside_bridge_edge,
    skidmark_intensity,
    skidmark_should_mark,
    update_car_physics,
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
    draw_pause_menu,
    draw_parking_spaces,
    draw_settings_menu,
    draw_pedestrians,
    draw_pedestrian_reflectors,
    draw_puddles,
    draw_rain,
    draw_splashes,
    draw_wet_roads,
    find_puddle_overlap,
    draw_resident_popup,
    resident_at_screen_position,
    draw_phone_offers,
    draw_scenery,
    draw_scenery_objects,
    draw_trees,
    draw_street_lights,
    draw_taxi_smoke,
    draw_passenger_nausea_bubble,
    draw_taxi_exhaust,
    draw_speed_cameras,
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
from ..pedestrian import PedestrianManager, PlayerPedestrian
from ..residents import ResidentManager
from ..police import place_speed_cameras
from ..roadworks import create_roadworks
from ..taxi import TaxiManager, TaxiState
from ..tile_streaming import PBF_TILE_SIZE_M, set_tile_size_m
from ..traffic_world import TrafficWorld
from ..world_cache import WorldCacheManager, clear_world_cache
from ..performance import FrameProfiler
from ..weather import SPLASH_MIN_SPEED_MPS, WeatherSystem

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
from .startup_screens import choose_language, confirm_outdated_cache, edit_city_list
from .debug_tools import _screenshot_directory, _write_debug_snapshot

# Maintain BBOX constant for backward compatibility
BBOX = DEFAULT_BBOX

logger = logging.getLogger(__name__)
RAGE_SHOUTS = ("PRKL!", "STNA!", "VTTU!", "HLVT!", "KRPÄ!", "KSPÄ!", "PSKA!")
RAGE_DISTANCE_TO_FULL_M = 400.0
RAGE_SHOUT_COST = 0.25


def _rage_from_speeding(
    rage_power: float, speed_mps: float, road_limit_mps: Optional[float], driven_distance_m: float,
) -> float:
    """Speeding builds rage; driving within the limit calms it back down -
    both at the same rate (RAGE_DISTANCE_TO_FULL_M of speeding fills the
    meter, the same distance under the limit empties it). No current road
    (unknown limit) leaves rage unchanged either way."""
    if road_limit_mps is None or driven_distance_m <= 0.0:
        return rage_power
    delta = driven_distance_m / RAGE_DISTANCE_TO_FULL_M
    if abs(speed_mps) > road_limit_mps + 0.01:
        return min(1.0, rage_power + delta)
    return max(0.0, rage_power - delta)


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
):
    """Load OSM data for `bbox` and build every world/gameplay-manager object
    the gameplay loop needs, showing loading-screen progress as it goes.

    Exits the process (matching main()'s prior inline behavior) if the OSM
    data fails to load or the bbox contains no map features.
    """
    sun_latitude, sun_longitude = city_centers.get(
        chosen_city,
        ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0),
    )
    logger.info(
        "Solar model: date=2026-08-31 city=%s latitude=%.6f longitude=%.6f",
        chosen_city,
        sun_latitude,
        sun_longitude,
    )

    last_progress_draw = 0.0

    def on_load_progress(fraction: float, message: str) -> None:
        nonlocal last_progress_draw
        loading_state[0] = max(0.0, min(1.0, fraction))
        loading_state[1] = message
        if threading.current_thread() is not threading.main_thread():
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

    if not ways and not waters and not buildings and not sceneries and not places:
        logger.error("No map features found in bbox. Try a different bbox.")
        sys.exit(1)

    minx, miny, maxx, maxy = bounds
    taxi_stops = getattr(res, "taxi_stops", [])
    bus_stops = getattr(res, "bus_stops", [])
    parking_spaces = getattr(res, "parking_spaces", [])
    scenery_objects = getattr(res, "scenery_objects", [])
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
    building_grid = SpatialWayGrid()
    building_grid.rebuild(buildings)
    scenery_grid = SpatialWayGrid()
    scenery_grid.rebuild(sceneries)
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
    career_total_distance_m = None
    if career is not None:
        career_total_distance_m = load_career_distance(career_file)
        car.odometer_m = career_total_distance_m
    else:
        car.odometer_m = load_gig_odometer(gig_odometer_file)
        if car.odometer_m == 0.0:
            car.odometer_m = float(random.randint(100000, 600000))
            save_gig_odometer(gig_odometer_file, car.odometer_m)

    # Initialize Taxi Manager for game mode
    on_load_progress(0.80, "Preparing taxi missions...")
    residents = ResidentManager(city_name=chosen_city)
    residents.set_city_center_m((minx + maxx) / 2.0, (miny + maxy) / 2.0)
    city_center = city_centers.get(chosen_city)
    if city_center is not None:
        residents.set_city_center_latlon(*city_center)
    taxi_mgr = TaxiManager(
        ways,
        places=places,
        buildings=buildings,
        taxi_stops=taxi_stops,
        language=language,
        resident_manager=residents,
    )
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
    # Initialize autonomous Pedestrian Manager
    on_load_progress(0.92, "Preparing pedestrians...")
    pedestrian_mgr = PedestrianManager(
        ways,
        target_count=args.pedestrian_count,
        traffic_lights=traffic_lights,
        crossings=crossings,
        logical_intersections=logical_intersections,
        traffic_vehicles=[],
        traffic_manager=None,
        residents=residents,
        venue_buildings=buildings,
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
        parking_spaces=parking_spaces,
        pedestrian_mgr=pedestrian_mgr,
        places=places,
        player_pedestrian=player_pedestrian,
        residents=residents,
        roadworks=roadworks,
        sceneries=sceneries,
        scenery_grid=scenery_grid,
        scenery_objects=scenery_objects,
        spatial_grid=spatial_grid,
        speed_bumps=speed_bumps,
        speed_cameras=speed_cameras,
        stop_signs=stop_signs,
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
            tr(language, "loading_osm"), language=language,
        )
        pygame.display.flip()
    clock.tick()  # Don't let dt jump on the frame after waiting.


def main() -> None:
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
        icon_path = os.path.join(os.path.dirname(__file__), "..", "assets", "roadragetrip_icon.png")
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
    if not config.get("game", "language", fallback="").strip():
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

    while app_running:
        city_summary = None

        # Show city selection menu if no explicit CLI override or when requested from pause menu
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

        world = _load_world(
            chosen_city, camera_city_name, bbox, city_centers, screen, font, clock,
            args, force_refresh, overpass_endpoints, bus_stops_enabled, roadworks_enabled,
            career, career_file, gig_odometer_file, language,
        )
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
        railing_grid = world.railing_grid
        railings = world.railings
        elements_count = world.elements_count
        logical_intersections = world.logical_intersections
        parking_spaces = world.parking_spaces
        pedestrian_mgr = world.pedestrian_mgr
        places = world.places
        player_pedestrian = world.player_pedestrian
        residents = world.residents
        roadworks = world.roadworks
        sceneries = world.sceneries
        scenery_grid = world.scenery_grid
        scenery_objects = world.scenery_objects
        spatial_grid = world.spatial_grid
        speed_bumps = world.speed_bumps
        speed_cameras = world.speed_cameras
        stop_signs = world.stop_signs
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
        physics_mode = config.get("game", "physics_realism", fallback="arcade")
        speed_limiter_enabled = True
        red_light_assist_enabled = False
        show_compass = False
        show_navigation = False
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
        game_time_seconds = 18.0 * 60.0 * 60.0
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
        last_map_revision = auto_fetch_manager.get_map_revision()
        water_elapsed = 0.0
        bridge_edge_crash_cooldown = 0.0
        visible_road_count_elapsed = 0.0
        visible_road_count = 0
        on_foot = True
        saved_gig_fares = taxi_mgr.completed_fares
        render_profile_last_log = time.perf_counter()
        render_profile_times = {}
        runtime_profiler = cProfile.Profile()
        runtime_profile_active = False
        frame_profiler = FrameProfiler()
        weather = WeatherSystem()
        clock.tick()  # Reset clock timer to avoid large dt on first frame

        while running:
            dt = min(clock.tick_busy_loop(FPS) / 1000.0, 0.1)  # Precise pacing; clamp lag spikes for physics safety
            frame_profiler.begin_frame()
            if awaiting_start:
                start_warmup_remaining = max(0.0, start_warmup_remaining - dt)
            elif start_hint_remaining > 0.0:
                start_hint_remaining = max(0.0, start_hint_remaining - dt)
            time_scale = 1.0 if taxi_mgr.current_passenger else 60.0
            game_time_seconds = (game_time_seconds + dt * time_scale) % (24.0 * 60.0 * 60.0)
            weather.update(dt * time_scale, dt)
            frame_profiler.set_metric(
                "weather", f"{weather.weather_type.value} wetness={weather.wetness:.0%}"
            )
            current_solar_bucket = int(game_time_seconds // (15.0 * 60.0))
            if current_solar_bucket != solar_time_bucket:
                car_latitude, car_longitude = meters_to_latlon(car.x, car.y, transformer_to_ll)
                if car_latitude is not None and car_longitude is not None:
                    sun_latitude, sun_longitude = car_latitude, car_longitude
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
                        start_hint_remaining = 8.0
                        continue
                    if event.key in (pygame.K_PAGEUP, pygame.K_PAGEDOWN):
                        time_delta = 60.0 * 60.0 if event.key == pygame.K_PAGEUP else -60.0 * 60.0
                        game_time_seconds = (game_time_seconds + time_delta) % (24.0 * 60.0 * 60.0)
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
                        if not on_foot:
                            length_m = getattr(car, "length_m", 4.0)
                            width_m = getattr(car, "width_m", 1.8)
                            left_x = -math.sin(car.heading)
                            left_y = math.cos(car.heading)
                            player_pedestrian.x = (
                                car.x
                                + math.cos(car.heading) * length_m * 0.2
                                + left_x * width_m * 0.85
                            )
                            player_pedestrian.y = (
                                car.y
                                + math.sin(car.heading) * length_m * 0.2
                                + left_y * width_m * 0.85
                            )
                            player_pedestrian.heading = car.heading
                            car.speed = 0.0
                            car.engine_on = False
                            on_foot = True
                            audio.play("car-door-open")
                        elif math.hypot(player_pedestrian.x - car.x, player_pedestrian.y - car.y) <= 3.0:
                            on_foot = False
                            start_hint_remaining = 0.0
                            car.speed = 0.0
                            car.engine_on = True
                            audio.play("car-door-open")
                    elif event.key == pygame.K_SPACE and not phone_open:
                        if rage_power >= RAGE_SHOUT_COST:
                            audio.play_driver_line("rage", language)
                            audio.play("carhorn_takes", volume=0.45)
                            rage_power -= RAGE_SHOUT_COST
                            rage_shout_timer = 5.0
                            rage_shout_text = random.choice(RAGE_SHOUTS)
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
                                                        hovered = _menu_item_at_y(s_ev.pos[1], 170, 32, 26, 8)
                                                        if hovered is not None:
                                                            settings_selected = hovered
                                                        continue
                                                    if s_ev.type == pygame.MOUSEBUTTONDOWN and s_ev.button == 1:
                                                        hovered = _menu_item_at_y(s_ev.pos[1], 170, 32, 26, 8)
                                                        if hovered is not None:
                                                            settings_selected = hovered
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
                                                    elif settings_selected == 6 and s_ev.unicode and s_ev.unicode.isprintable():
                                                        endpoint_text += s_ev.unicode
                                                        config.set("map", "overpass_endpoints", endpoint_text)
                                                        overpass_endpoints = get_overpass_endpoints(config)
                                                        save_config(config)
                                                    elif s_ev.key == pygame.K_UP:
                                                        settings_selected = (settings_selected - 1) % 8
                                                    elif s_ev.key == pygame.K_DOWN:
                                                        settings_selected = (settings_selected + 1) % 8
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
                                                        config.set("game", "language", language)
                                                        taxi_mgr.set_language(language)
                                                        save_config(config)
                                                draw_settings_menu(screen, font, language, config.getfloat("audio", "master_volume"), config.getfloat("audio", "music_volume"), config.getfloat("audio", "effects_volume"), config.getboolean("audio", "comments_enabled", fallback=True), config.getboolean("audio", "subtitles_enabled", fallback=True), endpoint_text, settings_selected, SCREEN_W, SCREEN_H, physics_mode=physics_mode)
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
                    elif event.key == pygame.K_F8:
                        weather.toggle_rain()
                        logger.info("Weather toggled: %s", weather.weather_type.value)
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
            if on_foot:
                forward_input = float(keys[pygame.K_w] or keys[pygame.K_UP]) - float(
                    keys[pygame.K_s] or keys[pygame.K_DOWN]
                )
                steer_input = float(keys[pygame.K_a] or keys[pygame.K_LEFT]) - float(
                    keys[pygame.K_d] or keys[pygame.K_RIGHT]
                )
                sprinting = keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]
                walking_speed = 8.0 if sprinting else 4.0
                if forward_input > 0.0:
                    player_pedestrian.speed = min(
                        walking_speed, player_pedestrian.speed + ACCEL * dt
                    )
                elif forward_input < 0.0:
                    player_pedestrian.speed = max(
                        -walking_speed, player_pedestrian.speed - BRAKE * dt
                    )
                elif player_pedestrian.speed > 0.0:
                    player_pedestrian.speed = max(0.0, player_pedestrian.speed - FRICTION * dt)
                else:
                    player_pedestrian.speed = min(0.0, player_pedestrian.speed + FRICTION * dt)

                if abs(player_pedestrian.speed) > 0.05 and abs(steer_input) > 0.01:
                    steer_effective = STEER_RATE / (
                        1.0 + abs(player_pedestrian.speed) * STEER_SPEED_FACTOR
                    )
                    player_pedestrian.heading += (
                        steer_input
                        * steer_effective
                        * dt
                        * (1.0 if player_pedestrian.speed >= 0.0 else -1.0)
                    )
                player_pedestrian.x += math.cos(player_pedestrian.heading) * player_pedestrian.speed * dt
                player_pedestrian.y += math.sin(player_pedestrian.heading) * player_pedestrian.speed * dt
            immobilized = taxi_mgr.tree_wait_timer > 0.0
            throttle = 0.0 if on_foot or immobilized else (1.0 if keys[pygame.K_w] or keys[pygame.K_UP] else 0.0)
            brake = 0.0 if on_foot or immobilized else (1.0 if keys[pygame.K_s] or keys[pygame.K_DOWN] else 0.0)
            steer_left = 0.0 if on_foot else (1.0 if keys[pygame.K_a] or keys[pygame.K_LEFT] else 0.0)
            steer_right = 0.0 if on_foot else (1.0 if keys[pygame.K_d] or keys[pygame.K_RIGHT] else 0.0)

            current_way = get_current_road_at_car(
                car, ways=ways, spatial_grid=spatial_grid, car_roads_only=True, current_way=current_way
            )
            speed_limit_mps = None
            if speed_limiter_enabled and current_way:
                speed_limit_mps = current_way.speed_limit_kmh / 3.6
            red_light_limit_mps = None
            nearby_traffic_lights = traffic_mgr._nearby_traffic_lights(car.x, car.y)
            if red_light_assist_enabled:
                red_light_limit_mps = taxi_mgr.get_red_light_assist_speed_limit(
                    car, nearby_traffic_lights, traffic_mgr.sim_time
                )
            if red_light_limit_mps is not None:
                speed_limit_mps = (
                    red_light_limit_mps
                    if speed_limit_mps is None
                    else min(speed_limit_mps, red_light_limit_mps)
                )

            previous_position = (car.x, car.y)
            # Off-road driving is allowed at a reduced speed.
            if not on_foot:
                with frame_profiler.section("physics"):
                    update_car_physics(
                        car, throttle, brake, steer_left, steer_right, dt,
                        ways=ways, spatial_grid=spatial_grid,
                        block_offroad=False, speed_limit_mps=speed_limit_mps,
                        nearby_vehicles=[], parking_spaces=parking_spaces,
                        scenery_grid=scenery_grid,
                        current_way=current_way, physics_mode=physics_mode,
                        wetness=weather.wetness,
                    )
                car.braking = brake > 0.0 and car.speed > 0.05
                midpoint = (
                    (previous_position[0] + car.x) * 0.5,
                    (previous_position[1] + car.y) * 0.5,
                )
                entered_roadwork = any(
                    not work.contains(*previous_position, margin_m=2.0)
                    and (
                        work.contains(*midpoint, margin_m=2.0)
                        or work.contains(car.x, car.y, margin_m=2.0)
                    )
                    for work in roadworks
                )
                if entered_roadwork:
                    car.x, car.y = previous_position
                    car.speed = 0.0
                    taxi_mgr.notification_msg = tr(language, "roadwork_blocked")
                    taxi_mgr.notification_timer = 2.5
                else:
                    current_way = get_current_road_at_car(
                        car,
                        ways=ways,
                        spatial_grid=spatial_grid,
                        car_roads_only=True,
                        current_way=current_way,
                    )
                in_water = not entered_roadwork and is_car_fully_in_water(
                    car, waters, current_way=current_way
                )
                if in_water:
                    water_elapsed = min(10.0, water_elapsed + dt)
                    taxi_mgr.notification_msg = (
                        f"{tr(language, 'water_timer')}: {max(0.0, 10.0 - water_elapsed):.1f} s"
                    )
                    taxi_mgr.notification_timer = 0.2
                    if water_elapsed >= 10.0:
                        respawn_car(car, ways, waters=waters, taxi_stops=taxi_stops)
                        taxi_mgr.handle_respawn(car.x, car.y)
                        taxi_mgr.notification_msg = tr(language, "water_driving")
                        taxi_mgr.notification_timer = 1.5
                        water_elapsed = 0.0
                        last_track_position = None
                        last_track_surface = None
                else:
                    water_elapsed = 0.0
            if immobilized:
                car.speed = 0.0
            movement_distance = math.hypot(car.x - previous_position[0], car.y - previous_position[1])
            audio.update_acceleration(
                abs(car.speed) > 0.5 and (throttle > 0.0 or brake > 0.0)
            )
            audio.update_comments(dt)
            driven_distance = math.hypot(car.x - previous_position[0], car.y - previous_position[1])
            road_limit_mps = current_way.speed_limit_kmh / 3.6 if current_way else None
            rage_power = _rage_from_speeding(rage_power, car.speed, road_limit_mps, driven_distance)
            if abs(car.speed) * 3.6 < 10.0 and taxi_mgr.sees_red_light(
                car, nearby_traffic_lights, traffic_mgr.sim_time
            ):
                rage_power = min(1.0, rage_power + 0.05 * dt)
            if car.is_sliding:
                # Adrenaline from a hard, tire-losing-grip corner feeds the
                # rage meter too, same as speeding does.
                rage_power = min(1.0, rage_power + 0.15 * dt)
            if first_gameplay_frame:
                logger.info("Gameplay frame: physics complete")

            with frame_profiler.section("collisions"):
                building_crash = taxi_mgr.check_building_collision(
                    car, buildings, traffic_mgr.sim_time, previous_position, ways=ways
                )
                tree_crash = taxi_mgr.check_tree_collision(
                    car, sceneries, traffic_mgr.sim_time, previous_position, ways=ways
                )
                fence_crash = taxi_mgr.check_fence_collision(
                    car, sceneries, traffic_mgr.sim_time, previous_position
                )
                taxi_mgr.check_curb_bump(
                    car, curbs, previous_position, traffic_mgr.sim_time, curb_grid=curb_grid
                )
                taxi_mgr.check_speed_bump(
                    car, speed_bumps, previous_position, traffic_mgr.sim_time
                )
                bridge_edge_crash = is_car_colliding_with_bridge_edge(car, current_way, ways=ways)
                if bridge_edge_crash:
                    pull_car_inside_bridge_edge(car, current_way)
                    # Bounce away from the rail so a held throttle cannot keep
                    # the car pinned against the same bridge edge.
                    car.speed = -max(2.5, min(abs(car.speed), 6.0))
                    taxi_mgr.taxi_smoke_timer = max(taxi_mgr.taxi_smoke_timer, 5.0)
                    if bridge_edge_crash_cooldown <= 0.0:
                        bridge_edge_crash_cooldown = 3.0
                        taxi_mgr.total_score -= 200
                        taxi_mgr.notification_msg = tr(language, "bridge_crash", penalty=200)
                        taxi_mgr.notification_timer = 3.5
            if building_crash or tree_crash or fence_crash or bridge_edge_crash:
                audio.play("car-crash", volume=0.7)
                audio.play_driver_line("collision", language)
            if first_gameplay_frame:
                logger.info("Gameplay frame: collision checks complete")

            # Dynamic lookahead camera offset in vehicle driving direction
            # Look ahead proportionally to car speed and heading, clamped to a percentage of viewport so car remains visible
            max_lead_screen_px = min(SCREEN_W, SCREEN_H) * 0.25
            max_lead_m = max_lead_screen_px / max(0.01, px_per_m)
            lead_distance_m = min(max_lead_m, max(0.0, abs(car.speed) * 0.8))

            focus_x = player_pedestrian.x if on_foot else car.x
            focus_y = player_pedestrian.y if on_foot else car.y
            target_camx = focus_x + math.cos(car.heading) * lead_distance_m
            target_camy = focus_y + math.sin(car.heading) * lead_distance_m

            # Smooth camera lerp
            cam_lerp_factor = min(1.0, 4.0 * dt)
            camx += (target_camx - camx) * cam_lerp_factor
            camy += (target_camy - camy) * cam_lerp_factor

            viewport_bounds = get_viewport_bounds(camx, camy, px_per_m=px_per_m, margin_m=30.0)

            # Update taxi missions & pickups
            previous_taxi_state = taxi_mgr.state
            previous_passenger = taxi_mgr.current_passenger
            previous_nausea_warning_timer = (
                previous_passenger.nausea_warning_timer if previous_passenger is not None else 0.0
            )
            previous_nausea_resolved = (
                previous_passenger.nausea_resolved if previous_passenger is not None else False
            )
            with frame_profiler.section("taxi"):
                taxi_mgr.update(car, dt, game_time_seconds=game_time_seconds)
            vomited_passenger = taxi_mgr.take_vomited_passenger(car)
            if vomited_passenger is not None:
                audio.play_passenger_line("Nyt alkaa jo helpottaa.", vomited_passenger.gender, language, vomited_passenger.name)
                passenger_pedestrian = pedestrian_mgr.spawn_pedestrian_at(
                    vomited_passenger.ped_x,
                    vomited_passenger.ped_y,
                    heading=vomited_passenger.ped_heading,
                )
                if passenger_pedestrian is not None:
                    pedestrian_mgr.pedestrians.append(passenger_pedestrian)
            current_passenger = taxi_mgr.current_passenger
            if (
                current_passenger is not None
                and not previous_nausea_resolved
                and current_passenger.nausea_resolved
            ):
                audio.play_passenger_line("Nyt alkaa jo helpottaa.", current_passenger.gender, language, current_passenger.name)
            if (
                current_passenger is not None
                and previous_nausea_warning_timer <= 0.0
                and current_passenger.nausea_warning_timer > 0.0
            ):
                audio.play_passenger_line_for_situation("nausea", current_passenger.gender, language, current_passenger.name)
                audio.play_passenger_line(
                    "Voisitko pysähtyä hetkeksi, tarvitsen raitista ilmaa.",
                    current_passenger.gender,
                    language,
                    current_passenger.name,
                )
            audio.update_passenger_speech(
                taxi_mgr.current_passenger is not None
                and taxi_mgr.state == TaxiState.DRIVING_TO_DROPOFF,
                taxi_mgr.current_passenger.gender if taxi_mgr.current_passenger else "woman",
                language,
                dt,
                taxi_mgr.current_passenger.name if taxi_mgr.current_passenger else None,
            )
            if (
                previous_taxi_state == TaxiState.CLIENT_WALKING_TO_CAR
                and taxi_mgr.state == TaxiState.DRIVING_TO_DROPOFF
            ):
                audio.play_passenger_line_for_situation(
                    "pickup", taxi_mgr.current_passenger.gender if taxi_mgr.current_passenger else "woman", language,
                    taxi_mgr.current_passenger.name if taxi_mgr.current_passenger else None,
                )
                audio.play_driver_line("pickup", language)
                audio.play("car-door-open")
            elif (
                previous_taxi_state == TaxiState.DRIVING_TO_DROPOFF
                and previous_passenger is not None
                and taxi_mgr.current_passenger is None
                and vomited_passenger is None
            ):
                audio.play_passenger_line_for_situation("dropoff", previous_passenger.gender, language, previous_passenger.name)
                audio.play_driver_line("dropoff", language)
                audio.play("car-door-open")
                passenger_pedestrian = pedestrian_mgr.spawn_pedestrian_at(
                    car.x + math.sin(car.heading) * 1.8,
                    car.y - math.cos(car.heading) * 1.8,
                    heading=car.heading,
                )
                if passenger_pedestrian is not None:
                    pedestrian_mgr.pedestrians.append(passenger_pedestrian)
            if career is None and taxi_mgr.completed_fares > saved_gig_fares:
                save_gig_odometer(gig_odometer_file, car.odometer_m)
                saved_gig_fares = taxi_mgr.completed_fares
            if career is not None and taxi_mgr.total_score >= CAREER_SCORE_LIMIT:
                career_index = int(career["city_index"])
                career_total_score = int(career["total_score"]) + taxi_mgr.total_score
                next_city_index = career_index + 1
                if next_city_index >= len(cities_list):
                    save_career(
                        career_file, career_index, career_total_score, completed=True,
                        total_distance_m=car.odometer_m,
                    )
                    city_summary = (chosen_city, taxi_mgr.total_score, taxi_mgr.completed_fares, None, career_total_score)
                    logger.info("Career completed in Helsinki")
                    running = False
                else:
                    save_career(
                        career_file, next_city_index, career_total_score,
                        total_distance_m=car.odometer_m,
                    )
                    next_city = list(reversed(cities_list))[next_city_index]
                    active_city_name = next_city
                    city_summary = (chosen_city, taxi_mgr.total_score, taxi_mgr.completed_fares, next_city, career_total_score)
                    logger.info("Career advanced to %s", active_city_name)
                    running = False
            was_wrong_way = taxi_mgr.wrong_way_duration > 0.0
            if slow_check_elapsed >= 0.1:
                slow_check_dt = slow_check_elapsed
                slow_check_elapsed = 0.0
                if taxi_mgr.check_wrong_way_violation(car, slow_check_dt, ways=ways, spatial_grid=spatial_grid):
                    if not was_wrong_way:
                        audio.play_driver_line("wrong_way", language)
                if taxi_mgr.check_speed_cameras(car, speed_cameras):
                    audio.play_driver_line("speed_camera", language)
            # Advance signals and taxi-world time; no autonomous vehicle update.
            with frame_profiler.section("traffic"):
                traffic_mgr.advance_time(dt)
            if not taxi_mgr.current_passenger and taxi_waiter_elapsed >= 0.2:
                taxi_waiter_elapsed = 0.0
                pedestrian_mgr.ensure_taxi_stop_waiter(taxi_stops, car, viewport_bounds=viewport_bounds)
            with frame_profiler.section("pedestrians"):
                pedestrian_mgr.update(
                    car, dt, viewport_bounds=viewport_bounds,
                    game_time_seconds=game_time_seconds,
                )
            frame_profiler.set_metric("visible_npcs", sum(
                viewport_bounds[0] <= npc.x <= viewport_bounds[2]
                and viewport_bounds[1] <= npc.y <= viewport_bounds[3]
                for npc in ()
            ))
            frame_profiler.set_metric("visible_pedestrians", sum(
                viewport_bounds[0] <= ped.x <= viewport_bounds[2]
                and viewport_bounds[1] <= ped.y <= viewport_bounds[3]
                for ped in pedestrian_mgr.pedestrians
            ))
            frame_profiler.set_metric("active_residents", len(traffic_mgr.residents.residents))
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
            traffic_mgr.let_taxi_pick_up_waiter(taxi_stops, pedestrian_mgr.pedestrians, dt)
            waiting_pedestrian = taxi_mgr.check_waiting_pickup(car, pedestrian_mgr.pedestrians, dt)
            if waiting_pedestrian is not None:
                pedestrian_mgr.pedestrians.remove(waiting_pedestrian)

            # Keep road logic on car roads, but recognize pedestrian ways as paved surfaces.
            surface_way = get_current_road_at_car(
                car,
                ways=ways,
                spatial_grid=spatial_grid,
                car_roads_only=False,
            )
            current_way = get_current_road_at_car(car, ways=ways, spatial_grid=spatial_grid, car_roads_only=True, current_way=current_way)
            on_road = current_way is not None
            is_grass = (
                surface_way is None
                and not is_point_on_parking_space(car.x, car.y, parking_spaces)
                and not is_point_in_parking_lot(car.x, car.y, scenery_grid=scenery_grid)
            )
            # Tire slip is the source of truth for a skidmark (SKIDMARK.md) -
            # not brake input, not even is_sliding alone (a tire can be
            # visibly slipping before the whole car counts as sliding; see
            # skidmark_should_mark's lower threshold).
            is_skidding = skidmark_should_mark(car.slip_amount)
            if movement_distance > 0.0 and (is_skidding or (is_grass and abs(car.speed) > 1.0)):
                start_new_trail = last_track_position is None or is_grass != last_track_surface
                if start_new_trail or math.hypot(car.x - last_track_position[0], car.y - last_track_position[1]) >= 1.0:
                    # The grass trail isn't a slip mark - it's a constant-
                    # weight dirt track from driving off-road at all.
                    intensity = skidmark_intensity(car.slip_amount) if is_skidding else 1.0
                    if start_new_trail:
                        tire_tracks.append(TireTrail(is_grass, car.x, car.y, car.heading, intensity))
                    else:
                        tire_tracks[-1].add(car.x, car.y, car.heading, intensity)
                    tire_track_point_count += 1
                    last_track_position = (car.x, car.y)
                    last_track_surface = is_grass
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
                # Drain every tile that has already finished background-fetching
                # in one pass (bounded by the 3x3 active region, 9 tiles) rather
                # than one per frame. The grid rebuilds below are O(total ways/
                # buildings) regardless of how many tiles were just integrated,
                # so draining several tiles across several frames used to pay
                # that same full-rebuild cost once per frame instead of once
                # per burst - a multi-frame stall right when several tiles
                # complete around the same time (e.g. a fast or diagonal move).
                integrated_tiles = auto_fetch_manager.integrate_completed_tiles(max_tiles=9)
                if integrated_tiles:
                    # Static render/collision indexes must match the live lists
                    # immediately; service graphs can continue in later stages.
                    with frame_profiler.section("map_sync:spatial_grid_immediate"):
                        spatial_grid.rebuild(ways)
                    with frame_profiler.section("map_sync:building_grid_immediate"):
                        building_grid.rebuild(buildings)
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
                    or len(waters) != water_grid.indexed_way_count
                    or len(crossings) != crossing_grid.indexed_way_count
                    or len(curbs) != curb_grid.indexed_way_count
                    or len(railways) != railway_grid.indexed_way_count
                    or len(railings) != railing_grid.indexed_way_count
                    or len(traffic_lights) != traffic_light_grid.indexed_way_count
                )
                if _map_sync_should_start(
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
                    with frame_profiler.section("map_sync:remove_trees"):
                        remove_trees_under_roads(sceneries, ways)
                    map_sync_stage = 2
                elif map_sync_stage == 2:
                    with frame_profiler.section("map_sync:spatial_grid"):
                        spatial_grid.rebuild(ways)
                    map_sync_stage = 3
                elif map_sync_stage == 3:
                    with frame_profiler.section("map_sync:building_grid"):
                        building_grid.rebuild(buildings)
                    map_sync_stage = 4
                elif map_sync_stage == 4:
                    with frame_profiler.section("map_sync:scenery_grid"):
                        scenery_grid.rebuild(sceneries)
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
                    with frame_profiler.section("map_sync:traffic"):
                        traffic_mgr.sync_map_data(
                            ways,
                            traffic_lights=traffic_lights,
                            stop_signs=stop_signs,
                            crossings=crossings,
                            buildings=buildings,
                            sceneries=sceneries,
                            parking_spaces=parking_spaces,
                            logical_intersections=logical_intersections,
                        )
                    map_sync_stage = 13
                elif map_sync_stage == 13:
                    with frame_profiler.section("map_sync:pedestrians"):
                        pedestrian_mgr.sync_map_data(
                            ways, traffic_lights=traffic_lights, logical_intersections=logical_intersections,
                        )
                        pedestrian_mgr.set_venue_buildings(buildings)
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
            draw_grass_texture(screen, camx, camy, px_per_m, profiler=frame_profiler)
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
            )
            stage_elapsed = time.perf_counter() - map_stage_start
            render_profile_times["map_scenery"] = render_profile_times.get("map_scenery", 0.0) + stage_elapsed
            frame_profiler.record("render:scenery", stage_elapsed * 1000.0)
            if first_gameplay_frame:
                logger.info("Gameplay frame: rendering water")
            map_stage_start = time.perf_counter()
            draw_waters(
                screen, waters, camx, camy, px_per_m=px_per_m,
                spatial_grid=water_grid, profiler=frame_profiler,
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
            stage_elapsed = time.perf_counter() - map_stage_start
            render_profile_times["map_roads"] = render_profile_times.get("map_roads", 0.0) + stage_elapsed
            frame_profiler.record("render:roads", stage_elapsed * 1000.0)
            # Trees are drawn here, after roads/parking - not inside
            # draw_scenery() above - so a road or parking surface (both
            # just painted) can never end up covering a real tree (see
            # render/scenery.py:draw_trees docstring).
            map_stage_start = time.perf_counter()
            draw_trees(
                screen,
                sceneries,
                camx,
                camy,
                px_per_m=px_per_m,
                tree_effects=taxi_mgr.tree_effects,
                fallen_trees=taxi_mgr.fallen_trees,
                spatial_grid=scenery_grid,
                ways=ways,
                road_spatial_grid=spatial_grid,
                profiler=frame_profiler,
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
                    npc for npc in ()
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
                npc for npc in () if getattr(npc, "is_on_foot", False)
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
            if car.engine_on and not on_foot:
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
            # Bridge track only here, redrawn after the car/pedestrians
            # above (see the only_bridges=False call near draw_ways) so an
            # elevated railway actually covers whatever's underneath it -
            # matches the bridge the screenshot flagged, where the taxi
            # rendered on top of a rail bridge it was really driving under.
            draw_railways(
                screen, railways, camx, camy, px_per_m=px_per_m, spatial_grid=railway_grid, only_bridges=True,
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
                draw_rain(screen, weather)

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
                render_profile_times.clear()
                render_profile_last_log = time.perf_counter()
            render_profile_times["count"] = render_profile_times.get("count", 0) + 1

            # Draw HUD and compass
            current_target = taxi_mgr.get_current_target()
            target_coords = (current_target.x, current_target.y) if current_target else None
            current_limit_kmh = getattr(current_way, "speed_limit_kmh", None) if current_way else None

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
                rage_power=rage_power,
                language=language,
                career_total_distance_m=car.odometer_m if career is not None else None,
                water_time_remaining=(10.0 - water_elapsed) if water_elapsed > 0.0 else None,
                game_time_seconds=game_time_seconds,
                game_time_realtime=taxi_mgr.current_passenger is not None,
                comment_text=audio.comment_text,
                comment_speaker=audio.comment_speaker,
                comment_speaker_name=audio.comment_speaker_name,
                subtitles_enabled=config.getboolean("audio", "subtitles_enabled", fallback=True),
                fps=clock.get_fps(),
                show_debug_hud=show_debug_hud,
                hud_layout=hud_layout,
                hud_rects=hud_rects,
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
                draw_resident_popup(
                    screen,
                    small_font,
                    traffic_mgr.residents.get(selected_resident_id),
                    traffic_mgr.residents,
                    SCREEN_W,
                    SCREEN_H,
                    pedestrian=selected_pedestrian,
                )
            if awaiting_start:
                draw_game_start_overlay(screen, font, chosen_city, SCREEN_W, SCREEN_H)
            elif start_hint_remaining > 0.0 and on_foot:
                draw_game_start_hint(screen, font, SCREEN_W)

            if first_gameplay_frame:
                logger.info("Gameplay frame: flipping display")
            frame_profiler.record(
                "rendering", (time.perf_counter() - render_profiler_start) * 1000.0
            )
            frame_profiler.end_frame()
            draw_frame_profiler(
                screen, small_font, frame_profiler,
                0, len(pedestrian_mgr.pedestrians),
            )
            if show_debug_hud:
                draw_g_force_meter(
                    screen, small_font, car.forward_g, car.lateral_g, car.is_sliding,
                    grip_usage=car.grip_usage, max_grip_g=car.max_grip_g,
                )
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
            )
        elif career is None:
            save_gig_odometer(gig_odometer_file, car.odometer_m)

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
