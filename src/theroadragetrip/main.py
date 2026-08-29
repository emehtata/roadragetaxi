import argparse
import logging
import math
import os
import random
import sys
from typing import Optional, Tuple

from .geo import clamp, dist_point_to_segment, meters_to_latlon
from .audio import AudioManager
from .config import cities_from_config, get_optional_int, load_config, save_config
from .localization import LANGUAGE_NAMES, SUPPORTED_LANGUAGES, normalize_language, tr
from .osm import (
    BBOX_PRESETS,
    CITY_CENTERS,
    DEFAULT_BBOX,
    DEFAULT_OVERPASS_ENDPOINTS,
    DEFAULT_ROAD_HALF_WIDTH_M,
    HIGHWAY_HALF_WIDTH,
    AutoFetchManager,
    Building,
    Place,
    Scenery,
    TaxiStop,
    TrafficLight,
    Water,
    Way,
    build_ways,
    configure_user_agent,
    fetch_osm_ways,
    load_local_sample,
    load_osm_cache,
    save_osm_cache,
)
from .physics import (
    ACCEL,
    BRAKE,
    FRICTION,
    MAX_SPEED,
    STEER_RATE,
    STEER_SPEED_FACTOR,
    Car,
    SpatialWayGrid,
    get_current_road_at_car,
    is_on_road,
    reset_trip,
    respawn_car,
    update_car_physics,
)
from .render import (
    FPS,
    PX_PER_M,
    SCREEN_H,
    SCREEN_W,
    draw_buildings,
    draw_car,
    draw_cyclists,
    draw_city_selection_menu,
    draw_compass,
    draw_crossings,
    draw_hud,
    draw_help_screen,
    draw_labels,
    draw_loading_screen,
    draw_npc_cars,
    draw_pause_menu,
    draw_settings_menu,
    draw_pedestrians,
    draw_phone_offers,
    draw_scenery,
    draw_taxi_smoke,
    draw_speed_cameras,
    draw_taxi_stops,
    draw_taxi_target,
    draw_traffic_lights,
    draw_waters,
    draw_ways,
    get_viewport_bounds,
    world_to_screen,
)
from .pedestrian import CyclistManager, PedestrianManager
from .police import place_speed_cameras
from .taxi import TaxiManager
from .traffic import TrafficManager, recommended_traffic_count

# Maintain BBOX constant for backward compatibility
BBOX = DEFAULT_BBOX

logger = logging.getLogger(__name__)
RAGE_SHOUTS = ("PRKL!", "STNA!", "VTTU!", "HLVT!", "KRPÄ!", "KSPÄ!", "PSKA!")
RAGE_DISTANCE_TO_FULL_M = 400.0
RAGE_SHOUT_COST = 0.25


