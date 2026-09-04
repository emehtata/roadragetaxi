"""Traffic signal state management for autonomous traffic."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, List, Optional

from .osm import IntersectionApproach, LogicalIntersection, SignalGroup

if TYPE_CHECKING:
    from .traffic import NPCCar


class TrafficLightManager:
    """Update cached logical signal groups and answer NPC signal queries."""

    def __init__(self, intersections: List[LogicalIntersection]):
        self.intersections = intersections
        self._groups: dict[str, SignalGroup] = {}
        for intersection in intersections:
            for approach in intersection.approaches:
                if approach.signal_group is not None:
                    self._groups[approach.signal_group.approach_id] = approach.signal_group

    def update(self, current_time: float) -> None:
        """Advance all signal groups from simulation time without rebuilding geometry."""
        for group in self._groups.values():
            group.get_state(current_time)

    def get_signal_state(self, approach: IntersectionApproach, current_time: float) -> str:
        """Return the signal state for an approach, or green when uncontrolled."""
        if approach.signal_group is None:
            return "green"
        return approach.signal_group.get_state(current_time)

    def find_approach(self, npc: NPCCar) -> Optional[IntersectionApproach]:
        """Find the cached incoming approach matching an NPC's road and heading."""
        best_approach = None
        best_distance = float("inf")
        heading_x = math.cos(npc.heading)
        heading_y = math.sin(npc.heading)
        for intersection in self.intersections:
            distance_to_center = math.hypot(
                npc.x - intersection.center[0], npc.y - intersection.center[1]
            )
            if distance_to_center > intersection.radius_m + 40.0:
                continue
            for approach in intersection.approaches:
                if npc.way not in approach.road_segments:
                    continue
                direction_x, direction_y = approach.direction_vector
                if heading_x * direction_x + heading_y * direction_y < 0.5:
                    continue
                if distance_to_center < best_distance:
                    best_approach = approach
                    best_distance = distance_to_center
        return best_approach
