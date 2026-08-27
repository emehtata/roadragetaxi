import argparse
import logging
import os
import sys
from typing import Optional, Tuple

from .geo import clamp, dist_point_to_segment, meters_to_latlon
from .osm import (
    BBOX_PRESETS,
    DEFAULT_BBOX,
    DEFAULT_OVERPASS_ENDPOINTS,
    DEFAULT_ROAD_HALF_WIDTH_M,
    HIGHWAY_HALF_WIDTH,
    AutoFetchManager,
    Building,
    Place,
    Scenery,
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
    draw_compass,
    draw_hud,
    draw_labels,
    draw_loading_screen,
    draw_scenery,
    draw_taxi_target,
    draw_waters,
    draw_ways,
    world_to_screen,
)
from .taxi import TaxiManager

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
        default="oulu",
        help="Named bounding box preset (e.g., oulu, helsinki)",
    )
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

    # Determine bounding box
    bbox = BBOX_PRESETS.get(args.preset.lower(), DEFAULT_BBOX)
    if args.bbox:
        try:
            parts = [float(p.strip()) for p in args.bbox.split(",")]
            if len(parts) == 4:
                bbox = tuple(parts)
        except Exception:
            logger.warning("Invalid bbox provided, using default preset (%s)", args.preset)

    if args.cache_ttl:
        os.environ["OSM_CACHE_TTL"] = str(args.cache_ttl)
    if args.force_refresh or args.no_cache:
        os.environ["OVERPASS_FORCE_REFRESH"] = "1"

    px_per_m = args.px_per_m or PX_PER_M

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
        ways, waters, buildings, sceneries, places, bounds = build_ways(elements, progress_callback=on_load_progress)
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
        fetch_func=fetch_osm_ways,
        build_func=_build_wrapper,
    )

    show_labels = True
    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_r:
                    respawn_car(car, ways, waters=waters)
                elif event.key == pygame.K_t:
                    reset_trip(car)
                    logger.info("Trip meter reset to 0 m")
                elif event.key == pygame.K_l:
                    show_labels = not show_labels
                    logger.info("Labels %s", "enabled" if show_labels else "disabled")
                elif event.key in (pygame.K_EQUALS, pygame.K_PLUS):
                    px_per_m *= 1.1
                elif event.key == pygame.K_MINUS:
                    px_per_m *= 0.9

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

        # Update taxi missions & pickups
        taxi_mgr.update(car, dt)

        # Camera follows car
        camx, camy = car.x, car.y

        # Road check (restricted to car roads)
        on_road = is_on_road(car, ways, spatial_grid=spatial_grid, car_roads_only=True)

        # Auto-fetch map tiles when approaching bounds (if enabled)
        if args.auto_fetch:
            started = auto_fetch_manager.start_if_needed(car, True, args.fetch_margin, args.fetch_tile_size)
            if started:
                logger.info("Triggered background auto-fetch")
            if len(ways) != spatial_grid.indexed_way_count:
                spatial_grid.rebuild(ways)
                taxi_mgr.sync_map_data(ways, places=places, buildings=buildings)

        # Render background and scene
        screen.fill((25, 80, 25))  # grass base
        draw_scenery(screen, sceneries, camx, camy, px_per_m=px_per_m)
        draw_waters(screen, waters, camx, camy, px_per_m=px_per_m)
        draw_buildings(screen, buildings, camx, camy, px_per_m=px_per_m)
        draw_ways(screen, ways, camx, camy, px_per_m=px_per_m)
        draw_taxi_target(screen, taxi_mgr, camx, camy, font, px_per_m=px_per_m)
        draw_car(screen, car, camx, camy, px_per_m=px_per_m)

        # Labels overlay (toggled with 'L')
        if show_labels:
            draw_labels(screen, font, ways, waters, buildings, sceneries, places, camx, camy, px_per_m=px_per_m)

        # Draw HUD and compass
        current_target = taxi_mgr.get_current_target()
        target_coords = (current_target.x, current_target.y) if current_target else None

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
        )
        draw_compass(screen, car, SCREEN_W - 64, 64, 28, font, target_pos=target_coords)

        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()