def parse_args(config=None, city_names=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="The Road Rage Trip (OSM PoC)")
    game = config["game"] if config else {}
    map_config = config["map"] if config else {}
    traffic_config = config["traffic"] if config else {}
    p.add_argument("--bbox", type=str, default=game.get("bbox") or None, help="south,west,north,east (lat/lon)")
    p.add_argument(
        "--preset",
        type=str,
        choices=city_names or list(BBOX_PRESETS.keys()),
        default=game.get("preset") or None,
        help="Named bounding box preset (e.g., oulu, helsinki, tampere, espoo)",
    )
    p.add_argument("--no-menu", action="store_true", default=game.getboolean("no_menu", fallback=False), help="Skip interactive city menu")
    p.add_argument("--force-refresh", action="store_true", default=game.getboolean("force_refresh", fallback=False), help="Force refresh from Overpass (ignore cache)")
    p.add_argument("--use-sample", action="store_true", default=game.getboolean("use_sample", fallback=False), help="Use bundled sample OSM data and skip Overpass")
    p.add_argument("--px-per-m", type=float, default=game.getfloat("px_per_m", fallback=9.0), help="Initial pixels per meter (zoom)")
    p.add_argument("--log-level", type=str, default=game.get("log_level", "INFO"), help="Logging level (DEBUG/INFO/WARNING)")
    p.add_argument("--no-cache", action="store_true", default=game.getboolean("no_cache", fallback=False), help="Disable cache usage (treated like force-refresh)")

    # Auto-fetching nearby map tiles when the car approaches the bbox edge
    p.add_argument("--no-auto-fetch", dest="auto_fetch", action="store_false", default=map_config.getboolean("auto_fetch", fallback=True), help="Disable on-demand map expansion")
    p.add_argument(
        "--fetch-margin",
        type=float,
        default=map_config.getfloat("fetch_margin", fallback=350.0),
        help="Distance in meters from bbox edge that triggers auto-fetch",
    )
    p.add_argument("--fetch-tile-size", type=float, default=map_config.getfloat("fetch_tile_size", fallback=2500.0), help="Meters to expand when auto-fetching")
    p.add_argument(
        "--build-in-process",
        action="store_true",
        default=map_config.getboolean("build_in_process", fallback=True),
        help="Build auto-fetched map data outside the gameplay process",
    )
    p.add_argument(
        "--traffic-count",
        type=int,
        default=get_optional_int(config, "traffic", "traffic_count") if config else None,
        help="Target number of NPC cars (default: scales with available streets, capped at 50)",
    )
    p.add_argument("--pedestrian-count", type=int, default=traffic_config.getint("pedestrian_count", fallback=20), help="Target number of pedestrians")
    p.add_argument("--cyclist-count", type=int, default=traffic_config.getint("cyclist_count", fallback=8), help="Target number of cyclists")

    return p.parse_args()


def configure_logging(level: Optional[str] = None) -> None:
    lvl = os.getenv("LOG_LEVEL", level or "INFO").upper()
    logging.basicConfig(level=getattr(logging, lvl, logging.INFO), format="%(levelname)s: %(message)s")


