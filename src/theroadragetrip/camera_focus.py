"""What the camera looks at when it is not on the player's taxi.

A focus is None (the taxi - the simulation's own camera), ("pan", x, y)
after a Ctrl+drag, ("resident", resident_id) or ("npc", vehicle) after a
click. main() applies it after the simulation's camera update each frame,
so returning to the taxi simply eases back.
"""
from __future__ import annotations

import math
from typing import Iterable, Optional, Tuple

FOLLOW_EASE_PER_S = 6.0  # how fast the camera catches up with a followed target


def _vehicle_carrying(resident_id, npcs: Iterable):
    for npc in npcs:
        riders = set(getattr(npc, "occupant_ids", ()) or ()) | set(getattr(npc, "passenger_ids", ()) or ())
        if getattr(npc, "current_driver_id", None) == resident_id or resident_id in riders:
            return npc
    return None


def focus_target(focus, pedestrians: Iterable, npcs) -> Optional[Tuple[float, float]]:
    """World point the focus is on now, or None when it is gone (the
    followed car left the world, the resident can't be found anywhere)."""
    kind = focus[0]
    if kind == "pan":
        return focus[1], focus[2]
    if kind == "npc":
        vehicle = focus[1]
        return (vehicle.x, vehicle.y) if any(npc is vehicle for npc in npcs) else None
    if kind == "resident":
        for pedestrian in pedestrians:
            if getattr(pedestrian, "resident_id", None) == focus[1]:
                return pedestrian.x, pedestrian.y
        vehicle = _vehicle_carrying(focus[1], npcs)  # walked into a car: follow the car
        return (vehicle.x, vehicle.y) if vehicle is not None else None
    return None


def ease_camera(camx: float, camy: float, target: Tuple[float, float], dt: float) -> Tuple[float, float]:
    blend = min(1.0, FOLLOW_EASE_PER_S * dt)
    return camx + (target[0] - camx) * blend, camy + (target[1] - camy) * blend


def pan(focus, camx: float, camy: float, dx_px: float, dy_px: float, px_per_m: float):
    """New ("pan", x, y) focus after dragging the mouse by (dx, dy) screen
    pixels: the world moves with the pointer (screen y grows downwards,
    world y northwards)."""
    x, y = (focus[1], focus[2]) if focus is not None and focus[0] == "pan" else (camx, camy)
    return ("pan", x - dx_px / px_per_m, y + dy_px / px_per_m)


def npc_at_screen_position(npcs, pos, camx, camy, px_per_m, screen_w, screen_h):
    """The NPC vehicle under a click (nearest, within its half length)."""
    best, best_distance = None, math.inf
    for npc in npcs:
        sx = (npc.x - camx) * px_per_m + screen_w / 2
        sy = screen_h / 2 - (npc.y - camy) * px_per_m
        distance = math.hypot(pos[0] - sx, pos[1] - sy)
        if distance <= max(12.0, getattr(npc, "length_m", 4.5) * 0.5 * px_per_m) and distance < best_distance:
            best, best_distance = npc, distance
    return best
