import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "osm"))

import extract_places as ep  # noqa: E402
from places_config import CATEGORIES, PlaceCategory  # noqa: E402
from theroadragetrip.world_places import load_places  # noqa: E402


def node(id, lat, lon, **tags):
    return {"type": "node", "id": id, "lat": lat, "lon": lon, "tags": tags}


def way(id, nodes, **tags):
    return {"type": "way", "id": id, "nodes": nodes, "tags": tags}


def relation(id, members, **tags):
    return {"type": "relation", "id": id, "members": members, "tags": tags}


def square(first_id, lat, lon, size=0.01):
    """Four corner nodes (untagged) + the closed node list of a square."""
    corners = [(lat, lon), (lat, lon + size), (lat + size, lon + size), (lat + size, lon)]
    nodes = [node(first_id + i, a, b) for i, (a, b) in enumerate(corners)]
    return nodes, [first_id, first_id + 1, first_id + 2, first_id + 3, first_id]


def by_id(places):
    return {place["id"]: place for place in places}


def test_node_station_is_extracted_with_code_osm_source_and_names():
    elements = [node(1, 65.0113, 25.4843, railway="station", name="Oulu", **{"railway:ref": "OL", "uic_ref": "1000", "name:sv": "Uleåborg", "name:en": "Oulu"})]
    places, stats = ep.extract_places(elements)
    assert places == [{
        "id": "railway_station_ol", "type": "railway_station", "name": "Oulu",
        "lat": 65.0113, "lon": 25.4843, "osm": {"type": "node", "id": 1},
        "names": {"sv": "Uleåborg"}, "station_code": "OL", "uic_ref": "1000",
    }]
    assert stats["categories"]["railway_station"] == {"candidates": 1, "places": 1}


def test_area_airport_gets_its_centroid_and_optional_codes():
    corners, ring = square(10, 64.92, 25.34)
    elements = corners + [way(100, ring, aeroway="aerodrome", name="Oulun lentoasema", iata="OUL", icao="EFOU")]
    (place,), _ = ep.extract_places(elements)
    assert place["id"] == "airport_efou" and place["osm"] == {"type": "way", "id": 100}
    assert (place["iata"], place["icao"]) == ("OUL", "EFOU")
    assert place["lat"] == pytest.approx(64.925, abs=1e-4) and place["lon"] == pytest.approx(25.345, abs=1e-4)


def test_international_airport_without_codes_keeps_a_generic_record():
    (place,), _ = ep.extract_places([node(5, 60.0, 25.0, aeroway="aerodrome", aerodrome="international", name="X")])
    assert place["id"] == "airport_n5" and "iata" not in place and "icao" not in place


def test_representative_point_stays_inside_an_l_shaped_area():
    # An L whose centroid falls in the notch, outside the shape.
    shape = [(0, 0), (0, 0.03), (0.005, 0.03), (0.005, 0.005), (0.03, 0.005), (0.03, 0), (0, 0)]
    nodes = [node(20 + i, 61.0 + a, 24.0 + b) for i, (a, b) in enumerate(shape[:-1])]
    ring = [20 + i for i in range(len(shape) - 1)] + [20]
    (place,), _ = ep.extract_places(nodes + [way(200, ring, aeroway="aerodrome", iata="LLL", name="L")])
    from shapely.geometry import Point, Polygon
    assert Polygon([(24.0 + b, 61.0 + a) for a, b in shape]).contains(Point(place["lon"], place["lat"]))


def test_multipolygon_relation_uses_outer_ring_and_label_node_wins():
    corners, ring = square(30, 60.5, 22.25)
    outer = way(300, ring)
    area = relation(3000, [{"type": "way", "ref": 300, "role": "outer"}], type="multipolygon", aeroway="aerodrome", iata="TKU", icao="EFTU", name="Turku")
    (place,), _ = ep.extract_places(corners + [outer, area])
    assert place["osm"] == {"type": "relation", "id": 3000}
    assert place["lat"] == pytest.approx(60.505, abs=1e-4)

    label = node(39, 60.501, 22.251)
    area_with_label = relation(3000, area["members"] + [{"type": "node", "ref": 39, "role": "label"}], **area["tags"])
    (place,), _ = ep.extract_places(corners + [label, outer, area_with_label])
    assert (place["lat"], place["lon"]) == (60.501, 22.251)


