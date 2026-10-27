"""The rest of the static world for chunk streaming (godot-16): what the
client draws from the map, prepared once at server start for clients that draw
from chunks (the Godot client). Everything here is static and visual: no
collision, no routing.

Ownership: every feature is in exactly one chunk, so a client never draws
one twice and an unloaded chunk takes exactly its own features along:
- points (crossings, signs, labels...): the chunk containing them
- polylines (curbs, level roads' parts...): their first point's chunk
- area polygons (landuse, islands, bridge decks): clipped to each chunk
  square they cover, each piece in its own chunk - a forest relation can
  span kilometres, more than the loaded chunks around the player
- bridge guardrail segments: their midpoint's chunk

Styles (colours, roof colours, gabled roofs) come from building_style.py
and map_style.py, computed here once.
"""

from __future__ import annotations

import math

from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

from .geo import dist_point_to_segment

GUARDRAIL_JOIN_M = 3.0  # close gaps between parallel bridge ways (~3 px at any zoom)
RAIL_BRIDGE_JOIN_M = 2.5  # one platform across ordinary parallel-track spacing
RAIL_DECK_HALF_M = 2.6 / 2.0 + 0.4  # half a sleeper + the deck margin
RAIL_UNDERPASS_MARGIN_M = 3.0  # deck/abutment beyond each side of the road cutting
LABEL_DISTRICT, LABEL_WATER, LABEL_AREA, LABEL_BUILDING, LABEL_ROAD = range(5)


def _rgb(color) -> list:
    return [int(color[0]), int(color[1]), int(color[2])]


def _ring(points) -> list:
    return [[round(x, 1), round(y, 1)] for x, y in points]


def clipped_pieces(points, size: float):
    """(cell, ring) pieces of a polygon cut along the chunk grid."""
    try:
        polygon = Polygon(points)
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
    except (ValueError, TypeError):
        return
    if polygon.is_empty:
        return
    minx, miny, maxx, maxy = polygon.bounds
    for ix in range(math.floor(minx / size), math.floor(maxx / size) + 1):
        for iy in range(math.floor(miny / size), math.floor(maxy / size) + 1):
            piece = polygon.intersection(box(ix * size, iy * size, (ix + 1) * size, (iy + 1) * size))
            for part in getattr(piece, "geoms", [piece]):
                if part.geom_type == "Polygon" and not part.is_empty and part.area > 0.05:
                    yield (ix, iy), _ring(part.exterior.coords[:-1])


def road_style(way) -> dict:
    """The parts of a road's look that aren't geometry:
    colour (road_color_for_way), centre line (dashed, or solid on a two-way
    road of 3+ lanes), one-way chevrons, bridge."""
    from .map_style import road_color_for_way, road_draw_rank

    style = {"color": _rgb(road_color_for_way(way)), "rank": road_draw_rank(way)}
    if way.is_drivable:
        lanes = max(1, int(getattr(way, "lanes", 1) or 1))
        forward, backward = getattr(way, "lanes_forward", None), getattr(way, "lanes_backward", None)
        oneway = int(getattr(way, "oneway", 0) or 0)
        solid = oneway == 0 and (lanes >= 3 or (forward or 0) >= 2 or (backward or 0) >= 2)
        color = (210, 235, 250) if getattr(way, "is_ice_road", False) else (130, 125, 120) if getattr(way, "highway", "") == "living_street" else (110, 110, 110)
        style["center"] = _rgb(color) + [2 if solid else 1]  # [r, g, b, 1 dashed / 2 solid]
        if oneway:
            style["oneway"] = 1 if oneway > 0 else -1
    if getattr(way, "is_bridge", False):
        style["bridge"] = True
    return style


_OWN_CENTERLINE_M = 50.0  # a bridge outline's own centrelines lie within its bounds; margin for safety


