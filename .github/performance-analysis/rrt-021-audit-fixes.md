# Repository audit fixes, 2026-11-03

All seven findings from the repository audit have focused fixes and regression coverage.

| Finding | Change | Regression |
| --- | --- | --- |
| 1. Pause left the server driving | Godot sends neutral input and an explicit pause/resume message. Python freezes gameplay while continuing to accept commands and publish save acknowledgements. Godot keeps its connection polling while paused. Disconnect releases that connection's pause. | `test_pause_freezes_gameplay_but_processes_save_and_resume`, `godot/tests/audit_menu_safety.gd` |
| 2. Replacement deleted the old save during setup | Selecting a replacement leaves the file alone. `--new-save-slot` starts the server with a private staging file on the save filesystem. Homes and automatic saves use the staging file; its first successful complete save atomically replaces the chosen slot. Failed publication preserves the old bytes. | `test_replacement_keeps_old_slot_until_complete_new_save`, `godot/tests/audit_menu_safety.gd` |
| 3. Inner rebuilds received fresh budgets | Every budgeted sync rebuild receives the time remaining in the current tick, capped at its existing 4 ms slice. Completed grid stages also yield before the next rebuild. The deadline is checked after the chunk callback. | `test_tile_merge_and_real_grid_sync_share_one_tick_budget` uses the real grid stage: a 3 ms merge leaves 1 ms for it, totaling 4 ms. |
| 4. A rebuild error held streaming forever | The complete background job catches errors and returns a failure result. The tick schedules a retry after one second, preserving the dirty areas and holding further merges so the retry sees the same synced world. | `test_failed_fallback_reports_failure_and_retry_preserves_dirty_regions`, `test_tick_restarts_a_failed_map_build_after_backoff` |
| 5. Invalid saved fare fields crashed restoration | Dates, numeric meter fields, target coordinates and passenger values are checked before changing the manager. Invalid fares are rejected without partial mutation. Invalid slot clock/sort metadata is ignored. | `test_invalid_fare_is_rejected_before_changing_manager`, `test_invalid_slot_date_and_sort_value_do_not_break_listing` |
| 6. Incoming commands were unbounded | Connections reject lines over 16 MiB and queues over 256 decoded messages. The server consumes at most 64 messages per connection per tick, preserving order. | Incoming overflow and bounded-batch tests in `tests/test_slow_clients.py` |
| 7. Waiting for taxi roads consumed the sync slice | A pending taxi-road worker yields a distinct waiting marker; the tick returns immediately instead of polling repeatedly until its deadline. | `test_waiting_for_taxi_worker_returns_without_polling_until_deadline` |

## Verification

- 269 related Python tests passed, seed `3795091198`.
- After final validation and pause-test additions, 92 server/save/integration tests passed, seed `1573406744`; 37 focused map/transport/save tests passed, seed `4107535855`. These sets overlap.
- Godot's main suite passed 3,897 checks with an isolated user profile. The existing suite assumes English labels and failed four checks against the local saved-language profile; the isolated run passed without weakening assertions.
- The new menu regression passed headlessly and with rendering. Replacement and pause-menu screenshots were captured and inspected. Existing pause-save and home-interior checks passed; first-person checks covered 35 plans with zero failures.
- Python compile and Git whitespace checks passed.

## Connected map-growth workload

The existing harness completed a 180-second Oulu drive at 20 m/s, covering 3,559 m over 5,339 ticks. Map work was active in 58.3% of ticks. Tick median/p95/p99/maximum were 12.2/30.1/45.0/88.3 ms; 35 ticks exceeded 50 ms and none exceeded 100 ms. The client received 5,337 states, with p99/maximum gaps of 54.2/102 ms and one gap over 100 ms. Replay recorded no frozen frames or clock snaps, and 8.0% wrong-speed frames.

This was a functional workload check, run while correctness checks were also being completed. It is not a controlled before/after benchmark and establishes no overall speedup. The raw capture is in [the data directory](rrt-021-audit-fixes-data/map-growth.json.gz).

The frame deadline remains soft: an individual geometry operation cannot be interrupted halfway through. Background world decoding, object transfer and garbage collection still contend with simulation; the capture recorded 54 young collections over 10 ms. These fixes do not establish that all rubberbanding is eliminated. Persistent rebuild errors retry with their dirty areas retained and logged, rather than silently abandoning those areas.
