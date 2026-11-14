"""Collision categories and the shared pair filter (docs/specs/collision-detection.md)."""
import math
from enum import IntFlag
from typing import Optional, Sequence, Tuple

from .geo import point_in_polygon, segments_intersect

from .map_level import SURFACE_LEVEL

Point = Tuple[float, float]


class Category(IntFlag):
    VEHICLE = 1
    PEDESTRIAN = 2
    ANIMAL = 4
    BUILDING = 8
    POST = 16
    BARRIER = 32
    ROADWORKS = 64
    NONSOLID = 128


_SOLID = Category.VEHICLE | Category.PEDESTRIAN | Category.ANIMAL | Category.BUILDING | Category.POST \
    | Category.BARRIER | Category.ROADWORKS
_NONE = Category(0)
COLLIDES: dict[Category, Category] = {
    Category.VEHICLE: _SOLID,
    Category.PEDESTRIAN: Category.VEHICLE | Category.BUILDING | Category.BARRIER,
    Category.ANIMAL: Category.VEHICLE,
    Category.BUILDING: Category.VEHICLE | Category.PEDESTRIAN,
    Category.POST: Category.VEHICLE,
    Category.BARRIER: Category.VEHICLE | Category.PEDESTRIAN,
    Category.ROADWORKS: Category.VEHICLE,
    Category.NONSOLID: _NONE,
}


def can_collide(a: Category, b: Category) -> bool:
    return bool(COLLIDES[a] & b)


def same_plane(a, b) -> bool:
    """Both bodies share the OSM `layer` and logical `map_level` (missing = surface)."""
    return (getattr(a, "layer", 0) == getattr(b, "layer", 0)
            and getattr(a, "map_level", SURFACE_LEVEL) == getattr(b, "map_level", SURFACE_LEVEL))


def _edges(points):
    return zip(points, points[1:] + points[:1])


def box_hits_polygon(corners: Sequence[Point], points: Sequence[Point], centre: Optional[Point] = None) -> bool:
    """A box (4 corners) overlaps the closed polygon `points`: centre or a corner inside it,
    a polygon vertex inside the box, or edges crossing."""
    points, corners = list(points), list(corners)
    if centre is not None and point_in_polygon(centre[0], centre[1], points):
        return True
    if any(point_in_polygon(x, y, points) for x, y in corners):
        return True
    min_x, max_x = min(x for x, _ in corners), max(x for x, _ in corners)
    min_y, max_y = min(y for _, y in corners), max(y for _, y in corners)
    box_edges = list(_edges(corners))
    for p, q in _edges(points):  # only edges reaching the box's AABB can cross it
        if (max(p[0], q[0]) >= min_x and min(p[0], q[0]) <= max_x
                and max(p[1], q[1]) >= min_y and min(p[1], q[1]) <= max_y):
            if any(segments_intersect(a, b, p, q) for a, b in box_edges):
                return True
    return any(min_x <= x <= max_x and min_y <= y <= max_y and point_in_polygon(x, y, corners) for x, y in points)


def box_hits_polyline(corners: Sequence[Point], points: Sequence[Point]) -> bool:
    """A box overlaps the open line `points` (no last-to-first edge)."""
    corners = list(corners)
    edges = list(_edges(corners))
    return any(
        point_in_polygon(a[0], a[1], corners) or any(segments_intersect(a, b, c, d) for c, d in edges)
        for a, b in zip(points, points[1:])
    )


def post_box_depth(px, py, radius, x, y, heading, length, width) -> float:
    """How deep a post of `radius` at (px, py) sits in the box expanded by it; > 0 is contact."""
    c, s = math.cos(heading), math.sin(heading)
    dx, dy = px - x, py - y
    return min(length / 2 + radius - abs(dx * c + dy * s), width / 2 + radius - abs(-dx * s + dy * c))
