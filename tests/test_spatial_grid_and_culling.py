
from theroadragetrip.geo import compute_bbox
from theroadragetrip.map_style import LEGACY_HIGHWAY_COLORS, road_color_for_way
from theroadragetrip.osm import Way
from theroadragetrip.physics import Car, SpatialWayGrid, get_road_layer_at_point, is_on_road
from theroadragetrip.osm import Scenery
from theroadragetrip.viewport import get_viewport_bounds


def test_compute_bbox():
    pts = [(10.0, 20.0), (30.0, 5.0), (-5.0, 15.0)]
    minx, miny, maxx, maxy = compute_bbox(pts)
    assert minx == -5.0
    assert miny == 5.0
    assert maxx == 30.0
    assert maxy == 20.0


def test_get_viewport_bounds():
    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx=100.0, camy=200.0, px_per_m=1.0, screen_w=800, screen_h=600, margin_m=50.0)
    # half_w = 400 + 50 = 450 -> [ -350, 550 ]
    # half_h = 300 + 50 = 350 -> [ -150, 550 ]
    assert vminx == -350.0
    assert vmaxx == 550.0
    assert vminy == -150.0
    assert vmaxy == 550.0


def test_spatial_way_grid_detection():
    w1 = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="primary", half_width_m=4.0)
    w2 = Way(points_m=[(500.0, 500.0), (600.0, 500.0)], highway="residential", half_width_m=3.0)

    grid = SpatialWayGrid(cell_size=200.0)
    grid.rebuild([w1, w2])

    car_on = Car(x=50.0, y=1.0, heading=0.0, speed=0.0)
    car_off = Car(x=50.0, y=50.0, heading=0.0, speed=0.0)
    car_on_w2 = Car(x=550.0, y=502.0, heading=0.0, speed=0.0)

    assert grid.is_on_road(car_on) is True
    assert grid.is_on_road(car_off) is False
    assert grid.is_on_road(car_on_w2) is True
    assert is_on_road(car_on, [w1, w2], spatial_grid=grid) is True
    assert is_on_road(car_off, [w1, w2], spatial_grid=grid) is False


def test_ways_in_rect_draw_order_is_stable_across_different_viewports():
    """Regression: a real Oulu park (small, nested inside a much bigger
    landuse polygon that's far larger than the screen) rendered fine from
    one camera position and vanished - fully painted over by the big
    polygon's own fill - from a camera position only ~24m away, with
    nothing about the map having changed. ways_in_rect() used to yield
    results in grid-scan order: a small viewport only ever sees a *few*
    of a huge polygon's many indexed cells, and *which* of those cells it
    happens to reach first (deciding whether the huge polygon is "seen"
    before or only at the same cell as the small one nested inside it)
    depends on the query rectangle's own corner - not on anything about
    the ways themselves. Two viewports panned a few meters apart, both
    still fully inside the huge polygon and both still containing the
    small one, could get them back in a different relative order.

    Reproduces the exact mechanism: `big` is much larger than either
    viewport (as a real landuse polygon is next to a car's view), so
    neither viewport sees its far edge - one starts west of `small`'s own
    cell (finding `big` there first, before ever reaching `small`'s
    cell); the other starts exactly at `small`'s cell (finding both there
    together, at the mercy of insertion order)."""
    cell_size = 100.0
    big = Scenery(
        [(0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0), (0.0, 1000.0)],
        "parking", bbox=(0.0, 0.0, 1000.0, 1000.0),
    )
    small = Scenery(
        [(410.0, 410.0), (490.0, 410.0), (490.0, 490.0), (410.0, 490.0)],
        "park", bbox=(410.0, 410.0, 490.0, 490.0),
    )

    grid = SpatialWayGrid(cell_size=cell_size)
    grid.rebuild([small, big])  # `small` listed first - must not decide anything on its own

    # Viewport A starts west of `small`'s cell (reaches `big` via a cell
    # `small` isn't in, first). Viewport B starts exactly at `small`'s own
    # cell corner (reaches both together). Both fully contain `small` and
    # are entirely inside `big`'s extent - neither sees `big`'s far edge.
    viewport_a = (0.0, 400.0, 600.0, 600.0)
    viewport_b = (400.0, 400.0, 600.0, 600.0)

    order_a = [sc.kind for sc in grid.ways_in_rect(*viewport_a)]
    order_b = [sc.kind for sc in grid.ways_in_rect(*viewport_b)]

    assert order_a == order_b == ["parking", "park"], (
        f"draw order must not depend on the viewport: got {order_a!r} vs {order_b!r} "
        "for the same two overlapping polygons"
    )


