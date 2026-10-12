
from theroadragetrip import map_style
from theroadragetrip.osm import Way


def test_road_style_keeps_surface_and_highway_fallbacks():
    concrete = Way([(0.0, 0.0), (1.0, 0.0)], "service", 3.0, surface="concrete")
    track = Way([(0.0, 0.0), (1.0, 0.0)], "track", 3.0)
    assert map_style.road_color_for_way(concrete) == map_style.SURFACE_COLORS["concrete"]
    assert map_style.road_color_for_way(track) == map_style.LEGACY_HIGHWAY_COLORS["track"]
