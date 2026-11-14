"""A few shoppers, some pushing carts, around big grocery stores with a car park."""
from __future__ import annotations

import math
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .geo import closest_point_and_dist_to_segment, point_in_polygon
from .pedestrian import PEDESTRIAN_SPAWN_RADIUS_M

STORE_SHOPS = frozenset({"supermarket", "hypermarket"})
PARKING_RANGE_M = 60.0
MAX_PER_STORE = 3
MAX_SHOPPERS = 60
OPEN_HOUR, CLOSE_HOUR = 7, 22  # ponytail: fixed hours, parse opening_hours if stores ever differ visibly
LEAVE_RADIUS_M = 150.0


def cart_for(ped_id) -> bool:
    """Stable across runs and processes (no random, no hash())."""
    return zlib.crc32(str(ped_id).encode()) % 2 == 0


def _distance_to_polygon(point, points) -> float:
    if point_in_polygon(*point, points):
        return 0.0
    return min(closest_point_and_dist_to_segment(*point, *a, *b)[3]
               for a, b in zip(points, points[1:] + points[:1]))


@dataclass
class Store:
    point: tuple[float, float]
    entrance: tuple[float, float]
    parking: tuple[float, float]
    shoppers: list = field(default_factory=list)
    next_spawn: int = 0


class ShopperCrowds:
    def __init__(self, pedestrians, sceneries) -> None:
        self.pedestrians = pedestrians
        self.sceneries = sceneries
        self.spawn_radius_m = PEDESTRIAN_SPAWN_RADIUS_M
        self.stores: list[Store] = []
        self._scanned = None
        self._next_update: datetime | None = None

    def _scan(self) -> None:
        buildings = self.pedestrians.buildings
        key = (id(buildings), len(buildings), id(self.sceneries), len(self.sceneries))
        if key == self._scanned:
            return
        self._scanned = key
        lots = [s.points_m for s in self.sceneries if s.kind == "parking" and len(s.points_m) >= 3]
        self.stores = []
        for building in buildings:
            shops = {getattr(building, "shop_type", None)} | {
                getattr(place, "shop_type", None) for place in getattr(building, "associated_places", ())}
            if not shops & STORE_SHOPS:
                continue
            bbox = building.bbox
            point = ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
            near = [lot for lot in lots
                    if min(_distance_to_polygon(p, lot) for p in (point, *building.points_m)) <= PARKING_RANGE_M]
            if not near:
                continue
            lot = min(near, key=lambda lot: _distance_to_polygon(point, lot))
            parking = (sum(x for x, _ in lot) / len(lot), sum(y for _, y in lot) / len(lot))
            entrances = list(getattr(building, "entrances", ()) or ())
            entrance = min(entrances, key=lambda e: math.dist(e, parking)) if entrances else point
            self.stores.append(Store(point, entrance, parking))

    def update(self, now: datetime, taxi_position: tuple[float, float]) -> None:
        if self._next_update is not None and now < self._next_update:
            return
        self._next_update = now + timedelta(seconds=5)
        self._scan()
        live = set(map(id, self.pedestrians.pedestrians))
        for store in self.stores:
            gone = [p for p in store.shoppers if math.dist((p.x, p.y), store.point) > LEAVE_RADIUS_M]
            for pedestrian in gone:  # held, so the population check leaves them to us
                if id(pedestrian) in live:
                    self.pedestrians.pedestrians.remove(pedestrian)
            store.shoppers = [p for p in store.shoppers if id(p) in live and p not in gone]
        if not OPEN_HOUR <= now.hour < CLOSE_HOUR:
            return
        total = sum(len(store.shoppers) for store in self.stores)
        for store in self.stores:
            if math.dist(store.point, taxi_position) > self.spawn_radius_m:
                continue
            while len(store.shoppers) < MAX_PER_STORE and total < MAX_SHOPPERS:
                # ponytail: they leave from the door or the lot and walk the normal footways;
                # a scripted lot<->door walk needs its own pedestrian state.
                start = store.entrance if store.next_spawn % 2 == 0 else store.parking
                store.next_spawn += 1
                spawn = self.pedestrians.spawn_pedestrian_at_door if start is store.entrance \
                    else self.pedestrians.spawn_pedestrian_at
                pedestrian = spawn(*start)
                if pedestrian is None or not self.pedestrians.add_pedestrian(pedestrian):
                    break
                pedestrian.cart = cart_for(pedestrian.resident_id)
                pedestrian.held_by = self
                store.shoppers.append(pedestrian)
                total += 1
