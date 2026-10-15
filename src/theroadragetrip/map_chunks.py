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
from .geo import dist_point_to_segment
from .map_level import SURFACE_MAP_LEVELS
from .protocol import PROTOCOL_VERSION, _line, encode, traffic_light_render_point

_KINDS = ("roads", "railways", "waters", "water_lines", "buildings", "taxi_stands", "fuel_stations", "traffic_lights", "roadworks",
          "trees", "construction_fences", "bollards", "railings", "scenery_objects", "street_lights",
          # godot-16 (static_world.py)
          "building_styles", "canopies", "rail_bridges", "rail_decks", "guardrails", "landuse", "traffic_islands",
          "parking", "curbs", "crossings", "speed_bumps", "signs", "speed_cameras", "bus_stops", "labels", "level_roads",
          "canopy_heights", "floodlit", "rinks", "floodlight_poles", "soccer_pitches")
# Decorative scenery_objects kinds; bollards, fuel pumps
# and street lamps have their own lists.
DECORATIVE_KINDS = ("bench", "waste_basket", "bicycle_parking", "statue", "picnic_table", "firepit", "fountain", "gate")

CHUNK_SIZE_M = 500.0
LOAD_RADIUS = 3    # chunks around the player's chunk that must be loaded (7 x 7, >= 1.5 km each way)
UNLOAD_RADIUS = 4  # loaded chunks are dropped beyond this - the gap stops edge flapping


def chunk_id(ix: int, iy: int) -> str:
    return f"{ix}_{iy}"


def cell_of(x: float, y: float, size: float = CHUNK_SIZE_M) -> tuple[int, int]:
    return math.floor(x / size), math.floor(y / size)


def cells_touched_by_line(points, size: float = CHUNK_SIZE_M) -> set[tuple[int, int]]:
    """Grid cells crossed by a polyline, including segments with no vertex in a cell."""
    cells = {cell_of(x, y, size) for x, y in points}
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        crossings = {0.0, 1.0}
        for a, b in ((ax, bx), (ay, by)):
            if a == b:
                continue
            for grid in range(math.floor(min(a, b) / size) + 1, math.ceil(max(a, b) / size)):
                crossings.add((grid * size - a) / (b - a))
        ordered = sorted(crossings)
        for start, end in zip(ordered, ordered[1:]):
            t = (start + end) * 0.5
            cells.add(cell_of(ax + (bx - ax) * t, ay + (by - ay) * t, size))
    return cells


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


def _underground_test(ways, surface_levels, on_m: float = 0.5):
    """A test for road-surface points (crossings, speed bumps, which the OSM
    build snaps onto their road, ignoring its map level): True when the
    point lies on a garage way (map_level off the surface) and on no
    surface road - so a garage ramp's street mouth stays. Garage ways are
    few, so this is a scan of them first; surface roads only for a hit."""
    def boxed(points):  # (points, bbox): a far way is skipped by its box, not walked segment by segment
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        return points, (min(xs) - on_m, min(ys) - on_m, max(xs) + on_m, max(ys) + on_m)

    levelled = [boxed(w.points_m) for w in ways if getattr(w, "map_level", None) not in surface_levels and len(w.points_m) >= 2]
    surface = None

    def near(item, x, y) -> bool:
        points, (minx, miny, maxx, maxy) = item
        return (minx <= x <= maxx and miny <= y <= maxy
                and any(dist_point_to_segment(x, y, a[0], a[1], b[0], b[1]) <= on_m for a, b in zip(points, points[1:])))

    def test(x: float, y: float) -> bool:
        nonlocal surface
        if not any(near(item, x, y) for item in levelled):
            return False
        if surface is None:
            surface = [boxed(w.points_m) for w in ways if getattr(w, "map_level", None) in surface_levels and len(w.points_m) >= 2]
        return not any(near(item, x, y) for item in surface)

    return test


# Region rebuilds (ChunkIndex.updated) also read objects this far outside
# the rebuilt cells: bridge guardrails and rail decks are unions of
# neighbouring bridges, a house's generated bays sit up to ~35 m from it.
REGION_MARGIN_M = 100.0
# The world lists a region rebuild filters by bbox. Everything else - the
# traffic lights and speed cameras, whose chunk ids are their index in the
# full list - is read from the world as is.
_REGION_LISTS = ("ways", "railways", "waters", "buildings", "sceneries", "scenery_objects", "taxi_stops", "railings",
                 "street_light_points", "parking_spaces", "curbs", "crossings", "speed_bumps", "stop_signs",
                 "yield_signs", "bus_stops", "level_ways", "places")