def test_ways_in_rect_draws_the_smaller_more_specific_area_last():
    """Independent of the stability fix above: a small, specific area
    (a named park) nested inside a large, general one (a landuse polygon
    far bigger than the current view) must draw on top of it, not be at
    the mercy of whichever happened to come first in the source OSM data
    or of grid-scan order - a real hand-drawn map layers the specific
    feature over its surroundings. Uses the same "big bigger than the
    viewport, small nested in one of its cells" shape as the stability
    test above, which is exactly the layout where insertion order (small
    listed first) used to win the scan and draw the small area first -
    i.e. underneath."""
    cell_size = 100.0
    small = Scenery(
        [(410.0, 410.0), (490.0, 410.0), (490.0, 490.0), (410.0, 490.0)],
        "grass", bbox=(410.0, 410.0, 490.0, 490.0),
    )
    big = Scenery(
        [(0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0), (0.0, 1000.0)],
        "residential", bbox=(0.0, 0.0, 1000.0, 1000.0),
    )

    grid = SpatialWayGrid(cell_size=cell_size)
    grid.rebuild([small, big])  # small listed FIRST in the source data - must not matter

    # A viewport starting exactly at small's own cell corner, entirely
    # inside big's extent - the case where both are first found together,
    # at the mercy of insertion order rather than area.
    order = [sc.kind for sc in grid.ways_in_rect(400.0, 400.0, 600.0, 600.0)]

    assert order == ["residential", "grass"]






def test_layer_transition_prefers_way_matching_vehicle_heading():
    east_west = Way(points_m=[(-20.0, 0.0), (20.0, 0.0)], highway="primary", half_width_m=5.0, layer=0)
    north_south_bridge = Way(
        points_m=[(0.0, -20.0), (0.0, 20.0)],
        highway="primary",
        half_width_m=5.0,
        layer=1,
        is_bridge=True,
    )
    grid = SpatialWayGrid([east_west, north_south_bridge])

    assert get_road_layer_at_point(0.0, 0.0, current_layer=2, heading=1.5708, spatial_grid=grid) == 1
    assert get_road_layer_at_point(0.0, 0.0, current_layer=2, heading=0.0, spatial_grid=grid) == 0















def test_road_color_prefers_osm_surface_over_highway():
    asphalt = Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="residential", half_width_m=4.0, surface="concrete")
    unknown = Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="residential", half_width_m=4.0, surface="new_material")
    sidewalk = Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="footway", half_width_m=1.2, is_drivable=False, surface="asphalt")
    cycleway = Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="cycleway", half_width_m=1.5, is_drivable=False)

    assert road_color_for_way(asphalt) == (166, 163, 154)
    # No recognized surface - falls back to the legacy per-highway-class
    # color (residential), not a flat generic grey.
    assert road_color_for_way(unknown) == LEGACY_HIGHWAY_COLORS["residential"]
    assert road_color_for_way(sidewalk) == (70, 70, 70)
    assert road_color_for_way(cycleway) == (115, 145, 150)


def test_road_color_falls_back_to_legacy_highway_class_without_a_surface_tag():
    """No surface tag at all (common in real OSM data) must still
    differentiate by road class, not collapse every highway type to the
    same flat grey."""
    motorway = Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="motorway", half_width_m=6.0)
    residential = Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="residential", half_width_m=4.0)
    track = Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="track", half_width_m=2.0)

    assert road_color_for_way(motorway) == LEGACY_HIGHWAY_COLORS["motorway"]
    assert road_color_for_way(residential) == LEGACY_HIGHWAY_COLORS["residential"]
    assert road_color_for_way(track) == LEGACY_HIGHWAY_COLORS["track"]
    # Different classes must actually look different, not all the same grey.
    assert len({road_color_for_way(motorway), road_color_for_way(residential), road_color_for_way(track)}) == 3












def _grid_ways(count: int) -> list:
    return [
        Way(
            points_m=[(float(i * 10), 0.0), (float(i * 10 + 5), 0.0)],
            highway="residential", half_width_m=2.0,
            bbox=(float(i * 10), -2.0, float(i * 10 + 5), 2.0),
        )
        for i in range(count)
    ]


def test_incremental_rebuild_serves_old_grid_until_finished():
    """bin-loader-v3.md: start_rebuild()/advance_rebuild() must not touch
    the live grid until the whole job commits - a query made mid-rebuild
    must see the OLD complete grid, never a partially-built one."""
    grid = SpatialWayGrid()
    old_ways = _grid_ways(5)
    grid.rebuild(old_ways)
    old_count = grid.indexed_way_count

    new_ways = _grid_ways(40)
    grid.start_rebuild(new_ways)
    assert grid.indexed_way_count == old_count, "old grid must still be live right after start_rebuild"
    assert not grid.advance_rebuild(0.0), "a job this size must not finish in a single zero-budget call"
    assert grid.indexed_way_count == old_count, "old grid must still be live mid-rebuild"


def test_incremental_rebuild_matches_synchronous_rebuild_exactly():
    ways = _grid_ways(60)
    sync_grid = SpatialWayGrid()
    sync_grid.rebuild(ways)

    inc_grid = SpatialWayGrid()
    inc_grid.start_rebuild(ways)
    finished = False
    steps = 0
    while not finished:
        finished = inc_grid.advance_rebuild(0.0)
        steps += 1
        assert steps < 1000, "incremental rebuild never finished"
    assert steps > 1, "a zero budget must force multiple advance_rebuild() calls"

    assert inc_grid.indexed_way_count == sync_grid.indexed_way_count == len(ways)
    assert inc_grid._pending_ways is None
    sync_results = sorted(id(w) for w in sync_grid.ways_in_rect(-100, -100, 1000, 100))
    inc_results = sorted(id(w) for w in inc_grid.ways_in_rect(-100, -100, 1000, 100))
    assert sync_results == inc_results == sorted(id(w) for w in ways)
