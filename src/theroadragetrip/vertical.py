"""The player car's height over the ground, decided on the server (docs/specs/terrain-following-bodies.md part 3).

TerrainFlight takes the car over the DEM; BumpFlight over a mapped speed bump, from the bump's profile, the speed and the car's
wheelbase alone (axle_hops, bump_hops), so it does not depend on the frame rate. The server has no bridge deck data: only
layer 0 is ever airborne. The client draws the server's air_height and land_bump (player state, protocol 3); it computes no arc.
"""
from __future__ import annotations

import bisect
import math
from typing import Callable, Dict, Iterable, Optional, Tuple

GRAVITY = 9.81
LAUNCH_MIN_MPS = 12.0
BUMP_DECAY_S = 0.25
RESET_JUMP_M = 5.0
SLOPE_WINDOW_M = 1.0  # the road's vertical speed under a take-off is its rise over this last length
LAND_BUMP_MPS = 8.0  # a landing at this vertical speed is a full bump
BUMP_LAND_MPS = 3.0  # ...and for a mapped bump's hop (a wheel's closing speed)
MIN_HOP_S = 0.05  # a hop shorter than this is no hop: no landing jolt
QUIET_M = 0.0  # after a landing a car drives this far before it can take off again (one crest, one hop)
FLIGHT_STEP_S = 1.0 / 240.0  # a terrain arc is integrated in sub-steps this short at most
SWEEP_M = 0.25  # a move is checked for a take-off every this far (a crest is not stepped over)
MAX_SWEEP_PIECES = 16


class TerrainFlight:
    """The car over the DEM. It leaves the ground where v^2 times the crest curvature reaches g, the curvature measured at
    the DEM's own spacing: a raster of `step` m cannot show a crest tighter than that, so its grade kinks and embankments
    (80 m cells) never launch a car, while a fine synthetic hill (10 m) does. It then flies a ballistic arc until it meets
    the ground. Only layer 0 launches."""

    def __init__(self) -> None:
        self.airborne = False
        self.z = 0.0
        self.vz = 0.0
        self.land_bump = 0.0
        self._layer = 0
        self._at: Optional[Tuple[float, float]] = None
        self._quiet_m = 0.0  # metres still to drive before the next take-off (after a landing or a hop that ended at once)
        self._air_s = 0.0
        self.last_hop_s = 0.0  # seconds in the air of the last hop
        self._last_ground = 0.0

    def _leaves(self, ground_at, step_m: float, x: float, y: float, cx: float, cy: float, speed: float) -> bool:
        """True where a car at (x, y) driving along (cx, cy) leaves the ground: v^2 times the crest curvature reaches g."""
        h = max(step_m, 1.0)
        curvature = (ground_at(x + cx * h, y + cy * h) - 2.0 * ground_at(x, y) + ground_at(x - cx * h, y - cy * h)) / (h * h)
        return speed * speed * -curvature >= GRAVITY

    @staticmethod
    def _clears(ground_at, x: float, y: float, cx: float, cy: float, speed: float, vz: float) -> bool:
        """True if the ballistic arc from (x, y) at vertical speed vz stays over the ground for MIN_HOP_S."""
        g0, t = ground_at(x, y), 0.0
        while t < MIN_HOP_S:
            t += MIN_HOP_S / 4.0
            if g0 + vz * t - 0.5 * GRAVITY * t * t <= ground_at(x + cx * abs(speed) * t, y + cy * abs(speed) * t):
                return False
        return True

    def _fly(self, ground_from: float, ground: float, dt: float) -> None:
        """The ballistic arc over `dt` seconds in fixed sub-steps (at most FLIGHT_STEP_S each), landing at the first contact."""
        if dt <= 0.0:
            return
        n = max(1, math.ceil(dt / FLIGHT_STEP_S))
        h = dt / n
        for i in range(1, n + 1):
            self.vz -= GRAVITY * h
            self.z += self.vz * h
            self._air_s += h
            under = ground_from + (ground - ground_from) * (i / n)  # the road along the tick's move
            if self.z < under:
                self.last_hop_s = self._air_s
                if self._air_s >= MIN_HOP_S:
                    self.land_bump = min(max(-self.vz / LAND_BUMP_MPS, 0.0), 1.0)
                self.airborne, self.z, self.vz, self._quiet_m = False, under, 0.0, QUIET_M
                return

    def step(self, ground_at, step_m: float, x: float, y: float, heading: float, speed: float, layer: int, dt: float) -> float:
        """Advance one tick; returns the ground height under the car. The move since the last tick is swept in
        SWEEP_M pieces, so a fast car cannot step over a crest and the take-off is where the crest is, whatever the frame rate.
        The raster's cell kinks are smoothed over its own spacing first (a cross average at half a cell), so an arc is not
        stopped by a kink the road does not have."""
        raw, half = ground_at, max(step_m, 1.0) * 0.5
        ground_at = lambda gx, gy: (2.0 * raw(gx, gy) + raw(gx + half, gy) + raw(gx - half, gy) + raw(gx, gy + half) + raw(gx, gy - half)) / 6.0
        ground = ground_at(x, y)
        self.land_bump = max(0.0, self.land_bump - dt / BUMP_DECAY_S)
        previous = self._at
        if previous is None or layer != self._layer or math.dist((x, y), previous) > RESET_JUMP_M:
            self.airborne, self.z, self.vz = False, ground, 0.0
            previous = None
        self._layer, self._at = layer, (x, y)
        if previous is not None and not self.airborne:
            self._quiet_m = max(0.0, self._quiet_m - math.dist((x, y), previous))
        if layer != 0:
            self.z = ground
            return ground
        if self.airborne:
            self._fly(self._last_ground, ground, dt)
            self._last_ground = ground
            return ground
        self.z = ground
        self._last_ground = ground
        if abs(speed) >= LAUNCH_MIN_MPS and previous is not None and self._quiet_m <= 0.0:
            d = math.copysign(1.0, speed)
            cx, cy = math.cos(heading) * d, math.sin(heading) * d
            pieces = min(MAX_SWEEP_PIECES, max(1, math.ceil(math.dist((x, y), previous) / SWEEP_M)))
            for i in range(1, pieces + 1):
                f = i / pieces
                px, py = previous[0] + (x - previous[0]) * f, previous[1] + (y - previous[1]) * f
                if self._leaves(ground_at, step_m, px, py, cx, cy, speed):
                    g0 = ground_at(px, py)
                    vz = abs(speed) * (g0 - ground_at(px - cx * SLOPE_WINDOW_M, py - cy * SLOPE_WINDOW_M)) / SLOPE_WINDOW_M
                    if not self._clears(ground_at, px, py, cx, cy, speed, vz):
                        continue  # the road curves too little (or rises again at once): the car stays on it
                    self.airborne, self.z, self._air_s, self.vz = True, g0, 0.0, vz
                    self._last_ground = ground
                    self._fly(g0, ground, (1.0 - f) * dt)  # the rest of the tick in the air
                    break
        return ground


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


