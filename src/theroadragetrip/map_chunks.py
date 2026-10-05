"""Player-centred map streaming for clients without their own map data
(the Godot client): the loaded OSM world cut into a square grid of chunks.

A chunk is identified by its grid cell, "ix_iy" with ix = floor(x / size).
It holds every road, railway, water and building with at least one vertex
in the cell, so a long road is in each chunk it passes through, and
clients draw it once per loaded chunk. Gameplay points (taxi stands, fuel
stations, traffic-light posts, roadworks) are in exactly one chunk, the
one containing them, so no client draws one twice. Python decides which
chunks a client needs (`plan`); the client only adds and removes what it's told.
Built from the same world objects the simulation uses - no second map model.
"""

from __future__ import annotations

import math

from . import static_world
from .fuel import fuel_station_price_cents
from .protocol import PROTOCOL_VERSION, _line, encode, traffic_light_render_point

_KINDS = ("roads", "railways", "waters", "buildings", "taxi_stands", "fuel_stations", "traffic_lights", "roadworks",
          "trees", "construction_fences", "bollards", "railings", "scenery_objects", "street_lights",
          # godot-16 (static_world.py)
          "building_styles", "canopies", "rail_bridges", "rail_decks", "guardrails", "landuse", "traffic_islands",
          "parking", "curbs", "crossings", "speed_bumps", "signs", "speed_cameras", "bus_stops", "labels", "level_roads")
# Decorative scenery_objects kinds (render/scenery.py draw_scenery_objects); bollards, fuel pumps
# and street lamps have their own lists.
DECORATIVE_KINDS = ("bench", "waste_basket", "bicycle_parking", "statue", "picnic_table", "firepit", "fountain", "gate")

CHUNK_SIZE_M = 500.0
LOAD_RADIUS = 3    # chunks around the player's chunk that must be loaded (7 x 7, >= 1.5 km each way)
UNLOAD_RADIUS = 4  # loaded chunks are dropped beyond this - the gap stops edge flapping


def chunk_id(ix: int, iy: int) -> str:
    return f"{ix}_{iy}"


def cell_of(x: float, y: float, size: float = CHUNK_SIZE_M) -> tuple[int, int]:
    return math.floor(x / size), math.floor(y / size)


def plan(loaded: set, center: tuple[int, int], load_radius: int = LOAD_RADIUS,
         unload_radius: int = UNLOAD_RADIUS) -> tuple[list[str], list[str]]:
    """(chunk ids to send, chunk ids to drop) for a client with `loaded`
    chunks around the player's cell `center`. Nearest chunks first."""
    cx, cy = center
    wanted = sorted(
        ((ix, iy) for ix in range(cx - load_radius, cx + load_radius + 1)
         for iy in range(cy - load_radius, cy + load_radius + 1)),
        key=lambda cell: max(abs(cell[0] - cx), abs(cell[1] - cy)),
    )
    to_load = [chunk_id(*cell) for cell in wanted if chunk_id(*cell) not in loaded]
    to_drop = []
    for cid in sorted(loaded):
        ix, iy = (int(part) for part in cid.split("_"))
        if max(abs(ix - cx), abs(iy - cy)) > unload_radius:
            to_drop.append(cid)
    return to_load, to_drop


