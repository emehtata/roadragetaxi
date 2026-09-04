"""Headless autonomous traffic audit for finding gameplay regressions."""
from __future__ import annotations

import argparse
import json
import math
import os
import random
from dataclasses import dataclass, asdict
from typing import List

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from theroadragetrip.osm import build_ways, load_local_sample
from theroadragetrip.geo import boxes_intersect
from theroadragetrip.physics import Car, is_point_on_road
from theroadragetrip.traffic import TrafficManager, compute_desired_lane_offset


@dataclass
class AuditFailure:
    step: int
    rule: str
    npc_id: int
    detail: str


def _overlapping_pairs(manager: TrafficManager) -> List[tuple]:
    pairs = []
    for index, first in enumerate(manager.npcs):
        for second in manager.npcs[index + 1:]:
            if first.state == "crashed" and second.state == "crashed":
                continue
            if first.layer == second.layer and boxes_intersect(
                first.x, first.y, first.heading, first.length_m, first.width_m,
                second.x, second.y, second.heading, second.length_m, second.width_m,
            ):
                pairs.append((first, second))
    return pairs


def _lane_offset_from_way(npc) -> float:
    """Return signed lateral distance from the NPC's current road centerline."""
    points = npc.way.points_m
    if len(points) < 2:
        return 0.0
    segment_index = min(max(npc.segment_idx, 0), len(points) - 2)
    if npc.direction == 1:
        start, end = points[segment_index], points[segment_index + 1]
    else:
        start, end = points[segment_index + 1], points[segment_index]
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 1e-6:
        return 0.0
    return ((npc.x - start[0]) * dy - (npc.y - start[1]) * dx) / length


def _has_lane_exception(npc) -> bool:
    """Return whether the current state gives an NPC a valid lane exception."""
    return (
        npc.overtaking
        or npc.state in {"turning", "parking", "parking_departure"}
        or npc.debug_waiting_for
        or npc.blocked_timer > 0.0
        or npc.escape_timer > 0.0
        or getattr(npc, "crashed_timer", 0.0) > 0.0
        or npc.state == "crashed"
        or getattr(npc, "turn_recovery_timer", 0.0) > 0.0
        or abs(npc.lane_offset - npc.target_lane_offset) > 0.2
    )


def _red_light_violation(manager, npc, previous_position) -> str | None:
    """Return a reason when an NPC crosses a red signal while moving forward."""
    if previous_position is None or npc.speed < 0.5:
        return None
    heading_x = math.cos(npc.heading)
    heading_y = math.sin(npc.heading)
    stop_lines = []
    approach = manager.traffic_light_manager.find_approach(npc)
    if approach is not None:
        stop_lines.append((
            (
                (approach.stop_line[0][0] + approach.stop_line[1][0]) * 0.5,
                (approach.stop_line[0][1] + approach.stop_line[1][1]) * 0.5,
            ),
            manager.traffic_light_manager.get_signal_state(approach, manager.sim_time),
        ))
    else:
        for light in manager._nearby_traffic_lights(npc.x, npc.y):
            if light.layer != npc.layer:
                continue
            if light.direction_angle is not None:
                angle_error = abs((light.direction_angle - npc.heading + math.pi) % (2.0 * math.pi) - math.pi)
                if angle_error > math.radians(45):
                    continue
            lateral = abs((light.x - npc.x) * -heading_y + (light.y - npc.y) * heading_x)
            if lateral <= 8.0:
                stop_lines.append(((light.x, light.y), light.get_state(manager.sim_time)))

    for stop_point, state in stop_lines:
        if state not in {"red", "all-red", "red+yellow"}:
            continue
        previous_longitudinal = (
            (stop_point[0] - previous_position[0]) * heading_x
            + (stop_point[1] - previous_position[1]) * heading_y
        )
        current_longitudinal = (
            (stop_point[0] - npc.x) * heading_x
            + (stop_point[1] - npc.y) * heading_y
        )
        if previous_longitudinal > 0.0 >= current_longitudinal:
            return f"crossed red signal at ({stop_point[0]:.1f},{stop_point[1]:.1f})"
    return None


def _turning_at_junction(manager, npc) -> bool:
    """Allow road-polygon gaps only while an NPC is turning at a junction."""
    if npc.state != "turning" or len(npc.way.points_m) < 2:
        return False
    candidate_indices = (npc.segment_idx, npc.segment_idx + 1)
    for index in candidate_indices:
        if not 0 <= index < len(npc.way.points_m):
            continue
        junction = npc.way.points_m[index]
        if manager._junction_near_point(junction, npc.layer) and math.hypot(
            npc.x - junction[0], npc.y - junction[1]
        ) <= 35.0:
            return True
    return False


def _turning_loop_violation(npc) -> str | None:
    """Report turn signals that keep an NPC turning indefinitely."""
    if (
        npc.state == "turning"
        and npc.next_route is None
        and getattr(npc, "turn_trajectory", None) is None
        and npc.turn_signal
        and npc.turn_signal_elapsed > 3.5
    ):
        return f"turn_signal={npc.turn_signal!r} elapsed={npc.turn_signal_elapsed:.1f}s"
    return None