def rink_frame(points) -> list | None:
    """[centre x, centre y, angle of the long side (rad), length, width] of
    a rink's smallest enclosing rectangle - where its hockey markings go."""
    from shapely.geometry import Polygon

    rectangle = Polygon(points).minimum_rotated_rectangle
    if rectangle.geom_type != "Polygon":
        return None
    (x0, y0), (x1, y1), (x2, y2) = list(rectangle.exterior.coords)[:3]
    side_a, side_b = math.hypot(x1 - x0, y1 - y0), math.hypot(x2 - x1, y2 - y1)
    if min(side_a, side_b) < 5.0:
        return None
    angle = math.atan2(y1 - y0, x1 - x0) if side_a >= side_b else math.atan2(y2 - y1, x2 - x1)
    centre = rectangle.centroid
    return [round(centre.x, 2), round(centre.y, 2), round(angle, 4), round(max(side_a, side_b), 2), round(min(side_a, side_b), 2)]


FLOODLIGHT_POLE_OUT_M = 2.0  # outside the field's rectangle
FLOODLIGHT_MIN_AREA_M2 = 2000.0  # smaller fields (tennis courts...) have no poles of their own; rinks always do
FLOODLIGHT_POLE_MERGE_M = 10.0  # poles of neighbouring fields closer than this are one


def floodlight_poles(points, kind: str = "pitch") -> list:
    """A floodlit field's light poles as street lights ([x, y, direction,
    pool reach], map_chunk.gd pool_fans): its rectangle's corners and the
    middle of each long side, FLOODLIGHT_POLE_OUT_M outside it, each aimed
    at the field's centre with a pool reaching across it."""
    frame = rink_frame(points)
    if frame is None:
        return []
    cx, cy, angle, length, width = frame
    if kind != "ice_rink" and length * width < FLOODLIGHT_MIN_AREA_M2:
        return []
    ux, uy = math.cos(angle), math.sin(angle)
    half_u, half_v = length / 2.0 + FLOODLIGHT_POLE_OUT_M, width / 2.0 + FLOODLIGHT_POLE_OUT_M
    reach = max(15.0, min(40.0, width * 0.9))
    poles = []
    for u, v in ((-1, -1), (0, -1), (1, -1), (-1, 1), (0, 1), (1, 1)):
        x, y = cx + ux * u * half_u - uy * v * half_v, cy + uy * u * half_u + ux * v * half_v
        poles.append((x, y, math.atan2(cy - y, cx - x), reach))
    return poles


def _item_rect(item) -> tuple[float, float, float, float] | None:
    if isinstance(item, tuple):  # a street light point (x, y, ...)
        return item[0], item[1], item[0], item[1]
    bbox = getattr(item, "bbox", None)
    if bbox and bbox != (0.0, 0.0, 0.0, 0.0):
        return bbox
    points = getattr(item, "points_m", None)
    if points:
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        return min(xs), min(ys), max(xs), max(ys)
    if hasattr(item, "x") and hasattr(item, "y"):
        return item.x, item.y, item.x, item.y
    return None  # unknown extent: always kept


class _RegionWorld:
    """`world` with its _REGION_LISTS cut to the objects reaching `rect`."""

    def __init__(self, world, rect) -> None:
        self._world, self._rect, self._lists = world, rect, {}

    def __getattr__(self, name):
        if name not in _REGION_LISTS:
            return getattr(self._world, name)
        if name not in self._lists:
            minx, miny, maxx, maxy = self._rect
            kept = []
            for item in getattr(self._world, name, ()):
                r = _item_rect(item)
                if r is None or (r[0] <= maxx and r[2] >= minx and r[1] <= maxy and r[3] >= miny):
                    kept.append(item)
            self._lists[name] = kept
        return self._lists[name]


