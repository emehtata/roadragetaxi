"""Tests for the loading screen's progress/message display."""
import os

import pygame

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from theroadragetrip.render.menus import draw_loading_screen


def _render(message: str) -> bytes:
    pygame.init()
    screen = pygame.Surface((640, 480))
    font = pygame.font.SysFont(None, 22)
    draw_loading_screen(screen, font, 0.4, message, screen_w=640, screen_h=480, language="en")
    return pygame.image.tostring(screen, "RGB")


def test_loading_screen_actually_draws_the_message():
    """Regression: draw_loading_screen() took a `message` parameter (fed
    by fetch_osm_ways/fetch_osm_ways_from_pbf's progress_callback,
    including which endpoint/file is being read - see osm/overpass.py,
    osm/pbf_source.py) but never rendered it - the subtitle line always
    showed a fixed, localized "loading_osm" string regardless. Different
    messages must produce visibly different frames; the same message must
    render identically."""
    frame_a = _render("Fetching scenery from https://overpass-api.de/api/interp...")
    frame_b = _render("Fetching scenery from https://overpass.private.coffee/...")
    frame_a_again = _render("Fetching scenery from https://overpass-api.de/api/interp...")

    assert frame_a != frame_b, "changing the message did not change the rendered frame"
    assert frame_a == frame_a_again, "rendering the same message twice was not deterministic"


def test_loading_screen_with_empty_message_still_renders():
    """An empty message (no fetch in flight yet) must not crash and must
    render differently from a frame with a real message - i.e. the detail
    line is actually conditional on `message`, not always drawn blank."""
    frame_empty = _render("")
    frame_with_message = _render("Checking cache...")

    assert frame_empty != frame_with_message
