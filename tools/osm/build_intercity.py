#!/usr/bin/env python3
"""Prepare a major-road routing artifact offline; does not modify world caches."""
import argparse
import json
from pathlib import Path
import sys
import time
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"src"))
from theroadragetrip.intercity import ROAD_CLASSES, IntercityGraph, build_pbf
from theroadragetrip.intercity_places import prepare_gateways


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source",type=Path)
    parser.add_argument("output",type=Path)
    parser.add_argument("--road-classes",nargs="+",choices=ROAD_CLASSES,default=ROAD_CLASSES)
    parser.add_argument("--backbone-only",action="store_true",help="Skip town approaches; this artifact is not ready for fares")
    parser.add_argument("--town-connectors",type=Path,help="JSON object keyed by catalogue ID: classes, extent_m, max_length_m")
    args = parser.parse_args()
    started = time.perf_counter()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="intercity-tool-",dir=args.output.parent) as temp:
        staged = Path(temp)/"ready.sqlite"
        stats = build_pbf(args.source,staged,args.road_classes)
        if not args.backbone_only:
            policies = json.loads(args.town_connectors.read_text()) if args.town_connectors else None
            if policies is not None and not isinstance(policies,dict):
                parser.error("--town-connectors must contain a JSON object keyed by place ID")
            stats["gateways"] = prepare_gateways(args.source,staged,town_policies=policies)
        staged.replace(args.output)
    graph = IntercityGraph(args.output)
    try:
        for key in ("junction_nodes","segments","directed_segments","gateway_places","missing_gateway_places"):
            if key in graph.metadata:
                stats[key] = graph.metadata[key]
        stats.update(graph.connectivity())
    finally:
        graph.close()
    stats.update(build_seconds=round(time.perf_counter()-started,3),size_bytes=args.output.stat().st_size)
    print(json.dumps(stats,indent=2))


if __name__ == "__main__":
    main()
