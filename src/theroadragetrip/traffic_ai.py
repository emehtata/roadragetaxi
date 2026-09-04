"""Per-vehicle driving decisions for autonomous traffic."""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Callable, Iterable

if TYPE_CHECKING:
    from .physics import Car
    from .osm import Way
    from .traffic import NPCCar


def update_lane_decision(
    npc: NPCCar,
    player_car: Car,
    nearby_npcs: Callable[[NPCCar], Iterable[NPCCar]],
    dt: float,
    lane_offset: Callable[[Way, bool, int], float],
    turn_lane_offset: Callable[[Way, str], float],
) -> None:
    """Update one NPC's lane and overtaking state without moving it."""
    npc.escape_timer = max(0.0, npc.escape_timer - dt)
    npc.turn_recovery_timer = max(0.0, npc.turn_recovery_timer - dt)
    npc.rage_timer = max(0.0, npc.rage_timer - dt)
    if npc.turn_signal:
        npc.turn_signal_elapsed += dt
    if getattr(npc.way, "oneway", 0) == 0 and npc.rage_timer <= 0.0:
        npc.overtaking = False
        npc.overtake_timer = 0.0
        if npc.turn_signal and npc.next_route is not None:
            npc.target_lane_offset = turn_lane_offset(npc.way, npc.turn_signal)
        else:
            npc.target_lane_offset = lane_offset(npc.way, False, npc.direction)
        npc.lane_offset = npc.target_lane_offset
    if npc.overtaking:
        npc.overtake_timer -= dt
        if npc.overtake_timer <= 0:
            npc.overtaking = False
            npc.target_lane_offset = lane_offset(npc.way, False, npc.direction)
    else:
        car_ahead = False
        for other in nearby_npcs(npc):
            if other is npc or other.layer != npc.layer:
                continue
            dx = other.x - npc.x
            dy = other.y - npc.y
            distance = math.hypot(dx, dy)
            if 3.0 < distance < 25.0:
                angle_to_other = math.atan2(dy, dx)
                angle_diff = (angle_to_other - npc.heading + math.pi) % (2 * math.pi) - math.pi
                if abs(angle_diff) < 0.6 and npc.speed > other.speed:
                    car_ahead = True
                    break

        if not car_ahead and player_car.layer == npc.layer:
            dx = player_car.x - npc.x
            dy = player_car.y - npc.y
            distance = math.hypot(dx, dy)
            if 3.0 < distance < 25.0:
                angle_to_player = math.atan2(dy, dx)
                angle_diff = (angle_to_player - npc.heading + math.pi) % (2 * math.pi) - math.pi
                if abs(angle_diff) < 0.6 and npc.speed > player_car.speed:
                    car_ahead = True

        if car_ahead and getattr(npc.way, "oneway", 0) != 0:
            npc.overtaking = True
            npc.overtake_timer = random.uniform(3.0, 6.0)
            npc.target_lane_offset = lane_offset(npc.way, True, npc.direction)

    offset_diff = npc.target_lane_offset - npc.lane_offset
    if abs(offset_diff) > 0.01:
        shift_speed = 3.0
        npc.lane_offset += math.copysign(min(abs(offset_diff), shift_speed * dt), offset_diff)