class ChunkIndex:
    """The world's static geometry bucketed by chunk, built once and then
    updated region by region as the map grows (updated())."""

    def __init__(self, world, size: float = CHUNK_SIZE_M, cells: set | None = None):
        """`cells`: build only these chunks (a region rebuild; `world` is then
        usually a _RegionWorld) - None: all of them."""
        self.size = size
        self._cells = cells
        self._outside = {kind: [] for kind in _KINDS}  # a region rebuild's features outside its cells, thrown away with it
        self._chunks: dict[str, dict] = {}
        self._encoded: dict[str, bytes] = {}
        for way in world.ways:
            # Surface roads only: a garage aisle
            # (map_level -1) stays in world.ways but is sent as a level road below.
            if len(way.points_m) >= 2 and getattr(way, "map_level", None) in SURFACE_MAP_LEVELS:
                self._add("roads", way.points_m, {
                    "points": _line(way.points_m), "half_width_m": way.half_width_m,
                    "drivable": bool(way.is_drivable), "layer": way.layer,
                    **static_world.road_style(way),  # colour, centre line, one-way, bridge (godot-16)
                })
        bridge_parts = static_world.rail_bridge_parts(world.railways, world.ways)
        for rail in world.railways:
            if len(rail.points_m) >= 2:  # a bridge track is drawn above the vehicles
                self._add("rail_bridges" if rail.is_bridge else "railways", rail.points_m, _line(rail.points_m))
        explicit_bridge_count = sum(rail.is_bridge and len(rail.points_m) >= 2 for rail in world.railways)
        for part in bridge_parts[explicit_bridge_count:]:
            # Explicit bridge tracks were added whole above; these are the
            # inferred short spans over a mapped below-grade road.
            self._add("rail_bridges", part.coords, _line(part.coords))
        for water in world.waters:
            # Only a closed water area is filled; a river or
            # stream line (Oulujoki's centre line) is drawn as a line, 3 m wide
            # - filled, it flooded the city.
            points = getattr(water, "points_m", ())
            if getattr(water, "is_polygon", False) and len(points) >= 4 and points[0] == points[-1]:
                self._add("waters", points, _line(points))
            elif len(points) >= 2:
                self._add("water_lines", points, _line(points))
        static_world.inherit_part_colours(world.buildings)
        for building in world.buildings:
            if len(building.points_m) < 3:
                continue
            # One owner each, the chunk of its centre (godot-17: drawn as a volume, a duplicate would cover others).
            chunk = self._chunk(cell_of(*static_world.building_owner(building), self.size))
            if static_world.is_open_roof(building):  # a canopy: drawn see-through, raised by its height, above the vehicles
                chunk["canopies"].append(_line(building.points_m))
                chunk["canopy_heights"].append(static_world.building_style(building)[2])
                continue
            chunk["buildings"].append(_line(building.points_m))  # buildings and their styles in step
            chunk["building_styles"].append(static_world.building_style(building))
        for stop in getattr(world, "taxi_stops", ()):
            self._add("taxi_stands", ((stop.x, stop.y),), [round(stop.x, 1), round(stop.y, 1)])
        for station in getattr(world, "scenery_objects", ()):  # fuel pumps and their price signs
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
            if post.kind == "bollard":  # street lamps are drawn with the street lights, not here
                self._add("bollards", ((post.x, post.y),), [round(post.x, 1), round(post.y, 1)])
        # Drawing only (godot-15): nothing collides with these.
        for railing in getattr(world, "railings", ()):  # its first point's chunk
            if len(railing.points_m) >= 2:
                self._add("railings", railing.points_m[:1], [getattr(railing, "kind", "fence"), _line(railing.points_m)])
        for obj in getattr(world, "scenery_objects", ()):
            if obj.kind in DECORATIVE_KINDS:
                self._add("scenery_objects", ((obj.x, obj.y),),
                          [round(obj.x, 1), round(obj.y, 1), obj.kind, round(obj.direction_angle or 0.0, 3)])
        # Street lights as street_lights.py places them (explicit OSM lamps, then
        # lit roads at fixed spacing): [x, y, the road's direction, pool radius].
        for lamp in getattr(world, "street_light_points", ()):
            x, y, direction, pool_radius = lamp[:4]
            # A fifth 1: a parking pole lighting all round (street lamps lean toward their road).
            self._add("street_lights", ((x, y),), [round(x, 1), round(y, 1), round(direction, 3), pool_radius]
                      + ([1] if len(lamp) > 4 and lamp[4] else []))
        self._add_static_world(world, bridge_parts)
        for work in getattr(world, "roadworks", ()):  # in the chunk of its midpoint
            middle = ((work.start[0] + work.end[0]) / 2.0, (work.start[1] + work.end[1]) / 2.0)
            self._add("roadworks", (middle,), {
                "start": [round(work.start[0], 2), round(work.start[1], 2)], "end": [round(work.end[0], 2), round(work.end[1], 2)],
                "lane_closed": bool(work.lane_closed), "half_width_m": getattr(work.way, "half_width_m", 4.0),
            })

    def _chunk(self, cell) -> dict:
        cid = chunk_id(*cell)
        chunk = self._chunks.get(cid)
        if chunk is None:
            if self._cells is not None and cell not in self._cells:
                return self._outside
            chunk = self._chunks[cid] = {kind: [] for kind in _KINDS}
        return chunk

    @classmethod
    def updated(cls, old: "ChunkIndex", world, region) -> tuple["ChunkIndex", set]:
        """`old` with the chunks touching `region` (metres rect) rebuilt from
        `world` - the same content a full rebuild gives there, at a fraction
        of the cost - and the ids of the chunks whose content changed. The
        other chunks (and their encoded bytes) are carried over."""
        size = old.size
        minx, miny, maxx, maxy = region
        first, last = cell_of(minx, miny, size), cell_of(maxx, maxy, size)
        cells = {(ix, iy) for ix in range(first[0], last[0] + 1) for iy in range(first[1], last[1] + 1)}
        margin = REGION_MARGIN_M
        rebuilt = cls(_RegionWorld(world, (first[0] * size - margin, first[1] * size - margin,
                                           (last[0] + 1) * size + margin, (last[1] + 1) * size + margin)), size, cells)
        index = cls.__new__(cls)
        index.size, index._cells, index._outside = size, None, {}
        ids = {chunk_id(*cell) for cell in cells}
        index._chunks = {cid: chunk for cid, chunk in old._chunks.items() if cid not in ids}
        index._chunks.update(rebuilt._chunks)
        changed = {cid for cid in ids if old._chunks.get(cid) != index._chunks.get(cid)}
        # list(): the tick may be encoding into `old` meanwhile (a pass already swapped in).
        index._encoded = {cid: data for cid, data in list(old._encoded.items()) if cid not in changed}
        return index, changed

    def _add(self, kind: str, points, feature) -> None:
        for cell in cells_touched_by_line(points, self.size):
            self._chunk(cell)[kind].append(feature)

    def _add_static_world(self, world, bridge_parts) -> None:
        """godot-16: the rest of what the client draws from the map (static_world.py)."""
        from .activities.plugins.soccer import is_soccer_pitch
        from .map_style import FLOODLIT_KINDS, FROZEN_IN_WINTER_KINDS, SCENERY_COLORS, SEASONAL_GROUND_KINDS, SPECKLE_SCENERY_KINDS

        # Biggest first, so nested areas draw on top (a pitch inside its
        # sports centre, a park inside a residential area). A container's
        # bbox is never smaller than its contents'.
        def bbox_area(scenery) -> float:
            xs = [p[0] for p in scenery.points_m]
            ys = [p[1] for p in scenery.points_m]
            return (max(xs) - min(xs)) * (max(ys) - min(ys))

        pole_cells: set = set()
        for scenery in sorted((s for s in getattr(world, "sceneries", ()) if len(s.points_m) >= 3), key=bbox_area, reverse=True):
            kind = str(scenery.kind).lower()
            island = kind == "traffic_island" or getattr(scenery, "kerbed", False)  # redrawn above the roads
            color = SCENERY_COLORS.get(kind, (38, 105, 38))
            # 1: snow and seasonal palettes, 2: frozen to ice in winter, 0: as is
            seasonal = 2 if kind in FROZEN_IN_WINTER_KINDS else 1 if kind in SPECKLE_SCENERY_KINDS or kind in SEASONAL_GROUND_KINDS else 0
            for cell, ring in static_world.clipped_pieces(scenery.points_m, self.size):
                self._chunk(cell)["landuse"].append([static_world._rgb(color), seasonal, ring])
                if kind in FLOODLIT_KINDS:
                    self._chunk(cell)["floodlit"].append(ring)
            if kind in FLOODLIT_KINDS:
                for pole in floodlight_poles(scenery.points_m, kind):
                    cell = (round(pole[0] / FLOODLIGHT_POLE_MERGE_M), round(pole[1] / FLOODLIGHT_POLE_MERGE_M))
                    if cell not in pole_cells:  # neighbouring fields share their poles
                        pole_cells.add(cell)
                        self._add("floodlight_poles", [pole[:2]], [round(v, 3) for v in pole])
            if is_soccer_pitch(scenery):  # its FIFA lines, drawn while there is no snow
                frame = rink_frame(scenery.points_m)
                if frame is not None:
                    self._add("soccer_pitches", scenery.points_m[:1], frame)
            if kind in ("ice_rink", "stadium"):  # closed all round (taxi.SOLID_AREA_KINDS): boards, or a wall
                outline = _line(list(scenery.points_m) + [scenery.points_m[0]])
                self._add("railings", scenery.points_m[:1], ["boards" if kind == "ice_rink" else "wall", outline])
                frame = rink_frame(scenery.points_m)
                if frame is not None:  # its hockey markings, drawn in winter
                    self._add("rinks", scenery.points_m[:1], frame)
                if island:
                    self._chunk(cell)["traffic_islands"].append([static_world._rgb(color), seasonal, ring])
        for deck in static_world.rail_bridge_decks(world.railways, bridge_parts=bridge_parts):
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
        underground = _underground_test(world.ways, SURFACE_MAP_LEVELS)
        for c in getattr(world, "crossings", ()):
            if underground(c.x, c.y):
                continue  # on a garage aisle: not a surface marking (the bug that showed them over the street)
            self._add("crossings", ((c.x, c.y),), [round(c.x, 2), round(c.y, 2), round(c.direction_angle or 0.0, 3),
                                                   round(getattr(c, "width_m", 5.0), 2), round(getattr(c, "length_m", 2.2), 2)])
        for b in getattr(world, "speed_bumps", ()):
            if underground(b.x, b.y):
                continue
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
        from .map_style import road_color_for_way
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
