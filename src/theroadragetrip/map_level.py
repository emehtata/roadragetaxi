"""Logical map levels (garage-01.md): 0 = surface, -1/-2 = garage levels
below it, 1+ = above it. The same integers as ParkingGarage.levels.

Not OSM layer=*: Way.layer / Car.layer order bridges and tunnels *within*
the surface world (draw order, which road you're on) and stay level 0.

Rule: an object with an explicit map_level is visible only on that level.
An object without one is surface world - every world object today -
visible on level 0 only, so level 0 renders exactly as before. A level is
never inferred from geometry (e.g. lying inside a garage polygon).

Roads (garage-04.md): draw_ways draws only SURFACE_MAP_LEVELS from the
surface network; draw_level_ways draws one explicit level from
level_view_ways. Underground, main() skips the level-less surface layers.
"""

from typing import Optional

SURFACE_LEVEL = 0


def object_map_level(obj) -> Optional[int]:
    """The object's explicit map level, or None when it has none."""
    return getattr(obj, "map_level", None)


def visible_on_level(obj, current_level: int) -> bool:
    level = getattr(obj, "map_level", None)
    return current_level == SURFACE_LEVEL if level is None else level == current_level


def surface_visible(current_level: int) -> bool:
    """Whether level-less (surface) layers draw at all - one check per
    layer per frame instead of one per object."""
    return current_level == SURFACE_LEVEL


# Way.map_level values the surface road cache (render/roads.draw_ways) keeps.
SURFACE_MAP_LEVELS = (None, SURFACE_LEVEL)


def level_view_ways(ways, level_ways) -> list:
    """Roads drawn by explicit level (render/roads.draw_level_ways): all of
    level_ways plus surface-network ways tagged off the surface (e.g. a
    level=-1 parking aisle). Built when map data changes, never per frame."""
    return list(level_ways) + [way for way in ways if way.map_level not in SURFACE_MAP_LEVELS]
