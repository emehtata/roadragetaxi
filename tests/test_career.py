from theroadragetrip.career import load_career, save_career


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