def test_category_matching_rejects_airfields_platforms_metro_and_closed():
    elements = [
        node(1, 60, 25, aeroway="aerodrome", icao="EFNU", name="Airfield"),  # no IATA: not a destination
        node(2, 60, 25.1, railway="platform", name="Laituri"),
        node(3, 60, 25.2, railway="station", station="subway", name="Metro"),
        node(4, 60, 25.3, railway="station", disused="yes", name="Closed"),
        node(5, 60, 25.4, public_transport="station", name="Bus station"),
        node(6, 60, 25.5, railway="halt", name="Halt"),
        node(7, 60, 25.6, railway="station", name=""),  # unnamed: reported, not exported
    ]
    places, stats = ep.extract_places(elements)
    assert [p["name"] for p in places] == ["Halt"]
    assert stats["unnamed_skipped"] == [{"category": "railway_station", "type": "node", "id": 7}]


def test_same_station_as_several_elements_dedupes_to_one_but_different_names_do_not():
    corners, ring = square(40, 65.011, 25.484, size=0.001)
    elements = corners + [
        way(400, ring, railway="station", name="Oulun rautatieasema", **{"name:en": "Oulu"}),
        node(41, 65.0112, 25.4845, railway="station", name="Oulu", **{"railway:ref": "OL"}),
        node(42, 65.0200, 25.4900, railway="halt", name="Oulu railway station", **{"railway:ref": "OL"}),  # same code
        node(43, 65.0114, 25.4846, railway="halt", name="Oulun satama"),  # similar name, different place
    ]
    places, stats = ep.extract_places(elements)
    assert sorted(p["name"] for p in places) == ["Oulu", "Oulun satama"]
    oulu = by_id(places)["railway_station_ol"]
    assert oulu["osm"] == {"type": "node", "id": 41}  # stations prefer the station point
    assert oulu["osm_duplicates"] == [{"type": "node", "id": 42}, {"type": "way", "id": 400}]
    assert stats["duplicates_merged"] == 2


def test_far_apart_places_with_the_same_name_stay_separate():
    elements = [
        node(1, 60.0, 25.0, railway="halt", name="Kylä"),
        node(2, 62.0, 25.0, railway="halt", name="Kylä"),
    ]
    places, _ = ep.extract_places(elements)
    assert len(places) == 2 and len({p["id"] for p in places}) == 2


def test_output_is_deterministic_and_sorted_whatever_the_input_order():
    elements = [
        node(3, 61.0, 25.0, railway="station", name="Beta"),
        node(1, 60.0, 25.0, aeroway="aerodrome", iata="ZZZ", name="Zeta"),
        node(2, 60.5, 25.0, railway="station", name="alpha"),
    ]
    first, _ = ep.extract_places(elements)
    second, _ = ep.extract_places(list(reversed(elements)))
    assert first == second
    assert [(p["type"], p["name"]) for p in first] == [("airport", "Zeta"), ("railway_station", "alpha"), ("railway_station", "Beta")]


def test_a_new_category_needs_only_configuration():
    ferry = PlaceCategory(
        type="ferry_terminal",
        osmium_filters=("nwr/amenity=ferry_terminal",),
        matches=lambda tags: tags.get("amenity") == "ferry_terminal",
        metadata={"operator": "operator"},
        identity_tags=(),
        dedupe_radius_m=500.0,
    )
    elements = [node(9, 60.15, 24.95, amenity="ferry_terminal", name="Katajanokka", operator="Viking")]
    places, stats = ep.extract_places(elements, CATEGORIES + (ferry,))
    assert places == [{
        "id": "ferry_terminal_n9", "type": "ferry_terminal", "name": "Katajanokka",
        "lat": 60.15, "lon": 24.95, "osm": {"type": "node", "id": 9}, "operator": "Viking",
    }]
    assert set(stats["categories"]) == {"airport", "railway_station", "ferry_terminal"}


