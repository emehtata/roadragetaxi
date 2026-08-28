import argparse
import logging
import math
import os
import sys
from typing import Optional, Tuple

from .geo import clamp, dist_point_to_segment, meters_to_latlon
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
    TrafficLight,
    Water,
    Way,
    build_ways,
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
    draw_city_selection_menu,
    draw_compass,
    draw_crossings,
    draw_hud,
    draw_labels,
    draw_loading_screen,
    draw_npc_cars,
    draw_pause_menu,
    draw_pedestrians,
    draw_scenery,
    draw_taxi_target,
    draw_traffic_lights,
    draw_waters,
    draw_ways,
    get_viewport_bounds,
    world_to_screen,
)
from .pedestrian import PedestrianManager
from .taxi import TaxiManager
from .traffic import TrafficManager

# Maintain BBOX constant for backward compatibility
BBOX = DEFAULT_BBOX

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="The Road Rage Trip (OSM PoC)")
    p.add_argument("--bbox", type=str, help="south,west,north,east (lat/lon)")
    p.add_argument(
        "--preset",
        type=str,
        choices=list(BBOX_PRESETS.keys()),
        default=None,
        help="Named bounding box preset (e.g., oulu, helsinki, tampere, espoo)",
    )
    p.add_argument("--no-menu", action="store_true", help="Skip city selection menu and start immediately")
    p.add_argument("--force-refresh", action="store_true", help="Force refresh from Overpass (ignore cache)")
    p.add_argument("--use-sample", action="store_true", help="Use bundled sample OSM data and skip Overpass")
    p.add_argument("--cache-ttl", type=int, help="Cache TTL in seconds (overrides OSM_CACHE_TTL env)")
    p.add_argument("--px-per-m", type=float, help="Initial pixels per meter (zoom)")
    p.add_argument("--log-level", type=str, help="Logging level (DEBUG/INFO/WARNING)")
    p.add_argument("--no-cache", action="store_true", help="Disable cache usage (treated like force-refresh)")

    # Auto-fetching nearby map tiles when the car approaches the bbox edge
    p.add_argument(
        "--auto-fetch",
        action="store_true",
        default=True,
        help="Auto-fetch adjacent map tiles when near bbox edge (default: enabled)",
    )
    p.add_argument("--no-auto-fetch", dest="auto_fetch", action="store_false", help="Disable on-demand map expansion")
    p.add_argument(
        "--fetch-margin",
        type=float,
        default=800.0,
        help="Distance in meters from bbox edge that triggers auto-fetch",
    )
    p.add_argument("--fetch-tile-size", type=float, default=2500.0, help="Meters to expand when auto-fetching")
    p.add_argument("--traffic-count", type=int, default=25, help="Target number of autonomous NPC cars (default: 25)")
    p.add_argument("--pedestrian-count", type=int, default=20, help="Target number of pedestrians (default: 20)")

    return p.parse_args()


def configure_logging(level: Optional[str] = None) -> None:
    lvl = os.getenv("LOG_LEVEL", level or "INFO").upper()
    logging.basicConfig(level=getattr(logging, lvl, logging.INFO), format="%(levelname)s: %(message)s")


