"""Mapped shop hours drive window lighting on the simulation clock."""
from datetime import datetime
from types import SimpleNamespace

from theroadragetrip.osm import Building, Place, build_ways
from theroadragetrip.map_chunks import ChunkIndex
from theroadragetrip.shop_lights import opening_state


def test_hours_follow_weekdays_overnight_and_exact_closing_time():
    hours = ("Mo-Fr 07:00-23:00; Sa 07:00-21:00; Su 10:00-21:00",)
    assert opening_state(hours, datetime(2025, 12, 22, 22, 59), 65.0, 25.47) == 1
    assert opening_state(hours, datetime(2025, 12, 22, 23), 65.0, 25.47) == 0
    assert opening_state(hours, datetime(2025, 12, 21, 9), 65.0, 25.47) == 0
    assert opening_state(("Fr 22:00-03:00",), datetime(2025, 12, 20, 2), 65.0, 25.47) == 1
    assert opening_state(("24/7",), datetime(2025, 12, 21, 3), 65.0, 25.47) == 1


def test_finnish_holidays_date_exceptions_and_bad_hours():
    now = datetime(2025, 12, 25, 12)
    assert opening_state(("Mo-Su 08:00-22:00; PH off",), now, 65.0, 25.47) == 0
    hours = ("Mo-Su 08:00-22:00; Dec 24 08:00-12:00",)
    assert opening_state(hours, datetime(2025, 12, 24, 13), 65.0, 25.47) == 0
    assert opening_state(("not valid hours",), now, 65.0, 25.47) == -1
    assert opening_state((), now, 65.0, 25.47) == -1


def test_building_and_associated_shop_hours_reach_loaded_chunks_only():
    store = Building([(0, 0), (30, 0), (30, 20), (0, 20)], building_type="retail",
                     opening_hours="Mo-Su 08:00-22:00")
    mixed = Building([(600, 0), (630, 0), (630, 20), (600, 20)], building_type="apartments",
                     associated_places=[Place(610, 10, "Shop", "supermarket", opening_hours="24/7")])
    world = SimpleNamespace(ways=[], railways=[], waters=[], buildings=[store, mixed], sceneries=[], scenery_objects=[])
    index = ChunkIndex(world)
    assert index.shop_lights(datetime(2025, 12, 22, 21), {"0_0"}) == {"0_0": [[0, 1]]}
    assert index.shop_lights(datetime(2025, 12, 22, 22), {"0_0", "1_0"}) == {"0_0": [[0, 0]], "1_0": [[0, 1]]}


def test_osm_way_relation_and_shop_node_keep_opening_hours():
    nodes = [{"type": "node", "id": n, "lat": 65 + dy, "lon": 25.47 + dx}
             for n, dx, dy in [(1, 0, 0), (2, .001, 0), (3, .001, .001), (4, 0, .001)]]
    way = {"type": "way", "id": 10, "nodes": [1, 2, 3, 4, 1],
           "tags": {"building": "retail", "shop": "supermarket", "opening_hours": "24/7"}}
    world = build_ways(nodes + [way])
    assert world.buildings[0].opening_hours == "24/7"
    assert world.buildings[0].shop_type == "supermarket"
    way["tags"] = {}
    relation = {"type": "relation", "id": 20, "members": [{"type": "way", "ref": 10, "role": "outer"}],
                "tags": {"type": "multipolygon", "building": "retail", "shop": "supermarket", "opening_hours": "Mo-Sa 08:00-22:00"}}
    assert build_ways(nodes + [way, relation]).buildings[0].opening_hours == "Mo-Sa 08:00-22:00"
    node = {"type": "node", "id": 5, "lat": 65.0005, "lon": 25.4705,
            "tags": {"shop": "supermarket", "name": "Shop", "opening_hours": "24/7"}}
    places = build_ways(nodes + [way, node]).places
    assert any(p.kind == "supermarket" and p.opening_hours == "24/7" for p in places)


def test_unnamed_shop_node_hours_still_attach_to_its_building():
    world = build_ways([
        {"type": "node", "id": 1, "lat": 65, "lon": 25.47},
        {"type": "node", "id": 2, "lat": 65, "lon": 25.471},
        {"type": "node", "id": 3, "lat": 65.001, "lon": 25.471},
        {"type": "node", "id": 4, "lat": 65.001, "lon": 25.47},
        {"type": "way", "id": 10, "nodes": [1, 2, 3, 4, 1], "tags": {"building": "retail"}},
        {"type": "node", "id": 5, "lat": 65.0005, "lon": 25.4705,
         "tags": {"shop": "supermarket", "opening_hours": "24/7"}},
    ])
    assert world.buildings[0].associated_places[0].opening_hours == "24/7"
    index = ChunkIndex(world)
    loaded = set(index._chunks)
    assert any(rows == [[0, 1]] for rows in index.shop_lights(datetime(2025, 12, 22, 3), loaded).values())


def test_local_clock_and_timezone_inference_work_without_system_tzdata(monkeypatch):
    import zoneinfo
    from datetime import timezone
    from theroadragetrip.shop_lights import _schedule, _opening_state

    def missing_zone(*args, **kwargs):
        raise zoneinfo.ZoneInfoNotFoundError("No system timezone database")
    _schedule.cache_clear()
    _opening_state.cache_clear()
    monkeypatch.setattr(zoneinfo, "ZoneInfo", missing_zone)
    hours = ("Mo-Su 08:00-22:00",)
    assert opening_state(hours, datetime(2025, 12, 22, 8), 65.0, 25.47) == 1
    assert opening_state(hours, datetime(2025, 12, 22, 5, 59, tzinfo=timezone.utc), 65.0, 25.47) == 0
    assert opening_state(hours, datetime(2025, 12, 22, 6, tzinfo=timezone.utc), 65.0, 25.47) == 1


def test_unlisted_retail_types_use_the_raw_shop_tag():
    from theroadragetrip.static_world import building_style
    shop = Building([(0, 0), (30, 0), (30, 20), (0, 20)], building_type="yes",
                    shop_type="optician", opening_hours="24/7")
    mixed = Building([(600, 0), (630, 0), (630, 20), (600, 20)], building_type="apartments", levels=4,
                     associated_places=[Place(610, 10, "Optician", "optician", opening_hours="24/7", shop_type="optician")])
    world = SimpleNamespace(ways=[], railways=[], waters=[], buildings=[shop, mixed], sceneries=[], scenery_objects=[])
    index = ChunkIndex(world)
    assert building_style(shop)[6] == 2 and building_style(mixed)[5:7] == [4, 2]
    assert index.shop_lights(datetime(2025, 12, 22, 10), {"0_0", "1_0"}) == {"0_0": [[0, 1]], "1_0": [[0, 1]]}
