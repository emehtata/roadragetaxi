"""On-demand, metre-scale home plans. Geometry stays independent of the viewer."""
from __future__ import annotations

import hashlib
import math
import random
from functools import lru_cache

from shapely import normalize, set_precision
from shapely.affinity import rotate, scale, translate
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

GENERATOR_VERSION = 5  # 5: fit compact, slightly irregular mapped L footprints
DOOR_WIDTH = 0.95
WALK_CLEAR_M = 0.35  # a walker's reach from a wall's line: godot/home_walk.gd RADIUS_M + WALL_HALF_M, with a margin
STEP_IN_M = 0.45  # a door is usable if this far through it, on each side, is clear floor (home_walk.gd SPAWN_IN_M)


def footprint(points) -> Polygon | None:
    try:
        if not all(len(p) == 2 and all(math.isfinite(v) for v in p) for p in points):
            return None
        polygon = Polygon(points)
        if polygon.is_valid and polygon.area >= 2.0 and polygon.exterior.is_simple:
            return normalize(polygon)
    except (TypeError, ValueError):
        pass
    return None


def _polygons(geometry):
    if geometry.geom_type == "Polygon":
        return [geometry] if geometry.area > 1e-7 else []
    return [p for part in getattr(geometry, "geoms", ()) for p in _polygons(part)]


def _lines(geometry):
    if geometry.geom_type == "LineString":
        return [geometry] if geometry.length > 1e-7 else []
    return [line for part in getattr(geometry, "geoms", ()) for line in _lines(part)]


def _door(boundary, rooms, target=None, sides=()):
    """A door on a straight stretch of `boundary` (its two jambs fit), toward
    `target` or on the longest stretch; with `sides` (the room polygons it
    joins, the inside first), only where a walker can step STEP_IN_M through
    on every given side - a room's thin strip along the hall holds no door."""
    segments = [LineString([a, b]) for line in _lines(boundary)
                for a, b in zip(line.coords, list(line.coords)[1:])
                if math.dist(a, b) >= DOOR_WIDTH + 0.4]
    if target is not None:
        segments.sort(key=lambda s: s.distance(target))
    else:
        segments.sort(key=lambda s: -s.length)
    clear = [side.buffer(-WALK_CLEAR_M) for side in sides]
    low, high = DOOR_WIDTH / 2 + 0.2, None
    for line in segments:
        high = line.length - DOOR_WIDTH / 2 - 0.2
        best = min(high, max(low, line.project(target))) if target is not None else line.length / 2
        # The preferred spot first, then outward from it in 0.1 m steps.
        spots = sorted({round(min(high, max(low, best + k * 0.1)), 3) for k in range(-200, 201)}, key=lambda m: abs(m - best))
        for middle in spots:
            a, b = line.interpolate(middle - DOOR_WIDTH / 2), line.interpolate(middle + DOOR_WIDTH / 2)
            if _passable(a, b, clear):
                return {"points": [list(a.coords[0]), list(b.coords[0])], "rooms": rooms}
    return None


def _passable(a, b, clear) -> bool:
    """Whether a step STEP_IN_M through door a-b lands in clear floor on each side:
    the first area on one side, the second (if any) on the other."""
    if not clear:
        return True
    mx, my = (a.x + b.x) / 2, (a.y + b.y) / 2
    nx, ny = -(b.y - a.y) / DOOR_WIDTH, (b.x - a.x) / DOOR_WIDTH
    probes = [Point(mx + nx * STEP_IN_M, my + ny * STEP_IN_M), Point(mx - nx * STEP_IN_M, my - ny * STEP_IN_M)]
    for one, other in (probes, probes[::-1]):
        if clear[0].contains(one) and (len(clear) < 2 or clear[1].contains(other)):
            return True
    return False


