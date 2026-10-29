import struct
from concurrent.futures import Future

import pytest

from theroadragetrip.osm import Building, Place, build_ways, load_local_sample
from theroadragetrip.world_cache import (
    BinaryWorldCacheLoader,
    BinaryWorldCacheWriter,
    InvalidWorldCache,
    WorldCacheManager,
    default_world_cache_dir,
)


@pytest.fixture
def sample_world():
    return build_ways(load_local_sample())


def test_default_world_cache_uses_the_os_cache_root(monkeypatch):
    monkeypatch.setattr("theroadragetrip.world_cache.default_cache_root", lambda: "/user-cache/RoadRageTrip")
    assert default_world_cache_dir().as_posix() == "/user-cache/RoadRageTrip/world"


def test_rwc_round_trip_preserves_game_data(tmp_path, sample_world):
    path = tmp_path / "area.rwc"
    BinaryWorldCacheWriter().write(path, sample_world, area_id="area")
    loaded = BinaryWorldCacheLoader().load(path)
    assert len(loaded.ways) == len(sample_world.ways)
    assert len(loaded.buildings) == len(sample_world.buildings)
    assert len(loaded.parking_spaces) == len(sample_world.parking_spaces)
    assert loaded.ways[0].points_m == sample_world.ways[0].points_m
    assert loaded.ways[0].speed_limit_kmh == sample_world.ways[0].speed_limit_kmh


def test_rwc_round_trip_preserves_scenery_objects(tmp_path):
    """Benches/waste baskets/bicycle parking/statues (osm/build.py's
    scenery_objects) must survive a save/load round trip - the bundled
    sample map used by `sample_world` has none of these tags, so this
    needs its own small synthetic fixture with some."""
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0, "tags": {"amenity": "bench"}},
        {"type": "node", "id": 2, "lat": 60.001, "lon": 25.001, "tags": {"historic": "memorial", "memorial": "statue", "name": "Founder"}},
    ]
    world = build_ways(elements)
    assert len(world.scenery_objects) == 2  # sanity: the fixture actually produced some

    path = tmp_path / "furniture.rwc"
    BinaryWorldCacheWriter().write(path, world, area_id="area")
    loaded = BinaryWorldCacheLoader().load(path)

    assert len(loaded.scenery_objects) == 2
    by_id = {obj.id: obj for obj in loaded.scenery_objects}
    assert by_id[1].kind == "bench"
    assert by_id[2].kind == "statue"
    assert by_id[2].name == "Founder"


def test_rwc_rehydrates_building_place_associations(tmp_path, sample_world):
    place = Place(10.0, 10.0, "K-Market", "supermarket", opening_hours="Mo-Sa 08:00-22:00", shop_type="supermarket")
    building = Building(
        [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)],
        name="Shop",
        bbox=(0.0, 0.0, 20.0, 20.0),
        associated_places=[place],
        opening_hours="24/7",
        shop_type="supermarket",
    )
    sample_world.buildings.append(building)
    sample_world.places.append(place)
    path = tmp_path / "associated.rwc"

    BinaryWorldCacheWriter().write(path, sample_world, area_id="associated")
    loaded = BinaryWorldCacheLoader().load(path)

    loaded_building = next(item for item in loaded.buildings if item.name == building.name)
    assert loaded_building.associated_places
    assert loaded_building.opening_hours == "24/7"
    assert loaded_building.shop_type == loaded_building.associated_places[0].shop_type == "supermarket"
    assert loaded_building.associated_places[0].opening_hours == "Mo-Sa 08:00-22:00"
    assert loaded_building.associated_places[0] is next(
        item for item in loaded.places if item.name == place.name and item.kind == place.kind
    )