def test_invalid_inputs_fail_with_a_message(tmp_path, capsys):
    assert ep.main([str(tmp_path / "missing.osm.pbf"), str(tmp_path / "out.json")]) == 1
    assert "input not found" in capsys.readouterr().err
    text = tmp_path / "notes.txt"
    text.write_text("x")
    assert ep.main([str(text), str(tmp_path / "out.json")]) == 1
    assert "unsupported input" in capsys.readouterr().err
    pbf = tmp_path / "x.osm.pbf"
    pbf.write_bytes(b"not a pbf")
    assert ep.main([str(pbf), str(tmp_path / "nowhere" / "out.json")]) == 1
    assert "output directory does not exist" in capsys.readouterr().err
    if shutil.which("osmium"):
        assert ep.main([str(pbf), str(tmp_path / "out.json")]) == 1
        assert "osmium failed" in capsys.readouterr().err
        assert not (tmp_path / "out.json").exists()


@pytest.mark.skipif(shutil.which("osmium") is None, reason="osmium-tool not installed")
def test_cli_on_a_small_pbf_writes_json_the_game_loads(tmp_path):
    xml = """<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6" generator="test">
 <node id="1" version="1" lat="64.92" lon="25.34"/>
 <node id="2" version="1" lat="64.92" lon="25.36"/>
 <node id="3" version="1" lat="64.94" lon="25.36"/>
 <node id="4" version="1" lat="64.94" lon="25.34"/>
 <node id="5" version="1" lat="65.0113" lon="25.4843">
  <tag k="railway" v="station"/><tag k="name" v="Oulu"/><tag k="railway:ref" v="OL"/>
 </node>
 <node id="6" version="1" lat="65.02" lon="25.49"><tag k="railway" v="platform"/><tag k="name" v="Raide 1"/></node>
 <way id="10" version="1">
  <nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/>
  <tag k="aeroway" v="aerodrome"/><tag k="name" v="Oulun lentoasema"/><tag k="iata" v="OUL"/><tag k="icao" v="EFOU"/>
 </way>
</osm>
"""
    source = tmp_path / "fixture.osm"
    source.write_text(xml, encoding="utf-8")
    pbf = tmp_path / "fixture.osm.pbf"
    subprocess.run(["osmium", "cat", str(source), "-o", str(pbf)], check=True)
    out = tmp_path / "places.json"

    assert ep.main([str(pbf), str(out)]) == 0
    first = out.read_bytes()
    assert ep.main([str(pbf), str(out)]) == 0
    assert out.read_bytes() == first  # byte-identical rerun

    document = json.loads(first)
    assert document["version"] == 1 and document["source"] == "fixture.osm.pbf"
    for place in document["places"]:
        assert {"id", "type", "name", "lat", "lon", "osm"} <= set(place)
        assert isinstance(place["lat"], float) and isinstance(place["lon"], float)

    places = load_places(out)
    assert [p.id for p in places] == ["airport_efou", "railway_station_ol"]
    assert places.get("airport_efou").metadata["iata"] == "OUL"
    assert [p.name for p in places.by_type("railway_station")] == ["Oulu"]
    assert places.find("oulu")[0].id == "railway_station_ol"
    assert [p.id for p in places.within(65.0, 25.45, 20_000)] == ["railway_station_ol", "airport_efou"]


def test_loader_tolerates_missing_or_wrong_files(tmp_path):
    assert len(load_places(tmp_path / "none.json")) == 0
    bad = tmp_path / "bad.json"
    bad.write_text('{"version": 99, "places": []}')
    assert len(load_places(bad)) == 0
    bad.write_text("{not json")
    assert len(load_places(bad)) == 0


def test_committed_places_json_loads_with_the_key_finnish_places():
    places = load_places()
    icaos = {p.metadata.get("icao") for p in places.by_type("airport")}
    assert {"EFHK", "EFOU", "EFRO", "EFTP", "EFTU", "EFKU", "EFVA"} <= icaos
    stations = {p.name for p in places.by_type("railway_station")}
    assert {"Helsinki", "Tampere", "Turku", "Oulu", "Kuopio", "Jyväskylä"} <= stations
    assert len({p.id for p in places}) == len(places)
