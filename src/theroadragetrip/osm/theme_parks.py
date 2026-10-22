"""Mapped amusement rides and a small clear-space layout for sparsely mapped parks."""
from shapely.affinity import scale
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from .models import Scenery

RIDE_KINDS = {"ferris_wheel", "carousel", "roller_coaster", "drop_tower", "swing_carousel"}


def prepare_theme_parks(sceneries, elements, nodes_m, buildings, waters, ways):
    rides = []
    for el in elements:
        tags = el.get("tags", {})
        kind = tags.get("attraction")
        if (kind not in RIDE_KINDS or tags.get("disused") == "yes" or tags.get("indoor") == "yes"
                or tags.get("layer", "0") != "0" or tags.get("level", "0") != "0"):
            continue
        if el["type"] == "node":
            centre = nodes_m.get(el["id"])
            if centre is None:
                continue
            shape = Point(*centre).buffer(7)
        elif el["type"] == "way":
            if any(n not in nodes_m for n in el.get("nodes", [])):
                continue  # incomplete streamed geometry must not invent a ride footprint
            points = [nodes_m[n] for n in el.get("nodes", [])]
            if len(points) < 2:
                continue
            shape = Polygon(points).buffer(0) if len(points) >= 4 and points[0] == points[-1] else LineString(points).buffer(3)
        else:
            continue
        ride = make_ride(shape, kind, tags.get("name"))
        if ride:
            rides.append(ride)
    # Explicitly mapped attractions take precedence over generated ones.
    parks = [s for s in sceneries if s.kind == "theme_park"]
    for park in parks:
        shape = Polygon(park.points_m).buffer(0)
        if shape.is_empty or any(shape.intersects(Polygon(r.points_m)) for r in rides):
            continue
        obstacles = [Polygon(b.points_m).buffer(2) for b in buildings if shape.intersects(box(*b.bbox))]
        obstacles += [Polygon(w.points_m).buffer(2) for w in waters if w.is_polygon and shape.intersects(box(*w.bbox))]
        obstacles += [LineString(w.points_m).buffer(w.half_width_m + 2) for w in ways if shape.intersects(box(*w.bbox))]
        clear = shape.buffer(-3).difference(unary_union(obstacles))
        # shortcut: four representative rides when OSM has only the park outline; replace as actual rides are mapped.
        for kind in ("carousel", "ferris_wheel", "roller_coaster", "swing_carousel"):
            reach = 16 if kind == "roller_coaster" else 9
            space = clear.buffer(-reach)
            if space.is_empty:
                break
            p = space.representative_point()
            footprint = p.buffer(8)
            if kind == "roller_coaster":
                footprint = scale(footprint, xfact=1.8, yfact=0.8, origin=p)
            ride = make_ride(footprint, kind, None)
            if ride:
                rides.append(ride)
                clear = clear.difference(footprint.buffer(7))
    sceneries.extend(rides)


def make_ride(shape, kind, name):
    if shape.is_empty or shape.geom_type != "Polygon" or shape.area < 12:
        return None
    inner = shape.buffer(-1.5)
    if inner.is_empty or inner.geom_type != "Polygon" or inner.exterior.length < 10:
        return None
    # A loop entirely within the mapped footprint also handles irregular coaster outlines.
    path = [tuple(inner.exterior.interpolate(inner.exterior.length * i / 48).coords[0]) for i in range(48)]
    path.append(path[0])
    return Scenery(list(shape.exterior.coords), "attraction_" + kind, name=name,
                   bbox=shape.bounds, attraction_path=path)
