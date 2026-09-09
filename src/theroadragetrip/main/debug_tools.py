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


def _screenshot_directory() -> str:
    if sys.platform.startswith("win"):
        home_dir = os.getenv("USERPROFILE") or os.path.expanduser("~")
        return os.path.join(home_dir, "Pictures", "TheRoadRageTrip")
    return os.path.abspath("screenshots")


def _write_debug_snapshot(
    path: str,
    car: Car,
    taxi_mgr,
    auto_fetch_manager,
    args,
    bbox,
    viewport_bounds,
    camx: float,
    camy: float,
    px_per_m: float,
    current_way,
    ways,
    waters,
    buildings,
    sceneries,
    places,
    taxi_stops,
    traffic_lights,
    crossings,
    elements_count: int,
    traffic_mgr,
    pedestrian_mgr,
    spatial_grid,
    map_sync_stage: int,
    chosen_city: str,
    camera_city_name,
    game_mode: str,
    on_foot: bool,
) -> None:
    minx, miny, maxx, maxy = auto_fetch_manager.get_bounds()
    now = time.time()
    taxi_scalars = {
        key: value
        for key, value in vars(taxi_mgr).items()
        if isinstance(value, (str, int, float, bool)) or value is None
    }
    passenger = taxi_mgr.current_passenger
    data = {
        "timestamp_ns": time.time_ns(),
        "car": asdict(car),
        "taxi": {
            "state": taxi_mgr.state,
            "scalar_properties": taxi_scalars,
            "current_passenger": asdict(passenger) if passenger is not None else None,
            "offer_count": len(taxi_mgr.offers),
            "tree_effect_count": len(taxi_mgr.tree_effects),
            "fallen_tree_count": len(taxi_mgr.fallen_trees),
            "vomit_puddle_count": len(taxi_mgr.vomit_puddles),
        },
        "world": {
            "city": chosen_city,
            "camera_city": camera_city_name,
            "game_mode": game_mode,
            "initial_bbox": list(bbox),
            "current_bounds": list(auto_fetch_manager.get_bounds()),
            "viewport_bounds": list(viewport_bounds),
            "camera": {"x": camx, "y": camy, "px_per_m": px_per_m},
            "feature_counts": {
                "elements_loaded": elements_count,
                "ways": len(ways),
                "waters": len(waters),
                "buildings": len(buildings),
                "sceneries": len(sceneries),
                "places": len(places),
                "taxi_stops": len(taxi_stops),
                "traffic_lights": len(traffic_lights),
                "crossings": len(crossings),
                "pedestrians": len(pedestrian_mgr.pedestrians),
            },
            "current_way": {
                "name": getattr(current_way, "name", None),
                "highway": getattr(current_way, "highway", None),
                "layer": getattr(current_way, "layer", None),
                "speed_limit_kmh": getattr(current_way, "speed_limit_kmh", None),
            } if current_way is not None else None,
            "spatial_grid": {"indexed_way_count": spatial_grid.indexed_way_count},
            "map_sync_stage": map_sync_stage,
            "on_foot": on_foot,
        },
        "auto_fetch": {
            "configured_enabled": bool(args.auto_fetch),
            "call_enabled": True,
            "margin_m": args.fetch_margin,
            "tile_size_m": args.fetch_tile_size,
            "build_in_process": bool(args.build_in_process),
            "manager_enabled_state": not auto_fetch_manager.get_fetching(),
            "is_fetching": auto_fetch_manager.get_fetching(),
            "progress": auto_fetch_manager.get_progress(),
            "last_trigger_reason": auto_fetch_manager.get_trigger_reason(),
            "last_fetch_time": auto_fetch_manager.last_fetch_time,
            "seconds_since_last_fetch": (
                now - auto_fetch_manager.last_fetch_time
                if auto_fetch_manager.last_fetch_time
                else None
            ),
            "cooldown_s": auto_fetch_manager.cooldown_s,
            "dead_end_count": len(auto_fetch_manager.dead_ends),
            "dead_ends": auto_fetch_manager.dead_ends,
            "known_dead_end": {
                direction: auto_fetch_manager.is_known_dead_end(car.x, car.y, direction)
                for direction in ("west", "east", "south", "north")
            },
            "distance_to_edges_m": {
                "west": car.x - minx,
                "east": maxx - car.x,
                "south": car.y - miny,
                "north": maxy - car.y,
            },
            "within_margin": {
                "west": car.x < minx + args.fetch_margin,
                "east": car.x > maxx - args.fetch_margin,
                "south": car.y < miny + args.fetch_margin,
                "north": car.y > maxy - args.fetch_margin,
            },
            "endpoint_audit": auto_fetch_manager.get_endpoint_fetch_audit(
                car,
                args.fetch_margin,
                args.fetch_tile_size,
                current_way=current_way,
            ),
        },
    }
    with open(path, "w", encoding="utf-8") as debug_file:
        json.dump(data, debug_file, ensure_ascii=False, indent=2, default=str)