def _l_shaped_rooms(polygon):
    """Partition a near-orthogonal L without changing its mapped outer walls."""
    for orientation in range(8):
        turn = (orientation % 4) * 90
        reflection = -1 if orientation >= 4 else 1
        oriented = scale(polygon, xfact=reflection, origin=(0, 0))
        aligned = set_precision(rotate(oriented, turn, origin=(0, 0)), 1e-7)
        x0, y0, x1, y1 = aligned.bounds
        # Ignore small mapping kinks when locating the notch, not when building rooms.
        notches = [(x, y) for x, y in aligned.simplify(0.2).exterior.coords
                   if x - x0 >= 3.5 and x1 - x >= 4.6 and y - y0 >= 5.2 and y1 - y >= 2.5]
        if not notches:
            continue
        nx, ny = min(notches, key=lambda p: aligned.symmetric_difference(
            box(x0, y0, p[0], y1).union(box(p[0], y0, x1, p[1]))).area)
        ideal = box(x0, y0, nx, y1).union(box(nx, y0, x1, ny))
        if (aligned.symmetric_difference(ideal).area > aligned.area * 0.02
                or aligned.hausdorff_distance(ideal) > 0.25):
            continue
        bedroom_x = x1 - 3.5
        service_y = y0 + 2.5
        hall_y = service_y + 1.5
        stair_x = nx + 2.4
        if (nx - x0 >= 4 and y1 - ny >= 3 and ny - hall_y >= 2
                and bedroom_x - stair_x >= 2 and bedroom_x - nx >= 4.8):
            middle = (nx + bedroom_x) / 2
            cells = [
                ("vestibule", box(stair_x, hall_y, bedroom_x, y1 + 1)),
                ("hall", box(nx, service_y, bedroom_x, hall_y)),
                ("living_kitchen", box(x0 - 1, y0 - 1, nx, y1 + 1)),
                ("bedroom", box(bedroom_x, y0 - 1, x1 + 1, y1 + 1)),
                ("bathroom", box(nx, y0 - 1, middle, service_y)),
                ("closet", box(middle, y0 - 1, bedroom_x, service_y)),
                ("stairs", box(nx, hall_y, stair_x, y1 + 1)),
            ]
        else:
            # Compact homes omit the separate closet and stair reservation.
            bedroom_x = x1 - 3.0
            service_y = y0 + 2.6
            hall_y = service_y + 1.5
            cells = [
                ("vestibule", box(nx, hall_y, bedroom_x, y1 + 1)),
                ("hall", box(nx, service_y, bedroom_x, hall_y)),
                ("living_kitchen", box(x0 - 1, y0 - 1, nx, y1 + 1)),
                ("bedroom", box(bedroom_x, y0 - 1, x1 + 1, y1 + 1)),
                ("bathroom", box(nx, y0 - 1, bedroom_x, service_y)),
            ]
        rooms = [(kind, unary_union(_polygons(aligned.intersection(cell)))) for kind, cell in cells]
        if any(room.geom_type != "Polygon" or room.interiors or room.buffer(-0.65).is_empty
               for _, room in rooms):
            continue
        if unary_union([room for _, room in rooms]).symmetric_difference(aligned).area > 1e-6:
            continue
        doors = []
        hall = rooms[1][1]
        for i, (_, room) in enumerate(rooms):
            if i == 1:
                continue
            door = _door(hall.boundary.intersection(room.boundary), [1, i], sides=(hall, room))
            if door is None:
                break
            doors.append(door)
        else:
            for door in doors:
                door["points"] = list(scale(rotate(LineString(door["points"]), -turn, origin=(0, 0)), xfact=reflection, origin=(0, 0)).coords)
            return [(kind, set_precision(scale(rotate(room, -turn, origin=(0, 0)), xfact=reflection, origin=(0, 0)), 1e-7)) for kind, room in rooms], doors
    return None


