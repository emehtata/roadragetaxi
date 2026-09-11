"""Tests for the lane-assist/speed-limiter indicator chips under the
speedometer (render/hud.py)."""
import os

import pygame

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from theroadragetrip.render.hud import (
    _draw_analog_speedometer,
    _draw_speedometer_indicators,
    default_hud_layout,
)


def _render(lane_assist_enabled: bool, lane_assist_active: bool, speed_limiter_enabled: bool) -> bytes:
    pygame.init()
    screen = pygame.Surface((300, 300))
    screen.fill((0, 0, 0))
    rect = pygame.Rect(10, 10, 190, 170)
    _draw_speedometer_indicators(screen, rect, lane_assist_enabled, lane_assist_active, speed_limiter_enabled)
    return pygame.image.tostring(screen, "RGB")


def test_indicator_chips_render_differently_per_state():
    """Regression: lane assist/speed limiter state was only ever visible
    as text in the debug HUD's status line - easy to miss during normal
    play. Each of the three toggle-relevant states (both off, lane assist
    on but idle, lane assist actively steering, limiter on) must produce
    a visibly different frame; the same state must render identically."""
    all_off = _render(False, False, False)
    lane_on_idle = _render(True, False, False)
    lane_active = _render(True, True, False)
    limiter_on = _render(False, False, True)
    all_off_again = _render(False, False, False)

    frames = [all_off, lane_on_idle, lane_active, limiter_on]
    for i, frame_a in enumerate(frames):
        for frame_b in frames[i + 1:]:
            assert frame_a != frame_b, "two different indicator states rendered identically"

    assert all_off == all_off_again, "rendering the same state twice was not deterministic"


def test_default_hud_layout_leaves_room_for_speedometer_indicators():
    """Regression: the speedometer box used to sit flush with the bottom
    of the screen (10px margin), leaving no room to draw anything below
    it - the indicator chips would render off-screen. The chips' own
    bottom edge must stay within the screen."""
    screen_w, screen_h = 1280, 720
    layout = default_hud_layout(screen_w, screen_h)
    pygame.init()
    screen = pygame.Surface((screen_w, screen_h))

    speedometer_rect = _draw_analog_speedometer(screen, 0.0, layout["speedometer"])
    _draw_speedometer_indicators(screen, speedometer_rect, True, True, True)

    chip_h, gap = 22, 6
    indicators_bottom = speedometer_rect.bottom + gap + chip_h
    assert indicators_bottom <= screen_h, (
        f"indicator chips extend to y={indicators_bottom}, past the {screen_h}px screen height"
    )
