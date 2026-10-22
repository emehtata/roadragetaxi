"""Static camping equipment on mapped pitches, fitted clear of access routes."""
import math

from shapely.affinity import rotate, translate
from shapely.geometry import LineString, Point, Polygon, box
from shapely.strtree import STRtree

from .models import SceneryObject


def populate_camp_pitches(elements, nodes_m, buildings, waters, ways, railings):
    pitches = sorted((e for e in elements if e.get("tags", {}).get("tourism") == "camp_pitch"), key=lambda e: (e["id"], e["type"]))
    if not pitches:
        return []
    obstacles = [Polygon(b.points_m).buffer(.4) for b in buildings if len(b.points_m) >= 3]
    obstacles += [Polygon(w.points_m).buffer(.5) for w in waters if w.is_polygon and len(w.points_m) >= 3]
    obstacles += [LineString(w.points_m).buffer(w.half_width_m + .5) for w in ways if len(w.points_m) >= 2 and w.layer == 0]
    obstacles += [LineString(r.points_m).buffer(.7) for r in railings if len(r.points_m) >= 2 and r.layer == 0]
    tree = STRtree(obstacles)
    access = [w for w in ways if w.highway in {"service", "track", "footway", "path", "pedestrian"} and w.layer == 0]
    objects, occupied = [], []
    for pitch in pitches:
        variation = abs(pitch["id"]) - 1
        tags = pitch["tags"]
        if (variation % 5 == 4 or tags.get("layer", "0") != "0" or tags.get("level", "0") != "0"
                or tags.get("indoor") == "yes" or tags.get("access") == "no"):
            continue
        if pitch["type"] == "node" and pitch["id"] in nodes_m:
            # shortcut: point pitches use a five-metre envelope until their boundaries are mapped.
            shape = Point(*nodes_m[pitch["id"]]).buffer(5)
        elif pitch["type"] == "way":
            ids = pitch.get("nodes", [])
            if len(ids) < 4 or ids[0] != ids[-1] or any(n not in nodes_m for n in ids):
                continue
            shape = Polygon([nodes_m[n] for n in ids]).buffer(0)
        else:
            continue
        if shape.is_empty:
            continue
        centre = Point(*nodes_m[pitch["id"]]) if pitch["type"] == "node" else shape.representative_point()
        nearby = min(access, key=lambda w: LineString(w.points_m).distance(centre), default=None)
        angle = 0.0
        if nearby is not None:
            line = LineString(nearby.points_m)
            along = line.project(centre)
            a, b = line.interpolate(max(0, along-1)), line.interpolate(min(line.length, along+1))
            angle = math.atan2(b.y-a.y, b.x-a.x)
        kinds = ["tent", "camper_van"] if variation % 3 == 0 else ["camper_van", "tent"]
        for kind in kinds:
            if kind == "tent" and tags.get("tents") == "no":
                continue
            if kind == "camper_van" and any(tags.get(tag) == "no" for tag in ("motorhome", "motorhomes", "caravans")):
                continue
            length, width = (3.2, 2.4) if kind == "tent" else (6.2, 2.5)
            placed = False
            for heading in (angle + math.pi/2, angle):
                footprint = translate(rotate(box(-length/2, -width/2, length/2, width/2), heading, use_radians=True), centre.x, centre.y)
                if (shape.covers(footprint) and not len(tree.query(footprint, predicate="intersects"))
                        and all(footprint.distance(other) > .8 for other in occupied)):
                    objects.append(SceneryObject(centre.x, centre.y, kind, id=-pitch["id"], direction_angle=heading))
                    occupied.append(footprint)
                    placed = True
                    break
            if placed:
                break
    return objects
