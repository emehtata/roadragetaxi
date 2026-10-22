"""Towed trailers: a body of its own behind the towing vehicle's hitch.

The trailer's axle is pulled after the hitch at a fixed distance (the
drawbar plus the body up to its axle), so it swings in behind on turns,
cuts the corner and straightens out - never a rigid extension of the car.
Pure geometry, shared by NPC traffic now and long trucks next.
"""
from __future__ import annotations

import math
from typing import Optional, Tuple

TELEPORT_SLACK_M = 3.0  # the axle this much off its distance: the vehicle was placed anew - start straight behind


def hitch_point(x: float, y: float, heading: float, length_m: float) -> Tuple[float, float]:
    """The middle of the towing vehicle's rear."""
    return x - math.cos(heading) * length_m * 0.5, y - math.sin(heading) * length_m * 0.5


def follow(hitch: Tuple[float, float], axle: Optional[Tuple[float, float]], heading: float, spec) -> Tuple[float, float]:
    """The axle's new place: pulled after the hitch, `drawbar + axle` behind it."""
    reach = spec.drawbar_m + spec.axle_m
    if axle is not None:
        dx, dy = hitch[0] - axle[0], hitch[1] - axle[1]
        distance = math.hypot(dx, dy)
        if distance > 1e-6 and abs(distance - reach) <= TELEPORT_SLACK_M:
            return hitch[0] - dx / distance * reach, hitch[1] - dy / distance * reach
    return hitch[0] - math.cos(heading) * reach, hitch[1] - math.sin(heading) * reach


def pose(hitch: Tuple[float, float], axle: Tuple[float, float], spec) -> Tuple[float, float, float]:
    """The trailer body's centre and heading (towards the hitch)."""
    heading = math.atan2(hitch[1] - axle[1], hitch[0] - axle[0])
    centre = spec.drawbar_m + spec.length_m * 0.5
    return hitch[0] - math.cos(heading) * centre, hitch[1] - math.sin(heading) * centre, heading
