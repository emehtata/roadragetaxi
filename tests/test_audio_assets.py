"""godot-03.md: the sound assets and every reference to them stay valid
(tools/validate_audio_assets.py); Godot-side loading is in godot/tests."""
import json
import math
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import validate_audio_assets as validator  # noqa: E402


def test_audio_levels_use_standard_library_pcm_math(monkeypatch, tmp_path):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=b"\x00\x00\x00\x40\xff"),
    )

    duration, dbfs = validator._levels(tmp_path / "clip.ogg")

    assert duration == pytest.approx(2 / 44100)
    assert dbfs == pytest.approx(20 * math.log10(math.sqrt(0.5) / 2))


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
