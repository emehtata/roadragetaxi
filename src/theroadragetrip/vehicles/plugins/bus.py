"""A public bus - high capacity, never household-owned. Not yet routed
along real bus lines or stopping at bus_stops (see NPC-003.md section 4's
"future support for bus stops and public transportation") - today it's
just a background-traffic vehicle plugin with bus-like dimensions/
capacity/speed."""
from __future__ import annotations

from ..base import VehicleDefinition, VehiclePlugin


class BusPlugin(VehiclePlugin):
    definition = VehicleDefinition(
        id="bus",
        name="Bus",
        sprite_key="car",
        length_m=11.0,
        width_m=2.5,
        capacity=40,
        max_speed_kmh=70.0,
        household_eligible=False,
        errand_eligible=False,
        traffic_weight=0.02,
    )


PLUGIN = BusPlugin()