def _rooms(polygon, rng):
    reference = _l_shaped_rooms(polygon)
    if reference is not None:
        return reference
    x0, y0, x1, y1 = polygon.bounds
    # shortcut: a single straight hall; use a studio when a bent hall would be required.
    if polygon.area < 42 or y1 - y0 < 6 or x1 - x0 < 5:
        return [("studio", polygon)], []
    cy = (y0 + y1) / 2 + rng.uniform(-0.25, 0.25)
    hall = polygon.intersection(box(x0 - 1, cy - 0.75, x1 + 1, cy + 0.75))
    if hall.geom_type != "Polygon" or hall.interiors:
        return [("studio", polygon)], []
    rooms = [("hall", hall)]
    doors = []
    for low, high in [(y0 - 1, cy - 0.75), (cy + 0.75, y1 + 1)]:
        side = polygon.intersection(box(x0 - 1, low, x1 + 1, high))
        # Two wings, each with at most three rooms: work depends on one house only.
        count = min(3, max(2 if side.area >= 24 else 1, int(side.area / 18)))  # 2 at 24 m²: a small house still gets rooms
        cuts = [x0 - 1] + [x0 + (x1 - x0) * i / count for i in range(1, count)] + [x1 + 1]
        parts = [p for a, b in zip(cuts, cuts[1:]) for p in _polygons(side.intersection(box(a, low, b, high)))]
        if any(p.area < 6 or p.buffer(-0.65).is_empty for p in parts):
            parts = _polygons(side)
        for part in parts:
            door = _door(part.boundary.intersection(hall.boundary), [0, len(rooms)], sides=(part, hall))
            if part.area < 6 or part.interiors or part.buffer(-0.65).is_empty or door is None:
                return [("studio", polygon)], []
            doors.append(door)
            rooms.append(("", part))
    if len(rooms) < 4:
        return [("studio", polygon)], []
    # Give the largest wing room to living; bathroom is the smallest remaining room.
    available = list(range(1, len(rooms)))
    living = max(available, key=lambda i: rooms[i][1].area)
    rooms[living] = ("living_kitchen", rooms[living][1])
    available.remove(living)
    bathroom = min(available, key=lambda i: rooms[i][1].area)
    rooms[bathroom] = ("bathroom", rooms[bathroom][1])
    available.remove(bathroom)
    rng.shuffle(available)
    for i in available:
        rooms[i] = ("bedroom", rooms[i][1])
    if len(available) > 1:
        i = available[-1]
        rooms[i] = ("kitchen", rooms[i][1])
        rooms[living] = ("living", rooms[living][1])
    return rooms, doors


FURNITURE = {
    "hall": [("shelf", 1.0, 0.35)],
    "living": [("sofa", 2.1, 0.85), ("table", 1.2, 0.8), ("chair", 0.45, 0.45), ("shelf", 1.0, 0.35)],
    "kitchen": [("counter", 2.0, 0.6), ("table", 1.2, 0.8), ("chair", 0.45, 0.45)],
    "bedroom": [("bed", 2.0, 1.4), ("wardrobe", 1.2, 0.6)],
    "bathroom": [("shower", 0.9, 0.9), ("toilet", 0.65, 0.45), ("sink", 0.55, 0.4)],
}
FURNITURE["living_kitchen"] = FURNITURE["living"] + [("counter", 2.0, 0.6)]
FURNITURE["vestibule"] = [("wardrobe", 1.2, 0.6)]
FURNITURE["closet"] = [("wardrobe", 1.2, 0.6)]
FURNITURE["stairs"] = []  # Reserved floor area; no upper-floor transition yet.
FURNITURE["studio"] = [("bed", 2.0, 1.4), ("counter", 1.5, 0.6), ("table", 0.8, 0.6)]


def _furnish(rooms, doors, rng):
    furniture = []
    occupied = []
    clearances = [LineString(d["points"]).buffer(1.0, cap_style=3) for d in doors]
    for i, (kind, room) in enumerate(rooms):
        safe = room.buffer(-0.22)
        if safe.is_empty:
            continue
        centre = room.representative_point()
        routes = [LineString([LineString(d["points"]).centroid, centre]).buffer(0.55)
                  for d in doors if i in d["rooms"]]
        forbidden = unary_union(clearances + routes)
        x0, y0, x1, y1 = room.bounds
        # Bounded candidates favour the walls, leaving the room centre for circulation.
        for name, width, depth in FURNITURE[kind]:
            placed = False
            for w, h in [(width, depth), (depth, width)]:
                xs = [x0 + 0.24 + w / 2, x1 - 0.24 - w / 2] + [x0 + (x1 - x0) * x / 8 for x in range(1, 8)]
                ys = [y0 + 0.24 + h / 2, y1 - 0.24 - h / 2] + [y0 + (y1 - y0) * y / 8 for y in range(1, 8)]
                candidates = [(x, y) for x in xs for y in ys]
                rng.shuffle(candidates)
                candidates.sort(key=lambda p: room.boundary.distance(Point(p)))
                for x, y in candidates:
                    shape = box(x - w / 2, y - h / 2, x + w / 2, y + h / 2)
                    if safe.covers(shape) and not shape.intersects(forbidden) and not any(shape.intersects(p) for p in occupied):
                        furniture.append({"kind": name, "room": i, "points": list(shape.exterior.coords)[:-1]})
                        occupied.append(shape.buffer(0.12))
                        placed = True
                        break
                if placed:
                    break
    return furniture