def choose_language(screen, font, clock, current_language: str = "fi") -> str:
    """Show the first-run language chooser."""
    import pygame

    selected = SUPPORTED_LANGUAGES.index(normalize_language(current_language))
    while True:
        clock.tick(30)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit(0)
            if event.type != pygame.KEYDOWN:
                continue
            if event.key in (pygame.K_LEFT, pygame.K_UP):
                selected = (selected - 1) % len(SUPPORTED_LANGUAGES)
            elif event.key in (pygame.K_RIGHT, pygame.K_DOWN):
                selected = (selected + 1) % len(SUPPORTED_LANGUAGES)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
                return SUPPORTED_LANGUAGES[selected]
            elif pygame.K_1 <= event.key <= pygame.K_9:
                index = event.key - pygame.K_1
                if index < len(SUPPORTED_LANGUAGES):
                    return SUPPORTED_LANGUAGES[index]

        language = SUPPORTED_LANGUAGES[selected]
        screen.fill((18, 24, 32))
        title = font.render(tr(language, "select_language"), True, (245, 245, 245))
        screen.blit(title, title.get_rect(center=(screen.get_width() // 2, 180)))
        for index, code in enumerate(SUPPORTED_LANGUAGES):
            color = (255, 215, 95) if index == selected else (210, 220, 230)
            label = font.render(f"{index + 1}. {LANGUAGE_NAMES[code]}", True, color)
            screen.blit(label, label.get_rect(center=(screen.get_width() // 2, 280 + index * 55)))
        hint = pygame.font.SysFont(None, 18).render(tr(language, "language_hint"), True, (150, 175, 195))
        screen.blit(hint, hint.get_rect(center=(screen.get_width() // 2, screen.get_height() - 80)))
        pygame.display.flip()
from .traffic import MAX_TRAFFIC_COUNT, TrafficManager, recommended_traffic_count, traffic_count_for_zoom


def main() -> None:
    config = load_config()
    configure_user_agent(config.get("game", "user_agent_id"))
    city_centers, bbox_presets = cities_from_config(config)
    args = parse_args(config, city_names=list(bbox_presets))
    configure_logging(args.log_level)

    try:
        global pygame
        import pygame as _pygame

        pygame = _pygame
    except Exception as e:
        logger.error("Missing runtime dependency 'pygame': %s", e)
        logger.error("Install dependencies with: pip3 install -r requirements.txt")
        logger.error(
            "Or for headless runs (CI): set SDL_VIDEODRIVER=dummy and install headless compatible packages."
        )
        sys.exit(1)

    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.display.set_caption("The Road Rage Trip (OSM PoC)")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont(None, 24)
    small_font = pygame.font.SysFont(None, 18)

    language = normalize_language(config.get("game", "language", fallback=""))
    if not config.get("game", "language", fallback="").strip():
        language = choose_language(screen, font, clock)
        config.set("game", "language", language)
        save_config(config)

    audio = AudioManager(
        master_volume=config.getfloat("audio", "master_volume", fallback=1.0),
        music_volume=config.getfloat("audio", "music_volume", fallback=0.2),
        effects_volume=config.getfloat("audio", "effects_volume", fallback=1.0),
    )

    # Outer game loop to support picking new starting city without restarting process
    app_running = True
    active_city_name = None

    while app_running:
        cities_list = list(city_centers.keys())
        selected_city_idx = 0

        # Show city selection menu if no explicit CLI override or when requested from pause menu
        if active_city_name is not None or (
            not args.bbox
            and not args.preset
            and not args.use_sample
            and not args.no_menu
        ):
            if active_city_name is not None and active_city_name in cities_list:
                selected_city_idx = cities_list.index(active_city_name)
            in_menu = True
            intro_until = pygame.time.get_ticks() + 1000
            while in_menu:
                clock.tick(30)
                for ev in pygame.event.get():
                    if ev.type == pygame.QUIT:
                        pygame.quit()
                        sys.exit(0)
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
                        elif ev.key in (pygame.K_LEFT, pygame.K_RIGHT):
                            selected_city_idx = (selected_city_idx + 5) % len(cities_list)
                        elif pygame.K_1 <= ev.key <= pygame.K_9:
                            idx = ev.key - pygame.K_1
                            if idx < len(cities_list):
                                selected_city_idx = idx
                                in_menu = False
                        elif ev.key in (pygame.K_0, pygame.K_KP0):
                            selected_city_idx = 9
                            in_menu = False
                        elif pygame.K_KP1 <= ev.key <= pygame.K_KP9:
                            idx = ev.key - pygame.K_KP1
                            if idx < len(cities_list):
                                selected_city_idx = idx
                                in_menu = False

                if pygame.time.get_ticks() < intro_until:
                    draw_loading_screen(screen, font, 1.0, "Ready", SCREEN_W, SCREEN_H, show_details=False)
                else:
                    draw_city_selection_menu(screen, font, cities_list, selected_city_idx, SCREEN_W, SCREEN_H, language)
                pygame.display.flip()

            chosen_city = cities_list[selected_city_idx]
            camera_city_name = chosen_city
            bbox = bbox_presets.get(chosen_city.lower(), DEFAULT_BBOX)
            logger.info("Selected starting city: %s (bbox: %s)", chosen_city, bbox)
        else:
            preset_key = args.preset.lower() if args.preset else "oulu"
            camera_city_name = args.preset
            bbox = bbox_presets.get(preset_key, DEFAULT_BBOX)
            if args.bbox:
                try:
                    parts = [float(p.strip()) for p in args.bbox.split(",")]
                    if len(parts) == 4:
                        bbox = (parts[0], parts[1], parts[2], parts[3])
                except Exception:
                    logger.warning("Invalid bbox provided, using default preset (%s)", preset_key)

        def on_load_progress(fraction: float, message: str) -> None:
            draw_loading_screen(screen, font, fraction, message)
            pygame.display.flip()
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit(0)

        on_load_progress(0.05, "Initializing scenery engine...")

        def on_build_progress(fraction: float, message: str) -> None:
            # Map construction is only part of startup; reserve final progress for manager setup.
            on_load_progress(min(0.9, fraction * 0.9), message)

        # Load map
        try:
            if args.use_sample:
                on_load_progress(0.2, "Loading bundled offline sample data...")
                elements = load_local_sample()
                if elements is None:
                    raise Exception("No local sample file found")
                logger.info("Using local sample (via --use-sample)")
                on_load_progress(0.5, f"Loaded {len(elements)} sample elements")
            else:
                elements = fetch_osm_ways(
                    bbox,
                    progress_callback=on_load_progress,
                    force_refresh=args.force_refresh or args.no_cache,
                )
            res = build_ways(elements, progress_callback=on_build_progress)
            crossings = getattr(res, "crossings", [])
            if len(res) == 8:
                ways, waters, buildings, sceneries, places, bounds, traffic_lights, crossings = res
            elif len(res) == 7:
                ways, waters, buildings, sceneries, places, bounds, traffic_lights = res
            else:
                ways, waters, buildings, sceneries, places, bounds = res[:6]
                traffic_lights = getattr(res, "traffic_lights", [])
        except Exception as e:
            logger.error("Failed to load OSM data: %s", e)
            sys.exit(1)

        if not ways and not waters and not buildings and not sceneries and not places:
            logger.error("No map features found in bbox. Try a different bbox.")
            sys.exit(1)

        minx, miny, maxx, maxy = bounds
        taxi_stops = getattr(res, "taxi_stops", [])
        on_load_progress(0.92, "Preparing road index...")
        # Spatial index for fast O(1) road collision detection
        spatial_grid = SpatialWayGrid()
        spatial_grid.rebuild(ways)

        # Spawn car on a road near center (avoiding water)
        car = Car(x=(minx + maxx) / 2, y=(miny + maxy) / 2, heading=0.0, speed=0.0)
        if ways:
            respawn_car(car, ways, near_center=True, bounds=bounds, waters=waters, taxi_stops=taxi_stops)

        # Initialize Taxi Manager for game mode
        on_load_progress(0.94, "Preparing taxi missions...")
        taxi_mgr = TaxiManager(ways, places=places, buildings=buildings, taxi_stops=taxi_stops, language=language)
        police_config = config["police"]
        taxi_stop_cameras = police_config.getboolean("taxi_stop_cameras", fallback=False)
        speed_cameras = place_speed_cameras(
            ways,
            bounds,
            camera_city_name,
            taxi_stops=taxi_stops if taxi_stop_cameras else None,
        )
        logger.info("Placed %d hidden speed cameras", len(speed_cameras))

        # Initialize autonomous Traffic Manager for NPC cars
        on_load_progress(0.96, "Preparing traffic...")
        traffic_count = args.traffic_count
        if traffic_count is None:
            traffic_count = recommended_traffic_count(ways)
        traffic_count = max(0, min(MAX_TRAFFIC_COUNT, traffic_count))
        base_traffic_count = traffic_count
        logger.info("Target NPC traffic: %d cars for %d road ways", traffic_count, len(ways))
        traffic_mgr = TrafficManager(
            ways,
            target_count=traffic_count,
            traffic_lights=traffic_lights,
            crossings=crossings,
        )

        # Initialize autonomous Pedestrian Manager
        on_load_progress(0.98, "Preparing pedestrians...")
        pedestrian_mgr = PedestrianManager(ways, target_count=args.pedestrian_count, traffic_lights=traffic_lights)
        cyclist_mgr = CyclistManager(ways, target_count=args.cyclist_count, traffic_lights=traffic_lights)
        base_pedestrian_count = pedestrian_mgr.target_count
        base_cyclist_count = cyclist_mgr.target_count

        # Prepare transformer for meters->latlon display
        try:
            from pyproj import Transformer

            transformer_to_ll = Transformer.from_crs("EPSG:3067", "EPSG:4326", always_xy=True)
        except Exception:
            transformer_to_ll = None
            logger.debug("pyproj not available; lat/lon display disabled")

        # Auto fetch manager (background)
        on_load_progress(0.99, "Starting game...")
        auto_fetch_manager = AutoFetchManager(
            ways,
            bounds,
            transformer_to_ll,
            waters=waters,
            buildings=buildings,
            sceneries=sceneries,
            places=places,
            traffic_lights=traffic_lights,
            crossings=crossings,
            fetch_func=fetch_osm_ways,
            build_func=build_ways,
            build_in_process=args.build_in_process,
        )
        on_load_progress(1.0, "Ready")
        logger.info("Entering gameplay loop")

        show_labels = True
        speed_limiter_enabled = True
        red_light_assist_enabled = False
        phone_open = False
        rage_shout_timer = 0.0
        rage_shout_text = RAGE_SHOUTS[0]
        rage_power = 0.0
        running = True
        current_way = get_current_road_at_car(car, ways=ways, spatial_grid=spatial_grid, car_roads_only=True)
        zoom_target = args.px_per_m if args.px_per_m is not None else 9.0
        px_per_m = max(0.25, zoom_target * 0.03)
        zoom_elapsed = 0.0
        zoom_duration = 3.0
        camx, camy = car.x, car.y
        first_gameplay_frame = True
        map_sync_stage = 0
        clock.tick()  # Reset clock timer to avoid large dt on first frame

        while running:
            dt = min(clock.tick(FPS) / 1000.0, 0.1)  # Clamp delta-time to prevent physics tunneling on lag spikes
            if first_gameplay_frame:
                logger.info("Gameplay frame: start")

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                    app_running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_p:
                        phone_open = not phone_open
                    elif event.key == pygame.K_SPACE and not phone_open:
                        if rage_power >= RAGE_SHOUT_COST:
                            traffic_mgr.rage_shout(car)
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
                        # Pause menu with options: Continue Game, Change City, Exit Game
                        pause_options = [
                            tr(language, "continue"), tr(language, "help"), tr(language, "settings_menu"),
                            tr(language, "change_city"), tr(language, "exit"),
                        ]
                        pause_selected = 0
                        is_paused = True

                        while is_paused:
                            clock.tick(30)
                            for p_ev in pygame.event.get():
                                if p_ev.type == pygame.QUIT:
                                    pygame.quit()
                                    sys.exit(0)
                                elif p_ev.type == pygame.KEYDOWN:
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
                                                draw_help_screen(screen, font, SCREEN_W, SCREEN_H, language)
                                                pygame.display.flip()
                                        elif pause_selected == 2:
                                            settings_selected = 0
                                            in_settings = True
                                            while in_settings:
                                                clock.tick(30)
                                                for s_ev in pygame.event.get():
                                                    if s_ev.type == pygame.QUIT:
                                                        pygame.quit()
                                                        sys.exit(0)
                                                    if s_ev.type != pygame.KEYDOWN:
                                                        continue
                                                    if s_ev.key == pygame.K_ESCAPE:
                                                        in_settings = False
                                                    elif s_ev.key == pygame.K_UP:
                                                        settings_selected = (settings_selected - 1) % 4
                                                    elif s_ev.key == pygame.K_DOWN:
                                                        settings_selected = (settings_selected + 1) % 4
                                                    elif s_ev.key in (pygame.K_LEFT, pygame.K_RIGHT):
                                                        delta = 0.05 if s_ev.key == pygame.K_RIGHT else -0.05
                                                        if settings_selected == 0:
                                                            language = SUPPORTED_LANGUAGES[(SUPPORTED_LANGUAGES.index(language) + (1 if delta > 0 else -1)) % 2]
                                                        else:
                                                            key = ("master_volume", "music_volume", "effects_volume")[settings_selected - 1]
                                                            value = max(0.0, min(1.0, config.getfloat("audio", key) + delta))
                                                            config.set("audio", key, f"{value:.2f}")
                                                            audio.set_volume(key.removesuffix("_volume"), value)
                                                        config.set("game", "language", language)
                                                        taxi_mgr.set_language(language)
                                                        save_config(config)
                                                draw_settings_menu(screen, font, language, config.getfloat("audio", "master_volume"), config.getfloat("audio", "music_volume"), config.getfloat("audio", "effects_volume"), settings_selected, SCREEN_W, SCREEN_H)
                                                pygame.display.flip()
                                        elif pause_selected == 3:
                                            # Change City
                                            is_paused = False
                                            running = False
                                            active_city_name = cities_list[selected_city_idx]
                                        elif pause_selected == 4:
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
                            draw_help_screen(screen, font, SCREEN_W, SCREEN_H, language)
                            pygame.display.flip()
                        clock.tick()
                    elif event.key == pygame.K_r:
                        respawn_car(car, ways, waters=waters, taxi_stops=taxi_stops)
                        camx, camy = car.x, car.y
                        taxi_mgr.handle_respawn(car.x, car.y)
                    elif event.key == pygame.K_x:
                        taxi_mgr.discard_mission(car.x, car.y)
                        logger.info("Passenger fare discarded by player")
                    elif event.key == pygame.K_t:
                        reset_trip(car)
                        logger.info("Trip meter reset to 0 m")
                    elif event.key == pygame.K_l:
                        show_labels = not show_labels
                        logger.info("Labels %s", "enabled" if show_labels else "disabled")
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
                        px_per_m *= 1.1
                    elif event.key == pygame.K_MINUS:
                        px_per_m *= 0.9

            if first_gameplay_frame:
                logger.info("Gameplay frame: events complete")

            if not running:
                break

            if phone_open:
                dt = 0.0
            rage_shout_timer = max(0.0, rage_shout_timer - dt)

            if zoom_elapsed < zoom_duration:
                zoom_elapsed = min(zoom_duration, zoom_elapsed + dt)
                progress = zoom_elapsed / zoom_duration
                eased = progress * progress * (3.0 - 2.0 * progress)
                px_per_m = px_per_m + (zoom_target - px_per_m) * eased

            zoom_scale = max(px_per_m, zoom_target)
            traffic_mgr.set_target_count(traffic_count_for_zoom(base_traffic_count, zoom_scale), car)
            pedestrian_mgr.set_target_count(traffic_count_for_zoom(base_pedestrian_count, zoom_scale), car)
            cyclist_mgr.set_target_count(traffic_count_for_zoom(base_cyclist_count, zoom_scale), car)

            keys = pygame.key.get_pressed()
            immobilized = taxi_mgr.tree_wait_timer > 0.0
            throttle = 0.0 if immobilized else (1.0 if keys[pygame.K_w] or keys[pygame.K_UP] else 0.0)
            brake = 0.0 if immobilized else (1.0 if keys[pygame.K_s] or keys[pygame.K_DOWN] else 0.0)
            steer_left = 1.0 if keys[pygame.K_a] or keys[pygame.K_LEFT] else 0.0
            steer_right = 1.0 if keys[pygame.K_d] or keys[pygame.K_RIGHT] else 0.0

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
            update_car_physics(
                car,
                throttle,
                brake,
                steer_left,
                steer_right,
                dt,
                ways=ways,
                spatial_grid=spatial_grid,
                block_offroad=False,
                speed_limit_mps=speed_limit_mps,
            )
            if immobilized:
                car.speed = 0.0
            audio.update_acceleration(throttle > 0.0 and abs(car.speed) > 0.5)
            driven_distance = math.hypot(car.x - previous_position[0], car.y - previous_position[1])
            road_limit_mps = current_way.speed_limit_kmh / 3.6 if current_way else None
            if road_limit_mps is not None and driven_distance > 0.0 and abs(car.speed) <= road_limit_mps + 0.01:
                rage_power = min(1.0, rage_power + driven_distance / RAGE_DISTANCE_TO_FULL_M)
            if taxi_mgr.sees_red_light(car, nearby_traffic_lights, traffic_mgr.sim_time):
                rage_power = min(1.0, rage_power + 0.05 * dt)
            if first_gameplay_frame:
                logger.info("Gameplay frame: physics complete")

            building_crash = taxi_mgr.check_building_collision(
                car, buildings, traffic_mgr.sim_time, previous_position, ways=ways
            )
            tree_crash = taxi_mgr.check_tree_collision(car, sceneries, traffic_mgr.sim_time, previous_position)
            if building_crash or tree_crash:
                audio.play("car-crash", volume=0.7)
            if first_gameplay_frame:
                logger.info("Gameplay frame: collision checks complete")

            # Dynamic lookahead camera offset in vehicle driving direction
            # Look ahead proportionally to car speed and heading, clamped to a percentage of viewport so car remains visible
            max_lead_screen_px = min(SCREEN_W, SCREEN_H) * 0.25
            max_lead_m = max_lead_screen_px / max(0.01, px_per_m)
            lead_distance_m = min(max_lead_m, max(0.0, abs(car.speed) * 0.8))

            target_camx = car.x + math.cos(car.heading) * lead_distance_m
            target_camy = car.y + math.sin(car.heading) * lead_distance_m

            # Smooth camera lerp
            cam_lerp_factor = min(1.0, 4.0 * dt)
            camx += (target_camx - camx) * cam_lerp_factor
            camy += (target_camy - camy) * cam_lerp_factor

            viewport_bounds = get_viewport_bounds(camx, camy, px_per_m=px_per_m, margin_m=30.0)

            # Update taxi missions & pickups
            taxi_mgr.update(car, dt)
            if taxi_mgr.check_car_collision(car, traffic_mgr.npcs, traffic_mgr.sim_time):
                audio.play("car-crash", volume=0.8)
            taxi_mgr.check_wrong_way_violation(car, dt, ways=ways, spatial_grid=spatial_grid)
            taxi_mgr.check_speed_cameras(car, speed_cameras)

            # Update autonomous traffic NPCs and pedestrians
            traffic_mgr.update(car, dt, viewport_bounds=viewport_bounds)
            if not taxi_mgr.current_passenger:
                pedestrian_mgr.ensure_taxi_stop_waiter(taxi_stops, car, viewport_bounds=viewport_bounds)
            pedestrian_mgr.update(car, dt, viewport_bounds=viewport_bounds)
            cyclist_mgr.update(car, dt, viewport_bounds=viewport_bounds)
            waiting_pedestrian = taxi_mgr.check_waiting_pickup(car, pedestrian_mgr.pedestrians, dt)
            if waiting_pedestrian is not None:
                pedestrian_mgr.pedestrians.remove(waiting_pedestrian)

            # Road check (restricted to car roads, fast-checking current segment first)
            current_way = get_current_road_at_car(car, ways=ways, spatial_grid=spatial_grid, car_roads_only=True, current_way=current_way)
            on_road = current_way is not None
            current_road_name = getattr(current_way, "name", None) if current_way else None
            if not current_road_name and current_way:
                current_road_name = getattr(current_way, "highway", "Road").replace("_", " ").title()

            # Auto-fetch map tiles when approaching bounds (if enabled)
            if args.auto_fetch:
                started = auto_fetch_manager.start_if_needed(car, True, args.fetch_margin, args.fetch_tile_size)
                if started:
                    logger.info(
                        "Triggered background auto-fetch (%s) at car=(%.1f, %.1f), speed=%.1f m/s, heading=%.2f rad, bounds=%s",
                        auto_fetch_manager.get_trigger_reason(),
                        car.x,
                        car.y,
                        car.speed,
                        car.heading,
                        auto_fetch_manager.get_bounds(),
                    )
                if len(ways) != spatial_grid.indexed_way_count and map_sync_stage == 0:
                    map_sync_stage = 1

                if map_sync_stage == 1:
                    spatial_grid.rebuild(ways)
                    map_sync_stage = 2
                elif map_sync_stage == 2:
                    taxi_mgr.sync_map_data(ways, places=places, buildings=buildings)
                    map_sync_stage = 3
                elif map_sync_stage == 3:
                    traffic_mgr.sync_map_data(ways, traffic_lights=traffic_lights, crossings=crossings)
                    map_sync_stage = 4
                elif map_sync_stage == 4:
                    pedestrian_mgr.sync_map_data(ways, traffic_lights=traffic_lights)
                    map_sync_stage = 5
                elif map_sync_stage == 5:
                    cyclist_mgr.sync_map_data(ways, traffic_lights=traffic_lights)
                    map_sync_stage = 0
            if first_gameplay_frame:
                logger.info("Gameplay frame: map update complete")

            # Render background and scene
            if first_gameplay_frame:
                logger.info("Gameplay frame: rendering scenery")
            screen.fill((25, 80, 25))  # grass base
            draw_scenery(
                screen,
                sceneries,
                camx,
                camy,
                px_per_m=px_per_m,
                tree_effects=taxi_mgr.tree_effects,
                fallen_trees=taxi_mgr.fallen_trees,
            )
            if first_gameplay_frame:
                logger.info("Gameplay frame: rendering water")
            draw_waters(screen, waters, camx, camy, px_per_m=px_per_m)
            if first_gameplay_frame:
                logger.info("Gameplay frame: rendering buildings")
            draw_buildings(screen, buildings, camx, camy, px_per_m=px_per_m)
            if first_gameplay_frame:
                logger.info("Gameplay frame: rendering roads")
            draw_ways(screen, ways, camx, camy, px_per_m=px_per_m)
            if first_gameplay_frame:
                logger.info("Gameplay frame: rendering overlays")
            draw_crossings(screen, crossings, camx, camy, px_per_m=px_per_m)
            draw_traffic_lights(screen, traffic_lights, traffic_mgr.sim_time, camx, camy, px_per_m=px_per_m)
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
            draw_pedestrians(screen, pedestrian_mgr.pedestrians, camx, camy, font=small_font, px_per_m=px_per_m, ways=ways)
            draw_cyclists(screen, cyclist_mgr.cyclists, camx, camy, px_per_m=px_per_m, ways=ways)
            draw_npc_cars(screen, traffic_mgr.npcs, camx, camy, px_per_m=px_per_m, ways=ways)
            draw_taxi_target(screen, taxi_mgr, camx, camy, font, px_per_m=px_per_m, language=language)
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
            )
            draw_taxi_smoke(screen, car, camx, camy, px_per_m=px_per_m, timer=taxi_mgr.taxi_smoke_timer)

            # Labels overlay (toggled with 'L')
            if show_labels:
                draw_labels(screen, font, ways, waters, buildings, sceneries, places, camx, camy, px_per_m=px_per_m)

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
                is_auto_fetching=(args.auto_fetch and auto_fetch_manager.get_fetching()),
                show_labels=show_labels,
                auto_fetch_progress=auto_fetch_manager.get_progress(),
                taxi_mgr=taxi_mgr,
                current_road_name=current_road_name,
                speed_limit_kmh=current_limit_kmh,
                speed_limiter_enabled=speed_limiter_enabled,
                red_light_assist_enabled=red_light_assist_enabled,
                rage_power=rage_power,
                language=language,
            )
            if phone_open:
                draw_phone_offers(screen, taxi_mgr, font, small_font, SCREEN_W, SCREEN_H, language)
            draw_compass(screen, car, SCREEN_W - 64, 64, 28, font, target_pos=target_coords)

            if first_gameplay_frame:
                logger.info("Gameplay frame: flipping display")
            pygame.display.flip()
            if first_gameplay_frame:
                logger.info("Gameplay frame: complete")
                first_gameplay_frame = False

    audio.close()
    pygame.quit()


if __name__ == "__main__":
    main()

