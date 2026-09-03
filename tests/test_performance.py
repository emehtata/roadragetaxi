from theroadragetrip.performance import FrameProfiler


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