def run_audit(steps: int = 1200, dt: float = 0.1, seed: int = 7) -> List[AuditFailure]:
    """Play the traffic simulation headlessly and return invariant violations."""
    random.seed(seed)
    elements = load_local_sample()
    if not elements:
        raise RuntimeError("bundled sample OSM data is unavailable")
    result = build_ways(elements)
    if not result.ways:
        raise RuntimeError("sample OSM data contains no roads")

    first_way = result.ways[0]
    start = first_way.points_m[0]
    player = Car(x=start[0], y=start[1], heading=0.0, speed=0.0)
    manager = TrafficManager(
        result.ways,
        target_count=100,
        spawn_radius_m=300.0,
        despawn_radius_m=450.0,
        traffic_lights=result.traffic_lights,
        stop_signs=result.stop_signs,
        yield_signs=result.yield_signs,
        crossings=result.crossings,
        parking_spaces=result.parking_spaces,
        parking_density=0.5,
    )
    viewport = (start[0] - 150.0, start[1] - 150.0, start[0] + 150.0, start[1] + 150.0)
    failures: List[AuditFailure] = []
    parked_positions = {}
    junction_wait_steps = {}
    lane_violation_steps = {}
    previous_positions = {}

    for step in range(steps):
        manager.update(player, dt, viewport_bounds=viewport)
        for npc in manager.npcs:
            npc_key = id(npc)
            red_light_detail = _red_light_violation(
                manager, npc, previous_positions.get(npc_key)
            )
            if red_light_detail is not None:
                failures.append(AuditFailure(step, "red_light_violation", npc_key, red_light_detail))
            previous_positions[npc_key] = (npc.x, npc.y)
            turning_detail = _turning_loop_violation(npc)
            if turning_detail is not None:
                failures.append(AuditFailure(step, "turning_loop", npc_key, turning_detail))
            if npc.state == "parked":
                position = (npc.x, npc.y)
                previous = parked_positions.get(npc_key)
                if previous is not None and position != previous:
                    failures.append(AuditFailure(step, "parked_vehicle_moved", npc_key, f"{previous} -> {position}"))
                parked_positions[npc_key] = position
            else:
                parked_positions.pop(npc_key, None)

            if npc.state in {"driving", "waiting", "braking"} and not is_point_on_road(
                npc.x, npc.y, ways=manager.ways, car_roads_only=True, layer=npc.layer
            ) and not _turning_at_junction(manager, npc) and npc.turn_recovery_timer <= 0.0 and not manager._junction_near_point(
                (npc.x, npc.y), npc.layer
            ):
                failures.append(AuditFailure(
                    step,
                    "vehicle_off_road",
                    npc_key,
                    f"state={npc.state} position=({npc.x:.1f},{npc.y:.1f}) "
                    f"way={getattr(npc.way, 'highway', '?')}",
                ))

            if npc.state in {"parking", "parking_departure"} and npc.parking_route:
                for route_point in npc.parking_route[:-1]:
                    if not is_point_on_road(
                        route_point[0], route_point[1], ways=manager.ways,
                        car_roads_only=True, layer=npc.layer,
                    ):
                        failures.append(AuditFailure(step, "parking_route_off_road", npc_key, str(route_point)))
                        break

            if npc.state in {"driving", "waiting", "braking", "turning"} and not _has_lane_exception(npc):
                actual_offset = _lane_offset_from_way(npc)
                desired_offset = compute_desired_lane_offset(
                    npc.way,
                    is_overtaking=False,
                    travel_direction=npc.direction,
                )
                if abs(actual_offset - desired_offset) > 1.8:
                    lane_violation_steps[npc_key] = lane_violation_steps.get(npc_key, 0) + 1
                    if lane_violation_steps[npc_key] >= 30:
                        failures.append(AuditFailure(
                            step,
                            "wrong_lane",
                            npc_key,
                            f"actual={actual_offset:.2f}m desired={desired_offset:.2f}m "
                            f"state={npc.state} way={getattr(npc.way, 'highway', '?')} "
                            f"direction={npc.direction} segment={npc.segment_idx}",
                        ))
                else:
                    lane_violation_steps[npc_key] = 0

            if (
                npc.debug_waiting_for == "junction"
                and npc.speed < 1.0
                and npc.junction_wait_timer >= 3.0
            ):
                junction_wait_steps[npc_key] = junction_wait_steps.get(npc_key, 0) + 1
                if junction_wait_steps[npc_key] > 60:
                    nearby = [
                        f"{id(other)}:{other.state}:{other.speed:.1f}:"
                        f"wait={other.junction_wait_timer:.1f}:"
                        f"dist={math.hypot(other.x - npc.x, other.y - npc.y):.1f}"
                        for other in manager.npcs
                        if other is not npc and math.hypot(other.x - npc.x, other.y - npc.y) < 30.0
                    ]
                    failures.append(AuditFailure(
                        step,
                        "junction_deadlock",
                        npc_key,
                        f"wait={npc.junction_wait_timer:.1f}s position=({npc.x:.1f},{npc.y:.1f}) nearby={nearby}",
                    ))
                    junction_wait_steps[npc_key] = -10**9
            else:
                junction_wait_steps[npc_key] = 0

        for first, second in _overlapping_pairs(manager):
            failures.append(AuditFailure(
                step,
                "vehicle_overlap",
                id(first),
                f"overlaps NPC {id(second)} "
                f"first=({first.x:.1f},{first.y:.1f},{first.heading:.2f},{first.state}) "
                f"second=({second.x:.1f},{second.y:.1f},{second.heading:.2f},{second.state})",
            ))

        if failures:
            break

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the headless autonomous traffic audit")
    parser.add_argument("--steps", type=int, default=1200)
    parser.add_argument("--dt", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    failures = run_audit(args.steps, args.dt, args.seed)
    if args.json:
        print(json.dumps([asdict(failure) for failure in failures]))
    elif failures:
        for failure in failures:
            print(f"FAIL step={failure.step} rule={failure.rule} npc={failure.npc_id}: {failure.detail}")
    else:
        print(f"PASS steps={args.steps} seed={args.seed}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())