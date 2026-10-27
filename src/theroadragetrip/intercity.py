"""Offline major-road preparation and read-only intercity routing.

This graph is independent of the streamed world; startup prepares it only
after the user explicitly enables intercity fares.
Callers supply validated OSM gateway nodes, not arbitrary city coordinates.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import heapq
import json
import math
from pathlib import Path
import sqlite3
import struct
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
import zlib

from .utils.pbf_index import osmium_command

VERSION = 1
ROAD_CLASSES = ("motorway", "motorway_link", "trunk", "trunk_link",
                "primary", "primary_link", "secondary", "secondary_link")
DEFAULT_SPEED_KMH = {"motorway": 100, "trunk": 80, "primary": 80, "secondary": 70,
                     "motorway_link": 40, "trunk_link": 40, "primary_link": 40, "secondary_link": 40,
                     "tertiary":60,"tertiary_link":40,"unclassified":50,"residential":30,"living_street":20,"service":20}


# ponytail: module-level reporter set only while prepare_database runs (one build at a time).
_report = None


def _step(step, count=""):
    """Tell the loading screen which of the four preparation steps runs."""
    if _report is not None:
        _report(f"{step}/4" + (f" · {count}" if count != "" else ""))


def prepare_database(source, output, progress=None):
    """Explicit user opt-in initialization; reuse a matching prepared graph."""
    global _report
    _report = progress
    try:
        return _prepare_database(source, output)
    finally:
        _report = None


def _prepare_database(source, output):
    from .intercity_places import (GATEWAY_VERSION, EXTENT_M, MAX_CONNECTOR_M,
                                  CONNECTOR_CLASSES, catalogue_digest, prepare_gateways)
    source,output = Path(source),Path(output)
    stat = source.stat()
    identity = {"path":str(source.resolve()),"size":stat.st_size,"mtime_ns":stat.st_mtime_ns}
    if output.is_file():
        try:
            graph = IntercityGraph(output)
            try:
                if (graph.metadata.get("source") == identity and graph.metadata.get("road_classes") == list(ROAD_CLASSES)
                        and graph.metadata.get("gateway_version") == GATEWAY_VERSION and graph.metadata.get("gateway_places",0) > 0):
                    policy = {"extent_m":EXTENT_M,"max_length_m":MAX_CONNECTOR_M,"classes":list(CONNECTOR_CLASSES)}
                    if (graph.metadata.get("catalogue_digest") == catalogue_digest()
                            and graph.metadata.get("speed_defaults_kmh") == DEFAULT_SPEED_KMH
                            and graph.metadata.get("connector_policy") == policy):
                        return output
            finally:
                graph.close()
        except (ValueError,sqlite3.Error):
            pass
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="intercity-ready-",dir=output.parent) as temp:
        staged = Path(temp)/"ready.sqlite"
        _step(1)
        build_pbf(source,staged)
        prepare_gateways(source,staged)
        current = source.stat()
        if (current.st_size,current.st_mtime_ns) != (stat.st_size,stat.st_mtime_ns):
            raise RuntimeError("Source PBF changed during town preparation")
        staged.replace(output)
    return output


def _elements(stream, step=None):
    root = None
    count = 0
    for event, element in ET.iterparse(stream, events=("start", "end")):
        if root is None:
            root = element
        if event == "end" and element.tag in {"node", "way", "relation"}:
            count += 1
            if step and count % 250_000 == 0:
                _step(step, f"{count / 1e6:.2f} M")
            yield element
            root.remove(element)


def _access(tags):
    if any(":conditional" in key for key in tags if key.split(":")[0] in
           {"access", "vehicle", "motor_vehicle", "motorcar", "oneway", "taxi"}):
        return False
    return next((tags[key] for key in ("taxi", "motorcar", "motor_vehicle", "vehicle", "access")
                 if key in tags), "yes") in {"yes", "designated", "permissive"}


def _speed(tags, direction, highway):
    value = tags.get("maxspeed:" + direction, tags.get("maxspeed", ""))
    named = {"FI:urban": 50, "FI:rural": 80}
    try:
        speed = named[value] if value in named else min(float(part.replace(" mph", "")) * (1.609344 if "mph" in part else 1)
                                                       for part in value.split(";"))
        if not math.isfinite(speed) or not 0 < speed <= 200:
            raise ValueError
    except (ValueError, TypeError):
        speed = DEFAULT_SPEED_KMH.get(highway, 50)
    return speed / 3.6


def _directions(tags):
    one = tags.get("oneway:motorcar", tags.get("oneway:motor_vehicle", tags.get("oneway")))
    if one is None:
        one = "yes" if tags.get("highway") in {"motorway", "motorway_link"} or tags.get("junction") == "roundabout" else "no"
    forward,reverse = ((True,False) if one in {"yes","1","true"} else
                       (False,True) if one in {"-1","reverse"} else
                       (True,True) if one in {"no","0","false"} else (False,False))
    for direction in ("forward","backward"):
        access = next((tags[key+":"+direction] for key in ("taxi","motorcar","motor_vehicle","vehicle","access")
                       if key+":"+direction in tags),"yes")
        if access not in {"yes","designated","permissive"}:
            if direction == "forward":
                forward = False
            else:
                reverse = False
    return forward,reverse


def build_xml(stream, output, project, road_classes=ROAD_CLASSES, source=None, *, connector_extract=False):
    """Compact selected OSM ways while retaining junctions and restrictions."""
    _step(4 if connector_extract else 2)
    road_classes = tuple(road_classes)
    permitted = set(ROAD_CLASSES)
    if connector_extract:
        permitted.update(("tertiary", "tertiary_link", "unclassified", "residential", "living_street", "service"))
    if not road_classes or set(road_classes) - permitted:
        raise ValueError("Backbone classes must be a nonempty subset of ROAD_CLASSES")
    nodes, ways, rules, blocked_nodes, blocked_ways = {}, [], [], set(), set()
    references = Counter()
    for element in _elements(stream, 4 if connector_extract else 2):
        tags = {tag.get("k"): tag.get("v") for tag in element.findall("tag")}
        identifier = int(element.get("id"))
        if element.tag == "node":
            point = project(float(element.get("lon")), float(element.get("lat")))
            if not all(math.isfinite(value) for value in point):
                raise ValueError("Invalid projected OSM node")
            nodes[identifier] = point
            if not _access(tags) or (tags.get("barrier") in {"bollard", "block", "cycle_barrier", "stile"}
                                     and not any(tags.get(key) in {"yes", "permissive", "designated"} for key in ("taxi", "motorcar", "motor_vehicle"))):
                blocked_nodes.add(identifier)
        elif element.tag == "way":
            if tags.get("highway") not in road_classes or tags.get("area") == "yes" or not _access(tags):
                continue
            refs = [int(node.get("ref")) for node in element.findall("nd")]
            if len(refs) < 2:
                continue
            if any(ref not in nodes for ref in refs):
                raise ValueError(f"Incomplete road way {identifier}")
            ways.append((identifier, refs, tags))
            references.update(set(refs))
        elif tags.get("type") == "restriction":
            if {"taxi", "motorcar", "motor_vehicle", "vehicle"} & {part.strip() for part in tags.get("except", "").split(";")}:
                continue
            members = [(m.get("role"), m.get("type"), int(m.get("ref"))) for m in element.findall("member")]
            incoming = [ref for role,kind,ref in members if role == "from" and kind == "way"]
            outgoing = [ref for role,kind,ref in members if role == "to" and kind == "way"]
            via_nodes = [ref for role,kind,ref in members if role == "via" and kind == "node"]
            via_ways = [ref for role,kind,ref in members if role == "via" and kind == "way"]
            restriction = tags.get("restriction:taxi", tags.get("restriction:motorcar", tags.get("restriction:motor_vehicle", tags.get("restriction", ""))))
            if (any(":conditional" in key for key in tags) or len(incoming) != 1 or len(outgoing) != 1
                    or not restriction.startswith(("no_", "only_")) or not (len(via_nodes) == 1 and not via_ways or via_ways and not via_nodes)):
                blocked_ways.update(incoming)
                continue
            rules.append((via_nodes[0] if via_nodes else None, incoming[0], outgoing[0], restriction, via_ways))

    keep = {node for node,count in references.items() if count > 1} | blocked_nodes
    keep.update(via for via,*_ in rules if via is not None)
    for _, refs, _ in ways:
        keep.update((refs[0], refs[-1]))
        # Closed ways and repeated interior nodes must retain their branches.
        keep.update(node for node,count in Counter(refs).items() if count > 1)
    keep.intersection_update(references)
    stats = {"version": VERSION, "source": source, "road_classes": list(road_classes),
             "source_geometry_nodes": len(references), "junction_nodes": len(keep),
             "segments": 0, "directed_segments": 0, "max_speed_mps": 0.0,
             "blocked_ways": len(blocked_ways), "restrictions": len(rules)}
    stats["no_uturn_ways"] = [way for way,_,tags in ways if tags.get("highway") in {"motorway","motorway_link"}
                              or tags.get("motorroad") == "yes" or tags.get("tunnel") == "yes"]
    stats["speed_defaults_kmh"] = DEFAULT_SPEED_KMH
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="intercity-", dir=output.parent) as temp:
        built = Path(temp) / "graph.sqlite"
        with sqlite3.connect(built) as db:
            db.executescript("""CREATE TABLE nodes(id INTEGER PRIMARY KEY,x REAL,y REAL);
                CREATE TABLE segments(id INTEGER PRIMARY KEY,a INTEGER,b INTEGER,way INTEGER,
                    highway TEXT,name TEXT,length REAL,forward_s REAL,reverse_s REAL,geometry BLOB);
                CREATE TABLE restrictions(via INTEGER,from_way INTEGER,to_way INTEGER,kind TEXT,via_ways TEXT);
                CREATE TABLE metadata(value TEXT);""")
            db.executemany("INSERT INTO nodes VALUES(?,?,?)", [(node,*nodes[node]) for node in sorted(keep)])
            db.executemany("INSERT INTO restrictions VALUES(?,?,?,?,?)", [(via,a,b,kind,json.dumps(chain)) for via,a,b,kind,chain in rules])
            for way, refs, tags in ways:
                if way in blocked_ways:
                    continue
                forward, reverse = _directions(tags)
                if not forward and not reverse:
                    continue
                first = 0
                for last in range(1,len(refs)):
                    if refs[last] not in keep:
                        continue
                    ids = refs[first:last+1]
                    points = [nodes[node] for node in ids]
                    first = last
                    if ids[0] in blocked_nodes or ids[-1] in blocked_nodes:
                        continue
                    length = sum(math.dist(a,b) for a,b in zip(points,points[1:]))
                    if length <= 0:
                        continue
                    speeds = [_speed(tags,direction,tags["highway"]) for direction in ("forward","backward")]
                    geometry = zlib.compress(struct.pack("<"+"d"*len(points)*2, *(coordinate for point in points for coordinate in point)))
                    db.execute("INSERT INTO segments(a,b,way,highway,name,length,forward_s,reverse_s,geometry) VALUES(?,?,?,?,?,?,?,?,?)",
                               (ids[0],ids[-1],way,tags["highway"],tags.get("name",tags.get("ref","")),length,
                                length/speeds[0] if forward else None,length/speeds[1] if reverse else None,geometry))
                    stats["segments"] += 1
                    stats["directed_segments"] += int(forward)+int(reverse)
                    stats["max_speed_mps"] = max(stats["max_speed_mps"],*speeds)
            if not stats["segments"]:
                raise ValueError("No usable major road segments")
            db.execute("DELETE FROM nodes WHERE id NOT IN (SELECT a FROM segments UNION SELECT b FROM segments)")
            stats["junction_nodes"] = db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            db.execute("INSERT INTO metadata VALUES(?)", (json.dumps(stats),))
        built.replace(output)
    return stats


def build_pbf(source, output, road_classes=ROAD_CLASSES):
    """Explicit offline operation, using the existing bundled/system osmium."""
    from pyproj import Transformer
    command = osmium_command()
    if command is None:
        raise RuntimeError("Building intercity data requires osmium-tool")
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve():
        raise ValueError("Output must not overwrite the source PBF")
    if not source.is_file():
        raise FileNotFoundError(source)
    if not road_classes or set(road_classes)-set(ROAD_CLASSES):
        raise ValueError("Unsupported backbone road classes")
    stamp = source.stat()
    with tempfile.TemporaryDirectory(prefix="intercity-source-") as temp:
        filtered = Path(temp) / "roads.pbf"
        staged = Path(temp) / "graph.sqlite"
        subprocess.run([command,"tags-filter",str(source),"w/highway="+",".join(road_classes),"r/type=restriction","-o",str(filtered)],
                       check=True,capture_output=True,timeout=1800)
        project = Transformer.from_crs("EPSG:4326","EPSG:3067",always_xy=True).transform
        with subprocess.Popen([command,"cat",str(filtered),"-f","osm"],stdout=subprocess.PIPE) as process:
            try:
                stats = build_xml(process.stdout,staged,project,road_classes,
                                  {"path":str(source.resolve()),"size":stamp.st_size,"mtime_ns":stamp.st_mtime_ns})
            except BaseException:
                process.kill()
                raise
            if process.wait() != 0:
                raise RuntimeError("osmium failed while reading major roads")
        current = source.stat()
        if (current.st_size,current.st_mtime_ns) != (stamp.st_size,stamp.st_mtime_ns):
            raise RuntimeError("Source PBF changed during preparation")
        output.parent.mkdir(parents=True,exist_ok=True)
        # Stage on the output filesystem so the final replacement stays atomic.
        with tempfile.TemporaryDirectory(prefix="intercity-publish-",dir=output.parent) as publication:
            import shutil
            ready = Path(publication)/"graph.sqlite"
            shutil.copyfile(staged,ready)
            ready.replace(output)
    return stats


@dataclass(frozen=True)
class IntercityRoute:
    start_node: int
    target_node: int
    segments: tuple  # (segment id, forward) in travel order
    points: tuple
    distance_m: float
    duration_s: float


class IntercityGraph:
    """Compact adjacency in memory; geometry remains on disk until requested."""
    def __init__(self, path):
        self.db = sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro",uri=True)
        try:
            self.metadata = json.loads(self.db.execute("SELECT value FROM metadata").fetchone()[0])
            if not isinstance(self.metadata,dict) or self.metadata.get("version") != VERSION:
                raise ValueError("Unsupported intercity graph version")
            self.nodes = {node:(x,y) for node,x,y in self.db.execute("SELECT * FROM nodes")}
            if not self.nodes or any(not all(math.isfinite(v) for v in point) for point in self.nodes.values()):
                raise ValueError("Invalid junction coordinates")
            self.edges = defaultdict(list)
            self.max_speed = 0.0
            for segment,a,b,way,length,forward,reverse in self.db.execute("SELECT id,a,b,way,length,forward_s,reverse_s FROM segments"):
                if a not in self.nodes or b not in self.nodes or not math.isfinite(length) or length <= 0:
                    raise ValueError("Invalid intercity segment")
                for start,end,seconds,direction in ((a,b,forward,True),(b,a,reverse,False)):
                    if seconds is not None:
                        if not math.isfinite(seconds) or seconds <= 0:
                            raise ValueError("Invalid segment travel time")
                        self.edges[start].append((end,segment,direction,seconds,way,length))
                        self.max_speed = max(self.max_speed,length/seconds)
            if self.max_speed <= 0:
                raise ValueError("No directed intercity edges")
            self.no_uturn_ways = set(self.metadata.get("no_uturn_ways",()))
            self.no_uturn_ways.update(row[0] for row in self.db.execute("SELECT way FROM segments WHERE highway IN ('motorway','motorway_link')"))
            self.rules = defaultdict(list)
            self.chains = []
            for via,a,b,kind,chain in self.db.execute("SELECT * FROM restrictions"):
                chain = json.loads(chain)
                if via is None:
                    self.chains.append(((a,*chain),b,kind))
                else:
                    self.rules[(via,a)].append((b,kind))
            self.history_limit = max((len(prefix) for prefix,_,_ in self.chains),default=1)
            self.prefixes = set()
            self.chain_rules = defaultdict(list)
            for prefix,to,kind in self.chains:
                for size in range(1,len(prefix)+1):
                    history = prefix[:size]
                    self.prefixes.add(history)
                    if kind.startswith("only_") or size == len(prefix):
                        self.chain_rules[history].append((prefix[size] if size < len(prefix) else to,kind,size == 1))
        except (sqlite3.Error,ValueError,TypeError,IndexError) as error:
            self.db.close()
            raise ValueError("Invalid intercity graph") from error

    def close(self):
        self.db.close()

    def connectivity(self):
        """Offline audit; not part of graph loading or route queries."""
        reverse = defaultdict(list)
        for node,edges in self.edges.items():
            for end,*_ in edges:
                reverse[end].append(node)
        visited,order = set(),[]
        for start in self.nodes:
            if start in visited:
                continue
            visited.add(start)
            stack = [(start,iter(edge[0] for edge in self.edges.get(start,())))]
            while stack:
                node,following = stack[-1]
                end = next(following,None)
                if end is None:
                    order.append(node)
                    stack.pop()
                elif end not in visited:
                    visited.add(end)
                    stack.append((end,iter(edge[0] for edge in self.edges.get(end,()))))
        visited,sizes,largest = set(),[],set()
        for start in reversed(order):
            if start in visited:
                continue
            stack,count,component = [start],0,set()
            visited.add(start)
            while stack:
                node = stack.pop()
                component.add(node)
                count += 1
                for end in reverse.get(node,()):
                    if end not in visited:
                        visited.add(end)
                        stack.append(end)
            sizes.append(count)
            if count > len(largest):
                largest = component
        self.largest_strong_component = largest
        visited,weak = set(),0
        for start in self.nodes:
            if start in visited:
                continue
            weak += 1
            stack = [start]
            visited.add(start)
            while stack:
                node = stack.pop()
                for end in [edge[0] for edge in self.edges.get(node,())]+reverse.get(node,[]):
                    if end not in visited:
                        visited.add(end)
                        stack.append(end)
        return {"weak_components":weak,"strong_components":len(sizes),"largest_strong_component_nodes":max(sizes,default=0)}

    def _allowed(self,state,following,end):
        node,incoming,previous,history = state
        if end == previous and incoming in self.no_uturn_ways:
            return False
        only = []
        rules = list(self.rules.get((node,incoming),()))
        if following == incoming and end == previous:
            if any(kind.startswith("only_") and expected != incoming
                   for size in range(1,len(history)+1) for expected,kind,_ in self.chain_rules.get(history[-size:],())):
                return False
        if following != incoming:
            outgoing = {edge[4] for edge in self.edges.get(node,())}
            for size in range(1,len(history)+1):
                for expected,kind,first in self.chain_rules.get(history[-size:],()):
                    if not first or expected in outgoing:
                        rules.append((expected,kind))
        for to,kind in rules:
            matches = following == to
            if to == incoming:
                matches = matches and ((end == previous) if "u_turn" in kind else end != previous)
            if kind.startswith("no_") and matches:
                return False
            if kind.startswith("only_"):
                only.append(matches)
        return not only or any(only)

    def route(self,start,target,*,deadline=None,cancelled=None,incoming=None,extent_m=None,allowed_ways=None):
        if start not in self.nodes or target not in self.nodes:
            return None
        if start == target:
            return IntercityRoute(start,target,(),(self.nodes[start],),0.0,0.0)
        initial = (start,*(incoming if incoming is not None else (None,None,())))
        costs,parents,queue = {initial:0.0},{},[(0.0,0,initial)]
        serial = 0
        expanded = 0
        while queue:
            expanded += 1
            if expanded % 256 == 1 and ((deadline is not None and time.perf_counter() > deadline)
                                      or (cancelled is not None and cancelled.is_set())):
                return None
            _,_,state = heapq.heappop(queue)
            node,way,previous,history = state
            if node == target:
                steps = []
                while state in parents:
                    state,edge = parents[state]
                    steps.append(edge)
                steps.reverse()
                points = []
                for segment,forward,_,_,_ in steps:
                    a,b,blob = self.db.execute("SELECT a,b,geometry FROM segments WHERE id=?",(segment,)).fetchone()
                    try:
                        raw = zlib.decompress(blob)
                    except zlib.error as error:
                        raise ValueError("Invalid intercity geometry compression") from error
                    if len(raw)%16 or len(raw)<32:
                        raise ValueError("Invalid intercity geometry")
                    geometry = list(struct.iter_unpack("<dd",raw))
                    if any(not all(math.isfinite(value) for value in point) for point in geometry):
                        raise ValueError("Invalid intercity geometry coordinates")
                    if math.dist(geometry[0],self.nodes[a]) > .01 or math.dist(geometry[-1],self.nodes[b]) > .01:
                        raise ValueError("Intercity geometry does not match source junctions")
                    if not forward:
                        geometry.reverse()
                    if points and math.dist(points[-1],geometry[0]) > 0.01:
                        raise ValueError("Disconnected route geometry")
                    points.extend(geometry[1:] if points else geometry)
                return IntercityRoute(start,target,tuple((e[0],e[1]) for e in steps),tuple(points),
                                      sum(e[4] for e in steps),sum(e[2] for e in steps))
            for end,segment,forward,seconds,following,length in self.edges.get(node,()):
                if allowed_ways is not None and following not in allowed_ways:
                    continue
                if extent_m is not None and math.dist(self.nodes[start],self.nodes[end]) > extent_m:
                    continue
                if not self._allowed(state,following,end):
                    continue
                following_history = history
                if following != way:
                    candidate = (*history,following)
                    following_history = next((candidate[-size:] for size in range(min(len(candidate),self.history_limit),0,-1)
                                              if candidate[-size:] in self.prefixes),())
                next_state = (end,following,node,following_history)
                cost = costs[state]+seconds
                if cost < costs.get(next_state,math.inf):
                    costs[next_state] = cost
                    parents[next_state] = (state,(segment,forward,seconds,following,length))
                    serial += 1
                    estimate = math.dist(self.nodes[end],self.nodes[target])/self.max_speed
                    heapq.heappush(queue,(cost+estimate,serial,next_state))
        return None
