"""Driver and passenger speech selection (godot-final-07), pygame-free.

The chatter catalogs (assets/passenger_chatter.json, driver_chatter.json)
and the rules that choose a line live here once. Pygame's AudioManager
plays the chosen line on its comment channel; the server's EventAudio sends
it to the clients as a "speech" event. A line is a recorded file
sounds/<speaker>_chatter/<g>_<language>_<hash>.wav, g "f" or "m".

The rules (audio.py's, unchanged):
- one line at a time: nothing while the last one still plays
- a driver line at most once per situation every 3 s, requested language,
  else the Finnish recording (the subtitle keeps the requested text)
- a passenger situation line from that situation's moods
- passenger chatter at random intervals while a passenger rides
- a specific passenger line by its Finnish text
"""

from __future__ import annotations

import json
import logging
import random
import wave
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

PACKAGE = Path(__file__).parent
CATALOGS = {"passenger": PACKAGE / "assets" / "passenger_chatter.json", "driver": PACKAGE / "assets" / "driver_chatter.json"}
SOUND_DIRS = {"passenger": PACKAGE / "sounds" / "passenger_chatter", "driver": PACKAGE / "sounds" / "driver_chatter"}
DRIVER_COOLDOWN_S = 3.0
SUBTITLE_S = 4.0  # how long the subtitle stays
MOODS_BY_SITUATION = {
    "collision": {"anxious", "stressed", "bad"},
    "nausea": {"nausea", "anxious"},
    "water": {"anxious", "stressed", "bad"},
    "pickup": {"good", "neutral", "curious"},
    "dropoff": {"good", "sad", "neutral"},
}


def load_lines(speaker: str) -> list:
    try:
        lines = json.loads(CATALOGS[speaker].read_text(encoding="utf-8")).get("lines", [])
        return lines if isinstance(lines, list) else []
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not load %s chatter: %s", speaker, exc)
        return []


def recorded_lines(speaker: str) -> dict:
    """(g, language, hash) -> clip seconds, for the recordings on disk (WAV
    headers only, no audio device)."""
    found = {}
    for path in SOUND_DIRS[speaker].glob("*.wav"):
        parts = path.stem.split("_", 2)
        if len(parts) != 3 or parts[0] not in ("f", "m") or parts[1] not in ("fi", "en"):
            continue
        try:
            with wave.open(str(path)) as clip:
                found[tuple(parts)] = clip.getnframes() / float(clip.getframerate() or 1)
        except (OSError, wave.Error, EOFError):
            continue
    return found


def gender_code(gender: str) -> str:
    return "f" if gender == "woman" else "m"


class Speech:
    """Chooses lines. `available(speaker, key)` says whether a recording can
    play (Pygame: a loaded Sound; the server: a file on disk); `rng` is the
    random source (tests inject one)."""

    def __init__(self, available: Callable[[str, tuple], bool], rng=random,
                 min_interval: float = 5.0, max_interval: float = 20.0) -> None:
        self.available = available
        self.rng = rng
        self.lines = {"passenger": load_lines("passenger"), "driver": load_lines("driver")}
        self.min_interval, self.max_interval = min_interval, max_interval
        self.interval = rng.uniform(min_interval, max_interval)
        self._driver_times: dict = {}

    def driver(self, situation: str, language: str, gender: str, now: float, busy: bool) -> Optional[dict]:
        if busy or now - self._driver_times.get(situation, -1e9) < DRIVER_COOLDOWN_S:
            return None
        candidates = [line for line in self.lines["driver"]
                      if isinstance(line, dict) and line.get("situation") == situation and line.get(language)]
        if not candidates:
            return None
        entry = self.rng.choice(candidates)
        key = (gender_code(gender), language, str(entry.get("hash", "")))
        if not self.available("driver", key) and language != "fi":
            key = (key[0], "fi", key[2])  # the Finnish recording; the subtitle stays in `language`
        if not self.available("driver", key):
            return None
        self._driver_times[situation] = now
        return self._line("driver", key, entry, language, None)

    def passenger_for_situation(self, situation: str, gender: str, language: str, speaker_name: Optional[str], busy: bool) -> Optional[dict]:
        moods = MOODS_BY_SITUATION.get(situation)
        candidates = [line for line in self.lines["passenger"]
                      if isinstance(line, dict) and line.get(language) and (moods is None or line.get("mood") in moods)]
        if not candidates:
            return None
        return self._passenger(self.rng.choice(candidates), gender, language, speaker_name, busy)

    def passenger_tick(self, active: bool, gender: str, language: str, dt: float, speaker_name: Optional[str], busy: bool) -> Optional[dict]:
        """Occasional chatter while a passenger rides; the interval restarts
        after every attempt (played or not), as audio.py's."""
        if not active:
            self.interval = self.rng.uniform(self.min_interval, self.max_interval)
            return None
        self.interval -= dt
        if self.interval > 0.0:
            return None
        candidates = [line for line in self.lines["passenger"] if isinstance(line, dict) and line.get(language)]
        if not candidates:
            return None
        line = self._passenger(self.rng.choice(candidates), gender, language, speaker_name, busy)
        self.interval = self.rng.uniform(self.min_interval, self.max_interval)
        return line

    def passenger_line(self, finnish_text: str, gender: str, language: str, speaker_name: Optional[str], busy: bool) -> Optional[dict]:
        entry = next((line for line in self.lines["passenger"] if isinstance(line, dict) and line.get("fi") == finnish_text), None)
        return self._passenger(entry, gender, language, speaker_name, busy) if entry is not None else None

    def _passenger(self, entry: dict, gender: str, language: str, speaker_name, busy: bool) -> Optional[dict]:
        key = (gender_code(gender), language, str(entry.get("hash")))
        if busy or not self.available("passenger", key):
            return None
        return self._line("passenger", key, entry, language, speaker_name)

    @staticmethod
    def _line(speaker: str, key: tuple, entry: dict, language: str, speaker_name) -> dict:
        # No text in `language`: the recording still plays, without a subtitle (as audio.py).
        return {"speaker": speaker, "key": key, "text": str(entry.get(language, "") or ""), "speaker_name": speaker_name, "mood": entry.get("mood")}
