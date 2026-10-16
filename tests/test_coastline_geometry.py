import json
import logging
from pathlib import Path

import pytest
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from theroadragetrip.osm.build import _sea_polygons


def build_projected(elements, bounds, monkeypatch):
    from types import SimpleNamespace
    from theroadragetrip.osm.build import build_ways
    from theroadragetrip.world_loader import with_fetch_bbox

    # Projected fixture avoids the process-global fake pyproj modules in older
    # tests; this scoped identity transform is restored after each test.
    class Transformer:
        @staticmethod
        def from_crs(*args, **kwargs):
            return SimpleNamespace(transform=lambda x, y: (x, y))
    monkeypatch.setitem(__import__("sys").modules, "pyproj", SimpleNamespace(Transformer=Transformer))
    converted = [dict(e, lon=e["x"], lat=e["y"]) if e["type"] == "node" else e for e in elements]
    x0, y0, x1, y1 = bounds
    return build_ways(with_fetch_bbox(converted, (y0, x0, y1, x1)))


@pytest.mark.parametrize("tags,kind", [({"natural": "water"}, "water"),
    ({"landuse": "reservoir"}, "reservoir"), ({"waterway": "riverbank"}, "river"),
    ({"natural": "bay"}, "bay"), ({"natural": "strait"}, "strait")])
def test_final_water_relation_stitches_outer_members_and_preserves_island(tags, kind, monkeypatch):
    coords = [(0, 0), (10, 0), (10, 10), (0, 10), (3, 3), (7, 3), (7, 7), (3, 7)]
    elements = [dict(type="node", id=i, x=x, y=y) for i, (x, y) in enumerate(coords, 1)]
    elements += [dict(type="way", id=i, nodes=nodes, tags={}) for i, nodes in
                 [(10, [1, 2, 3]), (11, [3, 4, 1]), (12, [5, 6, 7, 8, 5])]]
    elements.append(dict(type="relation", id=20, tags=dict(tags, type="multipolygon"), members=[
        dict(type="way", ref=10, role="outer"), dict(type="way", ref=11, role="outer"),
        dict(type="way", ref=12, role="inner")]))
    waters = build_projected(elements, (0, 0, 10, 10), monkeypatch).waters
    geometry = unary_union([Polygon(w.points_m) for w in waters if w.is_polygon])
    assert geometry.area == 84
    assert not geometry.covers(Point(5, 5)) and geometry.contains(Point(1, 1))
    assert all(w.kind == kind for w in waters)


def test_final_oulu_waters_leave_screenshot_land_dry(monkeypatch):
    fixture = json.loads((Path(__file__).parent / "fixtures/oulu_waters.json").read_text())
    waters = build_projected(fixture["elements"], fixture["bounds"], monkeypatch).waters
    land = Point(427870, 7211600)
    flooding = [w.kind for w in waters if w.is_polygon and Polygon(w.points_m).covers(land)]
    assert flooding == []
    assert any(w.is_polygon and Polygon(w.points_m).contains(Point(427870, 7211500)) for w in waters)
    # Real mapped island in relation 16252045, east of the screenshot.
    island = Point(428070.84957993357, 7211516.02749923)
    assert not any(w.is_polygon and Polygon(w.points_m).covers(island) for w in waters)
    assert all(Polygon(w.points_m).is_valid for w in waters if w.is_polygon)
    assert all(box(*fixture["bounds"]).covers(Polygon(w.points_m)) for w in waters if w.kind == "sea")


@pytest.mark.parametrize("extra", [{"waterway": "boatyard"}, {"waterway": "weir"}, {"barrier": "wall"}])
def test_coastline_is_collected_independently_of_its_other_tags(extra, monkeypatch):
    elements = [dict(type="node", id=i, x=x, y=y) for i, (x, y) in
                enumerate([(3, 3), (7, 3), (7, 7), (3, 7)], 1)]
    elements.append(dict(type="way", id=10, nodes=[1, 2, 3, 4, 1], tags=dict(extra, natural="coastline")))
    result = build_projected(elements, (0, 0, 10, 10), monkeypatch)
    water = unary_union([Polygon(w.points_m) for w in result.waters if w.is_polygon])
    assert water.area == 84 and not water.covers(Point(5, 5))
    assert all(w.kind == "sea" for w in result.waters)
    if "barrier" in extra:
        assert len(result.railings) == 1


def test_missing_coast_nodes_are_not_joined_across_the_gap(monkeypatch, caplog):
    elements = [dict(type="node", id=i, x=5, y=y) for i, y in enumerate([-1, 4, 6, 11], 1)]
    elements.append(dict(type="way", id=10, nodes=[1, 2, 999, 3, 4], tags={"natural": "coastline"}))
    assert not build_projected(elements, (0, 0, 10, 10), monkeypatch).waters
    assert "missing node references" in caplog.text


@pytest.mark.parametrize("tags,kind", [({"natural": "water"}, "water"),
    ({"landuse": "reservoir"}, "reservoir"), ({"waterway": "riverbank"}, "river")])
def test_inland_areas_remain_water_without_a_coastline(tags, kind, monkeypatch):
    elements = [dict(type="node", id=i, x=x, y=y) for i, (x, y) in
                enumerate([(3, 3), (7, 3), (7, 7), (3, 7)], 1)]
    elements.append(dict(type="way", id=10, nodes=[1, 2, 3, 4, 1], tags=tags))
    waters = build_projected(elements, (0, 0, 10, 10), monkeypatch).waters
    assert len(waters) == 1 and waters[0].kind == kind
    assert Polygon(waters[0].points_m).area == 16


