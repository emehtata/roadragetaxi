import collections
import concurrent.futures
from collections import defaultdict
import json
import logging
import math
import multiprocessing
import os
import random
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import requests

from ..geo import dist_point_to_segment, point_in_polygon
from ..tile_streaming import TileCoord, active_tiles, tile_bbox, tile_changes, world_to_tile

logger = logging.getLogger(__name__)

from .models import (
    Way,
    SignalGroup,
    IntersectionApproach,
    LogicalIntersection,
    TrafficLight,
)


def deduplicate_traffic_lights(traffic_lights: List[TrafficLight]) -> List[TrafficLight]:
    """Keep at most one OSM signal for each approach of a junction."""
    kept: List[TrafficLight] = []
    junction_radius = 60.0
    approach_angle = math.radians(45.0)

    for light in traffic_lights:
        nearby = [
            existing for existing in kept
            if existing.layer == light.layer
            and math.hypot(existing.x - light.x, existing.y - light.y) <= junction_radius
        ]
        same_approach = next(
            (
                existing for existing in nearby
                if (
                    existing.direction_angle is None
                    and light.direction_angle is None
                    and math.hypot(existing.x - light.x, existing.y - light.y) <= 8.0
                )
                or (
                    existing.direction_angle is not None
                    and light.direction_angle is not None
                    and abs(
                    (existing.direction_angle - light.direction_angle + math.pi) % (2.0 * math.pi) - math.pi
                    ) <= approach_angle
                )
            ),
            None,
        )
        if same_approach is None:
            kept.append(light)

    return kept


def complete_traffic_light_approaches(traffic_lights: List[TrafficLight], ways: List) -> List[TrafficLight]:
    """Add missing approach signals around an already signalized junction."""
    completed = list(traffic_lights)
    junction_radius = 60.0
    approach_angle = math.radians(45.0)
    visited: set[int] = set()

    for index, light in enumerate(traffic_lights):
        if index in visited:
            continue
        component = []
        pending = [index]
        visited.add(index)
        while pending:
            current_index = pending.pop()
            current = traffic_lights[current_index]
            component.append(current)
            for other_index, other in enumerate(traffic_lights):
                if other_index in visited or other.layer != current.layer:
                    continue
                if math.hypot(current.x - other.x, current.y - other.y) <= junction_radius:
                    visited.add(other_index)
                    pending.append(other_index)

        layer = component[0].layer
        center_x = sum(signal.x for signal in component) / len(component)
        center_y = sum(signal.y for signal in component) / len(component)
        arm_angles: List[float] = []
        for way in ways:
            if getattr(way, "layer", 0) != layer or len(way.points_m) < 2:
                continue
            segment = min(
                zip(way.points_m, way.points_m[1:]),
                key=lambda pair: dist_point_to_segment(
                    center_x, center_y, pair[0][0], pair[0][1], pair[1][0], pair[1][1]
                ),
            )
            if dist_point_to_segment(center_x, center_y, *segment[0], *segment[1]) > 100.0:
                continue
            angle = math.atan2(segment[1][1] - segment[0][1], segment[1][0] - segment[0][0])
            # A divided carriageway is commonly mapped as a one-way way.  Its
            # reverse geometric arm is not an incoming approach and must not
            # receive a synthetic signal.
            oneway = getattr(way, "oneway", 0)
            arm_angles_for_way = (
                (angle + math.pi,) if oneway == 1 else
                (angle,) if oneway == -1 else
                (angle, angle + math.pi)
            )
            for arm_angle in arm_angles_for_way:
                if all(
                    abs((arm_angle - existing + math.pi) % (2.0 * math.pi) - math.pi) > math.radians(25)
                    for existing in arm_angles
                ):
                    arm_angles.append(arm_angle)

        if len(arm_angles) < 3:
            continue
        generated_count = 0
        for arm_index, arm_angle in enumerate(arm_angles):
            approach_direction = (arm_angle + math.pi) % (2.0 * math.pi)
            if any(
                signal.direction_angle is not None
                and abs(
                    (signal.direction_angle - approach_direction + math.pi) % (2.0 * math.pi) - math.pi
                ) <= approach_angle
                for signal in component
            ):
                continue
            signal_axis = arm_angle % math.pi
            signal_offset = 8.0 if (math.pi * 0.25) <= signal_axis < (math.pi * 0.75) else 0.0
            completed.append(
                TrafficLight(
                    x=center_x + math.cos(arm_angle) * 14.0,
                    y=center_y + math.sin(arm_angle) * 14.0,
                    cycle_time=24.0,
                    offset=signal_offset,
                    layer=layer,
                    id=-(index + 1) * 100 - arm_index,
                    direction_angle=approach_direction,
                )
            )
            generated_count += 1

        if generated_count:
            for signal in component:
                if math.hypot(signal.x - center_x, signal.y - center_y) <= 1.5:
                    signal.renderable = False

        grouped: dict[int, SignalGroup] = {}
        for signal in completed:
            if signal.layer != layer or math.hypot(signal.x - center_x, signal.y - center_y) > junction_radius:
                continue
            if signal.direction_angle is None:
                continue
            direction = signal.direction_angle % (2.0 * math.pi)
            axis = direction % math.pi
            direction_key = round(direction / math.radians(25.0))
            group = grouped.get(direction_key)
            if group is None:
                phase_id = 1 if math.sin(axis) ** 2 > 0.5 else 0
                group = SignalGroup(
                    approach_id=f"{layer}:{center_x:.0f}:{center_y:.0f}:{direction_key}",
                    phase_id=phase_id,
                    offset=8.0 if phase_id else 0.0,
                    cycle_time=24.0,
                    green_duration=10.0,
                    yellow_duration=2.0,
                    all_red_duration=1.0,
                    red_duration=9.0,
                    red_yellow_duration=2.0,
                )
                grouped[direction_key] = group
            signal.signal_group = group
            signal.approach_id = group.approach_id
            signal.allowed_movements = group.allowed_movements

    return deduplicate_traffic_lights(completed)


