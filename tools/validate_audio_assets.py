"""Check the game's sound assets and every reference to them.

    SDL_AUDIODRIVER=dummy python tools/validate_audio_assets.py

Problems found (exit 1 if any):
- a catalog file that is missing, not OGG, used by two entries, too quiet to
  be heard at all, or far shorter/longer than its group's duration_s
- a loop group whose files aren't stereo (catalog format) or a one-shot that isn't mono
- a group the game plays (play_group / set_loop / on_rise in src/, or the
  Godot client's audio_events.json) that doesn't exist or has no files
- a Godot loop naming a variation the group doesn't have

Quiet is fine (the night and day beds are meant to be soft): only clips
below SILENT_DBFS - effectively nothing - fail. Whether Godot itself can
load each file is checked by the Godot test suite (make godot-test).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIO_ROOT = ROOT / "src" / "theroadragetrip" / "assets" / "audio"
CATALOG = AUDIO_ROOT / "audio_catalog.json"
GODOT_EVENTS = ROOT / "godot" / "audio" / "audio_events.json"
SILENT_DBFS = -70.0
DURATION_SLACK = (0.4, 2.0)  # a clip may be this fraction of the shortest / this multiple of the longest wanted length
# Groups that are played by the game but are speech libraries kept outside the catalog's SFX files.
SPEECH_GROUPS = {"passenger.chatter", "driver.chatter"}
_GROUP_CALL = re.compile(r"""(?:play_group|set_loop|on_rise)\(\s*(?:"[^"]*"\s*,\s*)?(?:[^,()"]*,\s*)?"([a-z_]+\.[a-z_]+)\"""")


def _levels(path: Path):
    """(duration s, channels, RMS dBFS) of a decoded file, via pygame's mixer."""
    import numpy as np
    import pygame

    if not pygame.mixer.get_init():
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.mixer.init(44100, -16, 2)
    sound = pygame.mixer.Sound(str(path))
    samples = pygame.sndarray.array(sound).astype(np.float64) / 32768.0
    rms = float(np.sqrt(np.mean(samples ** 2))) if samples.size else 0.0
    return sound.get_length(), 20.0 * np.log10(rms) if rms > 1e-9 else -200.0


def _channels(path: Path) -> int:
    """Channel count from the Vorbis identification header (no decoding)."""
    data = path.read_bytes()[:256]
    marker = data.find(b"\x01vorbis")
    return data[marker + 11] if marker >= 0 else 0


def referenced_groups() -> dict[str, list[str]]:
    """Group id -> where the game or the Godot client plays it."""
    found: dict[str, list[str]] = {}
    for path in (ROOT / "src" / "theroadragetrip").rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for group in _GROUP_CALL.findall(line):
                found.setdefault(group, []).append(f"{path.relative_to(ROOT)}:{number}")
    events = json.loads(GODOT_EVENTS.read_text(encoding="utf-8"))
    for key, steps in events.get("events", {}).items():
        for step in steps:
            found.setdefault(step["group"], []).append(f"godot events.{key}")
    for key, loop in events.get("loops", {}).items():
        found.setdefault(loop["group"], []).append(f"godot loops.{key}")
    return found


def validate(check_audio: bool = True) -> list[str]:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    root = AUDIO_ROOT
    one_shot, loop_channels = catalog["format"]["channels"]["one_shot"], catalog["format"]["channels"]["loop"]
    problems: list[str] = []
    owner: dict[str, str] = {}
    for group_id, group in catalog["groups"].items():
        low, high = min(group["duration_s"]), max(group["duration_s"])
        for entry in group["files"]:
            if entry.get("status") != "generated":
                continue
            path = root / entry["file"]
            where = f"{group_id}: {entry['file']}"
            if entry["file"] in owner:
                problems.append(f"{where} is also {owner[entry['file']]}")
            owner[entry["file"]] = entry["id"]
            if path.suffix != ".ogg":
                problems.append(f"{where} is not OGG (Godot loads OGG Vorbis at runtime)")
            if not path.exists():
                problems.append(f"{where} is missing")
                continue
            channels = _channels(path)
            wanted = loop_channels if group["loop"] else one_shot
            if channels != wanted:
                problems.append(f"{where} has {channels} channel(s), a {'loop' if group['loop'] else 'one-shot'} should have {wanted}")
            if check_audio:
                duration, dbfs = _levels(path)
                if dbfs < SILENT_DBFS:
                    problems.append(f"{where} is silent ({dbfs:.0f} dBFS)")
                if duration < low * DURATION_SLACK[0] or duration > high * DURATION_SLACK[1]:
                    problems.append(f"{where} lasts {duration:.2f} s, wanted {low}-{high} s")
    events = json.loads(GODOT_EVENTS.read_text(encoding="utf-8"))
    for group_id, places in sorted(referenced_groups().items()):
        group = catalog["groups"].get(group_id)
        if group is None:
            problems.append(f"{group_id} (played at {places[0]}) is not in the catalog")
        elif group_id not in SPEECH_GROUPS and not any(e.get("status") == "generated" for e in group["files"]):
            problems.append(f"{group_id} (played at {places[0]}) has no files")
    for key, loop in events.get("loops", {}).items():
        group = catalog["groups"].get(loop["group"], {"files": [], "loop": False})
        if not group["loop"]:
            problems.append(f"godot loop {key}: {loop['group']} is not a loop group")
        if loop.get("variation", 0) >= max(1, len(group["files"])):
            problems.append(f"godot loop {key}: variation {loop['variation']} doesn't exist")
    return problems


def main() -> int:
    problems = validate()
    for problem in problems:
        print("PROBLEM:", problem)
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    files = sum(1 for g in catalog["groups"].values() for e in g["files"] if e.get("status") == "generated")
    print(f"{files} files in {len(catalog['groups'])} groups, {len(referenced_groups())} groups referenced: "
          f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