def _side_edges(polygons, centerlines, max_angle=math.radians(30)):
    """Boundary edges of the union running along a centreline (not the flat
    ends): the bridge guardrails, in world metres."""
    merged = unary_union([p.buffer(GUARDRAIL_JOIN_M) for p in polygons]).buffer(-GUARDRAIL_JOIN_M)
    edges = []
    for polygon in getattr(merged, "geoms", [merged]):
        if polygon.is_empty or polygon.geom_type != "Polygon":
            continue
        ring = list(polygon.exterior.coords)
        # Only this bridge's own centrelines can be nearest to its edges (a
        # closer one would have joined it): not every bridge on the map per edge.
        minx, miny, maxx, maxy = polygon.bounds
        own = [s for s in centerlines if min(s[0][0], s[1][0]) <= maxx + _OWN_CENTERLINE_M
               and max(s[0][0], s[1][0]) >= minx - _OWN_CENTERLINE_M and min(s[0][1], s[1][1]) <= maxy + _OWN_CENTERLINE_M
               and max(s[0][1], s[1][1]) >= miny - _OWN_CENTERLINE_M] or centerlines
        for a, b in zip(ring, ring[1:]):
            angle = math.atan2(b[1] - a[1], b[0] - a[0])
            mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
            best = min(own, key=lambda s: dist_point_to_segment(mid[0], mid[1], s[0][0], s[0][1], s[1][0], s[1][1]))
            seg_angle = math.atan2(best[1][1] - best[0][1], best[1][0] - best[0][0])
            if abs((angle - seg_angle + math.pi / 2.0) % math.pi - math.pi / 2.0) < max_angle:
                edges.append((a, b))
    return edges


def bridge_guardrails(ways) -> list:
    """Guardrail segments along the outside of all road bridges."""
    bridges = [w for w in ways if getattr(w, "is_bridge", False) and len(w.points_m) >= 2]
    polygons, centerlines = [], []
    for way in bridges:
        line = LineString(way.points_m)
        if line.length > 1e-9:
            polygons.append(line.buffer(max(way.half_width_m, 0.5), cap_style="flat", join_style="mitre"))
            centerlines.extend(zip(way.points_m, way.points_m[1:]))
    return _side_edges(polygons, centerlines) if polygons else []


def rail_bridge_parts(railways, ways=()):
    """Track lines above vehicles, including untagged track over an underpass."""
    parts = [LineString(r.points_m) for r in railways if r.is_bridge and len(r.points_m) >= 2]
    underpasses = [
        LineString(w.points_m).buffer(max(0.5, w.half_width_m) + RAIL_UNDERPASS_MARGIN_M)
        for w in ways
        if len(w.points_m) >= 2 and getattr(w, "is_drivable", True)
        and (getattr(w, "is_tunnel", False) or getattr(w, "layer", 0) < 0)
    ]
    if not underpasses:
        return parts
    covered = unary_union(underpasses)
    for railway in railways:
        if railway.is_bridge or len(railway.points_m) < 2:
            continue
        intersection = LineString(railway.points_m).intersection(covered)
        if intersection.geom_type == "LineString" and not intersection.is_empty:
            parts.append(intersection)
        else:
            parts.extend(line for line in getattr(intersection, "geoms", ()) if line.geom_type == "LineString" and not line.is_empty)
    return parts


def rail_bridge_decks(railways, ways=(), bridge_parts=None):
    """Deck polygons (union of the bridge tracks' sleeper width + margin)
    for the rail bridges."""
    lines = bridge_parts if bridge_parts is not None else rail_bridge_parts(railways, ways)
    if not lines:
        return []
    decks = unary_union([l.buffer(RAIL_DECK_HALF_M, cap_style="flat", join_style="mitre").buffer(RAIL_BRIDGE_JOIN_M)
                         for l in lines]).buffer(-RAIL_BRIDGE_JOIN_M)
    return [list(p.exterior.coords)[:-1] for p in getattr(decks, "geoms", [decks]) if p.geom_type == "Polygon" and not p.is_empty]


