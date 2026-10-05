"""The rest of the static world for chunk streaming (godot-16): what Pygame
draws from the map, prepared once at server start for clients that draw
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

Styles (colours, roof colours, gabled roofs) come from the same functions
Pygame's renderers use, computed here once instead of per frame.
"""

from __future__ import annotations

import math

from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

from .geo import dist_point_to_segment

GUARDRAIL_JOIN_M = 3.0  # render/roads.py draw_ways: close gaps between parallel bridge ways (~3 px at any zoom)
RAIL_BRIDGE_JOIN_M = 1.5  # render/roads.py _RAILWAY_BRIDGE_JOIN_M
RAIL_DECK_HALF_M = 2.6 / 2.0 + 0.4  # half a sleeper + the deck margin (render/roads.py)
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
    """The parts of render/roads.py draw_ways' look that aren't geometry:
    colour (road_color_for_way), centre line (dashed, or solid on a two-way
    road of 3+ lanes), one-way chevrons, bridge."""
    from .render.common import road_color_for_way

    style = {"color": _rgb(road_color_for_way(way))}
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


def _side_edges(polygons, centerlines, max_angle=math.radians(30)):
    """Boundary edges of the union running along a centreline (not the flat
    ends): render/roads.py draw_ways' guardrails, in world metres."""
    merged = unary_union([p.buffer(GUARDRAIL_JOIN_M) for p in polygons]).buffer(-GUARDRAIL_JOIN_M)
    edges = []
    for polygon in getattr(merged, "geoms", [merged]):
        if polygon.is_empty or polygon.geom_type != "Polygon":
            continue
        ring = list(polygon.exterior.coords)
        for a, b in zip(ring, ring[1:]):
            angle = math.atan2(b[1] - a[1], b[0] - a[0])
            mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
            best = min(centerlines, key=lambda s: dist_point_to_segment(mid[0], mid[1], s[0][0], s[0][1], s[1][0], s[1][1]))
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


def rail_bridge_decks(railways):
    """Deck polygons (union of the bridge tracks' sleeper width + margin)
    for render/roads.py's rail bridges."""
    lines = [LineString(r.points_m) for r in railways if r.is_bridge and len(r.points_m) >= 2]
    if not lines:
        return []
    decks = unary_union([l.buffer(RAIL_DECK_HALF_M, cap_style="flat", join_style="mitre").buffer(RAIL_BRIDGE_JOIN_M)
                         for l in lines]).buffer(-RAIL_BRIDGE_JOIN_M)
    return [list(p.exterior.coords)[:-1] for p in getattr(decks, "geoms", [decks]) if p.geom_type == "Polygon" and not p.is_empty]


def building_style(building) -> list:
    """[roof colour, gabled, height m] as render/buildings.py picks them: a
    colour named in the building's (Finnish) name, else the per-building
    texture pick."""
    from .render import buildings as rb

    named = rb._building_colors_from_name(getattr(building, "name", None))
    if named is not None:
        roof = named[1]
    else:
        seed = getattr(building, "texture_seed", None)
        if seed is None:
            cx, cy = getattr(building, "center_m", (0.0, 0.0))
            seed = abs(math.sin(cx * 0.013 + cy * 0.017))
        roof = rb.BUILDING_ROOF_COLORS[min(len(rb.BUILDING_ROOF_COLORS) - 1, int(seed * len(rb.BUILDING_ROOF_COLORS)))]
    return [_rgb(roof), 1 if rb._uses_gabled_roof(building) else 0, round(rb._building_render_height(building), 1)]


def is_open_roof(building) -> bool:
    from .render.buildings import _is_open_roof

    return _is_open_roof(building)


def bus_stop_shapes(stop, ways):
    """render/roads.py draw_bus_stops' bay, shelter and label from the
    nearest same-layer drivable road within 45 m; None without one."""
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
                nearest = (d, p, (dx / length, dy / length), way.half_width_m)
    if nearest is None or nearest[0] > 45.0 * 45.0:
        return None
    _, p, t, hw = nearest
    n = (-t[1], t[0])
    side = 1.0 if (stop.x - p[0]) * n[0] + (stop.y - p[1]) * n[1] >= 0.0 else -1.0
    n = (n[0] * side, n[1] * side)
    at = lambda along, out: [round(p[0] + t[0] * along + n[0] * out, 2), round(p[1] + t[1] * along + n[1] * out, 2)]
    bay = [at(-14.0, hw), at(14.0, hw), at(10.0, hw + 2.2), at(-10.0, hw + 2.2)]
    centre_out = hw + 3.2
    shelter = [at(-2.5, centre_out - 1.0), at(2.5, centre_out - 1.0), at(2.5, centre_out + 1.0), at(-2.5, centre_out + 1.0)] \
        if getattr(stop, "shelter", False) else None
    return {"bay": bay, "shelter": shelter, "label": at(0.0, centre_out), "angle": round(math.atan2(t[1], t[0]), 3)}


def labels(world) -> list:
    """Label candidates as render/labels.py chooses them, by priority:
    districts, named waters, named areas, buildings (their places and
    their own name), roads. [x, y, text, category]; the client declutters
    per view, as Pygame does."""
    from .render.labels import DISTRICT_PLACE_KINDS

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
