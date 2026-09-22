"""Tests for the lane-assist/speed-limiter indicator chips under the
speedometer (render/hud.py)."""
import os

import pygame

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from theroadragetrip.render.hud import (
    _draw_analog_speedometer,
    _draw_fuel_meter,
    _draw_speedometer_indicators,
    default_hud_layout,
)
from datetime import date
from types import SimpleNamespace

from theroadragetrip.physics import Car
from theroadragetrip.render.hud import draw_hud


def _render(
    lane_assist_enabled: bool,
    lane_assist_active: bool,
    speed_limiter_enabled: bool,
    show_navigation: bool = False,
) -> bytes:
    pygame.init()
    screen = pygame.Surface((300, 300))
    screen.fill((0, 0, 0))
    rect = pygame.Rect(10, 10, 190, 170)
    _draw_speedometer_indicators(
        screen, rect, lane_assist_enabled, lane_assist_active, speed_limiter_enabled, show_navigation
    )
    return pygame.image.tostring(screen, "RGB")


def test_indicator_chips_render_differently_per_state():
    """Regression: lane assist/speed limiter/navigation state was only
    ever visible as text in the debug HUD's status line - easy to miss
    during normal play. Each of the toggle-relevant states (all off,
    lane assist on but idle, lane assist actively steering, limiter on,
    navigation on) must produce a visibly different frame; the same
    state must render identically."""
    all_off = _render(False, False, False, False)
    lane_on_idle = _render(True, False, False, False)
    lane_active = _render(True, True, False, False)
    limiter_on = _render(False, False, True, False)
    navigation_on = _render(False, False, False, True)
    all_off_again = _render(False, False, False, False)

    frames = [all_off, lane_on_idle, lane_active, limiter_on, navigation_on]
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
    _draw_speedometer_indicators(screen, speedometer_rect, True, True, True, True)

    chip_h, gap = 22, 6
    indicators_bottom = speedometer_rect.bottom + gap + chip_h
    assert indicators_bottom <= screen_h, (
        f"indicator chips extend to y={indicators_bottom}, past the {screen_h}px screen height"
    )


def test_fuel_meter_changes_for_full_low_and_empty_tanks():
    pygame.init()
    font = pygame.font.Font(None, 24)
    frames = []
    for fuel_l in (60.0, 8.0, 0.0):
        screen = pygame.Surface((240, 80))
        screen.fill((0, 0, 0))
        _draw_fuel_meter(screen, font, Car(0, 0, 0, 0, fuel_l=fuel_l), (10, 10), "en")
        frames.append(pygame.image.tostring(screen, "RGB"))
    assert len(set(frames)) == 3


def test_date_clock_and_taxi_score_do_not_overlap():
    """The full ISO date made the old fixed 140px clock allowance too small."""
    pygame.init()
    screen = pygame.Surface((1280, 720))
    font = pygame.font.Font(None, 24)
    taxi = SimpleNamespace(
        total_score=0,
        completed_fares=0,
        balance_cents=0,
        offers=[],
        current_passenger=None,
        state="PICKUP",
        fare_started_at=None,
        notification_timer=0.0,
        notification_msg="",
        get_current_target=lambda: None,
    )
    draw_hud(
        screen, font, Car(0, 0, 0, 0), False, 0, 1.0, None,
        taxi_mgr=taxi, game_time_seconds=19 * 3600 + 11 * 60,
        game_date=date(2026, 8, 30), temperature_c=12.3, language="fi",
    )

    clock = font.render("2026-08-30 Kello 19:11  +12.3 °C", True, (255, 230, 120)).get_rect(topright=(1268, 10))
    score = font.render("PISTEET: 0 pistettä | Kyydit: 0 | SALDO: 0,00 €", True, (255, 230, 110)).get_rect(
        topright=(clock.left - 12, 10)
    )
    assert score.right < clock.left
