"""Low-overhead frame timing for interactive performance diagnosis."""
from __future__ import annotations

import time
from collections import deque
from contextlib import contextmanager
from typing import Iterator


class FrameProfiler:
    def __init__(self, history_size: int = 120, spike_ms: tuple[float, ...] = (25.0, 50.0, 100.0)):
        self.enabled = False
        self.history = deque(maxlen=history_size)
        self.spike_ms = spike_ms
        self.sections: dict[str, float] = {}
        self.metrics: dict[str, int | float] = {}
        self.last_frame_ms = 0.0
        self.spike_count = 0
        self.last_spike: dict[str, object] | None = None
        self._frame_start = 0.0

    def toggle(self) -> bool:
        self.enabled = not self.enabled
        return self.enabled

    def begin_frame(self) -> None:
        if self.enabled:
            self.sections.clear()
            self._frame_start = time.perf_counter()

    def end_frame(self, real_frame_ms: float | None = None) -> None:
        """`real_frame_ms`, when given, is the actual wall-clock duration
        of this frame's *whole* loop iteration (e.g. Clock.tick_busy_loop()'s
        own return value) - including the pacing wait that throttles to
        the target FPS, not just the work measured between begin_frame()
        and here. Without it, a capped game (a real, ~60fps-paced frame)
        reports FPS from work time alone, which excludes that wait and so
        over-reports - e.g. 8ms of work on a 60fps-capped frame reads as
        "125 FPS" even though only 60 real frames are ever displayed a
        second. Callers that drive a real paced loop should pass it;
        callers with no pacing concept (most tests) can omit it and get
        the previous work-time-only behavior."""
        if not self.enabled:
            return
        work_ms = (time.perf_counter() - self._frame_start) * 1000.0
        self.last_frame_ms = real_frame_ms if real_frame_ms is not None else work_ms
        self.history.append(self.last_frame_ms)
        if any(self.last_frame_ms >= threshold for threshold in self.spike_ms):
            self.spike_count += 1
            self.last_spike = {
                "frame_ms": self.last_frame_ms,
                "sections": dict(self.sections),
            }

    def advance(self, real_frame_ms: float | None = None) -> None:
        """End the frame whose sections/metrics are already recorded, then
        immediately start the next one.

        `real_frame_ms` (typically Clock.tick_busy_loop()'s return value)
        describes the iteration that just finished - the one whose
        section() / record() calls already populated self.sections - not
        the iteration about to start. Call this once per loop iteration as
        soon as that duration is known (right after fetching it, before any
        of this iteration's own work), not at the bottom of the iteration:
        calling end_frame() there pairs the just-fetched duration with the
        CURRENT (about-to-begin) iteration's sections instead, which is a
        real, previously-shipped bug - a frame's displayed spike/section
        breakdown (last_spike, spike_subsystem) was silently the *next*
        frame's work, not the one that actually took that long. Confirmed
        against a real profiled drive: a 208ms outlier frame's own sections
        totaled ~18ms of ordinary work, while the *next* recorded frame's
        sections held a 152ms static-cache rebuild - the real cause,
        misattributed one frame later."""
        self.end_frame(real_frame_ms=real_frame_ms)
        self.begin_frame()

    def set_metric(self, name: str, value: object) -> None:
        if self.enabled:
            self.metrics[name] = value

    def record(self, name: str, milliseconds: float) -> None:
        if self.enabled:
            self.sections[name] = self.sections.get(name, 0.0) + milliseconds

    @contextmanager
    def section(self, name: str) -> Iterator[None]:
        if not self.enabled:
            yield
            return
        started = time.perf_counter()
        try:
            yield
        finally:
            self.sections[name] = self.sections.get(name, 0.0) + (
                time.perf_counter() - started
            ) * 1000.0

    @property
    def fps(self) -> float:
        return 1000.0 / self.last_frame_ms if self.last_frame_ms > 0.0 else 0.0

    def snapshot(self) -> dict[str, object]:
        average_ms = sum(self.history) / len(self.history) if self.history else 0.0
        spike_sections = (
            sorted(self.last_spike["sections"].items(), key=lambda item: -item[1])
            if self.last_spike
            else []
        )
        return {
            "frame_ms": self.last_frame_ms,
            "average_ms": average_ms,
            "fps": self.fps,
            "sections": dict(self.sections),
            "metrics": dict(self.metrics),
            "spikes": self.spike_count,
            "last_spike": self.last_spike,
            "spike_subsystem": spike_sections[0][0] if spike_sections else None,
        }
