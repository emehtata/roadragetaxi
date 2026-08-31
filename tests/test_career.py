import json

from theroadragetrip.career import (
    career_path,
    gig_odometer_path,
    load_career,
    load_career_distance,
    load_gig_odometer,
    save_career,
    save_gig_odometer,
)


def test_career_progress_is_persistent(tmp_path):
    path = tmp_path / "career.json"

    assert load_career(path, 10) == {"city_index": 0, "completed": False, "total_score": 0}

    save_career(path, 3, 12000)
    assert load_career(path, 10) == {"city_index": 3, "completed": False, "total_score": 12000}

    save_career(path, 9, 50000, completed=True)
    assert load_career(path, 10) == {"city_index": 9, "completed": True, "total_score": 50000}


def test_invalid_career_progress_starts_at_sysma(tmp_path):
    path = tmp_path / "career.json"
    path.write_text("not json", encoding="utf-8")

    assert load_career(path, 10) == {"city_index": 0, "completed": False, "total_score": 0}


def test_career_paths_use_config_directory(tmp_path):
    config_path = tmp_path / "settings.ini"

    assert career_path(config_path) == tmp_path / "career.json"
    assert gig_odometer_path(config_path) == tmp_path / "gig_odometer.json"


def test_load_career_normalizes_invalid_fields(tmp_path):
    path = tmp_path / "career.json"
    path.write_text(json.dumps({"city_index": 99, "completed": "yes", "total_score": "bad"}), encoding="utf-8")

    assert load_career(path, 2) == {"city_index": 0, "completed": True, "total_score": 0}

    path.write_text(json.dumps([]), encoding="utf-8")
    assert load_career(path, 2)["city_index"] == 0


def test_career_distance_and_odometer_handle_invalid_values(tmp_path):
    distance_path = tmp_path / "distance.json"
    odometer_path = tmp_path / "odometer.json"

    assert load_career_distance(distance_path) == 0.0
    assert load_gig_odometer(odometer_path, 4.0) == 4.0

    distance_path.write_text(json.dumps({"total_distance_m": -1}), encoding="utf-8")
    odometer_path.write_text(json.dumps({"odometer_m": "bad"}), encoding="utf-8")
    assert load_career_distance(distance_path) == 0.0
    assert load_gig_odometer(odometer_path, 4.0) == 4.0


def test_save_gig_odometer_clamps_negative_distance(tmp_path):
    path = tmp_path / "nested" / "odometer.json"

    save_gig_odometer(path, -10.0)

    assert json.loads(path.read_text(encoding="utf-8")) == {"odometer_m": 0.0}