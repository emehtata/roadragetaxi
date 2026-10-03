import time

import pytest

from theroadragetrip.performance import FrameProfiler, advance_chunked


def test_advance_chunked_processes_everything_across_multiple_calls():
    items = list(range(50))
    processed = []
    index = 0
    calls = 0
    while index < len(items):
        index = advance_chunked(items, index, 0.0, processed.append)
        calls += 1
        if calls > len(items):
            pytest.fail("advance_chunked made no forward progress")
    assert processed == items
    assert calls > 1, "a zero budget must force multiple calls, not finish in one"


def test_advance_chunked_finishes_in_one_call_with_a_generous_budget():
    items = list(range(50))
    processed = []
    index = advance_chunked(items, 0, 10.0, processed.append)
    assert index == len(items)
    assert processed == items


def test_advance_chunked_always_processes_at_least_one_item(monkeypatch):
    """A budget_s <= 0 (e.g. a stage that already overran an earlier
    sub-stage's shared deadline) must still make progress, never stall."""
    items = [1, 2, 3]
    processed = []
    index = advance_chunked(items, 0, -1.0, processed.append)
    assert index == 1
    assert processed == [1]


def test_frame_profiler_is_disabled_without_overhead_sections():
    profiler = FrameProfiler()
    profiler.begin_frame()
    with profiler.section("traffic"):
        pass
    profiler.end_frame()
    assert profiler.snapshot()["sections"] == {}


def test_frame_profiler_records_sections_and_spikes():
    profiler = FrameProfiler(spike_ms=(0.0,))
    profiler.enabled = True
    profiler.begin_frame()
    with profiler.section("traffic"):
        pass
    profiler.end_frame()
    snapshot = profiler.snapshot()
    assert snapshot["sections"]["traffic"] >= 0.0
    assert snapshot["spikes"] == 1
    profiler.set_metric("visible_npcs", 4)
    assert profiler.snapshot()["metrics"]["visible_npcs"] == 4
    assert profiler.snapshot()["last_spike"]["sections"]["traffic"] >= 0.0
    assert profiler.snapshot()["spike_subsystem"] == "traffic"
    profiler.record("rendering", 1.0)
    assert profiler.snapshot()["sections"]["rendering"] == 1.0
    profiler.record("collisions", 0.5)
    assert profiler.snapshot()["sections"]["collisions"] == 0.5


def test_end_frame_uses_real_frame_ms_when_given():
    """Regression: main()'s game loop is capped to 60fps by
    Clock.tick_busy_loop(FPS) - a frame whose actual work takes, say,
    5ms still spends another ~11.67ms paced/waiting before the next
    frame starts, so the real, displayed frame rate is always ~60fps.
    end_frame() used to measure only the work between begin_frame() and
    itself (perf_counter deltas), silently excluding that pacing wait -
    so the debug HUD's "FPS" reading (1000 / last_frame_ms) came out
    from work time alone and over-reported: confirmed via a real capped
    game loop, ~105fps displayed for an actual, real ~61fps game.
    end_frame(real_frame_ms=...) must use exactly the value passed
    (the loop's own Clock.tick_busy_loop() return value in production)
    instead of re-deriving a work-only figure."""
    profiler = FrameProfiler()
    profiler.enabled = True
    profiler.begin_frame()
    time.sleep(0.001)  # trivial work - real_frame_ms should still win
    profiler.end_frame(real_frame_ms=16.4)  # a realistic ~60fps-paced frame

    assert profiler.last_frame_ms == 16.4
    assert profiler.fps == pytest.approx(1000.0 / 16.4)


def test_advance_pairs_real_frame_ms_with_the_sections_recorded_before_it():
    """Regression: main()'s loop used to fetch raw_frame_ms, call
    begin_frame() (clearing sections), run the whole frame's work, and only
    then call end_frame(real_frame_ms=raw_frame_ms) - pairing a duration
    that describes the PREVIOUS iteration with sections describing the
    CURRENT one. advance() must end the frame using whatever was already
    recorded (from the previous begin_frame()/advance() onward), then start
    a fresh one - reproduced here with two simulated iterations."""
    profiler = FrameProfiler(spike_ms=(50.0,))
    profiler.enabled = True
    profiler.begin_frame()
    profiler.record("static_cache_rebuild", 152.0)  # heavy work during "frame 1"

    profiler.advance(real_frame_ms=208.0)  # frame 1 finishes; frame 2 begins
    assert profiler.history[-1] == 208.0
    assert profiler.sections == {}  # frame 2 starts clean
    assert profiler.last_spike["sections"] == {"static_cache_rebuild": 152.0}

    profiler.record("collisions", 2.0)  # frame 2's own, much lighter work
    profiler.advance(real_frame_ms=17.0)  # frame 2 finishes, under budget
    assert profiler.history[-1] == 17.0
    # frame 2's light work must not be blamed for frame 1's spike
    assert profiler.last_spike["sections"] == {"static_cache_rebuild": 152.0}


def test_end_frame_falls_back_to_work_time_without_real_frame_ms():
    """Callers with no pacing concept (most tests, and any caller that
    doesn't pass real_frame_ms) keep the previous work-time-only
    behavior - real_frame_ms is opt-in, not a breaking change."""
    profiler = FrameProfiler()
    profiler.enabled = True
    profiler.begin_frame()
    time.sleep(0.002)
    profiler.end_frame()

    assert profiler.last_frame_ms >= 2.0


def test_spike_culprit_prefers_detailed_render_section_over_parent_total():
    profiler = FrameProfiler(spike_ms=(25.0,))
    profiler.enabled = True
    profiler.begin_frame()
    profiler.record("rendering", 42.0)
    profiler.record("render:roads_cache_rebuild", 18.0)
    profiler.record("render:actors", 3.0)
    profiler.end_frame(real_frame_ms=45.0)

    snapshot = profiler.snapshot()
    assert snapshot["spike_subsystem"] == "render:roads_cache_rebuild"
    assert snapshot["spike_sections"][0] == ("render:roads_cache_rebuild", 18.0)


def test_incremental_static_rebuild_layers_share_one_frame_budget(monkeypatch):
    from theroadragetrip.render import common

    common._pending_incremental_rebuilds.clear()
    common.begin_static_cache_frame()
    monkeypatch.setattr(common.time, "perf_counter", lambda: 100.0)

    assert common._incremental_rebuild_deadline("scenery", False, 0.004) == 100.004
    assert common._incremental_rebuild_deadline("roads", False, 0.004) == 100.0
    assert common._incremental_rebuild_deadline("buildings", False, 0.004) == 100.0
    assert common._incremental_rebuild_deadline("roads", True, 0.004) == float("inf")
