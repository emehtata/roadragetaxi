import argparse
import cProfile
import concurrent.futures
import json
import logging
import math
import os
import random
import sys
import threading
import time
from dataclasses import asdict
from typing import Optional, Tuple

import pygame

from ..geo import clamp, dist_point_to_segment, meters_to_latlon
from ..audio import AudioManager
from ..config import (
    CONFIG_PATH,
    city_suggestions,
    cities_from_config,
    default_city_configuration,
    get_optional_int,
    get_overpass_endpoints,
    load_city_catalog,
    load_config,
    replace_city_in_config,
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
from ..localization import LANGUAGE_NAMES, SUPPORTED_LANGUAGES, normalize_language, tr
from ..osm import (
    BBOX_PRESETS,
    CITY_CENTERS,
    DEFAULT_BBOX,
    DEFAULT_OVERPASS_ENDPOINTS,
    DEFAULT_ROAD_HALF_WIDTH_M,
    HIGHWAY_HALF_WIDTH,
    AutoFetchManager,
    Building,
    BusStop,
    Place,
    Scenery,
    TaxiStop,
    TrafficLight,
    Water,
    Way,
    build_ways,
    clear_osm_cache,
    configure_user_agent,
    fetch_osm_ways,
    has_outdated_osm_cache,
    load_local_sample,
    load_osm_cache,
    remove_trees_under_roads,
    save_osm_cache,
)
from ..physics import (
    ACCEL,
    BRAKE,
    FRICTION,
    MAX_SPEED,
    STEER_RATE,
    STEER_SPEED_FACTOR,
    Car,
    SpatialWayGrid,
    get_current_road_at_car,
    is_car_colliding_with_bridge_edge,
    is_car_fully_in_water,
    is_on_road,
    is_point_on_parking_space,
    reset_trip,
    respawn_car,
    pull_car_inside_bridge_edge,
    update_car_physics,
)
from ..render import (
    FPS,
    PX_PER_M,
    SCREEN_H,
    SCREEN_W,
    draw_buildings,
    draw_bus_stops,
    draw_car,
    draw_city_selection_menu,
    draw_game_start_hint,
    draw_game_start_overlay,
    draw_city_editor,
    draw_city_summary,
    draw_mode_selection_menu,
    draw_compass,
    draw_crossings,
    draw_day_night_overlay,
    draw_grass_texture,
    draw_headlight_beams,
    draw_hud,
    draw_frame_profiler,
    begin_static_cache_frame,
    invalidate_static_caches,
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
    draw_resident_popup,
    resident_at_screen_position,
    draw_phone_offers,
    draw_scenery,
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
    world_to_screen,
)


logger = logging.getLogger(__name__)


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
    p.add_argument("--fetch-tile-size", type=float, default=map_config.getfloat("fetch_tile_size", fallback=500.0), help="Base auto-fetch bbox size in meters")
    p.add_argument(
        "--build-in-process",
        action="store_true",
        default=map_config.getboolean("build_in_process", fallback=True),
        help="Build auto-fetched map data outside the gameplay process",
    )
    p.add_argument("--pedestrian-count", type=int, default=traffic_config.getint("pedestrian_count", fallback=60), help="Target number of pedestrians")

    return p.parse_args()


def configure_logging(level: Optional[str] = None, file_logging: bool = False) -> None:
    lvl = os.getenv("LOG_LEVEL", level or "INFO").upper()
    log_level = getattr(logging, lvl, logging.INFO)
    log_format = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    handlers = [logging.StreamHandler()]
    handlers[0].setFormatter(logging.Formatter(log_format))
    if file_logging:
        file_handler = logging.FileHandler("roadragetrip.log", encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(log_format))
        handlers.append(file_handler)
    logging.basicConfig(level=log_level, handlers=handlers, force=True)