def test_rwc_round_trip_shares_one_signal_group_per_phase(tmp_path, sample_world):
    """Every physical TrafficLight and IntersectionApproach on the same
    signal phase shares one SignalGroup object before saving - that's how
    build_traffic_light_system wires them up, and it's what lets a
    pedestrian or the red-light-assist logic trust that querying one
    light's phase reflects every other light on the same phase. Naive
    per-record reconstruction on load would silently give each of them
    its own separate (if equal) SignalGroup instead."""
    assert sample_world.logical_intersections, "fixture must include a signalized intersection"
    intersection = sample_world.logical_intersections[0]
    assert len(intersection.traffic_lights) >= 2

    path = tmp_path / "signals.rwc"
    BinaryWorldCacheWriter().write(path, sample_world, area_id="signals")
    loaded = BinaryWorldCacheLoader().load(path)

    loaded_intersection = loaded.logical_intersections[0]
    lights_by_approach = {}
    for light in loaded_intersection.traffic_lights:
        lights_by_approach.setdefault(light.signal_group.approach_id, []).append(light)
    same_phase = next(group for group in lights_by_approach.values() if len(group) >= 2)
    assert same_phase[0].signal_group is same_phase[1].signal_group

    # An approach on that phase must share the very same object too, not
    # just an equal one - so changing the controller's state is visible
    # everywhere at once.
    approach = next(
        a for a in loaded_intersection.approaches
        if a.signal_group is not None and a.signal_group.approach_id == same_phase[0].signal_group.approach_id
    )
    assert approach.signal_group is same_phase[0].signal_group


def test_rwc_rejects_corrupt_and_unsupported_files(tmp_path, sample_world):
    path = tmp_path / "area.rwc"
    BinaryWorldCacheWriter().write(path, sample_world)
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(InvalidWorldCache):
        BinaryWorldCacheLoader().load(path)

    BinaryWorldCacheWriter().write(path, sample_world)
    raw = bytearray(path.read_bytes())
    raw[4:6] = struct.pack("<H", 99)
    path.write_bytes(raw)
    with pytest.raises(InvalidWorldCache, match="unsupported version"):
        BinaryWorldCacheLoader().load(path)


def test_stale_format_version_forces_a_rebuild_even_within_the_ttl(tmp_path, sample_world):
    """A fix to map-generation logic (e.g. the traffic-light phase-grouping
    safety fix) makes an already-written .rwc's *content* wrong even
    though its bytes are still well-formed. load_area()'s TTL check alone
    can't catch that - it only looks at wall-clock age (default 24h) - so
    a cache written minutes before a fix shipped would keep serving the
    old, buggy data for the rest of that day. FORMAT_VERSION exists
    exactly to be bumped for this: an old-version cache must be rebuilt
    on the very next load, regardless of how fresh its mtime is."""
    import struct

    from theroadragetrip.world_cache import FORMAT_VERSION

    calls = []
    manager = WorldCacheManager(
        tmp_path,
        fetch_func=lambda bbox: calls.append(bbox) or [],
        build_func=lambda elements: sample_world,
    )
    area_id = "stale-version-area"
    path = manager.path_for(area_id)
    manager.writer.write(path, sample_world, area_id=area_id)

    # Simulate a cache written by an older build: rewrite its format
    # version byte to one less than current, leaving mtime (and therefore
    # TTL freshness) untouched.
    raw = bytearray(path.read_bytes())
    raw[4:6] = struct.pack("<H", FORMAT_VERSION - 1)
    path.write_bytes(bytes(raw))

    loaded = manager.load_area(area_id, (1, 2, 3, 4))
    manager.close()

    assert loaded is sample_world
    assert calls == [(1, 2, 3, 4)], "a stale-format cache must trigger a rebuild, not be reused"


def test_world_cache_manager_hit_avoids_fetch(tmp_path, sample_world):
    calls = []
    manager = WorldCacheManager(
        tmp_path,
        fetch_func=lambda bbox: calls.append(bbox),
        build_func=lambda elements: sample_world,
    )
    area_id = "test-area"
    manager.writer.write(manager.path_for(area_id), sample_world, area_id=area_id)
    loaded = manager.load_area(area_id, (1, 2, 3, 4))
    manager.close()
    assert loaded.ways[0].points_m == sample_world.ways[0].points_m
    assert calls == []