def building_style(building) -> list:
    """[roof colour, gabled, height m, entrances, wall colour, floors,
    category] as building_style.py picks them: colours named in the
    building's (Finnish) name, else the per-building texture pick; the OSM
    entrances ([x, y] each); its floor count (OSM levels, else height / 3);
    category 1 house, 2 commercial, 0 other (the window rules)."""
    from . import building_style as rb

    named = rb._building_colors_from_name(getattr(building, "colour_name", None) or getattr(building, "name", None))
    if named is not None:
        wall, roof = named
    else:
        seed = getattr(building, "texture_seed", None)
        if seed is None:
            cx, cy = getattr(building, "center_m", (0.0, 0.0))
            seed = abs(math.sin(cx * 0.013 + cy * 0.017))
        index = min(len(rb.BUILDING_ROOF_COLORS) - 1, int(seed * len(rb.BUILDING_ROOF_COLORS)))
        roof, wall = rb.BUILDING_ROOF_COLORS[index], rb.BUILDING_WALL_COLORS[index]
    return [_rgb(roof), 1 if rb._uses_gabled_roof(building) else 0, round(rb._building_render_height(building), 1),
            [[round(x, 1), round(y, 1)] for x, y in getattr(building, "entrances", ())],
            _rgb(wall), rb._building_window_story_count(building),
            1 if rb._building_is_house(building) else 2 if rb._building_is_commercial(building) else 0] + \
        ([1] if getattr(building, "arena_windows", False) else [])


def inherit_part_colours(buildings) -> int:
    """A building:part (no building type of its own, no name) inside a
    building whose name names a colour takes that name for its colour
    (`colour_name`): Valkealinnantalo's taller unnamed part otherwise
    covered its white roof with a palette brown. Returns how many."""
    from .geo import point_in_polygon
    from . import building_style as rb

    named = [b for b in buildings if len(b.points_m) >= 3 and rb._building_colors_from_name(getattr(b, "name", None))]
    count = 0
    for part in buildings:
        if getattr(part, "name", None) or getattr(part, "building_type", None) is not None or len(part.points_m) < 3:
            continue
        cx, cy = building_owner(part)
        for parent in named:
            minx, miny, maxx, maxy = parent.bbox
            if minx <= cx <= maxx and miny <= cy <= maxy and point_in_polygon(cx, cy, parent.points_m):
                part.colour_name = parent.name
                count += 1
                break
    return count


def building_owner(building):
    """The one point a building is owned by (godot-17): its centre - a 2.5D
    volume drawn twice, by two chunks, would cover its neighbours."""
    cx, cy = getattr(building, "center_m", None) or (0.0, 0.0)
    if (cx, cy) == (0.0, 0.0):
        points = building.points_m
        cx, cy = sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)
    return cx, cy


def is_open_roof(building) -> bool:
    from .building_style import _is_open_roof

    return _is_open_roof(building)


BUS_BAY_DEPTH_M = 3.0  # beside the carriageway; a bus is 2.55 m wide


def _bus_stop_road(stop, ways):
    """The nearest same-layer drivable road within 45 m of a bus stop:
    (nearest point, unit direction t, unit normal n towards the stop, the
    stop's side of t (+1 left), the way), or None."""
    nearest = None
    for way in ways:
        if not way.is_drivable or len(way.points_m) < 2 or getattr(way, "layer", 0) != getattr(stop, "layer", 0):
            continue
        for start, end in zip(way.points_m, way.points_m[1:]):
            dx, dy = end[0] - start[0], end[1] - start[1]
            length_sq = dx * dx + dy * dy
            if length_sq <= 1e-9:
                continue
            f = max(0.0, min(1.0, ((stop.x - start[0]) * dx + (stop.y - start[1]) * dy) / length_sq))
            p = (start[0] + f * dx, start[1] + f * dy)
            d = (stop.x - p[0]) ** 2 + (stop.y - p[1]) ** 2
            if nearest is None or d < nearest[0]:
                length = math.sqrt(length_sq)
                nearest = (d, p, (dx / length, dy / length), way)
    if nearest is None or nearest[0] > 45.0 * 45.0:
        return None
    _, p, t, way = nearest
    n = (-t[1], t[0])  # left of t
    side = 1.0 if (stop.x - p[0]) * n[0] + (stop.y - p[1]) * n[1] >= 0.0 else -1.0
    return p, t, (n[0] * side, n[1] * side), side, way


