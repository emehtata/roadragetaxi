"""Characterization tests for theroadragetrip.main.main().

main() is a single, ~1850-line function with no return value and almost no
existing test coverage: it owns pygame setup, config/career file I/O, world
loading, and the whole per-frame game loop inline. These tests exist to pin
down its observable, black-box behavior (does it run without crashing under
various input sequences, does it write the state files it's supposed to)
*before* main() is decomposed into smaller pieces, so a future refactor has
something to run against.

Each test runs the real main() headlessly (SDL_VIDEODRIVER=dummy) in its own
subprocess via _main_loop_runner.py, with `--use-sample --no-menu` (skips
the city/mode selection menus and any real network access) and a scripted
pygame.event.get() replacement that drives specific key sequences. A
subprocess per test is used deliberately: main() calls pygame.quit()
unconditionally at the end, and several render/ submodules cache lazily
created Font/Surface objects at module scope for the life of the process;
reusing those across a pygame.quit() -> pygame.init() cycle in the same
process segfaults. Real players only ever call main() once per process, so
this also makes each test a more faithful reproduction of an actual run.
The scripted event queue always terminates within a bounded number of calls
(it starts returning QUIT once its script is exhausted), so a test can never
hang even if a scripted key sequence doesn't behave as expected.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pygame
import pytest

RUNNER = Path(__file__).with_name("_main_loop_runner.py")
REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"


def _run_main(tmp_path, argv_extra=(), event_frames=(), startup_padding=60, timeout=30):
    # The gameplay loop ignores all input for its first ~1.5s ("awaiting
    # start" warm-up) and then swallows the very next keydown purely to
    # dismiss that overlay, without running that key's normal handler. Send
    # an inert key first so every caller's event_frames represents the real
    # sequence they intend to test.
    scripted_frames = [[pygame.K_F15], *event_frames]
    spec = {
        "sandbox_dir": str(tmp_path),
        "argv_extra": list(argv_extra),
        "event_frames": [list(frame) for frame in scripted_frames],
        "startup_padding": startup_padding,
    }
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    env = dict(os.environ)
    env["SDL_VIDEODRIVER"] = "dummy"
    env["PYTHONPATH"] = str(SRC_DIR)

    result = subprocess.run(
        [sys.executable, str(RUNNER), str(spec_path)],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    assert result.returncode == 0, (
        f"main() subprocess exited with {result.returncode}\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    return tmp_path


def test_main_runs_a_few_frames_and_quits_cleanly(tmp_path):
    """Baseline: start, simulate several idle frames, quit. No exception, and
    the gig-mode odometer is persisted on clean shutdown (proving the full
    startup -> gameplay -> shutdown path executed)."""
    _run_main(tmp_path, event_frames=[[]] * 5)

    odometer_file = tmp_path / "gig_odometer.json"
    assert odometer_file.exists()
    data = json.loads(odometer_file.read_text(encoding="utf-8"))
    assert data["odometer_m"] > 0.0


def test_pause_menu_open_and_resume_does_not_crash(tmp_path):
    """Escape opens the pause menu; Escape again resumes it (the "Continue"
    binding to K_ESCAPE, see main()'s is_paused loop)."""
    _run_main(
        tmp_path,
        event_frames=[[], [pygame.K_ESCAPE], [pygame.K_ESCAPE], []],
    )


def test_pause_menu_help_screen_does_not_crash(tmp_path):
    """Escape -> Down (select Help) -> Enter (open) -> F1 (close) -> Escape
    (resume) -> quit."""
    _run_main(
        tmp_path,
        event_frames=[
            [pygame.K_ESCAPE],
            [pygame.K_DOWN],
            [pygame.K_RETURN],
            [pygame.K_F1],
            [pygame.K_ESCAPE],
            [],
        ],
    )


def test_phone_open_and_close_does_not_crash(tmp_path):
    _run_main(
        tmp_path,
        event_frames=[[], [pygame.K_p], [pygame.K_ESCAPE], []],
    )


def test_respawn_does_not_crash(tmp_path):
    _run_main(
        tmp_path,
        event_frames=[[], [pygame.K_r], [], []],
    )


def test_debug_respawn_to_bbox_edge_does_not_crash(tmp_path):
    """K_HOME jumps the car near a random edge of the current map bbox
    ("for auto-fetch testing", per the README) - a large, instant camera
    move rather than the gradual panning normal driving produces. Repeated
    a few times since the reported symptom (a game freeze followed by a
    sustained FPS drop) was specifically triggered by a respawn jump."""
    _run_main(
        tmp_path,
        event_frames=[
            [], [pygame.K_HOME], [], [],
            [pygame.K_HOME], [], [],
            [pygame.K_HOME], [], [],
        ],
    )


def test_hud_toggle_keys_do_not_crash(tmp_path):
    """Cycle through the single-key HUD/assist toggles used during normal
    play; each is handled by its own elif branch in the gameplay loop."""
    _run_main(
        tmp_path,
        event_frames=[
            [pygame.K_l], [pygame.K_l], [pygame.K_l],  # label cycling
            [pygame.K_k],  # lane keep assist
            [pygame.K_v],  # speed limiter
            [pygame.K_b],  # traffic-light assist
            [pygame.K_c],  # compass
            [pygame.K_n],  # navigation route
            [pygame.K_t],  # reset trip meter
            [pygame.K_SPACE],  # road rage shout
            [],
        ],
    )


def test_screenshot_key_writes_a_file(tmp_path):
    _run_main(
        tmp_path,
        event_frames=[[], [pygame.K_F12], []],
    )
    screenshots_dir = tmp_path / "screenshots"
    assert screenshots_dir.is_dir()
    assert list(screenshots_dir.glob("*.png"))
    assert list(screenshots_dir.glob("*.json"))
