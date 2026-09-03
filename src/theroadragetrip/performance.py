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

    def end_frame(self) -> None:
        if not self.enabled:
            return
        self.last_frame_ms = (time.perf_counter() - self._frame_start) * 1000.0
        self.history.append(self.last_frame_ms)
        if any(self.last_frame_ms >= threshold for threshold in self.spike_ms):
            self.spike_count += 1
            self.last_spike = {
                "frame_ms": self.last_frame_ms,
                "sections": dict(self.sections),
            }

    def set_metric(self, name: str, value: int | float) -> None:
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
        return {
            "frame_ms": self.last_frame_ms,
            "fps": self.fps,
            "sections": dict(self.sections),
            "metrics": dict(self.metrics),
            "spikes": self.spike_count,
            "last_spike": self.last_spike,
        }
