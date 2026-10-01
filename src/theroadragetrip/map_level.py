"""Logical map levels (garage-01.md): 0 = surface, -1/-2 = garage levels
below it, 1+ = above it. The same integers as ParkingGarage.levels.

Not OSM layer=*: Way.layer / Car.layer order bridges and tunnels *within*
the surface world (draw order, which road you're on) and stay level 0.

Rule: an object with an explicit map_level is visible only on that level.
An object without one is surface world - every world object today -
visible on level 0 only, so level 0 renders exactly as before. A level is
never inferred from geometry (e.g. lying inside a garage polygon).

ponytail: no render pass reads this yet - nothing carries an explicit
level and the player stays on 0. The phase that imports level=* objects
gates the surface layers on surface_visible() and draws its own level's
objects with visible_on_level().
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
