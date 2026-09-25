import json
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pygame

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import import_train_compositions as importer  # noqa: E402
from theroadragetrip.osm.models import Railway  # noqa: E402
from theroadragetrip.render.vehicles import draw_trains  # noqa: E402
from theroadragetrip.train_compositions import (  # noqa: E402
    GENERIC, LOCOMOTIVE_LENGTH_M, PROFILES, VEHICLE_GAP_M, TrainComposition, load_compositions, resolve, vehicle_profile,
)
from theroadragetrip.trains import Train, TrainRoute  # noqa: E402


def section(locomotives, wagons, total=None):
    return {"maximumSpeed": 200, "totalLength": total, "locomotives": locomotives, "wagons": wagons}


def digitraffic(number, day, sections, train_type="IC", category="Long-distance"):
    return {"trainNumber": number, "departureDate": day, "trainType": train_type, "trainCategory": category, "journeySections": sections}


# Shapes as Digitraffic returns them (IC 21 and a Pendolino, 2026-09-25).
IC21 = section(
    [{"location": 1, "locomotiveType": "Sr3", "powerType": "Electric"}],
    [
        {"length": 2640, "location": 3, "salesNumber": 6, "wagonType": "Ed"},
        {"length": 2640, "location": 2, "salesNumber": 7, "wagonType": "Ed"},
        {"catering": True, "length": 2640, "location": 4, "salesNumber": 3, "wagonType": "ERd"},
        {"length": 2740, "location": 5, "pet": True, "salesNumber": 1, "wagonType": "Edo"},
    ],
    total=130,
)
PENDOLINO = section(
    [{"location": 1, "locomotiveType": "Sm3", "powerType": "Electric"}],
    [{"length": 2814, "location": 1, "wagonType": "Sm3"}, {"catering": True, "length": 2590, "location": 2, "wagonType": "Sm3"},
     {"length": 2814, "location": 3, "wagonType": "Sm3"}],
)


def test_digitraffic_composition_is_condensed_in_train_order():
    compact = importer.compact(IC21)
    assert compact["total_length_m"] == 130 and compact["max_speed_kmh"] == 200
    assert compact["vehicles"] == [
        ["locomotive", "Sr3", None, []],
        ["wagon", "Ed", 26.4, []], ["wagon", "Ed", 26.4, []],  # location order, not list order
        ["wagon", "ERd", 26.4, ["catering"]], ["wagon", "Edo", 27.4, ["pet"]],
    ]
    # A multiple unit's "locomotive" is its own first car: not added twice.
    assert [v[0] for v in importer.compact(PENDOLINO)["vehicles"]] == ["wagon", "wagon", "wagon"]


def test_learned_database_persists_reuses_history_and_prefers_fresh_data(tmp_path):
    path = tmp_path / "train_compositions.json.gz"
    database = importer.load(path)
    importer.merge(database, [digitraffic(21, "2026-09-25", [IC21])], "2026-09-25T06:00:00Z")
    importer.merge(database, [digitraffic(8, "2026-09-25", [PENDOLINO], train_type="S")], "2026-09-25T06:00:00Z")
    importer.merge(database, [digitraffic(8000, "2026-09-25", [IC21], category="Commuter")], "2026-09-25T06:00:00Z")
    importer.write(database, path)

    loaded = load_compositions(path)  # offline: just the file
    assert "2026-09-25|8000" not in loaded["observations"]  # only long-distance trains are kept
    exact = resolve(loaded, "IC", "21", date(2026, 9, 25))
    assert exact.source == "exact" and len(exact.vehicles) == 5
    later = resolve(loaded, "IC", "21", date(2026, 10, 3))  # no data that day: reuse what was learned
    assert later.source == "history" and later.vehicles == exact.vehicles and later.observed == "2026-09-25"

    shorter = section([{"location": 1, "locomotiveType": "Sr2"}], [{"length": 2640, "location": 2, "wagonType": "Ed"}])
    importer.merge(loaded, [digitraffic(21, "2026-09-27", [shorter])], "2026-09-27T06:00:00Z")
    importer.merge(loaded, [digitraffic(21, "2026-09-20", [IC21])], "2026-09-27T07:00:00Z")  # older date: no override
    assert resolve(loaded, "IC", "21", date(2026, 10, 3)).observed == "2026-09-27"  # newest wins
    assert "2026-09-25|21" in loaded["observations"]  # the older observation is kept, not overwritten


