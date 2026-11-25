"""The world's speed bumps, shared with the Godot client (docs/specs/terrain-following-bodies.md part 1).

BUMP_PROFILES are godot/buildings_3d.gd's numbers (tests/fixtures/vertical_profiles.json holds both to them); BumpField
is the lookup the server reads: the bump under a point, or the next one ahead of an NPC.
"""
from __future__ import annotations

import math
from typing import Dict, Iterable, Optional, Tuple

# Speed-bump shapes (godot/buildings_3d.gd BUMP_PROFILES, the same numbers): kind -> (height m, length m,
# ramp m: 0 a raised cosine, else linear ramps to a flat top, width cap m or None = the road's)
BUMP_PROFILES: Dict[str, Tuple[float, float, float, Optional[float]]] = {
    "bump": (0.07, 0.6, 0.0, None), "hump": (0.10, 3.7, 0.0, None),
    "cushion": (0.08, 2.5, 0.0, 1.8), "table": (0.10, 4.6, 1.2, None),
}


def bump_profile(kind: str, s: float) -> float:
    """Height of a `kind` bump `s` m from its start along the road (0 outside it)."""
    height, length, ramp, _ = BUMP_PROFILES.get(kind, BUMP_PROFILES["bump"])
    if s <= 0.0 or s >= length:
        return 0.0
    if ramp:
        return height * min(s, length - s, ramp) / ramp
    return 0.5 * height * (1.0 - math.cos(2.0 * math.pi * s / length))


class BumpField:
    """The world's speed bumps in a 32 m grid: `height(x, y)` reads only the cells around the point."""
    CELL_M = 32.0

    def __init__(self, bumps: Iterable) -> None:
        self._cells: Dict[Tuple[int, int], list] = {}
        self.signature = None  # world_bump_field rebuilds when the world's list changes (map tiles load)
        for b in bumps:
            if getattr(b, "layer", 0) != 0:  # a bump on a bridge is not on the ground road under it
                continue
            kind = getattr(b, "kind", "bump")
            _, length, _, cap = BUMP_PROFILES.get(kind, BUMP_PROFILES["bump"])
            width = getattr(b, "width_m", 3.5)
            angle = getattr(b, "direction_angle", None) or 0.0
            row = (b.x, b.y, math.cos(angle), math.sin(angle), length, 0.5 * (min(width, cap) if cap else width), kind)
            self._cells.setdefault((int(b.x // self.CELL_M), int(b.y // self.CELL_M)), []).append(row)

    def ahead(self, x: float, y: float, heading: float, reach_m: float, lateral_m: float = 3.0) -> Optional[float]:
        """Metres from (x, y) along `heading` to the start of the nearest bump within `reach_m` (negative: on it) whose
        centre is within `lateral_m` of that line; None if there is none. reach_m must be under CELL_M."""
        cx, cy = int(x // self.CELL_M), int(y // self.CELL_M)
        c, s = math.cos(heading), math.sin(heading)
        nearest = None
        for i in (cx - 1, cx, cx + 1):
            for j in (cy - 1, cy, cy + 1):
                for bx, by, _, _, length, half, _ in self._cells.get((i, j), ()):
                    dx, dy = bx - x, by - y
                    along, across = dx * c + dy * s - length * 0.5, -dx * s + dy * c
                    if -length <= along <= reach_m and abs(across) <= min(lateral_m, half + 0.9) and (nearest is None or along < nearest):
                        nearest = along
        return nearest

    def height(self, x: float, y: float) -> float:
        if not self._cells:
            return 0.0
        cx, cy = int(x // self.CELL_M), int(y // self.CELL_M)
        top = 0.0
        for i in (cx - 1, cx, cx + 1):
            for j in (cy - 1, cy, cy + 1):
                for bx, by, c, s, length, half, kind in self._cells.get((i, j), ()):
                    dx, dy = x - bx, y - by
                    along, across = dx * c + dy * s, -dx * s + dy * c
                    if abs(along) < length * 0.5 and abs(across) <= half:
                        top = max(top, bump_profile(kind, along + length * 0.5))
        return top


    def crossing(self, p0: Tuple[float, float], p1: Tuple[float, float], margin: float = 0.0):
        """The bump row a move p0 -> p1 passes over (the one whose start is nearest p0), or None."""
        cx, cy = int(p1[0] // self.CELL_M), int(p1[1] // self.CELL_M)
        best = None
        for i in (cx - 1, cx, cx + 1):
            for j in (cy - 1, cy, cy + 1):
                for row in self._cells.get((i, j), ()):
                    s0, a0 = row_coords(row, p0)
                    s1, a1 = row_coords(row, p1)
                    length, half = row[4], row[5]
                    if min(s0, s1) < length + margin and max(s0, s1) > -margin and min(abs(a0), abs(a1)) <= half:
                        key = abs(s0 if s1 > s0 else length - s0)
                        if best is None or key < best[0]:
                            best = (key, row)
        return None if best is None else best[1]


def row_coords(row, p: Tuple[float, float]) -> Tuple[float, float]:
    """(distance from the bump's start along its axis, distance across it) of point p."""
    bx, by, c, s, length, _, _ = row
    dx, dy = p[0] - bx, p[1] - by
    return dx * c + dy * s + length * 0.5, -dx * s + dy * c


def world_bump_field(world) -> Optional[BumpField]:
    """The world's BumpField, rebuilt when map tiles added bumps to world.speed_bumps; None without any."""
    bumps = getattr(world, "speed_bumps", None)
    if not bumps:
        return None
    signature = hash(tuple(map(id, bumps)))  # any tile swap changes it (a few hundred ids per tick)
    field = getattr(world, "_bump_field", None)
    if field is None or field.signature != signature:
        field = world._bump_field = BumpField(bumps)
        field.signature = signature
    return field
