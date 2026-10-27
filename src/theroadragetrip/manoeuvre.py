"""Multi-point manoeuvres for NPC vehicles: a three-point turn out of a kerbside
spot, a reverse-and-correct into a yard.

A vehicle turns about its rear axle with a least turning radius
(physics.rear_axle_shift, min_turn_radius), so a pose it cannot drive onto
forwards is reached by the shortest path of forward and reverse arcs and
straights - a Reeds-Shepp path (rsplan, MIT). Poses here are the rear axle's
(x, y, heading); npc.py converts, checks the vehicle's body along the plan and
drives it run by run, reversing only when the space behind is clear (§§ 34-35).
"""
from __future__ import annotations

import math
from typing import Callable, List, Optional, Tuple

from rsplan import planner

Pose = Tuple[float, float, float]
STEP_M = 0.25  # between the plan's points
CHECK_EVERY = 2  # body checks every this many points (0.5 m)
MAX_DETOUR = 4.0  # a plan longer than this many times the straight distance, plus SLACK_M, is not a manoeuvre
SLACK_M = 20.0


def plan(start: Pose, goal: Pose, radius: float, valid: Callable[[float, float, float, int], bool]) -> Optional[List[List[Tuple[float, float, float, int]]]]:
    """The manoeuvre from `start` to `goal` (rear-axle poses) at `radius`: its
    runs, each a list of (x, y, heading, direction +1 forward / -1 reverse) in
    one direction - or None when there is none `valid` (the body's pose
    check, given each point's direction) holds along, or it is a long way
    round rather than a manoeuvre."""
    try:
        path = planner.path(start, goal, radius, 0.0, STEP_M)
    except (ValueError, ZeroDivisionError, RuntimeError):
        return None
    straight = math.hypot(goal[0] - start[0], goal[1] - start[1])
    if sum(abs(float(segment.length)) for segment in path.segments) > straight * MAX_DETOUR + SLACK_M:
        return None
    points = [(float(w.x), float(w.y), float(w.yaw), int(w.driving_direction)) for w in path.waypoints()]
    if not points or not all(valid(x, y, yaw, direction) for x, y, yaw, direction in points[::CHECK_EVERY] + points[-1:]):
        return None
    runs: List[List[Tuple[float, float, float, int]]] = []
    for point in points:
        if runs and runs[-1][-1][3] == point[3]:
            runs[-1].append(point)
        else:
            runs.append([point])
    return [run for run in runs if len(run) > 1 or run is runs[-1]]


def follow(run, rear_x: float, rear_y: float, heading: float, lookahead_m: float = 1.5) -> Tuple[float, bool]:
    """Steering for one run: (steer -1..1, positive left, as for the run's
    direction; whether the run's end is reached). Pure pursuit from the rear
    axle - aimed backwards on a reverse run, where steering acts the other way."""
    direction = run[0][3]
    nearest = min(range(len(run)), key=lambda i: (run[i][0] - rear_x) ** 2 + (run[i][1] - rear_y) ** 2)
    end = run[-1]
    if math.hypot(end[0] - rear_x, end[1] - rear_y) < 0.35 or nearest == len(run) - 1:
        return 0.0, True
    target = run[min(len(run) - 1, nearest + max(1, int(lookahead_m / STEP_M)))]
    desired = math.atan2(target[1] - rear_y, target[0] - rear_x) + (math.pi if direction < 0 else 0.0)
    error = math.atan2(math.sin(desired - heading), math.cos(desired - heading))
    steer = max(-1.0, min(1.0, error / math.radians(30.0)))
    return (steer if direction > 0 else -steer), False


if __name__ == "__main__":  # a three-point turn: about face on the spot
    runs = plan((0.0, 0.0, 0.0), (0.0, 0.0, math.pi), 3.7, lambda x, y, yaw, direction: abs(y) < 10.0)
    assert runs is not None and [run[0][3] for run in runs] == [1, -1, 1], runs and [run[0][3] for run in runs]
    assert plan((0.0, 0.0, 0.0), (0.0, 0.0, math.pi), 3.7, lambda x, y, yaw, direction: abs(y) < 1.0) is None  # no room
    print("ok")
