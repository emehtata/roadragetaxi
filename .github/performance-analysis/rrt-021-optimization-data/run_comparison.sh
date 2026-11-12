#!/usr/bin/env bash
set -euo pipefail

# Pass a checkout of 14803040; both versions use the same current audit harness.
baseline=${1:?usage: run_comparison.sh /path/to/baseline-checkout}
data=.github/performance-analysis/rrt-021-optimization-data
bench=.github/performance-analysis/rrt-019-sim-audit-data/bench_sim.py
for repeat in 1 2; do
  for version in before after; do
    source_root=src
    if [[ $version == before ]]; then source_root=$baseline/src; fi
    PYTHONPATH=$source_root .venv/bin/python "$bench" --at 427960 7210718 --city Oulu \
      --start-time 2026-10-23T17:00 --warmup 30 --seconds 60 --seed 1 --population-bands \
      --out "$data/$version-$repeat.json" > "/tmp/rrt021-$version-$repeat.log" 2>&1
  done
done
PYTHONPATH=src .venv/bin/python "$bench" --at 426700 7210140 --city Oulu \
  --start-time 2026-10-23T12:00 --warmup 0.034 --seconds 60 --seed 1 --population-bands \
  --out "$data/after-10.json" > /tmp/rrt021-after-10.log 2>&1
PYTHONPATH=src .venv/bin/python "$bench" --at 426850 7210250 --city Oulu \
  --start-time 2026-10-23T12:00 --warmup 0.034 --seconds 60 --seed 1 --population-bands \
  --out "$data/after-20.json" > /tmp/rrt021-after-20.log 2>&1
PYTHONPATH=src .venv/bin/python tools/bench_map_jitter.py --preset Oulu --osm-source overpass \
  --drive-s 180 --json "$data/map-growth.json" > /tmp/rrt021-map-growth.log 2>&1
PYTHONPATH=src .venv/bin/python "$bench" --at 427960 7210718 --city Oulu \
  --start-time 2026-10-23T17:00 --warmup 30 --seconds 60 --seed 1 --population-bands --route-steps \
  --out "$data/route-diagnostic.json" > /tmp/rrt021-route-diagnostic.log 2>&1
.venv/bin/python - <<'PY'
import json
from pathlib import Path

data = Path('.github/performance-analysis/rrt-021-optimization-data')
for name in ('before-1', 'before-2', 'after-1', 'after-2', 'after-10', 'after-20', 'route-diagnostic'):
    capture = json.loads((data / (name + '.json')).read_text())
    assert capture['ticks'] == len(capture['tick_samples']) == 1800, name
    assert abs(capture['wall_mean_ms'] - 1000 * sum(t['wall'] for t in capture['tick_samples']) / 1800) < 1e-6, name
assert json.loads((data / 'map-growth.json').read_text())['client']['states'] > 0
PY
