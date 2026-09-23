"""Static definitions for the built-in NPC vehicle types."""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class VehicleDefinition:
    id: str
    name: str
    sprite_key: str
    length_m: float
    width_m: float
    capacity: int
    max_speed_kmh: Optional[float] = None
    requires_parking: bool = True
    is_road_vehicle: bool = True
    household_eligible: bool = False
    passenger_eligible: bool = True
    errand_eligible: bool = True
    traffic_weight: float = 0.0
    experimental: bool = False


VEHICLE_DEFINITIONS = {
    definition.id: definition
    for definition in (
        VehicleDefinition("car", "Car", "car", 4.3, 1.8, 5, household_eligible=True, traffic_weight=0.75),
        VehicleDefinition("van", "Van", "car", 5.2, 2.0, 8, household_eligible=True, traffic_weight=0.08),
        VehicleDefinition("truck", "Truck", "car", 7.5, 2.3, 2, 80.0, errand_eligible=False, traffic_weight=0.05),
        VehicleDefinition("bus", "Bus", "car", 11.0, 2.5, 40, 70.0, errand_eligible=False, traffic_weight=0.02),
        VehicleDefinition("motorcycle", "Motorcycle", "motorcycle", 2.0, 0.7, 1, household_eligible=True, traffic_weight=0.10, experimental=True),
        VehicleDefinition("bicycle", "Bicycle", "bicycle", 1.8, 0.5, 1, requires_parking=False, is_road_vehicle=False),
    )
}


def vehicle_definition(vehicle_id: str) -> VehicleDefinition:
    return VEHICLE_DEFINITIONS.get(vehicle_id, VEHICLE_DEFINITIONS["car"])