def test_world_cache_can_build_a_miss_in_a_worker_process(tmp_path):
    elements = load_local_sample()
    manager = WorldCacheManager(
        tmp_path,
        fetch_func=lambda bbox: elements,
        build_func=build_ways,
    )
    manager.enable_process_build(build_ways)

    loaded = manager.load_area("worker-area", (1, 2, 3, 4), allow_covering=False)
    manager.close()

    assert loaded.ways
    assert manager.path_for("worker-area").exists()


def test_local_pbf_cold_pipeline_fetches_and_builds_inside_worker(tmp_path, sample_world, monkeypatch):
    calls = []

    class ImmediateExecutor:
        def submit(self, function, *args):
            calls.append((function, args))
            manager.writer.write(args[0], sample_world, area_id=args[1])
            future = Future()
            future.set_result(None)
            return future

        def shutdown(self, **kwargs):
            pass

    manager = WorldCacheManager(
        tmp_path,
        fetch_func=lambda bbox: (_ for _ in ()).throw(AssertionError("loader-thread fetch")),
        build_func=lambda elements: (_ for _ in ()).throw(AssertionError("loader-thread build")),
    )
    manager._build_executor = ImmediateExecutor()
    manager._process_build_func = build_ways
    manager._process_pbf_path = "/maps/finland.osm.pbf"

    loaded = manager.load_area("pbf-worker-area", (1, 2, 3, 4), allow_covering=False)
    manager.close()

    assert loaded.ways == sample_world.ways
    assert calls[0][0].__name__ == "_fetch_pbf_build_and_write_cache"
    assert calls[0][1][3] == "/maps/finland.osm.pbf"


def test_world_cache_falls_back_when_the_worker_process_breaks(tmp_path, sample_world):
    from concurrent.futures.process import BrokenProcessPool

    class BrokenExecutor:
        def submit(self, *args):
            raise BrokenProcessPool("worker stopped")

        def shutdown(self, **kwargs):
            pass

    manager = WorldCacheManager(
        tmp_path,
        fetch_func=lambda bbox: [],
        build_func=lambda elements: sample_world,
    )
    manager._build_executor = BrokenExecutor()
    manager._process_build_func = build_ways

    loaded = manager.load_area("fallback-area", (1, 2, 3, 4), allow_covering=False)
    manager.close()

    assert loaded is sample_world
    assert manager.path_for("fallback-area").exists()


def test_world_cache_manager_preload(tmp_path, sample_world):
    manager = WorldCacheManager(
        tmp_path,
        fetch_func=lambda bbox: [],
        build_func=lambda elements: sample_world,
    )
    future = manager.preload("preloaded", (1, 2, 3, 4))
    assert future.result().ways
    assert manager.path_for("preloaded").exists()
    manager.close()


def test_world_cache_miss_does_not_claim_configured_source_is_overpass(tmp_path, sample_world, caplog):
    manager = WorldCacheManager(
        tmp_path,
        fetch_func=lambda bbox: [],
        build_func=lambda elements: sample_world,
    )

    with caplog.at_level("INFO"):
        manager.load_area("pbf-area", (1, 2, 3, 4))
    manager.close()

    assert "loading OSM data from the configured source" in caplog.text
    assert "downloading Overpass JSON" not in caplog.text


def test_world_cache_manager_uses_covering_area_without_fetch(tmp_path, sample_world):
    calls = []
    sample_world.bounds = (0.0, 0.0, 100.0, 100.0)
    manager = WorldCacheManager(
        tmp_path,
        fetch_func=lambda bbox: calls.append(bbox),
        build_func=lambda elements: sample_world,
    )
    area_id = "1p000000_2p000000_100p000000_200p000000"
    manager.writer.write(manager.path_for(area_id), sample_world, area_id=area_id)

    loaded = manager.load_area("small-area", (10.0, 10.0, 90.0, 90.0))

    assert loaded.bounds == sample_world.bounds
    assert calls == []
    manager.close()


