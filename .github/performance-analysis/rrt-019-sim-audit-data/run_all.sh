#!/usr/bin/env bash
# The rrt-019 audit's scenario matrix, run one after another (no CPU sharing).
# From the repo root: bash .github/performance-analysis/rrt-019-sim-audit-data/run_all.sh [name-filter]
set -u
D=.github/performance-analysis/rrt-019-sim-audit-data
OULU="--at 427960 7210718 --city Oulu"
HKI="--at 385586 6672019 --city Helsinki"
RURAL="--at 395090 7176285 --city Oulu"
run() {
  name=$1; shift
  [[ -n "${FILTER:-}" && "$name" != *$FILTER* ]] && return
  echo "== $name $*"
  PYTHONPATH=src timeout 3600 .venv/bin/python $D/bench_sim.py "$@" --out $D/raw/$name.json > $D/raw/$name.log 2>&1 || echo "FAILED $name"
}
FILTER=${1:-}
run oulu_center_17_s2   $OULU --start-time 2026-10-23T17:00 --warmup 60 --seconds 120 --seed 2
run oulu_center_17_s3   $OULU --start-time 2026-10-23T17:00 --warmup 60 --seconds 120 --seed 3
run oulu_center_02      $OULU --start-time 2026-10-24T02:00 --warmup 60 --seconds 120 --seed 1
run oulu_center_17_zoom $OULU --start-time 2026-10-23T17:00 --warmup 60 --seconds 120 --seed 1 --view 426 240
run oulu_center_17_drive $OULU --start-time 2026-10-23T17:00 --warmup 30 --seconds 60 --seed 1 --speed 12 --heading 0 --box-km 4
run oulu_center_17_fare $OULU --start-time 2026-10-23T17:00 --warmup 60 --seconds 120 --seed 1 --fare
run rural_02            $RURAL --start-time 2026-10-24T02:00 --warmup 60 --seconds 120 --seed 1
run rural_12            $RURAL --start-time 2026-10-23T12:00 --warmup 60 --seconds 120 --seed 1
run hki_center_17       $HKI --start-time 2026-10-23T17:00 --warmup 60 --seconds 120 --seed 1
run hki_center_17_zoom  $HKI --start-time 2026-10-23T17:00 --warmup 60 --seconds 120 --seed 1 --view 426 240
run oulu_long_17        $OULU --start-time 2026-10-23T17:00 --warmup 30 --seconds 900 --seed 1
echo ALL DONE
