"""Tests for the tire-slip-driven skidmark model (.github/prompts/SKIDMARK.md).

Covers physics.skidmark_should_mark/skidmark_intensity (the "source of
truth" the spec requires - real tire slip, not brake input) and the
render side's intensity-based darkening and teleport-safety concerns are
covered by test_main_loop.py's broader smoke tests plus the dedicated
checks below.
"""
import os

from theroadragetrip.physics import (
    SKIDMARK_FULL_SLIP_THRESHOLD,
    SKIDMARK_SLIP_THRESHOLD,
    SLIDE_ENTER_THRESHOLD,
    skidmark_intensity,
    skidmark_should_mark,
)


def test_no_mark_below_the_slip_threshold():
    assert skidmark_should_mark(0.0) is False
    assert skidmark_should_mark(SKIDMARK_SLIP_THRESHOLD - 0.01) is False
    assert skidmark_intensity(0.0) == 0.0
    assert skidmark_intensity(SKIDMARK_SLIP_THRESHOLD) == 0.0


def test_mark_appears_before_the_car_counts_as_fully_sliding():
    """A tire can be visibly slipping before is_sliding's hysteresis
    would call the whole car "sliding" (SKIDMARK.md section 22.2)."""
    assert SKIDMARK_SLIP_THRESHOLD < SLIDE_ENTER_THRESHOLD
    midpoint = (SKIDMARK_SLIP_THRESHOLD + SLIDE_ENTER_THRESHOLD) / 2.0
    assert skidmark_should_mark(midpoint) is True


def test_intensity_rises_continuously_not_as_a_binary_switch():
    low = skidmark_intensity(SKIDMARK_SLIP_THRESHOLD + 0.01)
    mid = skidmark_intensity((SKIDMARK_SLIP_THRESHOLD + SKIDMARK_FULL_SLIP_THRESHOLD) / 2.0)
    high = skidmark_intensity(SKIDMARK_FULL_SLIP_THRESHOLD)
    assert 0.0 < low < mid < high == 1.0


def test_intensity_never_exceeds_one_past_full_slip():
    assert skidmark_intensity(1.0) == 1.0


def test_draw_tire_tracks_darkens_with_intensity():
    """Render-side check: a low-intensity segment must be visibly lighter
    than a high-intensity one, not the same solid color regardless of
    slip (SKIDMARK.md section 22.9)."""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame

    from theroadragetrip.render import draw_tire_tracks

    pygame.init()
    try:
        screen = pygame.display.set_mode((400, 400))

        def track_color(intensity):
            screen.fill((255, 255, 255))
            tracks = [
                (0.0, 0.0, 0.0, False, 1, intensity),
                (5.0, 0.0, 0.0, False, 1, intensity),
            ]
            draw_tire_tracks(screen, tracks, 2.5, 0.0, grass=False, px_per_m=20.0, screen_w=400, screen_h=400)
            # Sample near the drawn line's expected screen position.
            colors = {
                tuple(screen.get_at((x, y)))[:3]
                for x in range(400) for y in range(150, 250)
            } - {(255, 255, 255)}
            assert colors, "no tire track pixels found"
            return next(iter(colors))

        faint = track_color(0.1)
        dark = track_color(1.0)
        # Darker (lower RGB sum) at higher intensity.
        assert sum(dark) < sum(faint)
    finally:
        pygame.quit()
