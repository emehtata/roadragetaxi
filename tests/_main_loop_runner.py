"""Helper script run as a subprocess by test_main_loop.py.

Each characterization test needs its own fresh pygame session: main() calls
pygame.quit() unconditionally at the end, and several render/ submodules
cache lazily-created Font/Surface objects at module scope for the life of the
process. Reusing those cached objects across a pygame.quit() -> pygame.init()
cycle in the same process is unsafe (observed as a hard SDL segfault when two
main() calls ran back-to-back in one pytest process). Real players only ever
call main() once per process, so running each test's main() call in its own
subprocess is both the fix and the more faithful characterization.

Usage: python _main_loop_runner.py <path-to-json-spec>

The spec is a JSON object:
  {
    "sandbox_dir": "<absolute path main()'s file I/O should be sandboxed to>",
    "argv_extra": ["--some-flag", ...],
    "event_frames": [[<pygame key constant>, ...], ...],
    "startup_padding": <int>
  }
"""
import json
import sys
from pathlib import Path

import pygame


def main() -> None:
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    sandbox_dir = Path(spec["sandbox_dir"])

    import theroadragetrip.main  # noqa: F401 - populates sys.modules["theroadragetrip.main"]
    from theroadragetrip import config as config_module
    from theroadragetrip import osm as osm_module

    main_module = sys.modules["theroadragetrip.main"]

    config_path = sandbox_dir / "roadragetrip.ini"
    config = config_module.load_config(config_path)
    config.set("game", "language", "en")
    config.set("traffic", "pedestrian_count", "2")
    config_module.save_config(config, config_path)

    main_module.CONFIG_PATH = config_path
    main_module.load_config = lambda: config_module.load_config(config_path)
    main_module.save_config = lambda cfg, path=config_path: config_module.save_config(cfg, path)
    osm_module.CACHE_DIR = str(sandbox_dir / "osm_cache")

    sys.argv = [
        "road_rage_trip.py", "--use-sample", "--no-menu", "--log-level", "WARNING",
        *spec["argv_extra"],
    ]

    class ScriptedEvents:
        def __init__(self, frames, startup_padding, hard_cap=600):
            self._script = [[]] * startup_padding + [list(frame) for frame in frames]
            self._index = 0
            self._calls = 0
            self.hard_cap = hard_cap

        def __call__(self):
            self._calls += 1
            if self._calls > self.hard_cap or self._index >= len(self._script):
                return [pygame.event.Event(pygame.QUIT)]
            keys = self._script[self._index]
            self._index += 1
            return [pygame.event.Event(pygame.KEYDOWN, {"key": key, "unicode": ""}) for key in keys]

    pygame.event.get = ScriptedEvents(spec["event_frames"], spec["startup_padding"])

    # main()'s gameplay loop paces frames to real wall-clock time via
    # clock.tick_busy_loop(FPS) and won't accept input for the first ~1.5s
    # ("awaiting_start" warm-up, dismissed by the first keydown once past
    # it). pygame.time.Clock is an immutable C type, so its methods can't be
    # patched directly; replace the name itself with a fake before main()
    # constructs its Clock. Faking a fixed 100ms-per-frame pace (dt is
    # clamped to 0.1s elsewhere in main() as its own lag-spike safety cap,
    # so this is a code path the game is already designed to handle) clears
    # the warm-up in a deterministic ~15 frames instead of ~90 real-paced
    # ones, and makes the whole test run without waiting on wall-clock time.
    class _FakeClock:
        def tick(self, fps=0):
            return 100

        def tick_busy_loop(self, fps=0):
            return 100

        def get_fps(self):
            return 10.0

    pygame.time.Clock = _FakeClock

    import os
    os.chdir(sandbox_dir)

    main_module.main()


if __name__ == "__main__":
    main()
