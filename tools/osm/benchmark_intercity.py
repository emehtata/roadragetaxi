#!/usr/bin/env python3
"""Benchmark town approaches or explicit graph-node pairs and validate continuity."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"src"))
from theroadragetrip.intercity import IntercityGraph


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph",type=Path)
    parser.add_argument("--pair",nargs=3,action="append",default=[],metavar=("LABEL","START_NODE","END_NODE"))
    parser.add_argument("--town-pair",nargs=2,action="append",default=[],metavar=("ORIGIN","DESTINATION"))
    parser.add_argument("--repeat",type=int,default=2)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be positive")
    started = time.perf_counter()
    graph = IntercityGraph(args.graph)
    for origin,destination in args.town_pair:
        nodes = []
        for name in (origin,destination):
            matches = graph.db.execute("SELECT anchor FROM places WHERE kind IS NULL AND name=? COLLATE NOCASE",(name,)).fetchall()
            if len(matches) != 1:
                parser.error(f"Town {name!r} has no unique supported gateway; use explicit IDs")
            nodes.append(matches[0][0])
        args.pair.append((origin+"–"+destination,*nodes))
    if not args.pair:
        parser.error("Supply --pair or --town-pair")
    report = {"load_seconds":time.perf_counter()-started,"size_bytes":args.graph.stat().st_size,"routes":[]}
    try:
        for label,start,target in args.pair:
            for repeat in range(args.repeat):
                started = time.perf_counter()
                route = graph.route(int(start),int(target))
                result = {"label":label,"repeat":repeat,"seconds":time.perf_counter()-started,"reachable":route is not None}
                if route is not None:
                    node = int(start)
                    for segment,forward in route.segments:
                        a,b = graph.db.execute("SELECT a,b FROM segments WHERE id=?",(segment,)).fetchone()
                        assert node == (a if forward else b), "Disconnected segment sequence"
                        node = b if forward else a
                    assert node == int(target), "Route did not reach the requested graph node"
                    result.update(distance_m=route.distance_m,duration_s=route.duration_s,
                                  segments=len(route.segments),geometry_points=len(route.points))
                report["routes"].append(result)
    finally:
        graph.close()
    print(json.dumps(report,indent=2))


if __name__ == "__main__":
    main()
