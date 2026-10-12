import ast
import inspect

from theroadragetrip import map_style
from theroadragetrip.osm import Way


def test_map_style_is_pygame_free():
    tree = ast.parse(inspect.getsource(map_style))
    imports = [alias.name.split(".")[0] for node in ast.walk(tree)
               if isinstance(node, ast.Import) for alias in node.names]
    imports += [(node.module or "").split(".")[0] for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)]
    assert "pygame" not in imports


def test_road_style_keeps_surface_and_highway_fallbacks():
    concrete = Way([(0.0, 0.0), (1.0, 0.0)], "service", 3.0, surface="concrete")
    track = Way([(0.0, 0.0), (1.0, 0.0)], "track", 3.0)
    assert map_style.road_color_for_way(concrete) == map_style.SURFACE_COLORS["concrete"]
    assert map_style.road_color_for_way(track) == map_style.LEGACY_HIGHWAY_COLORS["track"]
