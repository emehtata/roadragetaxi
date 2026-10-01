"""Level visibility rule (garage-01.md): explicit map_level must match the
current level; objects without one are surface world (level 0)."""
from types import SimpleNamespace

from theroadragetrip.map_level import SURFACE_LEVEL, object_map_level, surface_visible, visible_on_level
from theroadragetrip.osm import Building, Way
from theroadragetrip.physics import Car

OBJECTS = {level: SimpleNamespace(map_level=level) for level in (0, -1, -2)}


def visible(current):
    return {level for level, obj in OBJECTS.items() if visible_on_level(obj, current)}


def test_only_the_current_level_is_visible():
    assert visible(0) == {0}
    assert visible(-1) == {-1}
    assert visible(-2) == {-2}
    assert visible(1) == set()


def test_level_transitions():
    assert [visible(level) for level in (0, -1, -2, -1, 0)] == [{0}, {-1}, {-2}, {-1}, {0}]


def test_objects_without_a_level_are_surface_world():
    road = Way([(0.0, 0.0), (10.0, 0.0)], "residential", 3.0, layer=-1)  # a tunnel: OSM layer, not map level
    building = Building([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)])
    for obj in (road, building):
        assert object_map_level(obj) is None
        assert visible_on_level(obj, SURFACE_LEVEL)
        assert not visible_on_level(obj, -1)
    assert surface_visible(0) and not surface_visible(-1)


def test_player_starts_on_the_surface():
    assert Car(0.0, 0.0, 0.0, 0.0).map_level == SURFACE_LEVEL