def test_invalid_standalone_water_is_not_filled(monkeypatch, caplog):
    elements = [dict(type="node", id=i, x=x, y=y) for i, (x, y) in
                enumerate([(2, 2), (8, 8), (2, 8), (8, 2)], 1)]
    elements.append(dict(type="way", id=10, nodes=[1, 2, 3, 4, 1], tags={"natural": "water"}))
    waters = build_projected(elements, (0, 0, 10, 10), monkeypatch).waters
    assert waters and not any(w.is_polygon for w in waters)
    assert "Invalid water way" in caplog.text


@pytest.mark.parametrize("inner_nodes", [[5, 6, 7], [5, 6, 999, 8, 5]])
def test_incomplete_island_relations_do_not_fill_the_missing_land(inner_nodes, monkeypatch, caplog):
    coords = [(0, 0), (10, 0), (10, 10), (0, 10), (3, 3), (7, 3), (7, 7), (3, 7)]
    elements = [dict(type="node", id=i, x=x, y=y) for i, (x, y) in enumerate(coords, 1)]
    elements += [dict(type="way", id=10, nodes=[1, 2, 3, 4, 1], tags={"natural": "water"}),
                 dict(type="way", id=11, nodes=inner_nodes, tags={}),
                 dict(type="relation", id=20, tags={"type": "multipolygon", "natural": "water"}, members=[
                     dict(type="way", ref=10, role="outer"), dict(type="way", ref=11, role="inner")])]
    assert not build_projected(elements, (0, 0, 10, 10), monkeypatch).waters
    assert "area fill withheld" in caplog.text


def sea(lines, rect=(0, 0, 10, 10)):
    rings = _sea_polygons(lines, rect)
    for ring in rings:
        polygon = Polygon(ring)
        assert polygon.is_valid and box(*rect).covers(polygon)
    return unary_union([Polygon(ring) for ring in rings])


def test_straight_and_joined_coastlines_have_sea_on_the_right():
    for lines in [[[(5, -1), (5, 11)]], [[(5, -1), (5, 5)], [(5, 5), (5, 11)]]]:
        water = sea(lines)
        assert water.area == 50
        assert water.contains(Point(8, 5)) and not water.covers(Point(2, 5))


def test_bay_and_peninsula_keep_their_actual_land_boundaries():
    line = [(5, -1), (5, 8), (8, 8), (8, 3), (11, 3)]
    inlet = sea([line])
    for point in [(6, 5), (9, 1)]:
        assert inlet.contains(Point(point))
    for point in [(2, 5), (9, 5), (6, 9)]:
        assert not inlet.covers(Point(point))
    # Reversing the same directed line exchanges the land/sea regions.
    peninsula = sea([line[::-1]])
    assert inlet.intersection(peninsula).area == 0
    assert inlet.area + peninsula.area == 100


def test_multiple_islands_and_narrow_channel_remain_land():
    islands = [[(2, 2), (4, 2), (4, 8), (2, 8), (2, 2)],
               [(4.2, 2), (6.2, 2), (6.2, 8), (4.2, 8), (4.2, 2)]]
    water = sea(islands)
    assert water.area == pytest.approx(76)
    assert water.contains(Point(4.1, 5))
    assert not water.covers(Point(3, 5)) and not water.covers(Point(5, 5))


@pytest.mark.parametrize("lines", [[], [[(5, 2), (5, 8)]],
    [[(5, -1), (5, 4)], [(5, 6), (5, 11)]],
    [[(5, -1), (5, 11)], [(7, 2), (7, 8)]]])
def test_missing_coastline_never_turns_unknown_land_into_sea(lines, caplog):
    with caplog.at_level(logging.WARNING):
        water = sea(lines)
    assert not water.covers(Point(8, 5))
    if lines:
        assert "coastline" in caplog.text or "incomplete" in caplog.text


def test_boundary_endpoints_need_no_artificial_closing_edge():
    assert sea([[(5, 0), (5, 10)]]).area == 50
    assert sea([[(5, 0.001), (5, 9.999)]]).is_empty


def test_offshore_and_inland_require_complete_surrounding_context():
    enclosure = [(-5, -5), (15, -5), (15, 15), (-5, 15), (-5, -5)]
    assert sea([enclosure]).is_empty  # CCW: region is on land
    assert sea([enclosure[::-1]]).area == 100  # CW: region inside sea
    assert sea([[(-5, -5), (-5, 15)]]).is_empty  # no evidence for this face


@pytest.mark.parametrize("lines", [
    [[(2, 2), (8, 8), (2, 8), (8, 2), (2, 2)]],
    [[(5, -1), (5, 11)], [(-1, 5), (11, 5)]],
    [[(5, -1), (5, 11)], [(5, 11), (5, -1)]],
])
def test_invalid_or_conflicting_coastline_is_diagnostic_and_deterministic(lines, caplog):
    with caplog.at_level(logging.WARNING):
        assert sea(lines).is_empty
        assert sea(lines).is_empty
    assert caplog.records


def test_oulu_cached_coastline_does_not_fill_tuira_land():
    fixture = json.loads((Path(__file__).parent / "fixtures/oulu_waters.json").read_text())
    nodes = {e["id"]: (e["x"], e["y"])
             for e in fixture["elements"] if e["type"] == "node"}
    lines = [[nodes[n] for n in e["nodes"]] for e in fixture["elements"]
             if e["type"] == "way" and e.get("tags", {}).get("natural") == "coastline"]
    water = sea(lines, fixture["bounds"])
    assert water.area == pytest.approx(1637249.4021759536)
    assert not water.covers(Point(427870, 7211600))  # land east of the screenshot's bridge
    # Old nearest-segment classification filled this complete mapped island
    # (OSM coastline way 118133030), adding 8,721.75 m² of false sea.
    assert not water.covers(Point(426799.7722060814, 7210908.35879254))
