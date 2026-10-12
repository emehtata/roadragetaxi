"""Street-light placement (the server places them once, map_sync / server)."""
import math

from theroadragetrip.osm import SceneryObject, Way
import theroadragetrip.street_lights as placement


def _scene():
    """Crossing lit/unlit urban roads, buildings and explicit lamps."""
    from theroadragetrip.osm import Building

    ways = [Way(points_m=[(-150.0, float(y)), (0.0, float(y)), (150.0, float(y))],
                highway="residential" if y % 20 else "tertiary", half_width_m=4.0,
                lit=None if y % 20 else "yes") for y in range(-100, 101, 25)]
    ways += [Way(points_m=[(float(x), -120.0), (float(x), 120.0)], highway="service", half_width_m=3.0)
             for x in range(-120, 121, 40)]
    buildings = [Building(points_m=[(x, y), (x + 8.0, y), (x + 8.0, y + 8.0), (x, y + 8.0)],
                          bbox=(x, y, x + 8.0, y + 8.0))
                 for x in (-90.0, 30.0) for y in (-60.0, 45.0)]
    lamps = [SceneryObject(x=x, y=7.0, kind="street_lamp") for x in (-33.3, 61.7)]
    return ways, buildings, lamps


def _place(ways, buildings, lamps):
    work = placement._snapshot_street_light_job("t", (-150.0, -120.0, 150.0, 120.0), ways, None, buildings, None,
                                                 None, None)
    work["explicit_lamps"] = lamps
    while not placement._advance_street_light_prep(work):
        pass
    while not placement._advance_street_light_placement(work):
        pass
    return work["lamps"]


def test_lamps_stand_beside_the_lit_roads_and_mapped_lamps_come_first():
    ways, buildings, lamps = _scene()
    placed = _place(ways, buildings, lamps)
    assert placed
    for lamp in lamps:  # each mapped lamp is placed where it is, once
        assert sum(1 for x, y, *_ in placed if (x, y) == (lamp.x, lamp.y)) == 1
    for x, y, *_ in placed:  # never on a carriageway
        assert not placement._point_overlaps_indexed_road(x, y, placement._build_street_light_road_index(ways))
    assert all(math.isfinite(direction) for _, _, direction, _ in placed)


def test_parking_poles_stand_where_four_spots_meet():
    """Two back-to-back rows of mapped spots: the poles at the shared
    corners between them, about PARKING_LIGHT_SPACING_M apart; no pole on a
    single row or on generated house parking."""
    from types import SimpleNamespace

    from theroadragetrip.street_lights import PARKING_LIGHT_SPACING_M, parking_row_lamps

    def spot(x, y, osm_id=1):
        points = [(x, y), (x + 2.5, y), (x + 2.5, y + 5.0), (x, y + 5.0), (x, y)]
        return SimpleNamespace(points_m=points, osm_id=osm_id, bbox=(x, y, x + 2.5, y + 5.0))

    rows = [spot(i * 2.5, 0.0) for i in range(20)] + [spot(i * 2.5, 5.0) for i in range(20)]  # back to back at y = 5
    poles = parking_row_lamps(rows)
    assert poles and all(abs(y - 5.0) < 1e-6 for _, y, *_ in poles)  # on the seam
    assert all(abs(x / 2.5 - round(x / 2.5)) < 1e-6 and 0.0 < x < 50.0 for x, *_ in poles)  # at a spot corner inside
    xs = sorted(x for x, *_ in poles)
    assert all(b - a >= PARKING_LIGHT_SPACING_M for a, b in zip(xs, xs[1:]))
    assert all(pole[4] is True for pole in poles)  # all round
    assert parking_row_lamps(rows[:20]) == []  # one row: no seam
    assert parking_row_lamps([spot(i * 2.5, 0.0, None) for i in range(20)] + [spot(i * 2.5, 5.0, None) for i in range(20)]) == []