def test_fallback_hierarchy_exact_history_type_generic(tmp_path):
    database = importer.load(tmp_path / "none.json.gz")
    importer.merge(database, [digitraffic(21, "2026-09-25", [IC21])], "2026-09-25T06:00:00Z")
    assert resolve(database, "IC", "21", date(2026, 9, 25)).source == "exact"
    assert resolve(database, "IC", "21", date(2026, 9, 26)).source == "history"
    assert resolve(database, "IC", "99", date(2026, 9, 26)).source == "type"  # unknown IC: a known IC shape
    assert resolve(database, "PYO", "99", date(2026, 9, 26)) is GENERIC
    assert resolve(None, "IC", "21", None) is GENERIC  # no database at all


def test_vehicle_lengths_offsets_and_total_length():
    composition = resolve({"latest": {"21": {**importer.compact(IC21), "departure_date": "2026-09-25"}}}, "IC", "21", None)
    lengths = [length for length, _ in composition.vehicles]
    assert lengths == [LOCOMOTIVE_LENGTH_M["Sr3"], 26.4, 26.4, 26.4, 27.4]
    assert composition.offsets[0] == lengths[0] / 2
    assert composition.offsets[1] == lengths[0] + VEHICLE_GAP_M + lengths[1] / 2
    assert abs(composition.length_m - (sum(lengths) + VEHICLE_GAP_M * 4)) < 1e-9
    assert abs(composition.length_m - 130) < 5  # agrees with Digitraffic's totalLength


def test_visual_profiles_stay_green_with_a_striped_restaurant_car():
    assert vehicle_profile("wagon", []) == "standard"
    assert vehicle_profile("wagon", ["catering", "disabled"]) == "restaurant"
    assert vehicle_profile("wagon", ["playground"]) == "family"
    assert vehicle_profile("wagon", ["something-new"]) == "standard"
    assert vehicle_profile("locomotive", []) == "locomotive"
    for base, _ in PROFILES.values():
        assert base[1] > base[0] and base[1] > base[2]  # green dominates every vehicle
    assert PROFILES["restaurant"][1] == (245, 245, 240)  # white stripe


def test_offline_import_failure_keeps_the_learned_database(tmp_path, monkeypatch, capsys):
    path = tmp_path / "train_compositions.json.gz"
    saved = tmp_path / "compositions.json"
    saved.write_text(json.dumps([digitraffic(21, "2026-09-25", [IC21])]))
    assert importer.main(["--from-json", str(saved), str(path)]) == 0
    before = path.read_bytes()

    def offline(day):
        raise ConnectionError("no network")

    monkeypatch.setattr(importer, "download", offline)
    assert importer.main([str(path)]) == 1
    assert "no compositions fetched" in capsys.readouterr().err and path.read_bytes() == before


def test_trains_of_any_length_are_drawn_vehicle_by_vehicle():
    pygame.init()
    route = TrainRoute([(0.0, 0.0), (1000.0, 0.0)])
    for count in (3, 5, 12):
        vehicles = ((19.6, "locomotive"),) + ((26.4, "standard"),) * (count - 2) + ((26.4, "restaurant"),)
        train = Train(route, 750.0, 1, composition=TrainComposition(vehicles))
        centres = [x for x, _, _ in train.cars()]
        assert len(centres) == count and centres == sorted(centres, reverse=True)  # front first, in order
        screen = pygame.Surface((1600, 80))  # 4 px/m around x = 600 m: 400..800 m
        draw_trains(screen, SimpleNamespace(trains=[train], routes=[]), 600.0, 0.0, px_per_m=4.0, screen_w=1600, screen_h=80)
        to_px = lambda x: round((x - 600.0) * 4 + 800)  # noqa: E731
        restaurant = to_px(centres[-1])
        assert screen.get_at((restaurant, 40))[:3] == PROFILES["restaurant"][1]  # its white stripe
        assert screen.get_at((restaurant, 44))[:3] == PROFILES["restaurant"][0]  # on green
        assert screen.get_at((to_px(centres[0]), 40))[:3] == PROFILES["locomotive"][0]
