"""One background planner for the player's intercity leg, not NPC traffic."""
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor
import logging
import math
import threading
import time

from .intercity import IntercityGraph
from .geo import dist_point_to_segment
from .traffic_world import graph_route_steps, run_route_steps

logger = logging.getLogger(__name__)


class IntercityPlanner:
    def __init__(self, path):
        self.path = path
        self.executor = ThreadPoolExecutor(max_workers=1,thread_name_prefix="intercity")
        self.graph = None  # SQLite and the cache belong exclusively to the worker.
        self.cache = OrderedDict()
        self.cancelled = threading.Event()
        self.closed = False

    def request(self, start, target_id, snapshot, layer=None, ways=()):
        self.cancelled.set()
        self.cancelled = threading.Event()
        return self.executor.submit(self._plan,start,target_id,snapshot,layer,ways,self.cancelled)

    def cancel(self):
        self.cancelled.set()

    def close(self):
        if not self.closed:
            self.closed = True
            self.cancel()
            self.executor.submit(self._close_graph)
            self.executor.shutdown(wait=False)

    def _close_graph(self):
        if self.graph:
            self.graph.close()

    def _plan(self,start,target_id,snapshot,layer,ways,cancelled):
        from .navigation_route import simplify_polyline
        if cancelled.is_set():
            return None
        if self.graph is None:
            self.graph = IntercityGraph(self.path)
            self.grid = defaultdict(list)
            for node,(x,y) in self.graph.nodes.items():
                self.grid[(int(x//1000),int(y//1000))].append(node)
        graph = self.graph
        loaded = {way.osm_id:way for way in ways if getattr(way,"osm_id",None) is not None}
        destination = graph.db.execute("SELECT anchor FROM places WHERE id=?",(target_id,)).fetchone()
        if not destination:
            return None
        target = destination[0]
        deadline = time.perf_counter()+10
        x,y = start
        candidates = sorted((node for gx in range(int(x//1000)-3,int(x//1000)+4)
                             for gy in range(int(y//1000)-3,int(y//1000)+4) for node in self.grid.get((gx,gy),())
                             if math.dist(start,graph.nodes[node]) <= 3000),key=lambda node:math.dist(start,graph.nodes[node]))[:16]
        for origin in candidates:
            if cancelled.is_set() or time.perf_counter() > deadline:
                return None
            point = graph.nodes[origin]
            incident = graph.db.execute("SELECT way FROM segments WHERE a=? OR b=?",(origin,origin)).fetchall()
            matching = [loaded[way] for (way,) in incident if way in loaded
                        and any(dist_point_to_segment(*point,*a,*b) <= .25
                                for a,b in zip(loaded[way].points_m,loaded[way].points_m[1:]))]
            if not matching:
                continue
            departure = run_route_steps(graph_route_steps(snapshot,start,point,on_road=True,start_layer=layer,strict=True,
                target_layer=matching[0].layer),deadline)
            if not departure:
                continue
            incoming = self._entry(graph,origin,departure,matching)
            if incoming is None:
                continue
            key = (graph.metadata["version"],origin,target,incoming)
            if key not in self.cache:
                self.cache[key] = graph.route(origin,target,deadline=deadline,cancelled=cancelled,incoming=incoming)
                if cancelled.is_set() or time.perf_counter() > deadline:
                    self.cache.pop(key,None)
                    return None
                if len(self.cache) > 64:
                    self.cache.popitem(last=False)
            self.cache.move_to_end(key)
            route = self.cache[key]
            if route is None:
                continue
            points = simplify_polyline([*departure,*route.points[1:]],1.0)
            remaining = [0.0]*len(points)
            for i in range(len(points)-2,-1,-1):
                remaining[i] = remaining[i+1]+math.dist(points[i],points[i+1])
            return {"points":points,"remaining":remaining,"origin":origin,"target":target,"place_id":target_id,
                    "version":graph.metadata["version"],"segments":route.segments,
                    "distance_m":route.distance_m+sum(math.dist(a,b) for a,b in zip(departure,departure[1:])),
                    "duration_s":route.duration_s}
        logger.info("No loaded legal departure to intercity destination %s",target_id)
        return None

    @staticmethod
    def _entry(graph,origin,departure,ways):
        """Carry the actual approach way into national turn-restriction state."""
        from .geo import dist_point_to_segment
        end = graph.nodes[origin]
        previous_point = next((p for p in reversed(departure[:-1]) if math.dist(p,end) > .25),None)
        if previous_point is None:
            return (None,None,())
        approach = math.atan2(end[1]-previous_point[1],end[0]-previous_point[0])
        for way in ways:
            for a,b in zip(way.points_m,way.points_m[1:]):
                if dist_point_to_segment(*end,*a,*b) > .25 or dist_point_to_segment(*previous_point,*a,*b) > 3:
                    continue
                direction = math.atan2(b[1]-a[1],b[0]-a[0])
                aligned = math.cos(direction-approach)
                if abs(aligned) < .95 or (way.oneway == 1 and aligned < 0) or (way.oneway == -1 and aligned > 0):
                    continue
                identity = way.osm_id
                # A local leg cannot prove the preceding history of a via-way restriction.
                if any(identity in prefix[1:] for prefix,_,_ in graph.chains):
                    continue
                before = None
                for node,_,_,_,edge_way,_ in graph.edges.get(origin,()):
                    if edge_way != identity:
                        continue
                    angle = math.atan2(end[1]-graph.nodes[node][1],end[0]-graph.nodes[node][0])
                    if math.cos(angle-approach) > .95:
                        before = node
                        break
                history = (identity,) if (identity,) in graph.prefixes else ()
                return identity,before,history
        return None
