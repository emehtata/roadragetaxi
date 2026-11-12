"""docs/data/osm_map_features.json stays consistent with the OSM classifier."""
import json
from pathlib import Path

from theroadragetrip.osm.build import TRAM_KINDS, _is_building
from theroadragetrip.osm.constants import HIGHWAY_HALF_WIDTH, OPEN_ROOF_BUILDING_TYPES

DB = json.loads((Path(__file__).resolve().parents[1] / "docs/data/osm_map_features.json").read_text())
HANDLING = {"drivable_road", "path", "rail", "building", "water", "landuse_fill",
            "vegetation", "poi", "traffic_control", "structure", "ignored"}
GEOMETRY = {"node", "way", "area", "relation"}
# Drivable via build_ways' DEFAULT_ROAD_HALF_WIDTH_M, not HIGHWAY_HALF_WIDTH.
DEFAULT_WIDTH_ROADS = {"motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link",
                       "road", "raceway", "escape", "bus_guideway", "construction", "proposed",
                       "rest_area", "services", "ladder", "via_ferrata", "elevator", "emergency_bay"}
MAIN_KEYS = ("highway building landuse natural waterway railway amenity leisure shop place man_made "
             "barrier power bridge tunnel layer route public_transport aeroway boundary").split()


def test_schema_and_allowed_values():
    assert isinstance(DB, list) and DB
    seen = set()
    for e in DB:
        assert set(e) == {"key", "value", "geometry", "handling", "notes"}, e
        assert all(isinstance(e[f], str) for f in ("key", "value", "handling", "notes")), e
        assert isinstance(e["geometry"], list) and set(e["geometry"]) <= GEOMETRY, e
        assert e["handling"] in HANDLING, e
        assert (e["key"], e["value"]) not in seen, e
        seen.add((e["key"], e["value"]))


def test_main_keys_covered():
    assert set(MAIN_KEYS) <= {e["key"] for e in DB}


def test_highway_matches_classifier():
    highway = {e["value"]: e["handling"] for e in DB if e["key"] == "highway"}
    for value in HIGHWAY_HALF_WIDTH:
        assert highway.get(value) in ("drivable_road", "path"), value
    assert {v for v, h in highway.items() if h == "drivable_road"} <= set(HIGHWAY_HALF_WIDTH) | DEFAULT_WIDTH_ROADS


def test_building_matches_classifier():
    for e in DB:
        if e["key"] == "building":
            assert _is_building({"building": e["value"]}), e
            assert e["handling"] == "building", e
            if e["value"] in OPEN_ROOF_BUILDING_TYPES:
                assert "open roof" in e["notes"], e


def test_tram_kinds_are_rail():
    rail = {e["value"] for e in DB if e["key"] == "railway" and e["handling"] == "rail"}
    assert set(TRAM_KINDS) <= rail
