"""Offline, bounded town approaches; never persist the national local network."""
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET

from .intercity import IntercityGraph, ROAD_CLASSES, _elements, _step, build_xml
from .utils.pbf_index import osmium_command

GATEWAY_VERSION = 1
CONNECTOR_CLASSES = ("tertiary", "tertiary_link", "unclassified", "residential", "living_street", "service")
EXTENT_M = 6000
MAX_CONNECTOR_M = 8000


def place_id(name, x, y, kind=None):
    # Coordinates disambiguate identically named catalogue entries.
    key = json.dumps([name.casefold(), round(x, 2), round(y, 2), kind], ensure_ascii=False)
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def catalogue():
    from .taxi import municipality_points
    return [(place_id(name,x,y,kind),name,x,y,weight,kind)
            for name,x,y,weight,kind in municipality_points()]


def catalogue_digest(places=None):
    return hashlib.sha256(json.dumps(catalogue() if places is None else places,ensure_ascii=False).encode()).hexdigest()


def landmark_provenance():
    from pyproj import Transformer
    from .world_places import load_places
    project = Transformer.from_crs("EPSG:4326","EPSG:3067",always_xy=True).transform
    result = []
    for place in load_places():
        x,y = project(place.lon,place.lat)
        identity = place_id(place.name,x,y,place.type)
        for alias in {place.name,*place.names.values()}:
            result.append((identity,alias,place.id,json.dumps(place.osm)))
    return result


