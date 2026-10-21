"""The simulation's view of the world: the reference screen size and scale
the camera follow and the NPC/pedestrian viewport culling are tuned for,
and the rectangle that view covers. No drawing here."""

from __future__ import annotations

import math

SCREEN_W, SCREEN_H = 1280, 720


def client_view_bounds(message):
    """Optional world-metre camera rectangle; reject unbounded/untrusted input."""
    command = message.get("command")
    bounds = command.get("view_bounds") if isinstance(command, dict) else None
    if not isinstance(bounds, list) or len(bounds) != 4:
        return None
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or abs(v) > 1e8 or not math.isfinite(v) for v in bounds):
        return None
    x0, y0, x1, y1 = bounds
    if not (0 < x1 - x0 <= 2000 and 0 < y1 - y0 <= 2000):
        return None
    return tuple(bounds)


SIMULATION_LOOKAHEAD_S = 12.0  # traffic and people simulated this far ahead of a moving taxi


def simulation_bounds(view, x, y, speed, heading=None):
    """Visible area plus entry time and a local safety envelope around the taxi.
    With the heading, the area reaches SIMULATION_LOOKAHEAD_S of travel ahead
    (time, not a fixed distance): at speed, traffic is planned on the road
    before the taxi gets there instead of in the last couple of seconds."""
    if heading is None:
        margin = 60.0 + min(240.0, abs(speed) * 3.0)
        return (min(view[0] - margin, x - 100), min(view[1] - margin, y - 100),
                max(view[2] + margin, x + 100), max(view[3] + margin, y + 100))
    margin = 60.0
    reach = abs(speed) * SIMULATION_LOOKAHEAD_S
    direction = heading if speed >= 0.0 else heading + math.pi
    ahead_x, ahead_y = x + math.cos(direction) * reach, y + math.sin(direction) * reach
    return (min(view[0] - margin, x - 100, ahead_x - margin), min(view[1] - margin, y - 100, ahead_y - margin),
            max(view[2] + margin, x + 100, ahead_x + margin), max(view[3] + margin, y + 100, ahead_y + margin))


def in_bounds(bounds, x, y, radius=0.0):
    return bounds[0] - radius <= x <= bounds[2] + radius and bounds[1] - radius <= y <= bounds[3] + radius


PX_PER_M = 0.7


def _segment_viewport_t_range(x0, y0, ux, uy, seg_len, vminx, vminy, vmaxx, vmaxy):
    """Return the (t_lo, t_hi) sub-range of [0, seg_len] along a unit-
    direction (ux, uy) segment starting at (x0, y0) that falls inside the
    viewport rect, or None if none of it does. O(1) - standard axis-
    aligned line/box clip (Liang-Barsky), used so a long segment with only
    one end near the camera doesn't get treated as visible along its
    entire length."""
    t_lo, t_hi = 0.0, seg_len
    for coord0, u, lo, hi in ((x0, ux, vminx, vmaxx), (y0, uy, vminy, vmaxy)):
        if abs(u) < 1e-9:
            if coord0 < lo or coord0 > hi:
                return None
            continue
        ta = (lo - coord0) / u
        tb = (hi - coord0) / u
        if ta > tb:
            ta, tb = tb, ta
        t_lo = max(t_lo, ta)
        t_hi = min(t_hi, tb)
        if t_lo > t_hi:
            return None
    return t_lo, t_hi


def get_viewport_bounds(
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    margin_m: float = 60.0,
) -> tuple[float, float, float, float]:
    """Calculate world coordinates (minx, miny, maxx, maxy) visible in the viewport."""
    half_w = (screen_w / 2.0) / px_per_m + margin_m
    half_h = (screen_h / 2.0) / px_per_m + margin_m
    return camx - half_w, camy - half_h, camx + half_w, camy + half_h


def minimum_px_per_m_for_viewport_width(
    max_width_m: float = 500.0,
    screen_w: int = SCREEN_W,
    margin_m: float = 30.0,
) -> float:
    """Return the minimum zoom that keeps the viewport width within its limit."""
    drawable_width_m = max(1.0, max_width_m - 2.0 * margin_m)
    return screen_w / drawable_width_m
