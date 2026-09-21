import json
import logging
import math
import os
import sys
import time
from dataclasses import asdict
from typing import List, Optional


from .. import tile_streaming
from ..geo import dist_point_to_segment, point_in_polygon
from ..physics import (
    Car,
)


logger = logging.getLogger(__name__)


def _nearest_boundary_distance(x: float, y: float, points: List, closed: bool) -> float:
    """Distance from (x, y) to the nearest edge of a polyline/polygon -
    0.0 if (x, y) is inside a closed one."""
    if closed and len(points) >= 3 and point_in_polygon(x, y, points):
        return 0.0
    edges = zip(points, points[1:] + points[:1]) if closed else zip(points, points[1:])
    return min(
        (dist_point_to_segment(x, y, ax, ay, bx, by) for (ax, ay), (bx, by) in edges),
        default=math.inf,
    )


def find_feature_at(
    x: float,
    y: float,
    ways: Optional[List] = None,
    curbs: Optional[List] = None,
    railings: Optional[List] = None,
    buildings: Optional[List] = None,
    sceneries: Optional[List] = None,
    parking_spaces: Optional[List] = None,
    waters: Optional[List] = None,
    railways: Optional[List] = None,
    tolerance_m: float = 3.0,
) -> Optional[dict]:
    """RENDER-audit.md section 19: the nearest mapped OSM feature to
    (x, y) - world coordinates, e.g. the mouse cursor via
    render.screen_to_world - across the map's own already-loaded
    feature lists, or None if nothing is within tolerance_m. A debug
    tool for diagnosing "is this feature parsed? rendered? drivable?"
    directly from the game instead of by reading code - only ever
    called on a deliberate click (see main.py's feature-inspector
    toggle), never per frame, so a plain linear scan across each
    category is fine here, unlike anything in the actual render path.

    Every category the game currently has a dedicated renderer for is
    "rendered: yes" here by construction - if a category existed that
    the renderer silently dropped, it wouldn't have a draw_* function to
    even reach this call site with in the first place. That's exactly
    the class of gap this tool exists to make easy to *find in the
    first place* (nothing to click on == nothing found, not a
    false "rendered: yes").
    """
    candidates = []  # (distance, info)

    for way in ways or ():
        points = getattr(way, "points_m", None)
        if not points or len(points) < 2:
            continue
        d = _nearest_boundary_distance(x, y, points, closed=False)
        if d <= tolerance_m:
            candidates.append((d, {
                "type": f"highway={getattr(way, 'highway', '?')}",
                "source": "OSM way",
                "id": getattr(way, "osm_id", None) or "unknown (not preserved by parser)",
                "rendered": "yes",
                "drivable": "yes" if getattr(way, "is_drivable", True) else "no",
            }))

    for curb in curbs or ():
        points = getattr(curb, "points_m", None)
        if not points or len(points) < 2:
            continue
        d = _nearest_boundary_distance(x, y, points, closed=False)
        if d <= tolerance_m:
            candidates.append((d, {
                "type": "barrier=kerb",
                "source": "OSM way",
                "id": "unknown (not preserved by parser)",
                "rendered": "yes (outline)",
                "drivable": "no",
            }))

    for railing in railings or ():
        points = getattr(railing, "points_m", None)
        if not points or len(points) < 2:
            continue
        d = _nearest_boundary_distance(x, y, points, closed=False)
        if d <= tolerance_m:
            candidates.append((d, {
                "type": f"barrier={getattr(railing, 'kind', '?')}",
                "source": "OSM way",
                "id": "unknown (not preserved by parser)",
                "rendered": "yes",
                "drivable": "no",
            }))

    for railway in railways or ():
        points = getattr(railway, "points_m", None)
        if not points or len(points) < 2:
            continue
        d = _nearest_boundary_distance(x, y, points, closed=False)
        if d <= tolerance_m:
            candidates.append((d, {
                "type": f"railway={getattr(railway, 'kind', '?')}",
                "source": "OSM way",
                "id": "unknown (not preserved by parser)",
                "rendered": "yes",
                "drivable": "no",
            }))

    for water in waters or ():
        points = getattr(water, "points_m", None)
        if not points or len(points) < 2:
            continue
        d = _nearest_boundary_distance(x, y, points, closed=bool(getattr(water, "is_polygon", False)))
        if d <= tolerance_m:
            candidates.append((d, {
                "type": f"natural/waterway={getattr(water, 'kind', '?')}",
                "source": "OSM way",
                "id": "unknown (not preserved by parser)",
                "rendered": "yes",
                "drivable": "no",
            }))

    for building in buildings or ():
        points = getattr(building, "points_m", None)
        if not points or len(points) < 3:
            continue
        d = _nearest_boundary_distance(x, y, points, closed=True)
        if d <= tolerance_m:
            candidates.append((d, {
                "type": "building",
                "source": "OSM way",
                "id": "unknown (not preserved by parser)",
                "rendered": "yes",
                "drivable": "no",
            }))

    for scenery in sceneries or ():
        points = getattr(scenery, "points_m", None)
        if not points or len(points) < 3:
            continue
        d = _nearest_boundary_distance(x, y, points, closed=True)
        if d <= tolerance_m:
            candidates.append((d, {
                "type": f"area kind={getattr(scenery, 'kind', '?')}",
                "source": "OSM way",
                "id": "unknown (not preserved by parser)",
                "rendered": "yes",
                "drivable": "no",
            }))

    for space in parking_spaces or ():
        points = getattr(space, "points_m", None)
        if not points or len(points) < 3:
            continue
        d = _nearest_boundary_distance(x, y, points, closed=True)
        if d <= tolerance_m:
            candidates.append((d, {
                "type": "amenity=parking_space",
                "source": "OSM way/node",
                "id": getattr(space, "osm_id", None) or "unknown",
                "rendered": "yes",
                "drivable": "no (parking target only)",
            }))

    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])
    return candidates[0][1]


