"""Budgeted, resumable work: a tick never stalls on one long rebuild."""
from __future__ import annotations

import gc
import math
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


class CollectorSchedule:
    """Cyclic GC kept out of the map sync, every cycle still collected.

    Measured: a collection over the sync's new graphs takes 20-116 ms whether
    it runs inside a tick or between ticks (both stop the tick loop: tick
    starts 133 ms apart). So the sync runs with the collector off
    (begin_sync; the server's chunk rebuild too: a 48-54 ms collection on its
    thread held the GIL against the tick), and its result is frozen at the end (end_sync): the next
    young passes skip it. Outside syncs collection is automatic, as tuned.
    Frozen objects are not lost to the collector: while no one is playing
    (idle) after_tick() unfreezes and runs a full pass, at most once a minute,
    so a cycle made during a sync is collected at the next pause."""

    FULL_EVERY_S = 60.0  # at most one full pass a minute while idle

    def __init__(self) -> None:
        self.full_passes = 0
        self._last_full = -math.inf
        self._holders = 0  # a map sync and the chunk rebuild it starts overlap: off until both end

    def begin_sync(self) -> None:
        self._holders += 1
        gc.disable()

    def end_sync(self) -> None:
        if self._holders > 0:
            self._holders -= 1
            if self._holders == 0:
                gc.freeze()
                gc.enable()

    def after_tick(self, idle: bool, now: float) -> None:
        if idle and self._holders == 0 and now - self._last_full >= self.FULL_EVERY_S:
            self._last_full = now
            self.full_passes += 1
            gc.unfreeze()
            gc.collect()


class Graveyard:
    """Replaced big structures (a whole route graph, its grids), freed in
    budgeted steps on the tick instead of all at once where they are
    replaced: dropping the last reference to one deallocated ~1e5 objects
    (9-16 ms in a sync slice). An object another holder still uses (a
    route job's graph) is only let go, never dismantled."""

    STEP_ITEMS = 2000

    def __init__(self) -> None:
        self._items: list = []

    def bury(self, *objects) -> None:
        self._items.extend(obj for obj in objects if obj is not None)

    def dig(self, budget_s: float) -> None:
        deadline = time.perf_counter() + budget_s
        first = True
        while self._items and (first or time.perf_counter() < deadline):
            first = False
            obj = self._items[-1]
            if sys.getrefcount(obj) > 3:  # this list, `obj`, the call's argument: anyone else still holds it
                self._items.pop()
            elif isinstance(obj, dict) and obj:
                for _ in range(min(self.STEP_ITEMS, len(obj))):
                    obj.popitem()
            elif isinstance(obj, list) and obj:
                del obj[-self.STEP_ITEMS:]
            elif isinstance(obj, set) and obj:
                for _ in range(min(self.STEP_ITEMS, len(obj))):
                    obj.pop()
            elif not isinstance(obj, (dict, list, set)) and hasattr(obj, "__dict__") and vars(obj):
                self._items.pop()
                attributes = vars(obj)
                self._items.extend(value for value in attributes.values() if isinstance(value, (dict, list, set)))
                attributes.clear()
            else:
                self._items.pop()


GRAVEYARD = Graveyard()  # the simulation thread's: bury where replaced, dig once a tick


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
