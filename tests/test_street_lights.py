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


def test_dirty_region_lights_a_new_primary_road_inside_existing_map_bounds():
    from types import SimpleNamespace
    from theroadragetrip.server import place_street_lights

    way = Way(points_m=[(-300, 0), (300, 0)], highway="primary", half_width_m=6, lit="yes")
    world = SimpleNamespace(ways=[way], buildings=[], parking_spaces=[])
    area = (-100, -30, 100, 30)
    full = place_street_lights(world)
    regional = place_street_lights(world, region=area)
    assert regional
    assert sorted(regional) == sorted(p for p in full if area[0] <= p[0] <= area[2] and area[1] <= p[1] <= area[3])
    way.lit = "no"
    assert place_street_lights(world, region=area) == []


def test_streamed_interior_tile_rebuilds_lamps_and_resends_lit_chunks(monkeypatch):
    from types import SimpleNamespace
    import theroadragetrip.server as server_module

    class InlineThread:
        def __init__(self, *, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(server_module.threading, "Thread", InlineThread)
    road = Way(points_m=[(-300, 0), (300, 0)], highway="primary", half_width_m=6, lit="yes")
    retained = (1000, 1000, 0, 8)
    obsolete = (0, 10, 0, 8)
    previous = [retained, obsolete]
    world = SimpleNamespace(ways=[road], buildings=[], parking_spaces=[], street_light_points=previous)
    encoded_lights = []
    index = SimpleNamespace(encoded=lambda cid: None)

    def updated(old, world, area):
        encoded_lights.append(list(world.street_light_points))
        return index, {"0_0"}

    monkeypatch.setattr(server_module.ChunkIndex, "updated", updated)
    server = SimpleNamespace(world=world, car=SimpleNamespace(x=0, y=0), _chunks_index=index,
                             _map_streamer=SimpleNamespace(sync_tiles={"tile"}, hold=False), _map_growth=[])
    outer = (-2000, -2000, 2000, 2000)
    server_module.SimulationServer._map_grew(server, outer, outer, [(-100, -30, 100, 30)])
    assert len(server._map_growth) == 2  # fast nearby pass, then the fully lit replacement
    lights = server._map_growth[-1][0]
    assert retained in lights and obsolete not in lights
    assert any(abs(x) < 100 and abs(y) < 20 for x, y, *_ in lights)
    assert encoded_lights[-1] == lights  # sent chunk data includes the new lamps
    assert world.street_light_points is previous  # only the tick swaps live state
    assert len({(x, y) for x, y, *_ in lights}) == len(lights)
    world.street_light_points = lights
    server_module.SimulationServer._map_grew(server, outer, outer, [(-100, -30, 100, 30)])
    assert sorted(server._map_growth[-1][0]) == sorted(lights)  # repeat merge is idempotent


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


def test_a_street_is_lit_from_one_side_and_a_divided_road_from_its_median():
    """Reported in Oulu: streets have lamps on one side; a motorway with a
    grass median has them in the median, none at the outer edges."""
    street = Way(points_m=[(-140.0, 0.0), (140.0, 0.0)], highway="primary", half_width_m=4.0, lit="yes")
    placed = _place([street], [], [])
    assert placed and len({y > 0 for _, y, *_ in placed}) == 1  # all on one side

    # Two carriageways 20 m apart (centres), each one-way: east on the south one, west on the north one
    south = Way(points_m=[(-140.0, -10.0), (140.0, -10.0)], highway="motorway", half_width_m=4.0, lit="yes", oneway=1)
    north = Way(points_m=[(140.0, 10.0), (-140.0, 10.0)], highway="motorway", half_width_m=4.0, lit="yes", oneway=1)
    placed = _place([south, north], [], [])
    assert placed and all(-6.0 < y < 6.0 for _, y, *_ in placed)  # in the median only
    xs = sorted(x for x, *_ in placed)
    assert all(b - a >= placement.STREET_LIGHT_MERGE_M for a, b in zip(xs, xs[1:]))  # one row, not two


def test_median_pools_are_round_and_reach_both_carriageways():
    from theroadragetrip.geo import dist_point_to_segment

    for angle in (0, math.pi / 2, math.pi, 3 * math.pi / 2):
        def point(x, y):
            return x * math.cos(angle) - y * math.sin(angle), x * math.sin(angle) + y * math.cos(angle)
        ways = [Way([point(-100, -10), point(100, -10)], 'motorway', 4, lit='yes', oneway=1),
                Way([point(100, 10), point(-100, 10)], 'motorway', 4, lit='yes', oneway=1)]
        lamps = _place(ways, [], [])
        assert lamps and all(len(lamp) == 5 and lamp[4] for lamp in lamps)
        for x, y, _, radius, _ in lamps:
            for road in ways:
                assert radius * 0.9 > dist_point_to_segment(x, y, *road.points_m[0], *road.points_m[1]) + road.half_width_m
        for level in (1, -1):
            ways[1].layer = level
            assert all(len(lamp) == 4 for lamp in _place(ways, [], []))
        ways[1].layer = 0
        ways[1].oneway = -1  # parallel traffic travelling in the same direction
        assert all(len(lamp) == 4 for lamp in _place(ways, [], []))


def test_explicit_median_lamp_is_round_but_outer_verge_lamp_is_directional():
    ways = [Way([(-100, -10), (100, -10)], 'motorway', 4, lit='yes', oneway=1),
            Way([(100, 10), (-100, 10)], 'motorway', 4, lit='yes', oneway=1, map_level=0)]
    lamps = [SceneryObject(x=0, y=0, kind='street_lamp'),
             SceneryObject(x=40, y=-16, kind='street_lamp')]
    placed = _place(ways, [], lamps)
    median = next(lamp for lamp in placed if lamp[:2] == (0, 0))
    verge = next(lamp for lamp in placed if lamp[:2] == (40, -16))
    assert median[4] is True
    assert len(verge) == 4
    ways[1].map_level = -1
    assert all(len(lamp) == 4 for lamp in _place(ways, [], lamps))


def test_a_wide_median_has_one_even_row_down_its_middle():
    """Pohjantie, Oulu: carriageways 10-25 m apart each put their median lamp
    at their own edge, and the 12 m merge then zig-zagged between the two
    rows (12/24 m gaps) and left the far lane dark - the taxi's automatic
    high beam flashed on and off there."""
    south = Way(points_m=[(-200.0, -12.0), (200.0, -12.0)], highway="motorway", half_width_m=7.0, lit="yes", oneway=1)
    north = Way(points_m=[(200.0, 12.0), (-200.0, 12.0)], highway="motorway", half_width_m=7.0, lit="yes", oneway=1)
    placed = _place([south, north], [], [])
    assert placed and all(abs(y) < 0.5 for _, y, *_ in placed)  # one row, mid-median
    xs = sorted(x for x, *_ in placed if -150 < x < 150)
    assert max(b - a for a, b in zip(xs, xs[1:])) <= placement.STREET_LIGHT_SPACING_M + 0.5
    for x in range(-150, 151, 2):  # every point of both outer lanes within the high-beam dip radius (entity_layer.gd)
        for y in (-17.5, 17.5):
            assert min(math.hypot(lx - x, ly - y) for lx, ly, *_ in placed) <= 22.0