def bus_stop_point(stop, ways):
    """The road beside a bus stop: (centre-line point, unit normal towards
    the stop, the way), or None. Its bay lies beyond that way's edge."""
    road = _bus_stop_road(stop, ways)
    return None if road is None else (road[0], road[2], road[4])


def bus_stop_shapes(stop, ways):
    """A bus stop beside the nearest same-layer drivable road within 45 m
    (None without one): the bay in that road's colour with "BUS" painted
    in it (`label`, along `angle`), the E6 stop sign at the bay's front
    end in right-hand traffic (`sign`), and a shelter or a bench behind
    the kerb when OSM says so."""
    from .map_style import road_color_for_way
    road = _bus_stop_road(stop, ways)
    if road is None:
        return None
    p, t, n, side, way = road
    at = lambda along, out: [round(p[0] + t[0] * along + n[0] * out, 2), round(p[1] + t[1] * along + n[1] * out, 2)]
    front = -side  # right-hand traffic: on t's left side buses drive against t
    hw = way.half_width_m
    depth = BUS_BAY_DEPTH_M
    bay = [at(-16.0, hw), at(16.0, hw), at(11.0, hw + depth), at(-11.0, hw + depth)]
    kerb = hw + depth + 1.2  # the waiting area behind the bay's kerb
    rect = lambda along, out, half_along, half_out: [at(along - half_along, out - half_out), at(along + half_along, out - half_out),
                                                    at(along + half_along, out + half_out), at(along - half_along, out + half_out)]
    shelter = rect(0.0, kerb + 0.6, 2.5, 0.8) if getattr(stop, "shelter", False) else None
    bench = rect(0.0, kerb + 0.4, 0.9, 0.25) if getattr(stop, "bench", False) and shelter is None else None
    angle = math.atan2(t[1], t[0])  # "BUS" along the bay, never upside down on the north-up map
    if abs(angle) > math.pi / 2:
        angle -= math.copysign(math.pi, angle)
    return {"bay": bay, "color": list(road_color_for_way(way)), "label": at(0.0, hw + depth / 2.0),
            "angle": round(angle, 3), "sign": at(front * 9.0, kerb + 0.4), "shelter": shelter, "bench": bench}


def labels(world) -> list:
    """Label candidates, by priority:
    districts, named waters, named areas, buildings (their places and
    their own name), roads. [x, y, text, category]; the client declutters
    per view."""
    from .map_style import DISTRICT_PLACE_KINDS

    found = []
    for place in getattr(world, "places", ()):
        if getattr(place, "name", None) and getattr(place, "kind", None) in DISTRICT_PLACE_KINDS:
            found.append([place.x, place.y, place.name, LABEL_DISTRICT])

    def centre(feature):
        bb = getattr(feature, "bbox", None)
        if bb and bb != (0.0, 0.0, 0.0, 0.0):
            return (bb[0] + bb[2]) * 0.5, (bb[1] + bb[3]) * 0.5
        points = feature.points_m
        return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)

    for water in getattr(world, "waters", ()):
        if getattr(water, "name", None) and water.points_m:
            found.append([*centre(water), water.name, LABEL_WATER])
    for scenery in getattr(world, "sceneries", ()):
        if getattr(scenery, "name", None) and scenery.points_m:
            found.append([*centre(scenery), scenery.name, LABEL_AREA])
    for building in getattr(world, "buildings", ()):
        named = [(p.name, p.x, p.y) for p in getattr(building, "associated_places", ()) if getattr(p, "name", None)]
        name = getattr(building, "name", None)
        if name and not any(n == name for n, _, _ in named) and building.points_m:
            named.append((name, *(getattr(building, "center_m", None) or centre(building))))
        found.extend([x, y, n, LABEL_BUILDING] for n, x, y in named)
    for way in getattr(world, "ways", ()):
        if getattr(way, "name", None) and len(way.points_m) >= 2:
            mid = len(way.points_m) // 2
            a, b = way.points_m[mid - 1], way.points_m[mid]
            found.append([(a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5, way.name, LABEL_ROAD])
    return [[round(x, 1), round(y, 1), text, category] for x, y, text, category in found]