class ChunkIndex:
    """The world's static geometry bucketed by chunk, built once (the map
    doesn't change during a session)."""

    def __init__(self, world, size: float = CHUNK_SIZE_M):
        self.size = size
        self._chunks: dict[str, dict] = {}
        self._encoded: dict[str, bytes] = {}
        for way in world.ways:
            if len(way.points_m) >= 2:
                self._add("roads", way.points_m, {
                    "points": _line(way.points_m), "half_width_m": way.half_width_m, "kind": way.highway or "",
                    "drivable": bool(way.is_drivable), "layer": way.layer,
                    **static_world.road_style(way),  # colour, centre line, one-way, bridge (godot-16)
                })
        for rail in world.railways:
            if len(rail.points_m) >= 2:  # a bridge track is drawn above the vehicles (render/roads.py)
                self._add("rail_bridges" if rail.is_bridge else "railways", rail.points_m, _line(rail.points_m))
        for water in world.waters:
            if len(getattr(water, "points_m", ())) >= 3:
                self._add("waters", water.points_m, _line(water.points_m))
        for building in world.buildings:
            if len(building.points_m) < 3:
                continue
            if static_world.is_open_roof(building):  # a canopy: drawn see-through, above the vehicles
                self._add("canopies", building.points_m, _line(building.points_m))
                continue
            for cell in {cell_of(x, y, self.size) for x, y in building.points_m}:  # buildings and their styles in step
                chunk = self._chunk(cell)
                chunk["buildings"].append(_line(building.points_m))
                chunk["building_styles"].append(static_world.building_style(building))
        for stop in getattr(world, "taxi_stops", ()):  # render/roads.py draw_taxi_stops
            self._add("taxi_stands", ((stop.x, stop.y),), [round(stop.x, 1), round(stop.y, 1)])
        for station in getattr(world, "scenery_objects", ()):  # draw_scenery_objects' pumps, draw_fuel_station_signs
            if station.kind == "fuel":
                self._add("fuel_stations", ((station.x, station.y),), {
                    "x": round(station.x, 1), "y": round(station.y, 1), "angle": round(station.direction_angle or 0.0, 3),
                    "is_area": bool(station.is_area), "name": station.name or "FUEL",
                    "price_cents": fuel_station_price_cents(station),  # the simulation's own price
                })
        # Posts only: the phase is per tick in `state` ("traffic_lights", by this id).
        for index, light in enumerate(getattr(getattr(world, "traffic_mgr", None), "traffic_lights", ())):
            if getattr(light, "renderable", True):
                x, y = traffic_light_render_point(light)
                self._add("traffic_lights", ((light.x, light.y),), {
                    "id": index, "x": round(x, 2), "y": round(y, 2), "angle": round(light.direction_angle or 0.0, 4),
                })
        # Obstacles the simulation collides with (taxi.py check_tree_collision,
        # check_fence_collision, check_post_collision); the collisions stay on
        # the server, these are for drawing them. Each in one chunk.
        for scenery in getattr(world, "sceneries", ()):
            kinds = getattr(scenery, "tree_kinds", ())
            variations = getattr(scenery, "tree_variations", ())
            for index, (x, y) in enumerate(getattr(scenery, "trees", ())):
                self._add("trees", ((x, y),), [round(x, 1), round(y, 1), kinds[index] if index < len(kinds) else "birch",
                                               round(variations[index], 2) if index < len(variations) else 0.5])
            if str(getattr(scenery, "kind", "")).lower() == "construction" and len(scenery.points_m) >= 3:
                self._add("construction_fences", scenery.points_m[:1], _line(scenery.points_m))  # its first corner's chunk
        for post in getattr(world, "scenery_objects", ()):
            if post.kind == "bollard":  # street lamps are drawn with the street lights, not here (render/scenery.py)
                self._add("bollards", ((post.x, post.y),), [round(post.x, 1), round(post.y, 1)])
        # Drawing only (godot-15): nothing collides with these.
        for railing in getattr(world, "railings", ()):  # render/roads.py draw_railings; its first point's chunk
            if len(railing.points_m) >= 2:
                self._add("railings", railing.points_m[:1], [getattr(railing, "kind", "fence"), _line(railing.points_m)])
        for obj in getattr(world, "scenery_objects", ()):
            if obj.kind in DECORATIVE_KINDS:
                self._add("scenery_objects", ((obj.x, obj.y),),
                          [round(obj.x, 1), round(obj.y, 1), obj.kind, round(obj.direction_angle or 0.0, 3)])
        # Street lights as render/roads.py places them (explicit OSM lamps, then
        # lit roads at fixed spacing): [x, y, the road's direction, pool radius].
        for x, y, direction, pool_radius in getattr(world, "street_light_points", ()):
            self._add("street_lights", ((x, y),), [round(x, 1), round(y, 1), round(direction, 3), pool_radius])
        self._add_static_world(world)
        for work in getattr(world, "roadworks", ()):  # render/roads.py draw_roadworks; in the chunk of its midpoint
            middle = ((work.start[0] + work.end[0]) / 2.0, (work.start[1] + work.end[1]) / 2.0)
            self._add("roadworks", (middle,), {
                "start": [round(work.start[0], 2), round(work.start[1], 2)], "end": [round(work.end[0], 2), round(work.end[1], 2)],
                "lane_closed": bool(work.lane_closed), "half_width_m": getattr(work.way, "half_width_m", 4.0),
            })

    def _chunk(self, cell) -> dict:
        return self._chunks.setdefault(chunk_id(*cell), {kind: [] for kind in _KINDS})

    def _add(self, kind: str, points, feature) -> None:
        for cell in {cell_of(x, y, self.size) for x, y in points}:
            self._chunk(cell)[kind].append(feature)

    def _add_static_world(self, world) -> None:
        """godot-16: the rest of what Pygame draws from the map (static_world.py)."""
        from .render.scenery import SCENERY_COLORS, _SPECKLE_SCENERY_KINDS

        for scenery in getattr(world, "sceneries", ()):
            if len(scenery.points_m) < 3:
                continue
            kind = str(scenery.kind).lower()
            island = kind == "traffic_island" or getattr(scenery, "kerbed", False)  # redrawn above the roads
            color = SCENERY_COLORS.get(kind, (38, 105, 38))
            seasonal = 1 if kind in _SPECKLE_SCENERY_KINDS or kind in ("residential", "recreation_ground") else 0
            for cell, ring in static_world.clipped_pieces(scenery.points_m, self.size):
                self._chunk(cell)["landuse"].append([static_world._rgb(color), seasonal, ring])
                if island:
                    self._chunk(cell)["traffic_islands"].append([static_world._rgb(color), seasonal, ring])
        for deck in static_world.rail_bridge_decks(world.railways):
            for cell, ring in static_world.clipped_pieces(deck, self.size):
                self._chunk(cell)["rail_decks"].append(ring)
        for a, b in static_world.bridge_guardrails(world.ways):
            self._add("guardrails", (((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0),), [round(a[0], 2), round(a[1], 2), round(b[0], 2), round(b[1], 2)])
        for space in getattr(world, "parking_spaces", ()):
            if len(space.points_m) >= 3:
                self._add("parking", space.points_m[:1], _line(space.points_m))
        for curb in getattr(world, "curbs", ()):
            if len(curb.points_m) >= 2:
                self._add("curbs", curb.points_m[:1], _line(curb.points_m))
        for c in getattr(world, "crossings", ()):
            self._add("crossings", ((c.x, c.y),), [round(c.x, 2), round(c.y, 2), round(c.direction_angle or 0.0, 3),
                                                   round(getattr(c, "width_m", 5.0), 2), round(getattr(c, "length_m", 2.2), 2)])
        for b in getattr(world, "speed_bumps", ()):
            self._add("speed_bumps", ((b.x, b.y),), [round(b.x, 2), round(b.y, 2), round(b.direction_angle or 0.0, 3),
                                                     round(getattr(b, "width_m", 3.5), 2), getattr(b, "kind", "bump")])
        for kind, signs in (("stop", getattr(world, "stop_signs", ())), ("yield", getattr(world, "yield_signs", ()))):
            for sign in signs:
                self._add("signs", ((sign.x, sign.y),), [round(sign.x, 2), round(sign.y, 2), kind, round(sign.direction_angle or 0.0, 3)])
        for index, camera in enumerate(getattr(world, "speed_cameras", ())):  # id: the index taxi.py flashes by
            self._add("speed_cameras", ((camera.x, camera.y),), [index, round(camera.x, 2), round(camera.y, 2), round(camera.heading, 3)])
        for stop in getattr(world, "bus_stops", ()):
            shapes = static_world.bus_stop_shapes(stop, world.ways)
            if shapes is not None:
                self._add("bus_stops", ((stop.x, stop.y),), shapes)
        for label in static_world.labels(world):
            self._add("labels", ((label[0], label[1]),), label)
        from .map_level import explicit_levels
        from .render.common import road_color_for_way
        for way in getattr(world, "level_ways", ()):
            if len(way.points_m) >= 2:
                levels = sorted({way.map_level, *explicit_levels(way)})
                self._add("level_roads", way.points_m[:1], [levels, _line(way.points_m), way.half_width_m,
                                                             static_world._rgb(road_color_for_way(way))])

    def message(self, cid: str) -> dict:
        """The "chunk" message for one chunk (an empty one outside the map,
        so the client knows it has it)."""
        ix, iy = (int(part) for part in cid.split("_"))
        content = self._chunks.get(cid, {kind: [] for kind in _KINDS})
        return {
            "type": "chunk", "version": PROTOCOL_VERSION, "chunk_id": cid,
            "bounds": [ix * self.size, iy * self.size, (ix + 1) * self.size, (iy + 1) * self.size],
            **content,
        }

    def encoded(self, cid: str) -> bytes:
        """The chunk message as wire bytes, encoded once: the map doesn't
        change, and re-encoding ~2 MB of JSON for every client would hold
        the GIL against the tick."""
        data = self._encoded.get(cid)
        if data is None:
            data = self._encoded[cid] = encode(self.message(cid))
        return data

    def encode_all(self) -> None:
        for cid in self._chunks:
            self.encoded(cid)
