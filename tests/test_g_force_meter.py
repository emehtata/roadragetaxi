"""Tests for the debug-HUD g-force meter widget."""
import os

import pygame

from theroadragetrip.render import draw_g_force_meter


def test_draw_g_force_meter_renders_without_crashing():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    try:
        screen = pygame.display.set_mode((1280, 720))
        font = pygame.font.SysFont(None, 18)

        draw_g_force_meter(screen, font, forward_g=0.0, lateral_g=0.0, is_sliding=False)
        draw_g_force_meter(screen, font, forward_g=0.8, lateral_g=-1.5, is_sliding=True)
        draw_g_force_meter(
            screen, font, forward_g=0.5, lateral_g=0.3, is_sliding=False,
            grip_usage=0.62, max_grip_g=0.9,
        )
    finally:
        pygame.quit()


def test_grip_usage_readout_renders_when_max_grip_g_is_given():
    """GRIP.md section 13: extend the meter with grip usage rather than
    leaving it g-force-only - checked by comparing the specific row the
    grip readout occupies (below the g-force readout) with and without
    max_grip_g, since the dial's F/B/L/R labels share the same color and
    would otherwise make this pass even if the readout were missing."""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    try:
        screen = pygame.display.set_mode((1280, 720))
        font = pygame.font.SysFont(None, 18)
        radius = 60
        center = (210 + radius, 720 - 180 + radius)
        # The "x.xx g" readout always renders at radius+16; the grip row (if
        # any) starts right below it - well past its own bottom edge so the
        # two never get confused with each other.
        g_readout_height = font.size("0.00 g")[1]
        row_y = center[1] + radius + 16 + g_readout_height + 4
        row_range = range(row_y, row_y + 16)
        x_range = range(max(0, center[0] - 60), center[0] + 60)

        def row_has_content():
            return any(
                tuple(screen.get_at((x, y)))[:3] != (0, 0, 0)
                for x in x_range for y in row_range
            )

        screen.fill((0, 0, 0))
        draw_g_force_meter(screen, font, forward_g=0.0, lateral_g=0.0, is_sliding=False)
        assert not row_has_content(), "grip row should be empty without max_grip_g"

        screen.fill((0, 0, 0))
        draw_g_force_meter(
            screen, font, forward_g=0.0, lateral_g=0.0, is_sliding=False,
            grip_usage=0.5, max_grip_g=0.9,
        )
        assert row_has_content(), "grip usage readout did not render"
    finally:
        pygame.quit()


def test_g_force_dot_moves_toward_the_demanded_direction():
    """The dot should shift up for acceleration and sideways for cornering,
    not just sit at the center regardless of input."""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    try:
        screen = pygame.display.set_mode((1280, 720))
        font = pygame.font.SysFont(None, 18)
        dot_color = (255, 210, 60)
        # The widget's own text readout is rendered in this same color, so
        # restrict the search to a box around the dial (a fixed, known
        # geometry - see draw_g_force_meter's `center`/`radius`) rather than
        # the whole screen, or the readout text's pixels would pollute the
        # centroid and mask the dot not actually having moved.
        radius = 60
        dial_center = (210 + radius, 720 - 180 + radius)
        x_range = range(dial_center[0] - radius, dial_center[0] + radius + 1)
        y_range = range(dial_center[1] - radius, dial_center[1] + radius + 1)

        def dot_centroid(forward_g, lateral_g):
            screen.fill((0, 0, 0))
            draw_g_force_meter(screen, font, forward_g=forward_g, lateral_g=lateral_g, is_sliding=False)
            pixels = [
                (x, y)
                for x in x_range
                for y in y_range
                if tuple(screen.get_at((x, y)))[:3] == dot_color
            ]
            assert pixels, "g-force dot did not render"
            return sum(x for x, _ in pixels) / len(pixels), sum(y for _, y in pixels) / len(pixels)

        neutral_x, neutral_y = dot_centroid(0.0, 0.0)
        accel_x, accel_y = dot_centroid(0.9, 0.0)
        assert accel_y < neutral_y, "accelerating should move the dot upward"
        assert abs(accel_x - neutral_x) < 2.0

        left_x, left_y = dot_centroid(0.0, -0.9)
        assert left_x < neutral_x, "negative lateral_g should move the dot toward L (screen-left)"
        assert abs(left_y - neutral_y) < 2.0
    finally:
        pygame.quit()
