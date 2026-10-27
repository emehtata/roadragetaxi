"""Bounded fallback layouts for miniature-golf facilities without mapped holes."""
import math

from shapely.geometry import LineString, Polygon, box


def miniature_golf_holes(points, obstacles=()):
    area = Polygon(points).buffer(0)
    for obstacle in obstacles:
        if area.intersects(obstacle):
            area = area.difference(obstacle)
    available = area.buffer(-0.85)
    if available.is_empty:
        return []
    x0, y0, x1, y1 = area.bounds
    centres = []
    # Coarse cells distribute the holes; smaller cells fill gaps in irregular sites.
    for divisions in (3, 5):
        for row in range(divisions):
            for column in range(divisions):
                cell = available.intersection(box(x0+(x1-x0)*column/divisions, y0+(y1-y0)*row/divisions,
                                                  x0+(x1-x0)*(column+1)/divisions, y0+(y1-y0)*(row+1)/divisions))
                if not cell.is_empty and cell.area > 1.0:
                    centre = cell.representative_point()
                    centres.append((centre.x, centre.y))
    holes, chosen = [], []
    length = min(10.0, max(2.2, min(x1-x0, y1-y0) / 3.5))
    while centres and len(holes) < 9:
        centre = max(centres, key=lambda p: min(math.dist(p, old) for old in chosen)) if chosen else min(
            centres, key=lambda p: math.dist(p, ((x0+x1)/2, (y0+y1)/2)))
        centres.remove(centre)
        index = len(holes)
        accepted = None
        for angle in (index * math.pi / 5, 0.0, math.pi / 2):
            for scale in (1.0, 0.7, 0.45):
                half = length * scale / 2
                bend = min(0.9, half * 0.35) if index % 3 else 0.0
                local = [(-half, 0), (0, bend), (half, 0)]
                line = LineString([(centre[0]+x*math.cos(angle)-y*math.sin(angle),
                                    centre[1]+x*math.sin(angle)+y*math.cos(angle)) for x, y in local])
                clipped = line.intersection(available)
                parts = list(clipped.geoms) if hasattr(clipped, "geoms") else [clipped]
                lane = max((p for p in parts if p.geom_type == "LineString"), key=lambda p: p.length, default=None)
                if lane is not None and lane.length >= 2.0:
                    accepted = lane
                    break
            if accepted is not None:
                break
        if accepted is not None:
            track = list(accepted.coords)
            if index % 2:
                track.reverse()
            holes.append(track)
            chosen.append(centre)
            available = available.difference(accepted.buffer(1.9))
    # shortcut: tiny or obstructed sites fit fewer than nine; never overlap tracks to force a count.
    return holes
