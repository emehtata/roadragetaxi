"""Playground equipment inside OSM leisure=playground areas.

Mapped equipment (OSM playground=*, OSM_EQUIPMENT_KINDS) is used as it is.
Finnish OSM maps the playgrounds themselves but rarely their equipment
(4 items across ~350 playgrounds in the cached Oulu maps), so a playground
with none mapped gets a typical set by its size: a sandpit and swings first,
then a slide, spring riders, a climbing frame and a seesaw. Placement is
seeded by the playground's position, so it is the same on every load and
every client. Each item keeps its safety clearance clear of the edge and of
the others, all square to the playground's longest edge.
"""
from __future__ import annotations

import math
import random
from typing import List, Sequence, Tuple

from .geo import compute_bbox, dist_point_to_segment, point_in_polygon

# In placing order: (kind, clearance radius m - the item and the free space around it).
# Game-scale, tighter than real safety zones: the median playground (~175 m2) gets four items.
EQUIPMENT = (("sandpit", 1.6), ("swing", 2.2), ("slide", 2.0), ("spring_rider", 0.8),
             ("climbing_frame", 1.8), ("spring_rider", 0.8), ("seesaw", 1.7), ("swing", 2.2))
M2_PER_ITEM = 40.0  # a playground this many square metres per item; smaller ones get fewer
ATTEMPTS = 40  # random spots tried per item before it is left out
# OSM playground=* -> the kind drawn (map_chunk.gd); other values are not drawn.
OSM_EQUIPMENT_KINDS = {"swing": "swing", "baby_swing": "swing", "basketswing": "swing", "slide": "slide",
                       "sandpit": "sandpit", "springy": "spring_rider", "climbingframe": "climbing_frame",
                       "structure": "climbing_frame", "climbing_net": "climbing_frame", "seesaw": "seesaw"}
EQUIPMENT_KINDS = frozenset(OSM_EQUIPMENT_KINDS.values())


def longest_edge_angle(points: Sequence[Tuple[float, float]]) -> float:
    """The direction (radians) of the polygon's longest edge."""
    edges = list(zip(points, list(points[1:]) + [points[0]]))
    (ax, ay), (bx, by) = max(edges, key=lambda edge: math.dist(*edge))
    return round(math.atan2(by - ay, bx - ax), 3)


def _area(points: Sequence[Tuple[float, float]]) -> float:
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(points, list(points[1:]) + [points[0]]))) / 2.0


def playground_equipment(points: Sequence[Tuple[float, float]]) -> List[Tuple[float, float, str, float]]:
    """[(x, y, kind, angle)] inside the polygon (world metres; angle in
    radians, as SceneryObject.direction_angle)."""
    if len(points) < 3:
        return []
    count = min(len(EQUIPMENT), int(_area(points) // M2_PER_ITEM))
    if count == 0:
        return []
    edges = list(zip(points, list(points[1:]) + [points[0]]))
    angle = longest_edge_angle(points)
    xs, ys = [x for x, _ in points], [y for _, y in points]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    rng = random.Random(int(round(cx * 10)) * 1_000_003 + int(round(cy * 10)))
    placed: List[Tuple[float, float, str, float]] = []
    for kind, radius in EQUIPMENT[:count]:
        for _ in range(ATTEMPTS):
            x, y = rng.uniform(min(xs), max(xs)), rng.uniform(min(ys), max(ys))
            if (point_in_polygon(x, y, list(points))
                    and min(dist_point_to_segment(x, y, *a, *b) for a, b in edges) >= radius
                    and all(math.dist((x, y), (px, py)) >= radius + other for px, py, _, other in placed)):
                placed.append((x, y, kind, radius))
                break
    return [(round(x, 1), round(y, 1), kind, angle) for x, y, kind, _ in placed]


def equipment_rows(sceneries, scenery_objects) -> List[list]:
    """Chunk rows [x, y, kind, angle] of every playground's equipment: the
    OSM-mapped items inside it (square to it unless mapped as an area), or a
    typical set when it has none; mapped items in no playground stay as mapped."""
    mapped = [obj for obj in scenery_objects if obj.kind in EQUIPMENT_KINDS]
    placed = set()
    rows: List[list] = []
    for scenery in sceneries:
        if scenery.kind != "playground" or len(scenery.points_m) < 3:
            continue
        minx, miny, maxx, maxy = compute_bbox(scenery.points_m)  # Scenery.bbox may be unset
        inside = [obj for obj in mapped if id(obj) not in placed and minx <= obj.x <= maxx and miny <= obj.y <= maxy
                  and point_in_polygon(obj.x, obj.y, list(scenery.points_m))]
        angle = longest_edge_angle(scenery.points_m)
        items = ([(obj.x, obj.y, obj.kind, angle if obj.direction_angle is None else obj.direction_angle) for obj in inside]
                 if inside else playground_equipment(scenery.points_m))
        placed.update(id(obj) for obj in inside)
        rows += [[round(x, 1), round(y, 1), kind, round(item_angle, 3)] for x, y, kind, item_angle in items]
    rows += [[round(obj.x, 1), round(obj.y, 1), obj.kind, round(obj.direction_angle or 0.0, 3)]
             for obj in mapped if id(obj) not in placed]  # a school yard's, a park's
    return rows
