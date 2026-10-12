"""Budgeted, resumable work: a tick never stalls on one long rebuild."""
from __future__ import annotations

import time


# Per-tick wall-clock budget for one map-sync stage's chunked rebuild
# (bin-loader-v3.md): small enough that even a stacked worst case stays
# well under a 30 Hz tick.
MAP_SYNC_BUDGET_S = 0.004


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
