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
            angle_error = abs((direction_angle - heading + math.pi) % (2.0 * math.pi) - math.pi)
            if angle_error > math.radians(angle_limit_deg):
                continue
        if nearest is None or longitudinal < nearest[0]:
            nearest = (longitudinal, tl)
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
        return TrafficDecision(TrafficAction.PROCEED, cruise_speed, reason="green light ahead")

    if state in ("red", "red+yellow"):
        if comfortable_stop_speed <= 0.3:
            return TrafficDecision(TrafficAction.STOP, 0.0, stop_position, reason=f"{state} light ahead")
        return TrafficDecision(
            TrafficAction.SLOW, min(cruise_speed, comfortable_stop_speed), stop_position,
            reason=f"{state} light ahead",
        )

    # Yellow: only brake if there's still comfortable room to stop in time;
    # a vehicle already inside the braking-too-late zone is committed and
    # proceeds through, exactly like a real driver would.
    if available_distance >= cruise_speed ** 2 / (2.0 * deceleration_mps2):
        return TrafficDecision(
            TrafficAction.SLOW, min(cruise_speed, comfortable_stop_speed), stop_position,
            reason="yellow light, stopping in time",
        )
    return TrafficDecision(TrafficAction.PROCEED, cruise_speed, reason="yellow light, already committed")
