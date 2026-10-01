"""Driving through a parking entrance between map levels (garage-08.md).

A connector (osm.LevelConnector, an amenity=parking_entrance node) changes
the player's Car.map_level only when all of these hold:

- every road through it (road_osm_ids) is loaded, and together they state
  at least two levels (map_level.explicit_levels - typically an inside
  ramp tagged level=0;-1). Garage levels, layer, tunnel and covered are
  never evidence; a connector's own level only has to agree;
- the car's current level is one of them and exactly one other remains,
  so the destination is never guessed;
- the car's movement this frame actually passes the entrance node (within
  TRANSITION_RADIUS_M) while it drives on one of those roads.

Then the connector is disarmed until the car is REARM_DISTANCE_M away, so
standing on or wobbling over the node can't toggle levels. Driving back
through it later reverses the change. Topology is resolved when map data
changes (startup, map sync), never per frame; per frame it is a short scan
of a few dozen resolved connectors.
"""

import math
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

from .map_level import explicit_levels

TRANSITION_RADIUS_M = 4.0  # how close the movement must pass the entrance node
REARM_DISTANCE_M = 10.0  # leave the entrance this far before it can fire again


@dataclass(frozen=True)
class ConnectorTopology:
    connector: object  # osm.LevelConnector
    levels: frozenset
    road_ids: frozenset

    def destination(self, level: int) -> Optional[int]:
        """The other level from `level`, or None when `level` isn't one of
        this connector's levels or more than one other level remains."""
        others = self.levels - {level}
        if level not in self.levels or len(others) != 1:
            return None
        return next(iter(others))


def resolve_connectors(connectors: Iterable, ways: Iterable, level_ways: Iterable) -> Tuple[List[ConnectorTopology], dict]:
    """Connectors whose loaded road topology states two or more levels,
    plus counts of why the others don't qualify."""
    roads = {way.osm_id: way for way in (*ways, *level_ways) if way.osm_id is not None}
    resolved = []
    stats = {"connectors": 0, "no_roads": 0, "missing_roads": 0, "no_level_evidence": 0,
             "single_level": 0, "conflicting_own_level": 0, "resolved": 0}
    for connector in connectors:
        stats["connectors"] += 1
        if not connector.road_osm_ids:
            stats["no_roads"] += 1
            continue
        if any(road_id not in roads for road_id in connector.road_osm_ids):
            stats["missing_roads"] += 1  # e.g. a tile not loaded yet: no transition until it is
            continue
        levels = frozenset().union(*(explicit_levels(roads[road_id]) for road_id in connector.road_osm_ids))
        if not levels:
            stats["no_level_evidence"] += 1
        elif len(levels) < 2:
            stats["single_level"] += 1
        elif connector.map_level is not None and connector.map_level not in levels:
            stats["conflicting_own_level"] += 1
        else:
            stats["resolved"] += 1
            resolved.append(ConnectorTopology(connector, levels, frozenset(connector.road_osm_ids)))
    return resolved, stats


class LevelTransitions:
    """Per-world connector state: the resolved topology (replaced on map
    sync) and which connectors are disarmed after firing."""

    def __init__(self, topologies: List[ConnectorTopology] = ()) -> None:
        self.topologies = list(topologies)
        self._disarmed: set = set()
        self.last_transition: Optional[Tuple[int, int, int]] = None  # (connector osm id, from, to)

    def update(self, car, previous_position, current_way) -> Optional[Tuple[int, int, int]]:
        """Change car.map_level if this frame's movement drove through a
        resolved connector on one of its roads. Returns (connector osm id,
        from level, to level) when it did."""
        px, py = previous_position
        dx, dy = car.x - px, car.y - py
        travel_sq = dx * dx + dy * dy
        way_id = getattr(current_way, "osm_id", None)
        fired = None
        for topology in self.topologies:
            connector = topology.connector
            if connector.osm_id in self._disarmed:
                if math.hypot(car.x - connector.x, car.y - connector.y) > REARM_DISTANCE_M:
                    self._disarmed.discard(connector.osm_id)
                continue
            if fired or travel_sq == 0.0 or way_id not in topology.road_ids:
                continue
            rx, ry = connector.x - px, connector.y - py
            along = (rx * dx + ry * dy) / travel_sq
            if not 0.0 < along <= 1.0:  # the node isn't between last and this frame's position
                continue
            if abs(rx * dy - ry * dx) / math.sqrt(travel_sq) > TRANSITION_RADIUS_M:
                continue
            destination = topology.destination(car.map_level)
            if destination is None:
                continue
            fired = (connector.osm_id, car.map_level, destination)
            car.map_level = destination
            self._disarmed.add(connector.osm_id)
        if fired:
            self.last_transition = fired
        return fired
