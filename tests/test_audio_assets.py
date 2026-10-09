"""godot-03.md: the sound assets and every reference to them stay valid
(tools/validate_audio_assets.py); Godot-side loading is in godot/tests."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import validate_audio_assets as validator  # noqa: E402


def test_every_sound_asset_and_reference_is_valid():
    assert validator.validate() == []


def test_the_validator_catches_a_broken_catalog(tmp_path, monkeypatch):
    catalog = json.loads(validator.CATALOG.read_text(encoding="utf-8"))
    door = catalog["groups"]["vehicle.door_open"]["files"]
    door[0]["file"] = "vehicle/no_such_door.ogg"
    door[1]["file"] = door[2]["file"]  # the same file under two ids
    catalog["groups"]["ambient.city_day"]["files"] = []  # a played loop with nothing to play
    broken = tmp_path / "audio_catalog.json"
    broken.write_text(json.dumps(catalog), encoding="utf-8")
    monkeypatch.setattr(validator, "CATALOG", broken)
    problems = "\n".join(validator.validate(check_audio=False))
    assert "no_such_door.ogg is missing" in problems
    assert "is also vehicle.door_open.02" in problems
    assert "ambient.city_day (played at" in problems and "has no files" in problems
