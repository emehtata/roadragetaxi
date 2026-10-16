"""Traffic-light decision layer shared by the player's red-light assist
(taxi.py) and autonomous NPC driving (npc.py).

Kept separate from both so neither the scoring-coupled player assist nor
the NPC driving loop has to re-derive "which light actually governs this
lane" - a single geometric definition of "relevant" light used by both.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

from .geo import angle_diff


class TrafficAction:
    PROCEED = "PROCEED"
    SLOW = "SLOW"
    STOP = "STOP"


@dataclass
class TrafficDecision:
    action: str
    target_speed_mps: float
    stop_position: Optional[Tuple[float, float]] = None
    reason: str = ""
    # The actual TrafficLight object this decision was based on, if any -
    # intersection-rules section 18/21: lets callers (debug HUD, tests) see exactly
    # which physical signal was judged relevant, not just a text reason.
    light: Optional[object] = None


def nearest_traffic_light_ahead(
    x: float,
    y: float,
    heading: float,
    traffic_lights,
    detection_distance_m: float = 45.0,
    lateral_limit_m: float = 8.0,
    angle_limit_deg: float = 45.0,
) -> Optional[Tuple[float, object]]:
    """Return (distance_ahead_m, TrafficLight) for the nearest light that
    actually governs this lane, or None.

    A light only counts as "ahead" here when it sits within a narrow
    forward cone of the travel line (lateral_limit_m either side) and,
    where the light records the road's alignment, roughly faces the
    vehicle's own direction of travel - a light for the opposing or a
    crossing approach must never be mistaken for the one controlling this
    lane, which is what a naive "nearest light" rule would get wrong at
    every intersection.
    """
    heading_x = math.cos(heading)
    heading_y = math.sin(heading)
    nearest = None
    for tl in traffic_lights:
        dx = tl.x - x
        dy = tl.y - y
        longitudinal = dx * heading_x + dy * heading_y
        lateral = abs(dx * -heading_y + dy * heading_x)
        if longitudinal <= 0.0 or longitudinal > detection_distance_m or lateral > lateral_limit_m:
            continue
        direction_angle = getattr(tl, "direction_angle", None)
        if direction_angle is not None:
            angle_error = abs(angle_diff(direction_angle, heading))
            if angle_error > math.radians(angle_limit_deg):
                continue
        if nearest is None or longitudinal < nearest[0]:
            nearest = (longitudinal, tl)
    return nearest


def nearest_vehicle_ahead(
    x: float,
    y: float,
    heading: float,
    obstacles,
    self_id=None,
    detection_distance_m: float = 30.0,
    lateral_limit_m: float = 2.5,
) -> Optional[Tuple[float, object]]:
    """Return (distance_ahead_m, obstacle) for the nearest of `obstacles`
    actually in this vehicle's own lane ahead of it, or None.

    collision-avoidance section 2: the exact same forward-cone projection
    nearest_traffic_light_ahead already uses (longitudinal/lateral
    dot-product test) - a lane is a narrow corridor, so an obstacle a couple
    of lanes over must never be mistaken for one actually blocking this
    one, the same reasoning that function's docstring gives for lights.

    `obstacles` is any iterable of objects with `.x`/`.y` (an NPCVehicle or
    a physics.Car both already satisfy this) - not typed to a single class
    so this works for other NPCs and the player's own car alike.
    self_id, when given, skips any obstacle whose id(...) matches (a
    vehicle is never "ahead of itself").
    """
    heading_x = math.cos(heading)
    heading_y = math.sin(heading)
    nearest = None
    for obstacle in obstacles:
        if self_id is not None and id(obstacle) == self_id:
            continue
        dx = obstacle.x - x
        dy = obstacle.y - y
        longitudinal = dx * heading_x + dy * heading_y
        lateral = abs(dx * -heading_y + dy * heading_x)
        if longitudinal <= 0.0 or longitudinal > detection_distance_m or lateral > lateral_limit_m:
            continue
        if nearest is None or longitudinal < nearest[0]:
            nearest = (longitudinal, obstacle)
    return nearest


def crossing_yield_decision(vehicle, obstacles, *, signs=(), speed_limit_mps=None):
    """Brake before conflicting traffic from the right at an unsignalled crossing."""
    def signed(car):
        fx, fy = math.cos(car.heading), math.sin(car.heading)
        for sign in signs:
            dx, dy = sign.x - car.x, sign.y - car.y
            direction = getattr(sign, "direction_angle", None)
            if (getattr(sign, "layer", 0) == getattr(getattr(car, "way", None), "layer", 0)
                    and -8.0 < dx * fx + dy * fy < 35.0
                    and abs(dx * fy - dy * fx) < 4.0
                    and (direction is None or abs(angle_diff(direction, car.heading)) < math.pi / 4.0)):
                return True
        return False

    fx, fy = math.cos(vehicle.heading), math.sin(vehicle.heading)
    own_way = getattr(vehicle, "way", None)
    own_signed = signed(vehicle)
    nearest = None
    for other in obstacles:
        state = getattr(other, "state", None)
        if (other is vehicle or not hasattr(other, "heading")
                or getattr(state, "value", state) in ("PARKED", "CRASHED")):
            continue
        other_way = getattr(other, "way", None)
        if getattr(own_way, "layer", 0) != getattr(other_way, "layer", 0):
            continue
        dx, dy = other.x - vehicle.x, other.y - vehicle.y
        gx, gy = math.cos(other.heading), math.sin(other.heading)
        cross = fx * gy - fy * gx
        if abs(cross) < 0.5:  # same lane or opposing traffic is not a crossing approach
            continue
        distance = (dx * gy - dy * gx) / cross
        other_distance = (dx * fy - dy * fx) / cross
        if not (0.0 < distance < 45.0 and -2.0 < other_distance < 45.0):
            continue
        other_signed = signed(other)
        own_priority = getattr(own_way, "priority_road", False) and not own_signed
        other_priority = getattr(other_way, "priority_road", False) and not other_signed
        right = dx * fy - dy * fx > 0.0
        if (own_priority and not other_priority) or (other_signed and not own_signed):
            continue
        if not ((own_signed and not other_signed) or (other_priority and not own_priority) or right):
            continue
        # A distant vehicle won't enter the intersection while we cross it.
        if other_distance / max(1.0, abs(getattr(other, "speed", 0.0))) > distance / max(2.0, abs(vehicle.speed)) + 4.0:
            continue
        buffer = getattr(other_way, "half_width_m", 3.5) + vehicle.length_m * 0.5 + 2.0
        gap = max(0.0, distance - buffer)
        cap = 0.0 if gap < 0.1 else math.sqrt(2.0 * 3.0 * gap)
        if nearest is None or cap < nearest.target_speed_mps:
            nearest = TrafficDecision(TrafficAction.STOP if gap < 0.1 else TrafficAction.SLOW,
                                      cap if speed_limit_mps is None else min(cap, speed_limit_mps),
                                      (vehicle.x + fx * gap, vehicle.y + fy * gap),
                                      "yielding to crossing traffic" if own_signed or other_priority else "yielding to traffic from right")
    return nearest


def decide_traffic_action(
    x: float,
    y: float,
    heading: float,
    traffic_lights,
    sim_time: float,
    speed_limit_mps: Optional[float] = None,
    detection_distance_m: float = 45.0,
    stop_buffer_m: float = 4.0,
    deceleration_mps2: float = 3.0,
) -> TrafficDecision:
    """Return a PROCEED/SLOW/STOP decision for the traffic light ahead of
    (x, y, heading), if any govern this lane.

    Yellow is a transition, not green: a vehicle already too close to stop
    comfortably keeps going (it's committed), everyone else brakes for the
    line - never treated as a plain "go".
    """
    cruise_speed = speed_limit_mps if speed_limit_mps is not None else 13.9  # ~50 km/h fallback
    nearest = nearest_traffic_light_ahead(x, y, heading, traffic_lights, detection_distance_m)
    if nearest is None:
        return TrafficDecision(TrafficAction.PROCEED, cruise_speed, reason="no relevant light ahead")

    distance, tl = nearest
    state = tl.get_state(sim_time)
    available_distance = max(0.0, distance - stop_buffer_m)
    stop_position = (
        x + math.cos(heading) * available_distance,
        y + math.sin(heading) * available_distance,
    )
    comfortable_stop_speed = math.sqrt(2.0 * deceleration_mps2 * available_distance)

    if state == "green":
        return TrafficDecision(TrafficAction.PROCEED, cruise_speed, reason="green light ahead", light=tl)

    if state in ("red", "red+yellow"):
        if comfortable_stop_speed <= 0.3:
            return TrafficDecision(TrafficAction.STOP, 0.0, stop_position, reason=f"{state} light ahead", light=tl)
        return TrafficDecision(
            TrafficAction.SLOW, min(cruise_speed, comfortable_stop_speed), stop_position,
            reason=f"{state} light ahead", light=tl,
        )

    # Yellow: only brake if there's still comfortable room to stop in time;
    # a vehicle already inside the braking-too-late zone is committed and
    # proceeds through, exactly like a real driver would.
    if available_distance >= cruise_speed ** 2 / (2.0 * deceleration_mps2):
        return TrafficDecision(
            TrafficAction.SLOW, min(cruise_speed, comfortable_stop_speed), stop_position,
            reason="yellow light, stopping in time", light=tl,
        )
    return TrafficDecision(
        TrafficAction.PROCEED, cruise_speed, reason="yellow light, already committed", light=tl,
    )