def attach_gateways(path, local_path, places, *, extent_m=EXTENT_M, max_connector_m=MAX_CONNECTOR_M, town_policies=None):
    """Retain only verified directed connector paths, sharing original OSM IDs."""
    if not 0 < extent_m <= EXTENT_M or not 0 < max_connector_m <= 20000:
        raise ValueError("Town connector extent must be 1..6000 m and length 1..20000 m")
    backbone, local = IntercityGraph(path), IntercityGraph(local_path)
    backbone.connectivity()
    main_component = backbone.largest_strong_component
    major_nodes = {node for a,b,highway in backbone.db.execute("SELECT a,b,highway FROM segments")
                   if highway in ROAD_CLASSES for node in (a,b)}
    seeds = main_component & major_nodes & local.nodes.keys()
    reverse = defaultdict(list)
    for node,edges in local.edges.items():
        for end,*_ in edges:
            reverse[end].append(node)
    def reachable(backward=False):
        seen = set(seeds)
        stack = list(seeds)
        while stack:
            node = stack.pop()
            neighbours = reverse.get(node,()) if backward else (edge[0] for edge in local.edges.get(node,()))
            for end in neighbours:
                if end not in seen:
                    seen.add(end)
                    stack.append(end)
        return seen
    connected = reachable() & reachable(True)
    del reverse
    report = {"supported": [], "missing": [], "connectors": []}
    selected, records = set(), []
    # Bucket queries keep preparation proportional to each town's bounded area.
    grid = defaultdict(list)
    for node,(x,y) in local.nodes.items():
        grid[(int(x//EXTENT_M),int(y//EXTENT_M))].append(node)
    street_nodes = set()
    public_street_nodes = set()
    for a,b,highway in local.db.execute("SELECT a,b,highway FROM segments WHERE highway NOT IN ('motorway','motorway_link','trunk','trunk_link')"):
        street_nodes.update((a,b))
        if highway != "service":
            public_street_nodes.update((a,b))
    try:
        for index,(identity,name,x,y,weight,kind) in enumerate(places):
            _step(4, f"{index}/{len(places)}")
            policy = (town_policies or {}).get(identity,{})
            town_extent = float(policy.get("extent_m",extent_m))
            town_maximum = float(policy.get("max_length_m",max_connector_m))
            classes = set(policy.get("classes",CONNECTOR_CLASSES))
            if not 0 < town_extent <= EXTENT_M or not 0 < town_maximum <= 20000 or classes-set(CONNECTOR_CLASSES):
                raise ValueError(f"Invalid bounded connector policy for {identity}")
            allowed_ways = None
            if classes != set(CONNECTOR_CLASSES):
                allowed_classes = classes|set(ROAD_CLASSES)
                allowed_ways = {way for way,highway in local.db.execute("SELECT DISTINCT way,highway FROM segments") if highway in allowed_classes}
            nearby = [node for gx in range(int(x//EXTENT_M)-1,int(x//EXTENT_M)+2)
                      for gy in range(int(y//EXTENT_M)-1,int(y//EXTENT_M)+2)
                      for node in grid[(gx,gy)] if math.dist((x,y),local.nodes[node]) <= town_extent]
            anchors = sorted((n for n in nearby if n in street_nodes and n in connected and math.dist((x,y),local.nodes[n]) <= (800 if kind else 1000)),
                             key=lambda n:(n not in public_street_nodes,math.dist((x,y),local.nodes[n])))[:12]
            candidates = sorted((n for n in nearby if n in seeds),key=lambda n:math.dist((x,y),local.nodes[n]))[:12]
            associations = []
            anchor = None
            for candidate_anchor in anchors:
                for gateway in candidates:
                    inward = local.route(gateway,candidate_anchor,deadline=time.perf_counter()+.25,extent_m=town_extent,allowed_ways=allowed_ways)
                    outward = local.route(candidate_anchor,gateway,deadline=time.perf_counter()+.25,extent_m=town_extent,allowed_ways=allowed_ways)
                    if inward and outward and max(inward.distance_m,outward.distance_m) <= town_maximum:
                        selected.update(segment for route in (inward,outward) for segment,_ in route.segments)
                        associations.append(gateway)
                        report["connectors"].append({"place":identity,"gateway":gateway,"anchor":candidate_anchor,
                                                     "in_m":round(inward.distance_m),"out_m":round(outward.distance_m)})
                    if len(associations) == 3:
                        break
                if associations:
                    anchor = candidate_anchor
                    break
            if anchor is None:
                report["missing"].append({"id":identity,"name":name,"reason":"no bidirectional bounded road approach"})
            else:
                report["supported"].append(identity)
                records.append((identity,name,x,y,weight,kind,anchor,json.dumps(associations)))
        if not records:
            raise ValueError("No towns have usable intercity gateways")
        backbone.close()
        backbone = None
        with sqlite3.connect(path) as db:
            db.executescript("""CREATE TABLE IF NOT EXISTS places(id TEXT PRIMARY KEY,name TEXT,x REAL,y REAL,
                weight INTEGER,kind TEXT,anchor INTEGER,gateways TEXT);
                CREATE TABLE IF NOT EXISTS gateway_report(value TEXT);
                CREATE TABLE IF NOT EXISTS place_aliases(place_id TEXT,alias TEXT,source_id TEXT,source_osm TEXT);""")
            db.execute("DELETE FROM places")
            db.executemany("INSERT INTO places VALUES(?,?,?,?,?,?,?,?)",records)
            db.execute("DELETE FROM place_aliases")
            identities = {row[0] for row in records}
            db.executemany("INSERT INTO place_aliases VALUES(?,?,?,?)",[row for row in landmark_provenance() if row[0] in identities])
            # Imported connector geometry keeps its OSM way/node identity and restrictions.
            existing = {(a,b,way) for a,b,way in db.execute("SELECT a,b,way FROM segments")}
            for segment in sorted(selected):
                row = local.db.execute("SELECT a,b,way,highway,name,length,forward_s,reverse_s,geometry FROM segments WHERE id=?",(segment,)).fetchone()
                if row[:3] in existing:
                    continue
                for node in row[:2]:
                    db.execute("INSERT OR IGNORE INTO nodes VALUES(?,?,?)",(node,*local.nodes[node]))
                db.execute("INSERT INTO segments(a,b,way,highway,name,length,forward_s,reverse_s,geometry) VALUES(?,?,?,?,?,?,?,?,?)",row)
                existing.add(row[:3])
            rules = set(db.execute("SELECT * FROM restrictions"))
            db.executemany("INSERT INTO restrictions VALUES(?,?,?,?,?)",[r for r in local.db.execute("SELECT * FROM restrictions") if r not in rules])
            metadata = json.loads(db.execute("SELECT value FROM metadata").fetchone()[0])
            metadata.update(gateway_version=GATEWAY_VERSION,connector_policy={"extent_m":extent_m,"max_length_m":max_connector_m,"classes":CONNECTOR_CLASSES},
                            gateway_places=len(records),missing_gateway_places=len(report["missing"]))
            metadata["catalogue_digest"] = catalogue_digest(places)
            metadata["town_connector_policies"] = town_policies or {}
            metadata["no_uturn_ways"] = sorted(set(metadata.get("no_uturn_ways",()))|set(local.metadata.get("no_uturn_ways",())))
            metadata["junction_nodes"] = db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            metadata["segments"],metadata["directed_segments"] = db.execute(
                "SELECT COUNT(*),SUM((forward_s IS NOT NULL)+(reverse_s IS NOT NULL)) FROM segments").fetchone()
            db.execute("UPDATE metadata SET value=?",(json.dumps(metadata),))
            db.execute("DELETE FROM gateway_report")
            db.execute("INSERT INTO gateway_report VALUES(?)",(json.dumps(report),))
    finally:
        if backbone:
            backbone.close()
        local.close()
    return report


def prepare_gateways(source, path, *, town_policies=None):
    """Filter local streets only inside catalogue regions, then discard the extract."""
    from pyproj import Transformer
    places = catalogue()
    project = Transformer.from_crs("EPSG:4326","EPSG:3067",always_xy=True).transform
    regions = defaultdict(list)
    for _,_,x,y,*_ in places:
        regions[(int(x//EXTENT_M),int(y//EXTENT_M))].append((x,y))
    classes = (*ROAD_CLASSES,*CONNECTOR_CLASSES)
    command = osmium_command()
    with tempfile.TemporaryDirectory(prefix="intercity-towns-") as temp:
        filtered,xml,local = [Path(temp)/name for name in ("roads.pbf","towns.osm","local.sqlite")]
        _step(3)
        subprocess.run([command,"tags-filter",str(source),"w/highway="+",".join(classes),"r/type=restriction","-o",str(filtered)],check=True,capture_output=True,timeout=1800)
        retained = set()
        with xml.open("wb") as output, subprocess.Popen([command,"cat",str(filtered),"-f","osm"],stdout=subprocess.PIPE) as process:
            output.write(b'<osm version="0.6">')
            try:
                for element in _elements(process.stdout, 3):
                    if element.tag == "node":
                        x,y = project(float(element.get("lon")),float(element.get("lat")))
                        if not any(math.dist((x,y),centre) <= EXTENT_M for gx in range(int(x//EXTENT_M)-1,int(x//EXTENT_M)+2)
                                   for gy in range(int(y//EXTENT_M)-1,int(y//EXTENT_M)+2) for centre in regions.get((gx,gy),())):
                            continue
                        retained.add(int(element.get("id")))
                        output.write(ET.tostring(element))
                    elif element.tag == "way":
                        # Split at the extraction boundary, never bridge a missing road section.
                        run = []
                        for ref in [int(nd.get("ref")) for nd in element.findall("nd")]+[None]:
                            if ref in retained:
                                run.append(ref)
                            else:
                                if len(run) >= 2:
                                    part = ET.Element("way",element.attrib)
                                    for node in run:
                                        ET.SubElement(part,"nd",ref=str(node))
                                    part.extend(element.findall("tag"))
                                    output.write(ET.tostring(part))
                                run = []
                    else:
                        output.write(ET.tostring(element))
            except BaseException:
                process.kill()
                process.wait()
                raise
            if process.wait():
                raise RuntimeError("osmium failed preparing town approaches")
            output.write(b'</osm>')
        with xml.open("rb") as stream:
            build_xml(stream,local,project,classes,connector_extract=True)
        return attach_gateways(path,local,places,town_policies=town_policies)
