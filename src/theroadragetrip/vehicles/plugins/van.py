"""A larger household/traffic vehicle - still an ordinary road car
mechanically, just bigger, with more seats."""
from __future__ import annotations

from ..base import VehicleDefinition, VehiclePlugin


class VanPlugin(VehiclePlugin):
    definition = VehicleDefinition(
        id="van",
        name="Van",
        sprite_key="car",  # no dedicated sprite yet - generic tinted body, larger footprint
        length_m=5.2,
        width_m=2.0,
        capacity=8,
        household_eligible=True,
        traffic_weight=0.08,
    )


PLUGIN = VanPlugin()
