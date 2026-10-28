"""Playground equipment inside OSM leisure=playground areas.

Finnish OSM maps the playgrounds themselves but rarely their equipment
(playground=*: 4 items across ~350 playgrounds in the cached Oulu maps), so
each playground gets a typical set by its size: a sandpit and swings first,
then a slide, spring riders, a climbing frame and a seesaw. Placement is
seeded by the playground's position, so it is the same on every load and
every client. Each item keeps its safety clearance clear of the edge and of
the others, all square to the playground's longest edge.
"""
from __future__ import annotations

import math
import random
from typing import List, Sequence, Tuple

from .geo import dist_point_to_segment, point_in_polygon

# In placing order: (kind, clearance radius m - the item and the free space around it).
# Game-scale, tighter than real safety zones: the median playground (~175 m2) gets four items.
EQUIPMENT = (("sandpit", 1.6), ("swing", 2.2), ("slide", 2.0), ("spring_rider", 0.8),
             ("climbing_frame", 1.8), ("spring_rider", 0.8), ("seesaw", 1.7), ("swing", 2.2))
M2_PER_ITEM = 40.0  # a playground this many square metres per item; smaller ones get fewer
ATTEMPTS = 40  # random spots tried per item before it is left out


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
    (ax, ay), (bx, by) = max(edges, key=lambda edge: math.dist(*edge))
    angle = round(math.atan2(by - ay, bx - ax), 3)
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
