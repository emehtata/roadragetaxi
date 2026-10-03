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


def parse_map_level(value) -> Optional[int]:
    """OSM level=* as a map level when it is one clean integer ("-1",
    " 2 ", "+1"), else None: multi-level ("-2;-1"), ranges ("0-2"),
    fractions ("1.5") and junk stay unset rather than guessed."""
    text = str(value).strip() if value is not None else ""
    digits = text[1:] if text[:1] in "+-" else text
    return int(text) if digits.isascii() and digits.isdigit() else None


def explicit_levels(way) -> frozenset:
    """Every level a road explicitly states: its map_level, or each integer
    of a multi-level raw level=* such as "0;-1" (a ramp between levels,
    garage-08.md). Empty when untagged or unclear ("0-1", "1.5", "0;x") -
    never from layer, tunnel, covered or geometry. Map-sync time only."""
    if getattr(way, "map_level", None) is not None:
        return frozenset((way.map_level,))
    return parse_level_list(getattr(way, "level", None))


def parse_level_list(raw) -> frozenset:
    """Each integer of a clean multi-level level=* ("0;-1" -> {0, -1});
    empty for a single value (parse_map_level's job) or anything unclear."""
    if not raw or ";" not in raw:
        return frozenset()
    levels = [parse_map_level(part) for part in raw.split(";")]
    return frozenset(levels) if None not in levels else frozenset()


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
    """Roads on some off-surface level (render/roads.draw_level_ways,
    LevelRoadNetworks): all of level_ways plus surface-network ways that
    explicitly state an off-surface level - a level=-1 parking aisle, or a
    level=0;-1 ramp, which also stays on the surface. Built when map data
    changes, never per frame."""
    return list(level_ways) + [
        way for way in ways
        if way.map_level not in SURFACE_MAP_LEVELS or explicit_levels(way) - {SURFACE_LEVEL}
    ]


def on_map_level(way, level: int) -> bool:
    """Whether a road belongs to logical map level `level`: its explicit
    map_level, or level 0 when it has none. The one membership rule for
    drawing, driving and routing (garage-05.md)."""
    way_level = getattr(way, "map_level", None)
    return way_level == level or (way_level is None and level == SURFACE_LEVEL)


class LevelRoadNetworks:
    """Driving networks for the off-surface levels: per explicit level, its
    roads and a SpatialWayGrid over them. Level 0 is not here - it is the
    existing surface spatial_grid (built with map_level=SURFACE_LEVEL).
    Built from world data when it changes (startup, map sync), never per
    frame; levels share no roads, so nothing connects across levels."""

    def __init__(self, ways=(), level_ways=()) -> None:
        from .physics import SpatialWayGrid

        by_level: dict = {}
        for way in level_view_ways(ways, level_ways):
            # A multi-level ramp (level=0;-1) is drivable on each level it
            # names; level 0 is the surface grid's job.
            for level in explicit_levels(way) - {SURFACE_LEVEL}:
                by_level.setdefault(level, []).append(way)
        self._networks = {level: (roads, SpatialWayGrid(roads)) for level, roads in by_level.items()}
        self._empty = ([], SpatialWayGrid())

    def network(self, level: int):
        """(roads, grid) on an off-surface level; empty when it has none."""
        return self._networks.get(level, self._empty)

    def levels(self) -> list:
        return sorted(self._networks)