def generate_floor_plan(building_id: str, points, entrance=None) -> dict:
    """Return a JSON-ready plan in local metres, or an explicit geometry error."""
    polygon = footprint(points)
    if polygon is None:
        return {"error": "invalid_geometry"}
    entry = tuple(entrance) if entrance is not None else None
    return _generate_cached(str(building_id), tuple(polygon.exterior.coords), entry, GENERATOR_VERSION)


@lru_cache(maxsize=8)
def _generate_cached(building_id, points, entrance, version):
    source = Polygon(points)
    origin = source.centroid.coords[0]
    polygon = translate(source, -origin[0], -origin[1])
    rectangle = list(polygon.minimum_rotated_rectangle.exterior.coords)
    a, b = max(zip(rectangle, rectangle[1:]), key=lambda pair: math.dist(*pair))
    angle = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180
    # Remove rotation noise so adjoining template rooms share exact boundary lines.
    polygon = normalize(set_precision(rotate(polygon, -angle, origin=(0, 0)), 1e-7))
    seed = hashlib.sha256(f"{building_id}:{version}".encode()).digest()
    rng = random.Random(seed)
    rooms, doors = _rooms(polygon, rng)
    target = rotate(translate(Point(entrance or origin), -origin[0], -origin[1]), -angle, origin=(0, 0))
    exterior = rooms[0][1].boundary.intersection(polygon.boundary)
    door = _door(exterior, [-1, 0], target, sides=(rooms[0][1],))
    if door is None and len(rooms) > 1:  # slanted or short hall ends: into the outer room nearest the entrance
        options = [_door(room.boundary.intersection(polygon.boundary), [-1, i], target, sides=(room,)) for i, (_, room) in enumerate(rooms) if i > 0]
        options = [d for d in options if d is not None]
        door = min(options, key=lambda d: LineString(d["points"]).distance(target)) if options else None
    if door is None and len(rooms) > 1:
        rooms, doors = [("studio", polygon)], []
        door = _door(polygon.boundary, [-1, 0], target, sides=(polygon,))
    if door is not None:
        doors.insert(0, door)
    walls = unary_union([p.boundary for _, p in rooms])
    openings = unary_union([LineString(d["points"]).buffer(0.015, cap_style=2) for d in doors])
    walls = walls.difference(openings)
    furniture = _furnish(rooms, doors, rng)

    # Restore the map's orientation, with north up in the client (which flips Y).
    def coords(shape):
        restored = rotate(shape, angle, origin=(0, 0))
        values = restored.exterior.coords if restored.geom_type == "Polygon" else restored.coords
        return [[round(x, 6), round(y, 6)] for x, y in values]

    for d in doors:
        a, b = d["points"]
        nx, ny = -(b[1] - a[1]) / DOOR_WIDTH, (b[0] - a[0]) / DOOR_WIDTH
        destination = rooms[d["rooms"][-1]][1]
        if not destination.covers(Point((a[0] + b[0]) / 2 + nx * 0.1, (a[1] + b[1]) / 2 + ny * 0.1)):
            nx, ny = -nx, -ny
        d["leaf"] = coords(Point(a[0] + nx * DOOR_WIDTH, a[1] + ny * DOOR_WIDTH))[0]
        d["points"] = coords(LineString(d["points"]))
    for item in furniture:
        item["points"] = coords(Polygon(item["points"]))[:-1]
    return {"building_id": building_id, "version": version, "area_m2": round(source.area, 1),
            "origin": [round(origin[0], 6), round(origin[1], 6)],  # the plan's (0, 0) in map metres
            "footprint": coords(polygon)[:-1], "simple": len(rooms) == 1,
            "rooms": [{"kind": kind, "points": coords(p)[:-1], "label_at": coords(p.representative_point())[0]}
                      for kind, p in rooms],
            "walls": [coords(line) for line in _lines(walls)], "doors": doors, "furniture": furniture}
