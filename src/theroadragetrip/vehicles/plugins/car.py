"""The ordinary household/traffic car - today's only vehicle type, and
still the overwhelming default in the population (see traffic_weight)."""
from __future__ import annotations

from ..base import VehicleDefinition, VehiclePlugin


class CarPlugin(VehiclePlugin):
    definition = VehicleDefinition(
        id="car",
        name="Car",
        sprite_key="car",
        length_m=4.3,
        width_m=1.8,
        capacity=5,
        max_speed_kmh=None,  # no cap beyond the road's own speed limit
        household_eligible=True,
        traffic_weight=0.75,
    )


PLUGIN = CarPlugin()
