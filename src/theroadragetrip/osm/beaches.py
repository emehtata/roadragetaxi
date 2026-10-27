"""Playable dry beach spots and short, connected routes into mapped water."""
import math

from shapely.geometry import LineString, Polygon, box
from shapely.ops import nearest_points


def prepare_beach(beach, waters, buildings, ways):
    shape = Polygon(beach.points_m).buffer(0)
    region = shape.buffer(15)
    wet = [Polygon(w.points_m).buffer(0) for w in waters if w.is_polygon and w.layer == 0
           and w.kind in {"water", "sea", "lake", "bay", "strait"} and region.intersects(box(*w.bbox))]
    obstacles = [Polygon(b.points_m).buffer(0.5) for b in buildings if region.intersects(box(*b.bbox))]
    obstacles += [LineString(w.points_m).buffer(w.half_width_m + 0.5) for w in ways
                  if region.intersects(box(*w.bbox))]
    dry = shape
    for geometry in wet + obstacles:
        dry = dry.difference(geometry)
    dry = dry.buffer(-2)
    if dry.is_empty:
        return
    x0, y0, x1, y1 = dry.bounds
    for row in range(8):
        for column in range(8):
            cell = dry.intersection(box(x0+(x1-x0)*column/8, y0+(y1-y0)*row/8,
                                        x0+(x1-x0)*(column+1)/8, y0+(y1-y0)*(row+1)/8))
            if not cell.is_empty:
                p = cell.representative_point()
                if all(math.dist((p.x, p.y), old) >= 3 for old in beach.beach_spots):
                    beach.beach_spots.append((p.x, p.y))
    # shortcut: swim within six metres of mapped shore; water temperature, depth and currents are not modeled.
    for water in wet:
        for index in range(16):
            land = dry.boundary.interpolate(dry.boundary.length * index / 16)
            edge = nearest_points(land, water)[1]
            distance = land.distance(edge)
            if not 0.1 < distance <= 12:
                continue
            dx, dy = (edge.x-land.x)/distance, (edge.y-land.y)/distance
            entry, target = (edge.x+dx*0.5, edge.y+dy*0.5), (edge.x+dx*6, edge.y+dy*6)
            route = LineString([(land.x, land.y), entry, target])
            if (water.covers(LineString([entry, target]).buffer(0.25))
                    and shape.union(water).buffer(0.5).covers(route.buffer(0.25))
                    and not any(route.buffer(0.5).intersects(o) for o in obstacles)
                    and all(math.dist((land.x, land.y), old[0]) >= 4 for old in beach.swim_routes)):
                beach.swim_routes.append([(land.x, land.y), entry, target])
