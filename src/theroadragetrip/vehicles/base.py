"""Static definitions for the built-in NPC vehicle types."""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TrailerSpec:
    """A towed trailer: its own body behind the hitch at the towing
    vehicle's rear, swinging on it (trailers.py) - a caravan now, a truck's
    trailer next."""
    kind: str  # how it is drawn ("caravan")
    length_m: float  # the body
    width_m: float
    drawbar_m: float  # from the hitch to the body's front
    axle_m: float  # from the body's front to its axle


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
    trailer: Optional[TrailerSpec] = None  # towed behind (length_m/width_m are the towing vehicle's)
    movement: str = "road"  # "road": npc.update_npc on the car network; "cycle": cycling.py on the cycle network
    mass_kg: float = 1500.0  # laden, driver or rider aboard: what a collision's impulse divides by (npc.collision_impulse)


VEHICLE_DEFINITIONS = {
    definition.id: definition
    for definition in (
        VehicleDefinition("car", "Car", "car", 4.3, 1.8, 5, household_eligible=True, traffic_weight=0.75, mass_kg=1500.0),
        VehicleDefinition("van", "Van", "car", 5.2, 2.0, 8, household_eligible=True, traffic_weight=0.08, mass_kg=2300.0),
        VehicleDefinition("truck", "Truck", "car", 7.5, 2.3, 2, 80.0, errand_eligible=False, traffic_weight=0.05, mass_kg=11000.0),
        VehicleDefinition("bus", "Bus", "car", 11.0, 2.5, 40, 70.0, errand_eligible=False, traffic_weight=0.02, mass_kg=14000.0),
        # Snow ploughing and other work later; for now ordinary slow traffic.
        VehicleDefinition("tractor", "Tractor", "car", 4.0, 2.2, 1, 60.0, passenger_eligible=False, errand_eligible=False, traffic_weight=0.02, mass_kg=4500.0),
        # Holiday traffic, as on the camp pitches (osm/campsites.py): a camper
        # van (car rules up to 3.5 t), and a car towing a caravan at most
        # 80 km/h - game policy for the general car-and-trailer limit (no
        # 100 km/h trailer approval modelled); over 70 km/h it may use
        # motorways (§ 58). Not shop-errand traffic: it does not fit a bay.
        VehicleDefinition("camper_van", "Camper van", "car", 6.2, 2.3, 4, traffic_weight=0.012, mass_kg=3300.0),
        VehicleDefinition("car_caravan", "Car with caravan", "car", 4.3, 1.8, 4, 80.0, errand_eligible=False, traffic_weight=0.008,
                          trailer=TrailerSpec("caravan", 4.8, 2.3, 0.9, 2.8), mass_kg=2800.0),  # with its caravan
        # A motorcycle with its rider: road traffic under car rules, in season only (motorcycle_season.py).
        # Its weight is the summer peak; the season factor scales it down to none in winter.
        VehicleDefinition("motorcycle", "Motorcycle", "motorcycle", 2.2, 0.8, 1, household_eligible=True, traffic_weight=0.03, mass_kg=300.0),
        # Cyclists: their own network and movement (cycling.py) and their own
        # demand share (npc.CYCLING_SHARE), not the car traffic_weight draw.
        VehicleDefinition("bicycle", "Bicycle", "bicycle", 1.8, 0.6, 1, 25.0, requires_parking=False, is_road_vehicle=False,
                          household_eligible=False, passenger_eligible=False, errand_eligible=False, movement="cycle", mass_kg=95.0),
    )
}


def vehicle_definition(vehicle_id: str) -> VehicleDefinition:
    return VEHICLE_DEFINITIONS.get(vehicle_id, VEHICLE_DEFINITIONS["car"])
