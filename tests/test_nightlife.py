"""rrt-019-nightclub: where nightclubs are (OSM) and when they play."""
from types import SimpleNamespace

from theroadragetrip import map_chunks
from theroadragetrip.nightlife import DEFAULT_OPENING_HOURS, nightclub_schedule, parse_opening_hours
from theroadragetrip.osm import Building, SceneryObject, build_ways

DAY = 24 * 60


def test_simple_opening_hours_become_weekly_intervals():
    # Kaarlenholvi, Oulu (OSM): We-Th 00:00-04:30; Fr-Su 22:00-04:30
    assert parse_opening_hours("We-Th 00:00-04:30; Fr-Su 22:00-04:30") == [
        [2 * DAY, 2 * DAY + 270], [3 * DAY, 3 * DAY + 270],
        [4 * DAY + 1320, 5 * DAY + 270], [5 * DAY + 1320, 6 * DAY + 270], [6 * DAY + 1320, 7 * DAY + 270],
    ]  # past midnight runs into the next day; Sunday's into Monday (beyond the week: the client wraps it)
    assert parse_opening_hours("Fr,Sa 23:00-05:00; Sa off") == [[4 * DAY + 1380, 5 * DAY + 300]]
    assert parse_opening_hours("Mo-Su 20:00-22:00, 23:00-02:00")[:2] == [[1200, 1320], [1380, 1560]]


def test_unsupported_hours_fall_back_to_the_default():
    for text in (None, "", "24/7", "PH off; Fr 22:00-04:00", "Jan-Mar Fr 22:00-04:00", "Fr 22:00+", "sunset-sunrise"):
        assert nightclub_schedule(text) == parse_opening_hours(DEFAULT_OPENING_HOURS)
    assert len(nightclub_schedule(None)) == 3  # Thursday to Saturday nights


def test_a_nightclub_node_keeps_its_hours_and_a_bar_is_not_a_nightclub():
    world = build_ways([
        {"type": "node", "id": 1, "lat": 65.0, "lon": 25.47,
         "tags": {"amenity": "nightclub", "name": "Ilona", "opening_hours": "Fr-Su 23:00-05:00"}},
        {"type": "node", "id": 2, "lat": 65.0, "lon": 25.48, "tags": {"amenity": "bar", "name": "Pub"}},
    ])
    clubs = [obj for obj in world.scenery_objects if obj.kind == "nightclub"]
    assert [(club.name, club.opening_hours) for club in clubs] == [("Ilona", "Fr-Su 23:00-05:00")]


def test_nightclubs_reach_one_chunk_each_from_points_and_buildings():
    club = SceneryObject(x=100.0, y=120.0, kind="nightclub", opening_hours="Fr-Su 23:00-05:00")
    building = Building(points_m=[(600, 100), (620, 100), (620, 120), (600, 120)], bbox=(600, 100, 620, 120),
                        venue_type="nightclub", center_m=(610.0, 110.0))
    bar = Building(points_m=[(700, 100), (720, 100), (720, 120), (700, 120)], bbox=(700, 100, 720, 120), venue_type="bar")
    world = SimpleNamespace(ways=[], railways=[], waters=[], buildings=[building, bar], sceneries=[], scenery_objects=[club])
    index = map_chunks.ChunkIndex(world)
    assert index.message("0_0")["nightclubs"] == [[100.0, 120.0, parse_opening_hours("Fr-Su 23:00-05:00")]]
    assert index.message("1_0")["nightclubs"] == [[610.0, 110.0, nightclub_schedule(None)]]
