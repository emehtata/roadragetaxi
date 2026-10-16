"""Budgeted, resumable work: a tick never stalls on one long rebuild."""
from __future__ import annotations

import gc
import sys
import time


# The map is ~1M long-lived, acyclic tracked objects: a full collection at the
# default thresholds takes 0.3-0.6 s holding the GIL - every thread stops, the
# tick too - and frees nothing (reference counting frees unloaded tiles). These
# keep young passes small and push full passes out to ~100M allocations
# (bin-loader-v10.md).
GC_THRESHOLDS = (10000, 10, 1000)
# A background map load or chunk rebuild hands the GIL back to the tick after
# 0.5 ms instead of the default 5 ms (osm-stream-00).
SWITCH_INTERVAL_S = 0.0005


def tune_interpreter() -> None:
    """The simulation server process's settings, before the world loads."""
    gc.set_threshold(*GC_THRESHOLDS)
    sys.setswitchinterval(SWITCH_INTERVAL_S)


# Per-tick wall-clock budget for one map-sync stage's chunked rebuild
# (bin-loader-v3.md): small enough that even a stacked worst case stays
# well under a 30 Hz tick.
MAP_SYNC_BUDGET_S = 0.004
# While the map under the player isn't there yet (a Home jump into an
# unloaded area) nothing on screen is worth the 4 ms cap: merge and sync
# may use most of a 30 Hz tick (33 ms) instead. Measured: ~1 s of sync
# work took 5-23 s of wall time at 4 ms per tick.
MAP_SYNC_URGENT_BUDGET_S = 0.020


def advance_chunked(items, index: int, budget_s: float, process_item) -> int:
    """Call process_item(item) for items[index:], stopping once budget_s
    has elapsed. Returns the new index - equal to len(items) once every
    item has been processed. Always processes at least one item (even
    with budget_s <= 0) so a chunked rebuild always makes forward
    progress, for any "clear and rebuild from a
    fixed item list" pass (bin-loader-v3.md) - the caller owns whatever
    process_item accumulates into, and decides when/whether to commit it
    as the new live result once index reaches len(items)."""
    deadline = time.perf_counter() + budget_s
    n = len(items)
    while index < n:
        process_item(items[index])
        index += 1
        if time.perf_counter() >= deadline:
            break
    return index