def test_region_preload_does_not_use_covering_legacy_area(tmp_path, sample_world):
    calls = []
    sample_world.bounds = (0.0, 0.0, 100.0, 100.0)
    manager = WorldCacheManager(
        tmp_path,
        fetch_func=lambda bbox, **kwargs: calls.append(bbox) or [],
        build_func=lambda elements: sample_world,
    )
    legacy_id = "1p000000_2p000000_100p000000_200p000000"
    manager.writer.write(manager.path_for(legacy_id), sample_world, area_id=legacy_id)

    loaded = manager.preload_region((10.0, 10.0, 90.0, 90.0)).result()

    assert loaded.bounds == sample_world.bounds
    assert calls == [(10.0, 10.0, 90.0, 90.0)]
    manager.close()


def test_world_cache_manager_accepts_nearly_identical_tile_bbox(tmp_path, sample_world):
    calls = []
    sample_world.bounds = (0.0, 0.0, 100.0, 100.0)
    manager = WorldCacheManager(
        tmp_path,
        fetch_func=lambda bbox: calls.append(bbox),
        build_func=lambda elements: sample_world,
    )
    area_id = "0p000000_0p000000_100p000000_100p000000"
    manager.writer.write(manager.path_for(area_id), sample_world, area_id=area_id)

    loaded = manager.load_area("nearby-tile", (-0.00005, -0.00005, 99.99995, 99.99995))

    assert loaded.bounds == sample_world.bounds
    assert calls == []
    manager.close()


def test_world_cache_manager_force_refresh_passes_fetch_flag(tmp_path, sample_world):
    calls = []
    manager = WorldCacheManager(
        tmp_path,
        fetch_func=lambda bbox, **kwargs: calls.append(kwargs) or [],
        build_func=lambda elements: sample_world,
    )

    manager.load_area("forced", (1, 2, 3, 4), force_refresh=True)
    manager.close()

    assert calls == [{"force_refresh": True}]


def test_clear_world_cache_removes_entries(tmp_path):
    from theroadragetrip.world_cache import clear_world_cache

    (tmp_path / "area.rwc").write_bytes(b"cache")
    (tmp_path / "nested").mkdir()

    assert clear_world_cache(tmp_path) == 2
    assert list(tmp_path.iterdir()) == []



def test_pending_count_counts_unfinished_loads_under_the_lock():
    """Regression: the debug metric iterated _futures without the lock
    while a background preload added to it - "dictionary changed size
    during iteration"."""
    import threading
    from concurrent.futures import Future

    from theroadragetrip.world_cache import WorldCacheManager

    manager = WorldCacheManager.__new__(WorldCacheManager)
    finished = Future()
    finished.set_result(None)
    manager._futures, manager._lock = {"a": Future(), "b": finished}, threading.Lock()
    assert manager.pending_count() == 1


def test_the_start_is_looked_up_by_its_point_in_every_cached_area(tmp_path, sample_world, caplog):
    """The game start asks for a point, not for an area with exactly its
    request's id: any cached area holding the point is the start's world."""
    fetched = []
    manager = WorldCacheManager(tmp_path, fetch_func=lambda bbox: fetched.append(bbox) or [],
                                build_func=lambda elements: sample_world)
    wide = manager.area_id((61.40, 25.60, 61.60, 25.80))  # an earlier, wider area around the point
    manager.writer.write(manager.path_for(wide), sample_world, area_id=wide)
    request = (61.489158, 25.665502, 61.516622, 25.722976)
    with caplog.at_level("INFO"):
        world = manager.load_area(manager.area_id(request), request, point=(61.50, 25.69))
        assert world.ways and fetched == []  # no exact file, no fetch: the wide area holds the start
        manager.load_area(manager.area_id((60.1, 24.9, 60.2, 25.0)), (60.1, 24.9, 60.2, 25.0), point=(60.15, 24.95))
    manager.close()
    assert "Point cache hit " + wide in caplog.text
    assert "no cached area holds the point lat=60.150000 lon=24.950000" in caplog.text and len(fetched) == 1