def build_logical_intersections(
    traffic_lights: List[TrafficLight], ways: List[Way], cluster_radius_m: float = 60.0
) -> List[LogicalIntersection]:
    """Build immutable-ish intersection geometry once from signal OSM evidence."""
    intersections: List[LogicalIntersection] = []
    for signal in traffic_lights:
        if any(
            existing.layer == signal.layer
            and math.hypot(signal.x - existing.center[0], signal.y - existing.center[1]) <= cluster_radius_m
            for existing in intersections
        ):
            continue
        nearby_signals = [
            candidate for candidate in traffic_lights
            if candidate.layer == signal.layer
            and math.hypot(candidate.x - signal.x, candidate.y - signal.y) <= cluster_radius_m
        ]
        center = (
            sum(candidate.x for candidate in nearby_signals) / len(nearby_signals),
            sum(candidate.y for candidate in nearby_signals) / len(nearby_signals),
        )
        candidate_ways = [
            way for way in ways
            if getattr(way, "layer", 0) == signal.layer
            and len(way.points_m) >= 2
            and min(
                dist_point_to_segment(center[0], center[1], start[0], start[1], end[0], end[1])
                for start, end in zip(way.points_m, way.points_m[1:])
            ) <= 100.0
        ]
        approaches: List[IntersectionApproach] = []
        for way in candidate_ways:
            segment = min(
                zip(way.points_m, way.points_m[1:]),
                key=lambda pair: dist_point_to_segment(center[0], center[1], *pair[0], *pair[1]),
            )
            dx = segment[1][0] - segment[0][0]
            dy = segment[1][1] - segment[0][1]
            length = math.hypot(dx, dy)
            if length <= 1e-6:
                continue
            directions = ((dx / length, dy / length), (-dx / length, -dy / length))
            oneway = getattr(way, "oneway", 0)
            if oneway == 1:
                directions = directions[:1]
            elif oneway == -1:
                directions = directions[1:]
            for direction_x, direction_y in directions:
                approach_id = f"{signal.layer}:{center[0]:.0f}:{center[1]:.0f}:{round(math.atan2(direction_y, direction_x), 2)}"
                if any(approach.approach_id == approach_id for approach in approaches):
                    continue
                stop_center = (
                    center[0] - direction_x * 12.0,
                    center[1] - direction_y * 12.0,
                )
                half_width = getattr(way, "half_width_m", 4.0)
                stop_line = (
                    (stop_center[0] - direction_y * half_width, stop_center[1] + direction_x * half_width),
                    (stop_center[0] + direction_y * half_width, stop_center[1] - direction_x * half_width),
                )
                matching_signal = next(
                    (
                        candidate for candidate in nearby_signals
                        if candidate.direction_angle is not None
                        and abs((candidate.direction_angle - math.atan2(direction_y, direction_x) + math.pi) % (2.0 * math.pi) - math.pi) <= math.radians(45.0)
                    ),
                    None,
                )
                allowed_movements = frozenset({"straight", "right"})
                turn_lanes = getattr(way, "turn_lanes", None)
                if turn_lanes:
                    movement_names = {
                        movement
                        for lane in turn_lanes.split("|")
                        for movement in lane.split(";")
                        if movement in {"left", "through", "right", "slight_left", "slight_right"}
                    }
                    allowed_movements = frozenset(
                        {"straight" if movement == "through" else movement for movement in movement_names}
                    ) or allowed_movements
                elif getattr(way, "lanes", 1) >= 3:
                    allowed_movements = frozenset({"left", "straight", "right"})
                if matching_signal is not None and allowed_movements != matching_signal.allowed_movements:
                    matching_signal.allowed_movements = allowed_movements
                    if matching_signal.signal_group is not None:
                        matching_signal.signal_group.allowed_movements = allowed_movements
                approaches.append(
                    IntersectionApproach(
                        approach_id=approach_id,
                        road_segments=[way],
                        direction_vector=(direction_x, direction_y),
                        stop_line=stop_line,
                        allowed_movements=allowed_movements,
                        signal_group=matching_signal.signal_group if matching_signal else None,
                    )
                )
        if len(approaches) >= 3:
            intersections.append(
                LogicalIntersection(
                    intersection_id=f"{signal.layer}:{center[0]:.0f}:{center[1]:.0f}",
                    center=center,
                    radius_m=cluster_radius_m,
                    layer=signal.layer,
                    approaches=approaches,
                    traffic_lights=nearby_signals,
                )
            )
    return intersections