WHEELBASE_RATIO = 0.6  # wheelbase over body length for a passenger car
DROOP_M = 0.06  # how far a wheel can drop from the body, on its spring, before the tyre leaves the road
BUMP_WINDOW_M = 2.0  # the road's vertical speed a wheel hands to the body: its rise over the last 2 m (tyre patch and suspension filter a short bump)
MIN_LIFT_M = 0.01
HOP_DS = 0.02  # metres between the lift samples kept per hop


def axle_hops(kind: str, v: float, scale: float = 1.0) -> list:
    """The hops ONE axle makes over a bump of `kind` at constant speed `v` m/s, closed form (no frame time).

    Physics (a quarter-car with a point-follower tyre): the road lifts the wheel, and the body, carried by the springs, keeps
    the vertical speed the road gave it (its rise over the last BUMP_WINDOW_M) and falls under g like a ghost.
    A wheel stays on the road while the road drops away less than the spring's droop DROOP_M beneath that ballistic path (the
    suspension absorbs it); only beyond that does the tyre leave the road, until the road comes back up to within DROOP_M.
    The hop is where the tyre is off, its lift is how far beyond the droop. Fixed 0.5 ms steps, fixed profile: the same plan for
    the same speed, whatever the frame rate. Each hop: (s_off, s_on, peak lift, vertical closing speed, lift samples, seconds),
    s along the road from the bump's start. `scale` stretches the profile's height (tests). Hops lifting under MIN_LIFT_M are
    not hops (a wheel that rises a centimetre is a jolt, not a hop)."""
    height, length, _, _ = BUMP_PROFILES.get(kind, BUMP_PROFILES["bump"])
    if v < LAUNCH_MIN_MPS:
        return []
    dt = 0.0005
    s = -BUMP_WINDOW_M
    z, vz = 0.0, 0.0
    hops, current, step = [], None, 0
    while s < length + v * 0.6:
        s += v * dt
        road = bump_profile(kind, s) * scale
        z += vz * dt
        vz -= GRAVITY * dt
        if z <= road:
            z, vz = road, v * (road - bump_profile(kind, s - BUMP_WINDOW_M) * scale) / BUMP_WINDOW_M
        lift = z - road - DROOP_M
        step += 1
        if lift > 0.0:
            if current is None:
                current = {"s0": s, "samples": [], "peak": 0.0}
            current["peak"] = max(current["peak"], lift)
            if step % max(1, round(HOP_DS / (v * dt))) == 0:
                current["samples"].append((s, lift))
        elif current is not None:
            road_vz = v * (road - bump_profile(kind, s - 0.01) * scale) / 0.01
            if current["peak"] >= MIN_LIFT_M:
                hops.append((current["s0"], s, current["peak"], vz - road_vz, current["samples"], (s - current["s0"]) / v))
            current = None
    return hops


