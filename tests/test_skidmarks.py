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


def test_coasting_corners_do_not_leave_marks_at_ordinary_speed():
    """Binary full-lock steering saturates the grip clamp on most ordinary
    turns; an unpowered corner at ordinary speed must not draw marks (the
    driven case is covered by tests/test_rwd_oversteer.py)."""
    from theroadragetrip.physics import Car, skidmark_should_mark, update_car_physics

    for mode in ("arcade", "simulation"):
        for speed in (5.0, 8.0):
            car = Car(x=0.0, y=0.0, heading=0.0, speed=speed)
            marks = 0
            for _ in range(60):
                update_car_physics(car, 0.0, 0.0, 1.0, 0.0, 1 / 60, ways=[], block_offroad=False, physics_mode=mode)
                marks += skidmark_should_mark(car.skid_amount)
            assert marks == 0


def test_a_spinning_cars_marks_are_a_ring_not_a_filled_blob():
    """Reported: donut skidmarks came out as a filled star-shaped blob. A
    car circling with the rear tyres sliding must leave two thin rings."""
    import math
    import os
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame
    from theroadragetrip.render import TireTrail, draw_tire_tracks

    pygame.init()
    screen = pygame.Surface((400, 400))
    screen.fill((0, 0, 0))
    radius = 5.0  # m, centre path of the car
    trail = None
    heading = 0.0
    for step in range(0, 361, 4):  # one sample per 4 degrees of heading, like main()
        angle = math.radians(step)
        x, y = radius * math.sin(angle), radius * (1 - math.cos(angle))
        heading = angle
        if trail is None:
            trail = TireTrail(False, x, y, heading, 1.0)
        else:
            trail.add(x, y, heading, 1.0)
    draw_tire_tracks(screen, [trail], 0.0, radius, grass=False, px_per_m=20.0, screen_w=400, screen_h=400)
    lit = sum(1 for x in range(400) for y in range(400) if screen.get_at((x, y))[0] > 0)
    # Two rings of ~2*pi*r*px each, ~5px wide, is a few thousand px; a filled
    # disc of the same size would be ~30k+.
    assert 0 < lit < 9000


def test_both_tyre_marks_sit_side_by_side_at_any_heading():
    """The two tyres of a mark must be perpendicular to the car's heading
    (side by side at the rear axle), not offset diagonally along it."""
    import math
    import os
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame
    from theroadragetrip.render import TireTrail, draw_tire_tracks

    pygame.init()
    for heading_deg in (0, 30, 45, 90, 135, 200):
        heading = math.radians(heading_deg)
        screen = pygame.Surface((400, 400))
        screen.fill((0, 0, 0))
        trail = TireTrail(False, 0.0, 0.0, heading, 1.0)
        # Drive straight ahead along the heading so each tyre draws a line
        # parallel to it; the two lines' perpendicular separation is the track.
        for step in range(1, 6):
            trail.add(math.cos(heading) * step, math.sin(heading) * step, heading, 1.0)
        draw_tire_tracks(screen, [trail], 2.0 * math.cos(heading), 2.0 * math.sin(heading), grass=False,
                         px_per_m=20.0, screen_w=400, screen_h=400)
        pts = [(x, y) for x in range(400) for y in range(400) if screen.get_at((x, y))[0] > 0]
        assert pts
        # Project every lit pixel on the car's screen-space lateral axis:
        # two tyres 1.44 m (28.8 px) apart -> two clusters of about that separation.
        lat = sorted(x * -math.sin(heading) + y * -math.cos(heading) for x, y in pts)
        assert 22.0 < lat[-1] - lat[0] < 36.0, (heading_deg, lat[-1] - lat[0])


def test_excessive_braking_from_high_speed_locks_the_front_tyres_too():
    from theroadragetrip.physics import Car, update_car_physics

    def brake(speed, mode="simulation"):
        car = Car(x=0.0, y=0.0, heading=0.0, speed=speed)
        locked = False
        for _ in range(20):
            update_car_physics(car, 0.0, 1.0, 0.0, 0.0, 1 / 60, ways=[], block_offroad=False, physics_mode=mode)
            locked = locked or car.front_lockup
        return locked

    for mode in ("arcade", "simulation"):
        assert brake(30.0, mode)       # ~108 km/h panic stop
        assert not brake(8.0, mode)    # low speed: rears only


def test_front_lockup_trails_draw_four_marks_and_others_two():
    import math
    import os
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame
    from theroadragetrip.render import TireTrail, draw_tire_tracks

    pygame.init()

    def lit(front):
        screen = pygame.Surface((400, 400))
        screen.fill((0, 0, 0))
        trail = TireTrail(False, 0.0, 0.0, 0.0, 1.0, False, front)
        for step in range(1, 6):
            trail.add(float(step), 0.0, 0.0, 1.0, front)
        draw_tire_tracks(screen, [trail], 2.5, 0.0, grass=False, px_per_m=20.0, screen_w=400, screen_h=400)
        cols = {y for x in range(400) for y in range(400) if screen.get_at((x, y))[0] > 0}
        rows = sorted(cols)
        clusters = 1 + sum(1 for a, b in zip(rows, rows[1:]) if b - a > 3)
        return sum(1 for x in range(400) for y in range(400) if screen.get_at((x, y))[0] > 0), clusters

    rear_px, rear_clusters = lit(False)
    all_px, all_clusters = lit(True)
    assert rear_clusters == 2
    assert all_px > rear_px * 1.3  # front marks add to the rear ones (same two lanes, 2.4 m ahead)
