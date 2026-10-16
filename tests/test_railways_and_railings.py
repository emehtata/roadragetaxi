"""Tests for railway (railway=rail/tram/...) and railing (barrier=fence/railing) extraction and rendering."""
from theroadragetrip.osm import Railing, Railway, Way, build_ways
from theroadragetrip.world_cache import BinaryWorldCacheLoader, BinaryWorldCacheWriter


def test_build_ways_parses_railway_rail_as_railway():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.001},
        {"type": "way", "id": 30, "nodes": [1, 2], "tags": {"railway": "rail"}},
    ]

    result = build_ways(elements)

    assert len(result.railways) == 1
    assert result.railways[0].kind == "rail"
    assert len(result.railways[0].points_m) == 2


def test_build_ways_marks_railway_bridge_yes_as_is_bridge():
    """A rail line tagged bridge=yes (or a positive layer with no bridge
    tag) is a structure spanning whatever's below it, not ground-level
    track - same detection as roads' is_bridge (osm/build.py)."""
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.001},
        {"type": "way", "id": 30, "nodes": [1, 2], "tags": {"railway": "rail", "bridge": "yes", "layer": "1"}},
        {"type": "node", "id": 3, "lat": 60.001, "lon": 25.0},
        {"type": "node", "id": 4, "lat": 60.001, "lon": 25.001},
        {"type": "way", "id": 31, "nodes": [3, 4], "tags": {"railway": "rail"}},
    ]

    result = build_ways(elements)

    assert len(result.railways) == 2
    assert result.railways[0].is_bridge is True
    assert result.railways[1].is_bridge is False




def test_build_ways_ignores_subway_railway():
    """Subway is underground and invisible from street level - must not
    render as a surface rail line."""
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.001},
        {"type": "way", "id": 31, "nodes": [1, 2], "tags": {"railway": "subway"}},
    ]

    result = build_ways(elements)

    assert len(result.railways) == 0


def test_build_ways_parses_barrier_fence_and_railing():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.001},
        {"type": "way", "id": 32, "nodes": [1, 2], "tags": {"barrier": "fence"}},
        {"type": "node", "id": 3, "lat": 60.001, "lon": 25.0},
        {"type": "node", "id": 4, "lat": 60.001, "lon": 25.001},
        {"type": "way", "id": 33, "nodes": [3, 4], "tags": {"barrier": "railing"}},
    ]

    result = build_ways(elements)

    assert len(result.railings) == 2


def test_build_ways_parses_barrier_hedge_and_wall_with_kind():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.001},
        {"type": "way", "id": 32, "nodes": [1, 2], "tags": {"barrier": "hedge"}},
        {"type": "node", "id": 3, "lat": 60.001, "lon": 25.0},
        {"type": "node", "id": 4, "lat": 60.001, "lon": 25.001},
        {"type": "way", "id": 33, "nodes": [3, 4], "tags": {"barrier": "wall"}},
    ]

    result = build_ways(elements)

    by_kind = {r.kind for r in result.railings}
    assert by_kind == {"hedge", "wall"}




def test_railway_is_bridge_round_trips_through_world_cache(tmp_path):
    """Regression: a Railway loaded from a cached .rwc written before
    is_bridge existed on the dataclass silently reconstructs with
    is_bridge=False (Railway(**record) just uses the field's default for
    a missing key) - no error, no warning. That's exactly what
    FORMAT_VERSION (world_cache.py) exists to catch by forcing a rebuild
    instead of a silent wrong reload; this only confirms today's format
    actually carries the field through, not the version-bump discipline
    itself (see test_stale_format_version_forces_a_rebuild_even_within_
    the_ttl in test_world_cache.py for that)."""
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.001},
        {"type": "way", "id": 30, "nodes": [1, 2], "tags": {"railway": "rail", "bridge": "yes"}},
    ]
    world = build_ways(elements)
    assert world.railways[0].is_bridge is True
    path = tmp_path / "bridge.rwc"
    BinaryWorldCacheWriter().write(path, world, area_id="bridge")
    loaded = BinaryWorldCacheLoader().load(path)

    assert loaded.railways[0].is_bridge is True


def test_railways_and_railings_round_trip_through_world_cache(tmp_path):
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.001},
        {"type": "way", "id": 30, "nodes": [1, 2], "tags": {"railway": "tram"}},
        {"type": "node", "id": 3, "lat": 60.001, "lon": 25.0},
        {"type": "node", "id": 4, "lat": 60.001, "lon": 25.001},
        {"type": "way", "id": 32, "nodes": [3, 4], "tags": {"barrier": "fence"}},
    ]
    world = build_ways(elements)
    path = tmp_path / "area.rwc"
    BinaryWorldCacheWriter().write(path, world, area_id="area")
    loaded = BinaryWorldCacheLoader().load(path)

    assert len(loaded.railways) == 1
    assert loaded.railways[0].kind == "tram"
    assert loaded.railways[0].points_m == world.railways[0].points_m
    assert len(loaded.railings) == 1
    assert loaded.railings[0].points_m == world.railings[0].points_m
























