# Evidence: ten-minute NPC traffic observation

Runtime source: `b885d0b619e324522bb63fe0b8640055f7cbd2f1`.
2026-10-15 06:09:49–06:19:49 UTC; actual wall duration 600.023 seconds.
See [the plan](../npc-traffic-safety-2026-10-15.md) for conclusions and limits.

- `summary.json`: complete run metadata, sampled state/recovery counts,
  low-progress flags, half-minute population checkpoints and tick distribution.
- `incidents.jsonl`: both actual collision callbacks, with pre-response poses,
  endpoint overlaps, nearby obstacles and five-second sampled histories.
- `client-episodes.json`: 139 sampled two-metre/30-second low-displacement
  episodes from the read-only client. Parked visits/activities are included:
  this is not a list of confirmed deadlocks. `last_s` for the collector includes
  socket shutdown; individual episodes end with their last state sample.
- `readonly_client.py`: diagnostic local socket reader; sends no commands.
- `probes.py`, `probes-results.json`: six small reproductions of current defects.
  Their assertions document the *unfixed baseline*, not legal compliance;
  replace/invert them as the corresponding planned fixes land.

The full 406-frame gzip trace and ordinary server log remain locally under
`/tmp/rrt-traffic-observation-2026-10-15`; only collision histories and episode
summaries are committed. No runtime source, player save or settings file was
edited. Diagnostic scripts set the test weather and stationary-player fixture
in memory. No graphical client or rendered-FPS measurement was used.

Reproduce from the repository root (inspect the local PBF path in the observer
before running on another machine):

```sh
PYTHONPATH=src .venv/bin/python tools/observe_npc_traffic.py --self-test
PYTHONPATH=src .venv/bin/python tools/observe_npc_traffic.py --seconds 600 --out /tmp/rrt-traffic-observation-2026-10-15
```

Optionally, in another terminal after `metadata.json` appears:

```sh
.venv/bin/python .github/performance-analysis/npc-traffic-safety-2026-10-15-data/readonly_client.py /tmp/rrt-traffic-observation-2026-10-15
PYTHONPATH=src .venv/bin/python .github/performance-analysis/npc-traffic-safety-2026-10-15-data/probes.py
PYTHONPATH=src .venv/bin/python -m pytest tests/test_crossing_priority.py tests/test_npc_population.py tests/test_pedestrians.py -q
```

Use a fresh output directory for each observation: incident JSONL appends for
crash resilience. No observer is installed into the simulation. It listens on
localhost and uses the existing local map/cache; it does not clear/download maps.
The reader's exact join time changes the sampled episodes. Physical ticks are
fixed-step, paced at 30 Hz; OS scheduling and slow ticks account for wall versus
simulated-time difference. Seeded randomness cannot remove route-budget timing
variation. The read-only client adds serialization overhead after it joins.
