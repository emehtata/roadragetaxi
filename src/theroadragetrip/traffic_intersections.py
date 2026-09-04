"""Intersection reservation management for autonomous traffic."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, List, Optional

from .osm import IntersectionApproach, LogicalIntersection

if TYPE_CHECKING:
    from .traffic import NPCCar


class IntersectionManager:
    """Reserve signalized intersection conflict areas for near-field NPCs."""

    def __init__(self, intersections: List[LogicalIntersection]):
        self.intersections = intersections
        self._reservations: dict[str, dict[int, str]] = {}

    def _intersection_for(self, approach: IntersectionApproach) -> Optional[LogicalIntersection]:
        for intersection in self.intersections:
            if approach in intersection.approaches:
                return intersection
        return None

    def can_enter(self, npc: NPCCar, approach: IntersectionApproach) -> bool:
        intersection = self._intersection_for(approach)
        if intersection is None:
            return True
        reservations = self._reservations.get(intersection.intersection_id, {})
        return all(
            owner_id == id(npc) or reserved_approach == approach.approach_id
            for owner_id, reserved_approach in reservations.items()
        )

    def request_enter(self, npc: NPCCar, approach: IntersectionApproach) -> bool:
        if not self.can_enter(npc, approach):
            return False
        intersection = self._intersection_for(approach)
        if intersection is None:
            return True
        self._reservations.setdefault(intersection.intersection_id, {})[
            id(npc)
        ] = approach.approach_id
        npc.reserved_intersection_id = intersection.intersection_id
        return True

    def release(self, npc: NPCCar) -> None:
        for intersection_id, reservations in list(self._reservations.items()):
            reservations.pop(id(npc), None)
            if not reservations:
                self._reservations.pop(intersection_id, None)
        npc.reserved_intersection_id = None

    def update(self, npcs: List[NPCCar]) -> None:
        active_ids = {id(npc) for npc in npcs}
        for intersection in self.intersections:
            reservations = self._reservations.get(intersection.intersection_id)
            if not reservations:
                continue
            for npc_id in list(reservations):
                npc = next((candidate for candidate in npcs if id(candidate) == npc_id), None)
                if npc is None or npc_id not in active_ids:
                    reservations.pop(npc_id, None)
                    continue
                if (
                    npc.layer != intersection.layer
                    or math.hypot(
                        npc.x - intersection.center[0],
                        npc.y - intersection.center[1],
                    ) > intersection.radius_m + 6.0
                ):
                    self.release(npc)
