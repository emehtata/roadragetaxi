"""A motorcycle - small, one-seat, household-eligible. Reuses render/
vehicles.py's existing (previously unused) motorcycle sprite branch, and
is only ever spawned when [experimental] enable_two_wheelers is on (see
NPCVehicleManager's vehicle_distribution wiring)."""
from __future__ import annotations

from ..base import VehicleDefinition, VehiclePlugin


class MotorcyclePlugin(VehiclePlugin):
    definition = VehicleDefinition(
        id="motorcycle",
        name="Motorcycle",
        sprite_key="motorcycle",
        length_m=2.0,
        width_m=0.7,
        capacity=1,
        household_eligible=True,
        traffic_weight=0.10,
        experimental=True,
    )


PLUGIN = MotorcyclePlugin()
