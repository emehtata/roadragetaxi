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
        "window_decorations": window_decorations(moment),
    }


def window_decorations(moment) -> bool:
    """Advent candle bridges and Christmas stars in the windows: from the first
    Sunday of Advent (27 November - 3 December) until Epiphany, 6 January."""
    if moment.month == 1:
        return moment.day <= 6
    if moment.month == 12:
        return True
    if moment.month == 11 and moment.day >= 27:
        first_advent = 27 + (6 - __import__("datetime").date(moment.year, 11, 27).weekday())
        return moment.day >= first_advent
    return False


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
    if not _building_is_house_by_tag(building):
        return None
    return yard_spot(building, world)


# Flagpoles: a share of residential and commercial buildings has one in its yard.
FLAGPOLE_SHARE = {1: 0.20, 2: 0.30, 0: 0.15}  # house, commercial, other (apartment blocks, offices)
FLAGPOLE_OUT_M = 4.0


def flagpole_spot(building, world, category: int):
    """A flagpole's foot in the building's yard (yard_spot, 4 m out), for a
    deterministic share of buildings by category; None for the rest and for
    outbuildings and plain walls (category 3)."""
    share = FLAGPOLE_SHARE.get(category)
    if share is None or len(building.points_m) < 3:
        return None
    x, y = building.points_m[0]
    if (math.sin(round(x) * 12.9898 + round(y) * 78.233) * 43758.5453) % 1.0 >= share:
        return None
    return yard_spot(building, world, FLAGPOLE_OUT_M)


def yard_spot(building, world, out_m: float = 2.0):
    """One spot `out_m` outside a wall of the building, never inside a building, road/path or water."""
    if getattr(building, "map_level", None) not in SURFACE_MAP_LEVELS:
        return None
    points = building.points_m
    for a, b in zip(points, points[1:] + points[:1]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length < 3:
            continue
        for side in (1, -1):
            x = (a[0] + b[0]) / 2 + side * dy / length * out_m
            y = (a[1] + b[1]) / 2 - side * dx / length * out_m
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


# Finland's flag days (Ministry of the Interior, intermin.fi/liputus/liputuspaivat):
# official (asetus 383/1978) and customary (Valtiokalenteri). Election days and a
# president's inauguration have no date rule here.
FIXED_FLAG_DAYS = {(2, 5), (2, 28), (3, 19), (4, 9), (4, 27), (5, 1), (5, 9), (5, 12), (6, 4), (7, 6),
                   (10, 1), (10, 10), (10, 24), (11, 6), (11, 20), (12, 6), (12, 8)}


def _nth_weekday(year: int, month: int, weekday: int, n: int):
    import datetime
    first = datetime.date(year, month, 1)
    return first + datetime.timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int):
    import datetime
    last = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
    return last - datetime.timedelta(days=(last.weekday() - weekday) % 7)


def is_flag_day(day) -> bool:
    """The date (any datetime/date) is a Finnish flag day, Midsummer Day included."""
    year = day.year
    date = day.date() if hasattr(day, "date") else day
    return ((date.month, date.day) in FIXED_FLAG_DAYS
            or date == _nth_weekday(year, 5, 6, 2)  # Mother's Day: the second Sunday of May
            or date == _nth_weekday(year, 5, 6, 3)  # Fallen Soldiers' Memorial Day: the third
            or date == _nth_weekday(year, 11, 6, 2)  # Father's Day: the second Sunday of November
            or date == _last_weekday(year, 8, 5)  # Finnish Nature Day: the last Saturday of August
            or date.month == 6 and date.weekday() == 5 and 20 <= date.day <= 26)  # Midsummer Day


def flag_state(moment, sun_altitude_deg: float, noon_altitude_deg: float) -> str:
    """'full', 'half' (half-mast) or '' (no flags): from 08:00 until sunset, in
    summer 21:00 at the latest; where the sun stays down (polar night) until
    16:00; Independence Day until 20:00; Midsummer from 18:00 on its Eve
    through the night until 21:00 on Midsummer Day. Fallen Soldiers' Memorial
    Day: half-mast until noon (custom)."""
    hour = moment.hour + moment.minute / 60.0
    if moment.month == 6 and moment.weekday() == 4 and 19 <= moment.day <= 25:  # Midsummer Eve
        return "full" if hour >= 18.0 else ""
    if moment.month == 6 and moment.weekday() == 5 and 20 <= moment.day <= 26:  # Midsummer Day, up since its Eve
        return "full" if hour < 21.0 else ""
    if not is_flag_day(moment) or hour < 8.0:
        return ""
    if (moment.month, moment.day) == (12, 6):
        return "full" if hour < 20.0 else ""
    if noon_altitude_deg < -0.833:  # the sun does not rise: the winter recommendation
        down = hour >= 16.0
    else:
        down = hour >= 21.0 or (hour >= 12.0 and sun_altitude_deg < -0.833)  # set (not yet risen before noon)
    if down:
        return ""
    if moment.date() == _nth_weekday(moment.year, 5, 6, 3) and hour < 12.0:
        return "half"
    return "full"
