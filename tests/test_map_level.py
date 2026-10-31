"""Level visibility rule (garage-01.md): explicit map_level must match the
current level; objects without one are surface world (level 0)."""
from types import SimpleNamespace

from theroadragetrip.map_level import SURFACE_LEVEL
from theroadragetrip.physics import Car

OBJECTS = {level: SimpleNamespace(map_level=level) for level in (0, -1, -2)}


def test_player_starts_on_the_surface():
    assert Car(0.0, 0.0, 0.0, 0.0).map_level == SURFACE_LEVEL
