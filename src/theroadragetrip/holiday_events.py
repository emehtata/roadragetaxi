"""Finnish-local holiday schedules and static, non-colliding yard decorations."""
import math

from .building_style import _building_is_house_by_tag
from .geo import point_in_polygon
from .map_level import SURFACE_MAP_LEVELS
from .physics import is_point_in_water, is_point_on_road


def holiday_events(moment):
    day = (moment.month, moment.day)
    halloween = (day == (10, 31) and moment.hour >= 18) or (day == (11, 1) and moment.hour < 6) or day in {(10, d) for d in range(24, 31)}
    return {
        "fireworks": (day == (12, 31) and moment.hour >= 18) or (day == (1, 1) and moment.hour < 2),
        "halloween": halloween,
        "halloween_ghosts": halloween and (moment.hour >= 20 or moment.hour < 6),
        "christmas": day[0] == 12 and 1 <= day[1] <= 24,
        "santas": day == (12, 24),
        "midsummer_bonfires": midsummer_bonfires(moment),
    }


BONFIRE_SHORE_SPACING_M = 300.0


def midsummer_bonfires(moment) -> bool:
    """Juhannuskokko: lit on Midsummer Eve (the Friday before the Saturday
    of 20-26 June) from 21 until 03 the next morning."""
    eve = moment.month == 6 and moment.weekday() == 4 and 19 <= moment.day <= 25
    morning = moment.month == 6 and moment.weekday() == 5 and 20 <= moment.day <= 26
    return eve and moment.hour >= 21 or morning and moment.hour < 3


def bonfire_spot_is_clear(x, y, world) -> bool:
    """Open ground: no building, road or water within a bonfire's 4 m."""
    def nearby(name, grid_name):
        grid = getattr(world, grid_name, None)
        return grid.ways_in_rect(x - 4, y - 4, x + 4, y + 4) if grid else getattr(world, name, ())
    probes = [(x, y)] + [(x + 4 * math.cos(i * math.pi / 4), y + 4 * math.sin(i * math.pi / 4)) for i in range(8)]
    buildings, waters = nearby("buildings", "building_grid"), nearby("waters", "water_grid")
    return not any(any(point_in_polygon(px, py, b.points_m) for b in buildings)
                   or is_point_on_road(px, py, ways=world.ways, spatial_grid=getattr(world, "spatial_grid", None))
                   or is_point_in_water(px, py, waters) for px, py in probes)


def santa_costume(ped, resident, day):
    """Dress some existing adult walkers; never give them different traffic rules."""
    return bool(day is not None and resident is not None and resident.gender == "male"
                and (day.year - resident.birth_date.year - ((day.month, day.day) <
                     (resident.birth_date.month, resident.birth_date.day))) >= 18 and ped.resident_id % 4 == 0
                and not ped.is_cyclist and getattr(ped, "activity", None) is None)


def house_yard_spot(building, world):
    """One spot outside a house wall, never inside a building, road/path or water.

    Built with the map, not queried per frame. Missing yard ownership in OSM
    means this is decorative scenery only, never evidence of driving access.
    """
    if not _building_is_house_by_tag(building) or getattr(building, "map_level", None) not in SURFACE_MAP_LEVELS:
        return None
    points = building.points_m
    for a, b in zip(points, points[1:] + points[:1]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length < 3:
            continue
        for side in (1, -1):
            x = (a[0] + b[0]) / 2 + side * dy / length * 2
            y = (a[1] + b[1]) / 2 - side * dx / length * 2
            def nearby(name, grid_name):
                grid = getattr(world, grid_name, None)
                return grid.ways_in_rect(x - 1, y - 1, x + 1, y + 1) if grid else getattr(world, name, ())
            buildings = nearby("buildings", "building_grid")
            waters = nearby("waters", "water_grid")
            probes = [(x, y)] + [(x + 1.6 * math.cos(i * math.pi / 4), y + 1.6 * math.sin(i * math.pi / 4))
                                 for i in range(8)]
            if any(point_in_polygon(px, py, building.points_m) or
                   any(point_in_polygon(px, py, other.points_m) for other in buildings) or
                   is_point_on_road(px, py, ways=world.ways, spatial_grid=getattr(world, "spatial_grid", None)) or
                   is_point_in_water(px, py, waters) for px, py in probes):
                continue
            return [round(x, 2), round(y, 2)]
    return None
