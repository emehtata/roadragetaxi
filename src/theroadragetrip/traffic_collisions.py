"""Collision separation and crash handling for autonomous traffic."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Callable, Iterable, List, Tuple

from .geo import (
    boxes_intersect,
    dist_point_to_segment,
    get_oriented_box_corners,
    point_in_polygon,
)

if TYPE_CHECKING:
    from .osm import Way
    from .traffic import NPCCar


def resolve_npc_static_obstacle(
    npc: NPCCar,
    previous_position: Tuple[float, float],
    nearby_buildings: Callable[[float, float, float], Iterable[Any]],
    nearby_trees: Callable[[float, float, float], Iterable[Tuple[float, float]]],
    nearby_ways: Callable[[float, float, float], Iterable[Way]],
    crash: Callable[[NPCCar, float], None],
) -> bool:
    """Stop an NPC that reaches a building or tree outside a drivable road."""
    car_radius = math.hypot(npc.length_m, npc.width_m) * 0.5
    corners = get_oriented_box_corners(
        npc.x, npc.y, npc.heading, npc.length_m, npc.width_m
    )
    for building in nearby_buildings(npc.x, npc.y, car_radius):
        if getattr(building, "layer", 0) != npc.layer:
            continue
        points = getattr(building, "points_m", ())
        if len(points) < 3:
            continue
        bbox = getattr(building, "bbox", None)
        if bbox == (0.0, 0.0, 0.0, 0.0):
            xs, ys = zip(*points)
            bbox = (min(xs), min(ys), max(xs), max(ys))
        if bbox and not (
            bbox[0] - car_radius <= npc.x <= bbox[2] + car_radius
            and bbox[1] - car_radius <= npc.y <= bbox[3] + car_radius
        ):
            continue
        intersects = point_in_polygon(npc.x, npc.y, points) or any(
            point_in_polygon(x, y, points) for x, y in corners
        )
        if not intersects:
            intersects = any(
                dist_point_to_segment(
                    npc.x, npc.y, points[index][0], points[index][1],
                    points[(index + 1) % len(points)][0],
                    points[(index + 1) % len(points)][1],
                ) <= car_radius
                for index in range(len(points))
            )
        if not intersects:
            continue
        if any(
            getattr(way, "layer", 0) == npc.layer
            and not getattr(way, "is_tunnel", False)
            and any(
                dist_point_to_segment(
                    npc.x, npc.y, start[0], start[1], end[0], end[1]
                ) <= getattr(way, "half_width_m", 3.0)
                for start, end in zip(way.points_m, way.points_m[1:])
            )
            for way in nearby_ways(npc.x, npc.y, car_radius)
        ):
            continue
        npc.x, npc.y = previous_position
        crash(npc, 3.0)
        return True

    tree_radius = car_radius + 1.0
    for tree_x, tree_y in nearby_trees(npc.x, npc.y, tree_radius):
        if math.hypot(npc.x - tree_x, npc.y - tree_y) > tree_radius:
            continue
        away_x = previous_position[0] - tree_x
        away_y = previous_position[1] - tree_y
        away_distance = math.hypot(away_x, away_y)
        if away_distance < 1e-6:
            away_x = -math.cos(npc.heading)
            away_y = -math.sin(npc.heading)
            away_distance = 1.0
        safe_distance = tree_radius + 0.2
        npc.x = tree_x + away_x / away_distance * safe_distance
        npc.y = tree_y + away_y / away_distance * safe_distance
        crash(npc, 3.0)
        return True
    return False


def resolve_npc_collisions(
    npcs: List[NPCCar],
    build_grid: Callable[[], None],
    nearby_npcs: Callable[[NPCCar], Iterable[NPCCar]],
    keep_near_way: Callable[[NPCCar], None],
    crash: Callable[[NPCCar], None],
    lane_offset: Callable[[Way, bool, int], float],
) -> None:
    """Separate overlapping NPCs and disable genuine moving-car crashes."""
    build_grid()
    for _ in range(24):
        build_grid()
        resolved_pairs = set()
        found_collision = False
        for npc in npcs:
            for other in nearby_npcs(npc):
                if other is npc or other.layer != npc.layer:
                    continue
                pair = tuple(sorted((id(npc), id(other))))
                if pair in resolved_pairs:
                    continue
                resolved_pairs.add(pair)
                if not boxes_intersect(
                    npc.x, npc.y, npc.heading, npc.length_m, npc.width_m,
                    other.x, other.y, other.heading, other.length_m, other.width_m,
                ):
                    continue
                found_collision = True
                dx = npc.x - other.x
                dy = npc.y - other.y
                distance = math.hypot(dx, dy)
                if distance <= 1e-6:
                    dx = math.cos(npc.heading)
                    dy = math.sin(npc.heading)
                    normalizing_distance = 1.0
                else:
                    normalizing_distance = distance
                min_distance = (npc.length_m + other.length_m) * 0.5 + 1.0
                push = max(0.5, min(8.0, min_distance - distance)) * 0.5
                nx = dx / normalizing_distance
                ny = dy / normalizing_distance
                npc_is_static = npc.state in {"parked", "reserved"}
                other_is_static = other.state in {"parked", "reserved"}
                if npc_is_static or other_is_static:
                    if npc_is_static and other_is_static:
                        npc.speed = 0.0
                        other.speed = 0.0
                    elif npc_is_static:
                        other.x -= nx * push * 2.0
                        other.y -= ny * push * 2.0
                        other.speed = 0.0
                        keep_near_way(other)
                    else:
                        npc.x += nx * push * 2.0
                        npc.y += ny * push * 2.0
                        npc.speed = 0.0
                        keep_near_way(npc)
                    continue
                if npc.state == "parking" or other.state == "parking":
                    if npc.state == "parking" and other.state == "parking":
                        npc.speed = 0.0
                        other.speed = 0.0
                    elif npc.state == "parking":
                        other.x -= nx * push * 2.0
                        other.y -= ny * push * 2.0
                        other.speed = 0.0
                        keep_near_way(other)
                    else:
                        npc.x += nx * push * 2.0
                        npc.y += ny * push * 2.0
                        npc.speed = 0.0
                        keep_near_way(npc)
                    continue
                if abs(math.cos(npc.heading - other.heading)) > 0.7:
                    separation = (
                        (npc.x - other.x) * math.cos(npc.heading)
                        + (npc.y - other.y) * math.sin(npc.heading)
                    )
                    direction = 1.0 if separation >= 0.0 else -1.0
                    backoff = 8.0
                    trailing_npc = other if separation >= 0.0 else npc
                    npc.x += math.cos(npc.heading) * backoff * direction
                    npc.y += math.sin(npc.heading) * backoff * direction
                    other.x -= math.cos(npc.heading) * backoff * direction
                    other.y -= math.sin(npc.heading) * backoff * direction
                    keep_near_way(npc)
                    keep_near_way(other)
                    trailing_npc.blocked_timer = max(trailing_npc.blocked_timer, 2.0)
                    trailing_npc.escape_timer = max(trailing_npc.escape_timer, 2.0)
                    trailing_npc.overtaking = True
                    trailing_npc.overtake_timer = trailing_npc.escape_timer
                    trailing_npc.target_lane_offset = lane_offset(
                        trailing_npc.way,
                        getattr(trailing_npc.way, "oneway", 0) != 0,
                        trailing_npc.direction,
                    )
                    npc.speed = 0.0
                    other.speed = 0.0
                    continue
                npc.x += nx * push
                npc.y += ny * push
                other.x -= nx * push
                other.y -= ny * push
                keep_near_way(npc)
                keep_near_way(other)
                if boxes_intersect(
                    npc.x, npc.y, npc.heading, npc.length_m, npc.width_m,
                    other.x, other.y, other.heading, other.length_m, other.width_m,
                ):
                    backoff = 6.0
                    heading_alignment = abs(math.cos(npc.heading - other.heading))
                    if heading_alignment > 0.7:
                        separation = (
                            (npc.x - other.x) * math.cos(npc.heading)
                            + (npc.y - other.y) * math.sin(npc.heading)
                        )
                        direction = 1.0 if separation >= 0.0 else -1.0
                        npc.x += math.cos(npc.heading) * backoff * direction
                        npc.y += math.sin(npc.heading) * backoff * direction
                        other.x -= math.cos(other.heading) * backoff * direction
                        other.y -= math.sin(other.heading) * backoff * direction
                    else:
                        npc.x -= math.cos(npc.heading) * backoff
                        npc.y -= math.sin(npc.heading) * backoff
                        other.x -= math.cos(other.heading) * backoff
                        other.y -= math.sin(other.heading) * backoff
                    keep_near_way(npc)
                    keep_near_way(other)
                npc.speed = 0.0
                other.speed = 0.0
                crash(npc)
                crash(other)
        if not found_collision:
            break
