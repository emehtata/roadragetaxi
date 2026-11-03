# RRT-021 optimization captures

See [the implementation and results report](../rrt-021-simulation-optimization.md).

`run_comparison.sh /path/to/14803040-checkout` runs two sequential Oulu rush-hour captures per version, the optimized suburb captures, the connected map-growth drive and a route-step diagnostic. Both versions use the current audit harness and the same virtual environment. The script checks that stationary captures contain 1,800 ticks and that recorded means reconcile with their raw samples. It writes uncompressed JSON; the checked-in raw captures are gzip-compressed to keep them small.

`results.json` contains all capture summaries without the large per-tick arrays. Each `*.json.gz` retains the complete original JSON, including every stationary tick. Tick `wall`, `cpu` and inclusive `sec` phase timings are in seconds; summary timings are milliseconds. Inclusive parent and child phases must not be added together. Vehicle counts include parked NPCs; moving means `abs(speed) > 0.5`.

- `before-1` / `before-2`: unchanged production source at `14803040`.
- `after-1` / `after-2`: final optimized source, 30 seconds warm-up and 60 seconds measured.
- `after-10` / `after-20`: final optimized suburb scenarios, one warm-up tick and 60 seconds measured.
- `route-diagnostic-before-transit`: intermediate optimized source before slicing the synchronous transit fallback; diagnostic probe enabled.
- `route-diagnostic`: final source with the diagnostic probe; excluded from the unprofiled timing comparison because it adds overhead.
- `map-growth`: final source, real socket client, 180-second drive with map streaming.
- `profiles.txt`: exploratory cProfile attribution used to select the changes; not a controlled timing comparison.
- `verification.txt`: correctness checks and capture consistency checks.

Live timer budgets influence trip progress and spawn timing, so these seeded runs do not have identical entity histories. The report includes actual populations and distinguishes stationary timing from connected-client delivery.
