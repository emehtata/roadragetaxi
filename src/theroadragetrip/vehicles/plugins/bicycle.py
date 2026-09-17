"""A bicycle - registered for capability-query completeness (NPC-003.md
acceptance criteria explicitly list it), but never auto-spawned by
NPCVehicleManager (traffic_weight=0.0): pedestrian.py's CyclistManager
already fully owns background bicycle traffic through its own pedestrian-
network-based movement/spawn system. Building a second bicycle movement
path through the road-vehicle Driver/parking system here would duplicate
that existing system, which NPC-003.md section 1/17 explicitly says not
to do. is_road_vehicle=False and requires_parking=False reflect that a
bicycle doesn't use the road-vehicle parking/traffic pipeline at all."""
from __future__ import annotations

from ..base import VehicleDefinition, VehiclePlugin


class BicyclePlugin(VehiclePlugin):
    definition = VehicleDefinition(
        id="bicycle",
        name="Bicycle",
        sprite_key="bicycle",
        length_m=1.8,
        width_m=0.5,
        capacity=1,
        requires_parking=False,
        is_road_vehicle=False,
        household_eligible=False,
        traffic_weight=0.0,
    )


PLUGIN = BicyclePlugin()
