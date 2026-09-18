"""A freight truck - background traffic only, never household-owned, and
slower than ordinary traffic (max_speed_kmh cap)."""
from __future__ import annotations

from ..base import VehicleDefinition, VehiclePlugin


class TruckPlugin(VehiclePlugin):
    definition = VehicleDefinition(
        id="truck",
        name="Truck",
        sprite_key="car",
        length_m=7.5,
        width_m=2.3,
        capacity=2,
        max_speed_kmh=80.0,
        household_eligible=False,
        errand_eligible=False,
        traffic_weight=0.05,
    )


PLUGIN = TruckPlugin()