def main() -> None:
    args = parse_args()
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

    # Outer game loop to support picking new starting city without restarting process
    app_running = True
    active_city_name = None

    while app_running:
        cities_list = list(CITY_CENTERS.keys())
        selected_city_idx = 0

        # Show city selection menu if no explicit CLI override or when requested from pause menu
        if active_city_name is not None or (not args.bbox and not args.preset and not args.use_sample and not args.no_menu):
            if active_city_name is not None and active_city_name in cities_list:
                selected_city_idx = cities_list.index(active_city_name)
            in_menu = True
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

                draw_city_selection_menu(screen, font, cities_list, selected_city_idx, SCREEN_W, SCREEN_H)
                pygame.display.flip()

            chosen_city = cities_list[selected_city_idx]
            bbox = BBOX_PRESETS.get(chosen_city.lower(), DEFAULT_BBOX)
            logger.info("Selected starting city: %s (bbox: %s)", chosen_city, bbox)
        else:
            preset_key = args.preset.lower() if args.preset else "oulu"
            bbox = BBOX_PRESETS.get(preset_key, DEFAULT_BBOX)
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
                elements = fetch_osm_ways(bbox, progress_callback=on_load_progress)
            res = build_ways(elements, progress_callback=on_load_progress)
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
        # Spatial index for fast O(1) road collision detection
        spatial_grid = SpatialWayGrid()
        spatial_grid.rebuild(ways)

        # Spawn car on a road near center (avoiding water)
        car = Car(x=(minx + maxx) / 2, y=(miny + maxy) / 2, heading=0.0, speed=0.0)
        if ways:
            respawn_car(car, ways, near_center=True, bounds=bounds, waters=waters)

        # Initialize Taxi Manager for game mode
        taxi_mgr = TaxiManager(ways, places=places, buildings=buildings)
        taxi_mgr.spawn_mission(car.x, car.y)

        # Initialize autonomous Traffic Manager for NPC cars
        traffic_mgr = TrafficManager(ways, target_count=args.traffic_count, traffic_lights=traffic_lights)

        # Initialize autonomous Pedestrian Manager
        pedestrian_mgr = PedestrianManager(ways, target_count=args.pedestrian_count, traffic_lights=traffic_lights)

        # Prepare transformer for meters->latlon display
        try:
            from pyproj import Transformer

            transformer_to_ll = Transformer.from_crs("EPSG:3067", "EPSG:4326", always_xy=True)
        except Exception:
            transformer_to_ll = None
            logger.debug("pyproj not available; lat/lon display disabled")

        # Auto fetch manager (background)
        def _build_wrapper(elems):
            return build_ways(elems)

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
            build_func=_build_wrapper,
        )

        show_labels = True
        running = True
        current_way = None
        px_per_m = args.px_per_m if args.px_per_m is not None else PX_PER_M
        camx, camy = car.x, car.y
        clock.tick()  # Reset clock timer to avoid large dt on first frame

        while running:
            dt = min(clock.tick(FPS) / 1000.0, 0.1)  # Clamp delta-time to prevent physics tunneling on lag spikes

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                    app_running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        # Pause menu with options: Continue Game, Change City, Exit Game
                        pause_options = ["Continue Game", "Change City", "Exit Game"]
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
                                            # Change City
                                            is_paused = False
                                            running = False
                                            active_city_name = cities_list[selected_city_idx]
                                        elif pause_selected == 2:
                                            # Exit Game
                                            pygame.quit()
                                            sys.exit(0)

                            # Redraw current frame beneath pause overlay
                            draw_pause_menu(screen, font, pause_options, pause_selected, SCREEN_W, SCREEN_H)
                            pygame.display.flip()

                        # Reset clock after unpausing to prevent sudden dt physics jumps
                        clock.tick()
                    elif event.key == pygame.K_r:
                        respawn_car(car, ways, waters=waters)
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
                    elif event.key in (pygame.K_EQUALS, pygame.K_PLUS):
                        px_per_m *= 1.1
                    elif event.key == pygame.K_MINUS:
                        px_per_m *= 0.9

            if not running:
                break

            keys = pygame.key.get_pressed()
            throttle = 1.0 if keys[pygame.K_w] or keys[pygame.K_UP] else 0.0
            brake = 1.0 if keys[pygame.K_s] or keys[pygame.K_DOWN] else 0.0
            steer_left = 1.0 if keys[pygame.K_a] or keys[pygame.K_LEFT] else 0.0
            steer_right = 1.0 if keys[pygame.K_d] or keys[pygame.K_RIGHT] else 0.0

            # Update physics (enforcing driving on car roads only, blocking off-road movement)
            update_car_physics(
                car,
                throttle,
                brake,
                steer_left,
                steer_right,
                dt,
                ways=ways,
                spatial_grid=spatial_grid,
                block_offroad=True,
            )

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
            if traffic_lights:
                taxi_mgr.check_red_light_violation(car, traffic_lights, traffic_mgr.sim_time)
            taxi_mgr.check_car_collision(car, traffic_mgr.npcs, traffic_mgr.sim_time)
            taxi_mgr.check_wrong_way_violation(car, dt, ways=ways, spatial_grid=spatial_grid)

            # Update autonomous traffic NPCs and pedestrians
            traffic_mgr.update(car, dt, viewport_bounds=viewport_bounds)
            pedestrian_mgr.update(car, dt, viewport_bounds=viewport_bounds)

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
                    logger.info("Triggered background auto-fetch")
                if len(ways) != spatial_grid.indexed_way_count:
                    spatial_grid.rebuild(ways)
                    taxi_mgr.sync_map_data(ways, places=places, buildings=buildings)
                    traffic_mgr.sync_map_data(ways, traffic_lights=traffic_lights)
                    pedestrian_mgr.sync_map_data(ways, traffic_lights=traffic_lights)

            # Render background and scene
            screen.fill((25, 80, 25))  # grass base
            draw_scenery(screen, sceneries, camx, camy, px_per_m=px_per_m)
            draw_waters(screen, waters, camx, camy, px_per_m=px_per_m)
            draw_buildings(screen, buildings, camx, camy, px_per_m=px_per_m)
            draw_ways(screen, ways, camx, camy, px_per_m=px_per_m)
            draw_crossings(screen, crossings, camx, camy, px_per_m=px_per_m)
            draw_traffic_lights(screen, traffic_lights, traffic_mgr.sim_time, camx, camy, px_per_m=px_per_m)
            draw_pedestrians(screen, pedestrian_mgr.pedestrians, camx, camy, font=small_font, px_per_m=px_per_m)
            draw_npc_cars(screen, traffic_mgr.npcs, camx, camy, px_per_m=px_per_m)
            draw_taxi_target(screen, taxi_mgr, camx, camy, font, px_per_m=px_per_m)
            draw_car(screen, car, camx, camy, px_per_m=px_per_m)

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
                is_auto_fetching=(args.auto_fetch and auto_fetch_manager.is_fetching),
                show_labels=show_labels,
                auto_fetch_progress=auto_fetch_manager.get_progress(),
                taxi_mgr=taxi_mgr,
                current_road_name=current_road_name,
                speed_limit_kmh=current_limit_kmh,
            )
            draw_compass(screen, car, SCREEN_W - 64, 64, 28, font, target_pos=target_coords)

            pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()

