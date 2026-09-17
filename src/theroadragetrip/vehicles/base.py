"""Generic NPC vehicle-type plugin interface (see .github/prompts/NPC-003.md).

A plugin describes one vehicle type (car, van, truck, ...) via a
``VehicleDefinition`` plus a plain ``VehiclePlugin`` subclass. The Vehicle
Core (``npc.py``) only ever calls the capability-query methods below - it
never branches on a vehicle's type id. Every built-in plugin is pure data
(no method overrides needed); a future plugin with genuinely different
behavior can still override any query.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class VehicleDefinition:
    """Static description of one vehicle type."""

    id: str
    name: str
    # What render/vehicles.py's draw_npc_cars uses to pick a sprite - it
    # already branches on vehicle_type in ("motorcycle", "moped") for a
    # dedicated sprite and falls back to the generic tinted rectangle body
    # for everything else. sprite_key just names which of those two
    # rendering paths this plugin uses; adding a real third sprite is a
    # rendering change, not a Vehicle Core one.
    sprite_key: str
    length_m: float
    width_m: float
    capacity: int  # passenger capacity, including the driver
    max_speed_kmh: Optional[float] = None
    requires_driver: bool = True
    requires_parking: bool = True
    is_road_vehicle: bool = True
    household_eligible: bool = False
    passenger_eligible: bool = True
    errand_eligible: bool = True
    # Relative spawn weight among road-vehicle plugins for the general
    # background population (NPCVehicleManager) - 0.0 means "never
    # auto-spawned into the population" (e.g. bicycle, already owned by
    # pedestrian.py's CyclistManager).
    traffic_weight: float = 0.0
    # Off by default even when traffic_weight > 0 - NPCVehicleManager
    # excludes it from the population unless explicitly opted in (see its
    # include_experimental param, wired to config's
    # [experimental] enable_two_wheelers). Generic, not a per-id special
    # case in the Vehicle Core - any future opt-in-only vehicle type
    # reuses this same flag.
    experimental: bool = False


class VehiclePlugin:
    """Base class for one vehicle type.

    Plain class with plain methods (not abc.ABC/typing.Protocol) - matches
    activities.ActivityPlugin's own convention, the direct precedent this
    mirrors.
    """

    definition: VehicleDefinition

    def has_driver_requirement(self) -> bool:
        return self.definition.requires_driver

    def get_passenger_capacity(self) -> int:
        return self.definition.capacity

    def requires_parking(self) -> bool:
        return self.definition.requires_parking

    def can_be_household_owned(self) -> bool:
        return self.definition.household_eligible

    def can_carry_passengers(self) -> bool:
        return self.definition.passenger_eligible

    def can_be_used_for_errands(self) -> bool:
        return self.definition.errand_eligible

    def get_dimensions(self) -> Tuple[float, float]:
        return self.definition.length_m, self.definition.width_m

    def get_max_speed_kmh(self) -> Optional[float]:
        return self.definition.max_speed_kmh