def _npc_snapshot(vehicle, driver=None) -> dict:
    """Structured per-NPC state for debug snapshots - the JSON analogue of
    the F7 debug overlay (render/hud.py's draw_npc_debug_panel), so an NPC's
    driving/routing/parking state can be inspected from a screenshot's JSON
    without needing that overlay enabled at capture time."""
    way = vehicle.way
    next_way = getattr(driver, "next_way", None) if driver is not None else None
    decision = getattr(driver, "decision", None)
    light = getattr(decision, "light", None)
    return {
        "vehicle_id": vehicle.vehicle_id,
        "has_driver": driver is not None,
        "resident_id": vehicle.owner_id,
        "state": vehicle.state,
        "vehicle_type": vehicle.vehicle_type,
        "capacity": vehicle.capacity,
        "occupant_count": (
            len(vehicle.trip_group.boarded_resident_ids) if vehicle.trip_group is not None else 0
        ),
        "occupant_ids": (
            sorted(vehicle.trip_group.boarded_resident_ids) if vehicle.trip_group is not None else []
        ),
        "x": vehicle.x,
        "y": vehicle.y,
        "heading": vehicle.heading,
        "speed_kmh": vehicle.speed * 3.6,
        "target_speed_kmh": driver.target_speed_mps * 3.6 if driver is not None else 0.0,
        "way": {"name": getattr(way, "name", None), "highway": getattr(way, "highway", None)} if way else None,
        "next_way": (
            {"name": getattr(next_way, "name", None), "highway": getattr(next_way, "highway", None)}
            if next_way else None
        ),
        "route_index": driver.path_index if driver is not None else None,
        "route_length": len(driver.path) - 1 if driver is not None else None,
        "route_progress": driver.route_progress if driver is not None else None,
        "lookahead_distance_m": getattr(driver, "lookahead_distance_m", 0.0) if driver is not None else 0.0,
        "steering_input": getattr(driver, "steering_input", 0.0) if driver is not None else 0.0,
        "maneuver": driver.next_maneuver if driver is not None else None,
        "lane_bias": getattr(driver, "current_lane_bias", None) if driver is not None else None,
        "traffic_action": decision.action if decision is not None else None,
        "traffic_reason": decision.reason if decision is not None else None,
        "stop_position": list(decision.stop_position) if decision is not None and decision.stop_position is not None else None,
        "signal_id": (getattr(light, "approach_id", None) or getattr(light, "id", None)) if light is not None else None,
        "destination": list(driver.destination) if driver is not None else (
            list(vehicle.destination) if vehicle.destination is not None else None
        ),
        "destination_parking_space_id": vehicle.destination_parking_space_id,
        "is_taxi": vehicle.is_taxi,
        "is_police": vehicle.is_police,
        "fallen": vehicle.fallen,
        "crashed_timer": vehicle.crashed_timer,
        "debug_waiting_for": vehicle.debug_waiting_for,
    }


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
    npcs=(),
    npc_drivers=None,
    npc_manager=None,
    frame_profiler=None,
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
        "npcs": [
            _npc_snapshot(vehicle, npc_drivers.get(vehicle.vehicle_id) if npc_drivers is not None else None)
            for vehicle in npcs
        ],
        "npc_population": {
            "total": len(npcs),
            "moving": sum(
                1 for vehicle in npcs
                if str(vehicle.state) not in ("PARKED", "CRASHED")
                and npc_drivers is not None and vehicle.vehicle_id in npc_drivers
            ),
            "within_150m": sum(
                1 for vehicle in npcs
                if (vehicle.x - car.x) ** 2 + (vehicle.y - car.y) ** 2 <= 150.0 ** 2
            ),
            "moving_target": getattr(npc_manager, "target_moving_count", None),
            "diagnostics": dict(getattr(npc_manager, "population_diagnostics", {})),
        },
        "performance": frame_profiler.snapshot() if frame_profiler is not None else None,
        "auto_fetch": {
            "configured_enabled": bool(args.auto_fetch),
            "call_enabled": True,
            "margin_m": args.fetch_margin,
            # The real live tile-streaming grid size (tile_streaming.
            # TILE_SIZE_M, set once at startup - see set_tile_size_m in
            # main()), NOT args.fetch_tile_size: that CLI value only feeds
            # AutoFetchManager.start_if_needed(), a legacy margin-based
            # fetch path no longer called anywhere - reporting it here was
            # reporting a number that has nothing to do with the tiles
            # actually being streamed.
            "tile_size_m": tile_streaming.TILE_SIZE_M,
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
                tile_streaming.TILE_SIZE_M,
                current_way=current_way,
            ),
        },
    }
    with open(path, "w", encoding="utf-8") as debug_file:
        json.dump(data, debug_file, ensure_ascii=False, indent=2, default=str)
