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

    from theroadragetrip.render import TireTrail, draw_tire_tracks

    pygame.init()
    try:
        screen = pygame.display.set_mode((400, 400))

        def track_color(intensity):
            screen.fill((255, 255, 255))
            trail = TireTrail(False, 0.0, 0.0, 0.0, intensity)
            trail.add(5.0, 0.0, 0.0, intensity)
            draw_tire_tracks(screen, [trail], 2.5, 0.0, grass=False, px_per_m=20.0, screen_w=400, screen_h=400)
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


def test_trail_bbox_lets_out_of_view_trails_be_skipped_cheaply():
    """Regression: draw_tire_tracks used to scan every point of every
    accumulated tire track every frame regardless of visibility - at a
    realistic session's worth of tracks (~4000 points) this measured
    ~10ms/frame on its own, enough by itself to occasionally drop below
    50 fps. Trails now carry a running bbox so a trail nowhere near the
    viewport is skipped with one cheap check - verified here by behavior
    (an out-of-view trail draws nothing, an in-view one still does),
    since the actual speed win isn't reliably assertable as a timing
    threshold in CI."""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame

    from theroadragetrip.render import TireTrail, draw_tire_tracks
    from theroadragetrip.render.common import get_viewport_bounds

    pygame.init()
    try:
        screen = pygame.display.set_mode((400, 400))
        camx, camy, px_per_m = 0.0, 0.0, 20.0
        viewport_bounds = get_viewport_bounds(camx, camy, px_per_m, 400, 400, 10.0)

        near_trail = TireTrail(False, 0.0, 0.0, 0.0, 1.0)
        near_trail.add(5.0, 0.0, 0.0, 1.0)
        far_trail = TireTrail(False, 100_000.0, 100_000.0, 0.0, 1.0)
        far_trail.add(100_005.0, 100_000.0, 0.0, 1.0)

        screen.fill((255, 255, 255))
        draw_tire_tracks(
            screen, [far_trail], camx, camy, grass=False, px_per_m=px_per_m,
            screen_w=400, screen_h=400, viewport_bounds=viewport_bounds,
        )
        assert screen.get_at((10, 10))[:3] == (255, 255, 255), "an out-of-view trail drew something"

        screen.fill((255, 255, 255))
        draw_tire_tracks(
            screen, [far_trail, near_trail], camx, camy, grass=False, px_per_m=px_per_m,
            screen_w=400, screen_h=400, viewport_bounds=viewport_bounds,
        )
        colors = {tuple(screen.get_at((x, y)))[:3] for x in range(400) for y in range(150, 250)}
        assert colors - {(255, 255, 255)}, "the in-view trail should still draw normally"
    finally:
        pygame.quit()


def test_ordinary_full_lock_cornering_does_not_leave_tyre_marks_but_still_slides_when_far_over_limit():
    """Binary full-lock steering saturates the grip clamp on most ordinary
    turns; that used to force a full slide (and a black mark). Marks now
    need the clamp exceeded by a real margin, while is_sliding (slip_amount)
    still reports any over-limit corner as sliding."""
    from theroadragetrip.physics import Car, skidmark_should_mark, update_car_physics

    def corner(speed, frames=60):
        car = Car(x=0.0, y=0.0, heading=0.0, speed=speed)
        marks = 0
        for _ in range(frames):
            update_car_physics(car, 1.0, 0.0, 1.0, 0.0, 1 / 60, ways=[], block_offroad=False, physics_mode="arcade")
            marks += skidmark_should_mark(car.skid_amount)
        return marks

    assert corner(16.0) == 0  # ~58 km/h full lock, throttle on
    assert corner(20.0) == 0  # ~72 km/h
    assert corner(35.0) > 30  # ~126 km/h: genuinely far past the limit
