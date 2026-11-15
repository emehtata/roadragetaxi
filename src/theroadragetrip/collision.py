"""Collision categories and the shared pair filter (docs/specs/collision-detection.md)."""
import math
from collections import deque
from enum import IntFlag
from itertools import chain
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
    Category.PEDESTRIAN: Category.VEHICLE | Category.PEDESTRIAN | Category.BUILDING | Category.BARRIER,
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


def circle_hits_circle(ax, ay, ar, bx, by, br) -> float:
    """Overlap depth of two circles; 0 when apart."""
    return max(0.0, ar + br - math.hypot(bx - ax, by - ay))


def post_box_depth(px, py, radius, x, y, heading, length, width) -> float:
    """How deep a post of `radius` at (px, py) sits in the box expanded by it; > 0 is contact."""
    c, s = math.cos(heading), math.sin(heading)
    dx, dy = px - x, py - y
    return min(length / 2 + radius - abs(dx * c + dy * s), width / 2 + radius - abs(-dx * s + dy * c))


class StaticEntry:
    """One indexed static obstacle; `bbox` is fixed at insert."""
    __slots__ = ("obj", "category", "layer", "level", "bbox", "source", "group")
    half_width_m = 0.0  # SpatialWayGrid pads cells by this

    def __init__(self, obj, category: Category, layer: int, level, bbox, source: str):
        self.obj, self.category, self.layer, self.level, self.bbox, self.source = obj, category, layer, level, bbox, source
        self.group: list = []  # the entries of its source item; emptied when that item unloads


def _bbox_of(obj):
    bbox = getattr(obj, "bbox", None)
    if bbox and tuple(bbox) != (0.0, 0.0, 0.0, 0.0):
        return tuple(bbox)
    points = getattr(obj, "points_m", None)
    if points:
        xs, ys = zip(*points)
        return (min(xs), min(ys), max(xs), max(ys))
    if hasattr(obj, "x") and hasattr(obj, "y"):
        return (obj.x, obj.y, obj.x, obj.y)
    return None


REMOVALS_PER_SYNC = 64  # bounded grid clean-up per sync after a tile unload (~1 us each)


class StaticObstacleIndex:
    """The level-aware static-obstacle index (buildings, fences, railings, posts, trees)
    over one SpatialWayGrid. Streamed source lists add and remove entries without a rebuild."""

    def __init__(self, cell_size: float = 50.0):
        from .physics import SpatialWayGrid  # physics imports map data; keep collision.py light
        self.grid = SpatialWayGrid(cell_size, map_level=None)
        self._sources: dict = {}  # source -> [list ref, count indexed, {id(item): [StaticEntry]}]
        self._dead: list = []  # unloaded entries (category 0: no query matches them) still in the grid

    def _drain(self, budget: int = REMOVALS_PER_SYNC) -> None:
        dead, remove = self._dead, self.grid.remove
        for entry in dead[-budget:]:
            remove(entry)
        del dead[-budget:]

    def sync(self, source: str, items: list, category: Category, accept=None, expand=None) -> None:
        state = self._sources.get(source)
        if state is None:
            state = self._sources[source] = [items, 0, {}]
        ref, count, entries = state
        if ref is items and len(items) == count and not self._dead:
            return  # every tick: nothing new
        new = items[count:] if ref is items and len(items) >= count else self._diff(items, entries)
        if self._dead:
            self._drain()
        flags, surface_only = int(category), not category & Category.BUILDING  # plain int: IntFlag & is slow
        for item in new:
            if id(item) in entries:
                continue  # listed twice: indexed once
            made = []
            if accept is None or accept(item):
                for obj in (expand(item) if expand is not None else (item,)):
                    bbox = _bbox_of(obj)
                    if bbox is None:
                        continue
                    level = None if surface_only else getattr(obj, "map_level", None)
                    level = SURFACE_LEVEL if level is None else level  # on_map_level: none = surface
                    entry = StaticEntry(obj, flags, getattr(obj, "layer", 0), level, bbox, source)
                    entry.group = made
                    self.grid.insert(entry)
                    made.append(entry)
            if made:  # only indexed items: forget and query never touch the rejected
                entries[id(item)] = made
        state[0], state[1] = items, len(items)

    def forget(self, section: str, removed: list) -> None:
        """autofetch unloaded `removed` from the world list `section` (filtered in place):
        their entries leave queries now, at a cost proportional to them, and the next sync
        of that list needs no diff. "sceneries" covers "sceneries.trees" too."""
        removed_ids = None
        for source, state in self._sources.items():
            if source.split(".")[0] != section:
                continue
            if removed_ids is None:
                removed_ids = set(map(id, removed))
            popped = list(map(state[2].pop, removed_ids & state[2].keys()))  # all C: no per-item bytecode
            self._dead.extend(chain.from_iterable(popped))  # out of the grid over the next syncs (_drain)
            deque(map(list.clear, popped), 0)  # empty groups: out of queries now
            # The list lost exactly `removed`: the synced prefix shrinks by as many (one of them in the
            # unsynced tail only makes the tail start early; the duplicate check skips what is indexed).
            state[1] = max(0, state[1] - len(removed))

    def _diff(self, items: list, entries: dict) -> list:
        """A replaced or shrunk list (a tile unloaded): drop the entries of the items gone,
        by identity; survivors keep theirs. Returns the items not indexed yet."""
        alive = set(map(id, items))
        for key in entries.keys() - alive:
            made = entries.pop(key)
            self._dead.extend(made)  # out of the grid over the next syncs
            made.clear()  # an empty group: out of queries now
        added = alive - entries.keys()  # (rejected items come back here and are checked again)
        return [item for item in items if id(item) in added] if added else []

    def query(self, x, y, radius, categories: Category, level=None, layer=None, source=None) -> list:
        """Unique objects whose bbox reaches the square around (x, y), in insertion order."""
        grid, size = self.grid.grid, self.grid.cell_size
        minx, miny, maxx, maxy = x - radius, y - radius, x + radius, y + radius
        found, categories = {}, int(categories)
        gy0, gy1 = int(miny // size), int(maxy // size) + 1
        for gx in range(int(minx // size), int(maxx // size) + 1):
            for gy in range(gy0, gy1):
                for entry in grid.get((gx, gy), ()):
                    b = entry.bbox
                    if (entry.category & categories and entry.group and b[0] <= maxx and b[2] >= minx and b[1] <= maxy and b[3] >= miny
                            and (source is None or entry.source == source)
                            and (layer is None or entry.layer == layer)
                            and (level is None or entry.level == level)):
                        found[id(entry)] = entry
        if len(found) < 2:
            return [entry.obj for entry in found.values()]
        order = self.grid._insertion_order
        return [entry.obj for entry in sorted(found.values(), key=lambda e: order[id(e)])]

    def indexed(self, source: str) -> tuple:
        """(list ref, count) last synced for `source`."""
        state = self._sources.get(source)
        return (state[0], state[1]) if state else (None, 0)

    def objects(self, source: str) -> list:
        state = self._sources.get(source)
        return [entry.obj for made in state[2].values() for entry in made] if state else []
