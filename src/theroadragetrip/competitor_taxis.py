"""Competitor taxis: they take phone fares the player sees, and drive them
(docs/competitor-taxis.md). A competitor is an NPC car of vehicle_kind
"taxi" (npc.py drives it, stops included); this module decides which fare
it takes and walks its TaxiJob through the legs.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional, Tuple

COMPETITOR_TAXIS = 3  # of the NPC population's moving-traffic spawns
NIGHT_COMPETITOR_TAXIS = 10  # busy city centres on Friday/Saturday nights
CRUISE_DWELL_S = 10.0  # a free taxi pauses for dispatch before cruising again
CLAIM_RADIUS_M = 1500.0  # a competitor this near an offer's pickup may take it
CLAIM_RATE_PER_S = 1.0 / 30.0  # ...this often: offers stay on the phone a while
DISPATCH_INTERVAL_S = 1.0
STOP_DWELL_S = 6.0  # at a stop: the passenger boards or leaves
MAX_ROUTE_ATTEMPTS = 5  # a leg that cannot be routed this often: the job is dropped


def night_taxi_target(moment, local_fraction: float, city_target: int) -> int:
    """Gameplay demand estimate, scaled to local density and the existing population budget."""
    if moment is None:
        return 0
    late = (moment.hour >= 22 and moment.weekday() in (4, 5)) or (moment.hour < 6 and moment.weekday() in (5, 6))
    return min(NIGHT_COMPETITOR_TAXIS, math.ceil(max(0, city_target) * 0.25 * max(0.0, min(1.0, local_fraction)))) if late else 0


@dataclass
class TaxiJob:
    passenger_name: str
    pickup: Tuple[float, float]
    dropoff: Tuple[float, float]
    leg: str = "pickup"  # "pickup", then "dropoff"
    state: str = "await_departure"  # "await_departure" -> "driving" -> "stopped" (see the doc)
    stop_until: float = 0.0
    route_attempts: int = 0

    @property
    def target(self) -> Tuple[float, float]:
        return self.pickup if self.leg == "pickup" else self.dropoff

    @property
    def passenger_aboard(self) -> bool:  # (the roof light is lit)
        return self.leg == "dropoff"

    def departing(self) -> None:
        """The leg's route was applied: on the way."""
        self.state = "driving"

    def route_failed(self) -> bool:
        """A leg's route could not be planned; True: give the job up."""
        self.route_attempts += 1
        return self.route_attempts >= MAX_ROUTE_ATTEMPTS

    def at_stop(self, now: float) -> bool:
        """The car is parked: arrived, or still at the stop. Returns True
        when the job is done (the passenger has left at the drop-off)."""
        if self.state == "driving":
            self.state, self.stop_until = "stopped", now + STOP_DWELL_S
        elif self.state == "stopped" and now >= self.stop_until:
            if self.leg == "dropoff":
                return True
            self.leg, self.state, self.route_attempts = "dropoff", "await_departure", 0
        return False


def is_competitor(vehicle) -> bool:
    return getattr(vehicle, "vehicle_kind", None) == "taxi"


def make_competitor(vehicle) -> None:
    vehicle.vehicle_kind = "taxi"
    vehicle.is_taxi = True
    if getattr(vehicle, "vehicle_type", None) == "van":
        vehicle.capacity = 9  # eight passengers plus the driver


class Dispatcher:
    """Hands phone offers to idle competitors (once a DISPATCH_INTERVAL_S)."""

    def __init__(self, rng: Optional[random.Random] = None) -> None:
        self.rng = rng or random.Random()
        self.elapsed = 0.0
        self.taken = 0  # offers competitors have taken

    def update(self, taxi_mgr, npc_manager, dt: float) -> None:
        from .localization import tr
        from .npc import NPCState

        self.elapsed += dt
        if self.elapsed < DISPATCH_INTERVAL_S or not taxi_mgr.offers:
            return
        interval, self.elapsed = self.elapsed, 0.0
        idle = [v for v in npc_manager.vehicles
                if is_competitor(v) and v.taxi_job is None and v.state == NPCState.PARKED
                and npc_manager.drivers.get(v.vehicle_id) is not None
                and not getattr(npc_manager.drivers[v.vehicle_id], "route_job_pending", False)]
        chance = 1.0 - math.exp(-CLAIM_RATE_PER_S * interval)
        for offer in list(taxi_mgr.offers):
            if not idle:
                return
            pickup = offer.passenger.pickup
            nearest = min(idle, key=lambda v: math.hypot(v.x - pickup.x, v.y - pickup.y))
            if math.hypot(nearest.x - pickup.x, nearest.y - pickup.y) > CLAIM_RADIUS_M or self.rng.random() >= chance:
                continue
            dropoff = offer.passenger.dropoff
            nearest.taxi_job = TaxiJob(offer.passenger.name, (pickup.x, pickup.y), (dropoff.x, dropoff.y))
            idle.remove(nearest)
            taxi_mgr.offers.remove(offer)
            taxi_mgr.notification_msg = tr(taxi_mgr.language, "competitor_took_fare", name=offer.passenger.name)
            taxi_mgr.notification_timer = 4.0
            self.taken += 1