def _merged(intervals: list) -> list:
    out = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def bump_hops(kind: str, v: float, wheelbase: float) -> dict:
    """What a car of `wheelbase` m does over a bump: the front axle meets the profile first and the rear one a wheelbase later,
    each with its own hops. In s of the car's middle: `front` and `rear` hop lists, `air` the merged stretches with an axle off
    the road (steering or drive lost), `seconds` the time in them. The same for the same (kind, speed, wheelbase)."""
    key = (kind, round(v, 1), round(wheelbase, 2))
    if key not in _PLANS:
        hops = axle_hops(kind, round(v, 1))
        half = wheelbase / 2.0
        front = [(h[0] - half, h[1] - half, h) for h in hops]
        rear = [(h[0] + half, h[1] + half, h) for h in hops]
        air = _merged([(a, b) for a, b, _ in front + rear])
        _PLANS[key] = {"front": front, "rear": rear, "air": air, "seconds": sum(b - a for a, b in air) / round(v, 1) if v else 0.0,
                       "peak": max([h[2] for h in hops], default=0.0) / 2.0}
        if len(_PLANS) > 256:
            _PLANS.pop(next(iter(_PLANS)))
    return _PLANS[key]


_PLANS: dict = {}


def _lift_at(hop, s: float) -> float:
    samples = hop[4]
    if not samples or s < samples[0][0] or s > samples[-1][0]:
        return 0.0
    i = bisect.bisect_left(samples, (s,))
    if i == 0:
        return samples[0][1]
    (s0, l0), (s1, l1) = samples[i - 1], samples[min(i, len(samples) - 1)]
    return l0 if s1 == s0 else l0 + (l1 - l0) * (s - s0) / (s1 - s0)


class BumpFlight:
    """The hop of the player's car over a mapped speed bump, from bump_hops at the speed at the bump's start. Per move it adds
    the seconds of the hop the move covered (air_s), so the airtime is the same at any frame rate. air_height is the body's
    lift: the mean of the two axles' lifts. `airborne` while an axle is off the road."""

    def __init__(self) -> None:
        self.airborne = False
        self.air_height = 0.0
        self.land_bump = 0.0
        self.air_s = 0.0
        self._row = None
        self._plan = None
        self._dir = 1.0
        self._speed = 0.0
        self._skip = None

    def _s(self, p) -> float:
        s, _ = row_coords(self._row, p)
        return s if self._dir > 0 else self._row[4] - s

    def step(self, p0, p1, speed: float, dt: float, field, layer: int, wheelbase: float = 2.4) -> None:
        self.land_bump = max(0.0, self.land_bump - dt / BUMP_DECAY_S)
        self.air_s, self.airborne, self.air_height = 0.0, False, 0.0
        if field is None or layer != 0 or abs(speed) < LAUNCH_MIN_MPS:
            self._row, self._skip = None, None
            return
        if self._row is None:
            row = field.crossing(p0, p1, wheelbase / 2.0 + 1.0)
            if row is None:
                self._skip = None
                return
            if row is self._skip:
                return
            s0, _ = row_coords(row, p0)
            s1, _ = row_coords(row, p1)
            self._row, self._dir, self._speed = row, (1.0 if s1 >= s0 else -1.0), abs(speed)
            self._plan = bump_hops(row[6], self._speed, wheelbase)
        a, b = self._s(p0), self._s(p1)
        half = wheelbase / 2.0
        for lo, hi in self._plan["air"]:
            self.air_s += max(0.0, min(b, hi) - max(a, lo)) / self._speed
            if lo <= b < hi:
                self.airborne = True
        lifts = [0.0, 0.0]
        for i, hops in enumerate((self._plan["front"], self._plan["rear"])):
            for lo, hi, hop in hops:
                if lo <= b < hi:
                    lifts[i] = _lift_at(hop, b + (half if i == 0 else -half))
                if a < hi <= b:
                    self.land_bump = max(self.land_bump, min(max(-hop[3] / BUMP_LAND_MPS, 0.0), 1.0))
        self.air_height = 0.5 * (lifts[0] + lifts[1])
        end = max([self._row[4] + half] + [hi for _, hi in self._plan["air"]])
        if b >= end or b < -2.0 - half:
            self._skip, self._row, self._plan = self._row, None, None


def dem_step_m(dem) -> float:
    """The sample spacing of a DEM (its crests are not resolved finer than this)."""
    from .osm.elevation import DEM80_STEP
    return float(getattr(dem, "step", DEM80_STEP))


def ground_height(dem, x: float, y: float) -> float:
    """The terrain under (x, y): the DEM, flat 0 without one. Speed bumps are not in it (BumpFlight handles them)."""
    base = dem.height_m(x, y) if dem is not None else None
    return base or 0.0


def world_ground_at(world) -> Optional[Callable[[float, float], float]]:
    """`ground_at` for update_car_physics: the world's DEM; None on flat ground."""
    dem = getattr(world, "dem", None)
    return None if dem is None else (lambda x, y: ground_height(dem, x, y))


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
