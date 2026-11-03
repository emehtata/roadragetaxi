#!/usr/bin/env bash
set -euo pipefail

D=.github/performance-analysis/rrt-021-simulation-performance-audit-data
B=.github/performance-analysis/rrt-019-sim-audit-data/bench_sim.py
run() {
  name=$1; shift
  PYTHONPATH=src timeout 3600 .venv/bin/python "$B" "$@" --population-bands --out "$D/raw/$name.json"
}

# Natural population bands; no NPC count or traffic-demand overrides.
run oulu_10 --at 426700 7210140 --city Oulu --start-time 2026-10-23T12:00 --warmup 0.034 --seconds 60 --seed 1
run oulu_20 --at 426850 7210250 --city Oulu --start-time 2026-10-23T12:00 --warmup 0.034 --seconds 60 --seed 1
run oulu_40_60 --at 427960 7210718 --city Oulu --start-time 2026-10-23T17:00 --warmup 30 --seconds 60 --seed 1
