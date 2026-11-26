"""Catalog sky source/photometry and time/location orientation contracts."""
from __future__ import annotations

import importlib.util
import json
import math
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def builder():
    spec = importlib.util.spec_from_file_location("build_star_sky", ROOT / "tools/build_star_sky.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_catalog_filter_rejects_invalid_records_and_keeps_colorless_cutoff():
    build = builder()
    rows = [
        {"name": "SAO 1", "ra": "359.9", "dec": "89.9", "vmag": "6.0", "proper_motion_ra_fk5": "0", "proper_motion_dec_fk5": "0", "spect_type": ""},
        {"name": "SAO 2", "ra": "1", "dec": "0", "vmag": "6.1", "proper_motion_ra_fk5": "0", "proper_motion_dec_fk5": "0", "spect_type": "G2"},
        {"name": "SAO 3", "ra": "nan", "dec": "0", "vmag": "1", "proper_motion_ra_fk5": "0", "proper_motion_dec_fk5": "0", "spect_type": "G2"},
        {"name": "Sol", "ra": "0", "dec": "0", "vmag": "-26", "proper_motion_ra_fk5": "0", "proper_motion_dec_fk5": "0", "spect_type": "G2"},
    ]
    selected, rejected = build.select_stars(rows)
    assert len(selected) == 1 and selected[0][0] == 1
    assert rejected == {"fainter_than_limit": 1, "invalid_fields": 1, "non_stellar": 1}


def test_magnitude_order_is_continuous_across_atlas_bands():
    build = builder()
    values=[]
    for magnitude in (-1.6,0,.01,.99,1,1.01,1.99,2,2.01,5,5.01,6):
        band,encoded = build.encoded_star(magnitude)
        decoded = encoded*.12*2.5118864**((6-band)*.5)
        values.append(decoded)
    assert all(first>second for first,second in zip(values,values[1:]))
    for edge in range(1,6):
        before=build.encoded_star(edge)
        after=build.encoded_star(edge+.00001)
        decode=lambda row:row[1]*.12*2.5118864**((6-row[0])*.5)
        assert decode(after)==pytest.approx(decode(before),rel=.0001)


def test_pinned_catalog_filter_and_rights():
    import hashlib
    build = builder()
    manifest = json.loads((ROOT / "godot/assets/sky/source.json").read_text())
    stars = json.loads((ROOT / "godot/assets/sky/stars.json").read_text())
    assert manifest["source_sha256"] == build.SOURCE_SHA256
    assert hashlib.sha256((ROOT / "godot/assets/sky/stars.json").read_bytes()).hexdigest() == build.STARS_SHA256
    assert manifest["selected_count"] == len(stars) == 5092
    assert len({star[0] for star in stars}) == len(stars)
    assert all(star[3] <= 6.0 for star in stars)
    assert {151881, 67174, 308, 252838}.issubset({star[0] for star in stars})
    assert manifest["license"] == "US-government-public-domain"
    assert "ntrs.nasa.gov" in " ".join(manifest["rights_evidence"])
    assert "mixed" in manifest["photometry"].lower()


def test_observer_basis_against_reference():
    from theroadragetrip.calendar import star_sky_state, grid_azimuth, finnish_local_time
    sky = star_sky_state(datetime(2026, 1, 15, 0, 0), 65.01, 25.47)
    columns = sky["basis"]
    assert len(columns) == 3
    for column in columns:
        assert sum(v*v for v in column) == pytest.approx(1.0, abs=1e-10)
    assert sum(columns[0][i]*columns[1][i] for i in range(3)) == pytest.approx(0.0, abs=1e-10)
    later = star_sky_state(datetime(2026, 1, 15, 6, 0), 65.01, 25.47)
    assert columns != later["basis"]
    assert sky["utc"] == "2026-01-14T22:00:00Z"
    assert sky["observer"] == [65.01, 25.47]
    stars = {row[0]: row for row in json.loads((ROOT / "godot/assets/sky/stars.json").read_text())}
    references = json.loads((ROOT / "tests/data/star_sky_reference.json").read_text())
    for case in references["cases"]:
        utc = datetime.fromisoformat(case["utc"].replace("Z", "+00:00")).replace(tzinfo=None)
        state = star_sky_state(finnish_local_time(utc), case["latitude"], case["longitude"])
        direction = builder().direction(stars[case["sao"]])
        world = [sum(state["basis"][j][i]*direction[j] for j in range(3)) for i in range(3)]
        altitude = math.degrees(math.asin(world[1]))
        azimuth = math.degrees(math.atan2(world[0], -world[2])) % 360
        expected_az = grid_azimuth(case["azimuth"], case["latitude"], case["longitude"])
        assert abs(altitude-case["altitude"]) < .1
        assert abs((azimuth-expected_az+180)%360-180)*math.cos(math.radians(altitude)) < .1


def test_atlas_rebuild_preserves_poles_seam_and_magnitude_six(tmp_path):
    import hashlib
    from PIL import Image
    build = builder()
    stars = json.loads((ROOT / "godot/assets/sky/stars.json").read_text())
    build.bake(stars, tmp_path)
    manifest = json.loads((ROOT / "godot/assets/sky/source.json").read_text())
    for name in ("stars_0.png", "stars_1.png"):
        assert hashlib.sha256((tmp_path/name).read_bytes()).hexdigest() == manifest["asset_sha256"][name]
    images = [Image.open(tmp_path/f"stars_{i}.png") for i in range(2)]
    for star in stars:
        if star[3] < 5.9 and abs(star[2]) < 88 and not (star[1] < .2 or star[1] > 359.8):
            continue
        x,y,z = build.direction(star)
        px = int(math.atan2(y,x)%math.tau/math.tau*build.WIDTH)%build.WIDTH
        py = min(build.HEIGHT-1, int((.5-math.asin(z)/math.pi)*build.HEIGHT))
        band = max(0, min(6, math.ceil(star[3])))
        assert images[band//4].getpixel((px,py))[band%4] > 8


def test_state_uses_player_position_and_cached_utc(tmp_path, monkeypatch):
    from tests.test_server_headless import _build_server
    from theroadragetrip.geo import meters_to_latlon
    server = _build_server(tmp_path, monkeypatch)
    sky = server.calendar_state()["star_sky"]
    player = server.world.player_pedestrian if server._on_foot else server.car
    latitude, longitude = meters_to_latlon(player.x, player.y)
    assert sky["observer"] == pytest.approx([latitude, longitude], abs=.0001)
    assert server.calendar_state()["star_sky"] == sky
    player.x += 10000
    moved = server.calendar_state()["star_sky"]
    assert moved["observer"] != sky["observer"]
    assert moved["basis"] != sky["basis"]


def test_dst_fold_and_input_cache_are_unambiguous():
    from theroadragetrip.calendar import star_sky_state
    first = star_sky_state(datetime(2026, 10, 25, 3, 30, fold=0), 65.01, 25.47)
    second = star_sky_state(datetime(2026, 10, 25, 3, 30, fold=1), 65.01, 25.47)
    assert first["utc"] == "2026-10-25T00:30:00Z"
    assert second["utc"] == "2026-10-25T01:30:00Z"
    assert first["basis"] != second["basis"]
    assert star_sky_state(datetime(2026, 10, 25, 3, 30, 9, fold=1), 65.01, 25.47) is second
    assert not star_sky_state(datetime(2050, 1, 1),65.01,25.47)["supported"]


def test_star_scenarios_require_rendered_catalog_stars():
    registry = json.loads((ROOT / "tools/visual_scenarios.json").read_text())
    scenarios = {s["id"]: s for s in registry["scenarios"]}
    for name in ("stars_dark_rural_night", "stars_city_night", "stars_overcast_night", "stars_day_control", "stars_time_shift_night"):
        scenario = scenarios[name]
        assert scenario["requires"]["catalog_stars"]["min_projected"] >= 3
        assert scenario["camera"] == "eye"
    assert scenarios["stars_dark_rural_night"]["cloud"] == 0
    assert scenarios["stars_overcast_night"]["cloud"] == 1
    assert scenarios["stars_dark_rural_night"]["start_time"] != scenarios["stars_time_shift_night"]["start_time"]
    from theroadragetrip.geo import meters_to_latlon
    rural=scenarios["stars_dark_rural_night"]
    args=rural["server_args"]
    south,west,north,east=map(float,args[args.index("--bbox")+1].split(","))
    cell_x,cell_y=(int(value//500) for value in rural["pose"][:2])
    for dx in (-1,2):
        for dy in (-1,2):
            latitude,longitude=meters_to_latlon((cell_x+dx)*500,(cell_y+dy)*500)
            assert south<=latitude<=north and west<=longitude<=east, "dark-site lighting context must be inside real source coverage"
