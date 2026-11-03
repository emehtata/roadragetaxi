# RRT-021 scaling captures

Run `./.github/performance-analysis/rrt-021-simulation-performance-audit-data/run_scaling.sh` from the repository root. It uses the audit-only `rrt-019` harness with `--population-bands`; it does not override NPC counts or traffic demand.

Each raw JSON file contains 1,800 measured `SimulationServer.tick(1/30)` calls. Counts are sampled after the tick timer stops. Bands are `[target-5,target+5)` total NPC vehicles, including parked vehicles; moving means `abs(speed) > 0.5`. Tick durations and phase means are reported for each band.

| Capture | Location and time | Warm-up | Map (ways / buildings / parking) | Population bands observed |
|---|---|---:|---:|---|
| `raw/oulu_10.json` | Oulu suburb, 426700 / 7210140, noon | 1 tick | 4,503 / 1,467 / 741 | 10 band: 9–14; 20 band: 15–16 |
| `raw/oulu_20.json` | Oulu suburb, 426850 / 7210250, noon | 1 tick | 4,503 / 1,467 / 741 | 20 band: 21–24 |
| `raw/oulu_40_60.json` | Oulu center, 427960 / 7210718, 17:00 | 30 s | 8,687 / 2,586 / 1,699 | 40 band: 40–44; 60 band: 55–56 |
| `raw/helsinki_40_exploratory.json` | Helsinki, night | 15 s | 18,108 / 2,886 / 65 | Exploratory only; background map-worker startup failed and fallback loading took 87.6 s |

The 10/20 suburb captures share map and time but naturally differ in vehicle counts. The 40/60 bands come from a different location and rush-hour clock. Results therefore characterize these workloads, not a controlled cost-per-vehicle curve. The Helsinki capture is excluded from the Oulu comparison because its cold map load and fallback worker path added unrelated startup and memory pressure.
