import json
import logging
import os
import sys
import time
from dataclasses import asdict


from ..physics import (
    Car,
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
    scenery_objects=(),
    speed_bumps=(),
    railways=(),
    railings=(),
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
                "scenery_objects": len(scenery_objects),
                "speed_bumps": len(speed_bumps),
                "railways": len(railways),
                "railings": len(railings),
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
            "osm_source": args.osm_source,
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
