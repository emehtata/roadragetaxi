"""Railway station announcements, assembled from the clip library in
assets/railway_announcements (manifest.json, see its README.md): when a
long-distance train arrives at or leaves a station, the station's
loudspeakers say e.g. "Hyvät matkustajat. InterCity viisikymmentäseitsemän
Helsingistä saapuu raiteelle kolme." Heard from the platform, fading with
distance like the other located sounds (audio.SPATIAL_RANGES_M).
"""
from __future__ import annotations

import json
import logging
import time
from collections import deque
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

ASSET_DIR = Path(__file__).with_name("assets") / "railway_announcements"
MAX_SPOKEN_NUMBER = 999  # the clip set covers 0-999 (manifest numbers)
MAX_WAIT_S = 20.0  # a queued announcement older than this (real seconds) is dropped as stale


def number_components(value: int) -> List[int]:
    """Finnish number parts, largest first: 523 -> [500, 20, 3], 519 ->
    [500, 19] (11-19 are words of their own), 1008 -> [1000, 8]. Same
    rule as ai-audio-studio/announcements.py, which made the clips."""
    if value == 0:
        return [0]
    parts = []
    thousands, rest = divmod(value, 1000)
    hundreds, rest = divmod(rest, 100)
    if thousands:
        parts.append(thousands * 1000)
    if hundreds:
        parts.append(hundreds * 100)
    if 11 <= rest <= 19:
        parts.append(rest)
    else:
        if rest >= 10:
            parts.append(rest // 10 * 10)
        if rest % 10:
            parts.append(rest % 10)
    return parts


class AnnouncementScript:
    """Turns a train event into the list of clip files to play, from the
    manifest alone (no audio needed - testable)."""

    def __init__(self, manifest: dict) -> None:
        self.manifest = manifest
        self.numbers = {
            int(value): entry["file"]
            for group in manifest.get("numbers", {}).values() for value, entry in group.items()
        }
        self.train_types = {entry.get("train_type"): entry["file"] for entry in manifest.get("train_types", {}).values()}
        # Places by their written name (default_text when the spoken text was corrected).
        self.place_ids = {
            entry.get("default_text", entry["text"]): place_id for place_id, entry in manifest.get("places", {}).items()
        }

    def _file(self, category: str, key: str) -> Optional[str]:
        entry = self.manifest.get(category, {}).get(key)
        return entry["file"] if entry else None

    def _number(self, value) -> List[str]:
        try:
            value = int(str(value).strip())
        except ValueError:
            return []
        if not 0 <= value <= MAX_SPOKEN_NUMBER:
            return []
        files = [self.numbers.get(part) for part in number_components(value)]
        return files if all(files) else []

    def _place(self, name: str, form: str) -> List[str]:
        place_id = self.place_ids.get(name)
        file = self._file(form, place_id) if place_id else None
        return [file] if file else []

    def phrases(self, kind: str, train_type: str, number, station: str, origin: str, destination: str,
                track: str) -> List[List[str]]:
        """The announcement as phrases (clip files said together, a short
        pause between phrases - never inside a number, which would turn
        "kaksikymmentä kaksi" into "20 ... 2"). kind "arrived": [attention]
        [type number] [from origin] [saapuu] [raiteelle track]; "departed":
        [type number] [to destination] [lähtee] [raiteelta track]. [] when
        the train type has no clip (commuter trains) - no announcement."""
        train_file = self.train_types.get(train_type)
        if train_file is None:
            return []
        if kind == "arrived":
            place = self._place(origin, "places_from") if origin and origin != station else []
            verb, platform = "arriving", "raiteelle"
        else:
            place = self._place(destination, "places_to") if destination and destination != station else []
            verb, platform = "departing", "raiteelta"
        phrases = [[train_file] + self._number(number), place, [f for f in (self._file("phrases", verb),) if f]]
        track_files = self._number(track)
        if track_files and self._file("platforms", platform):
            phrases.append([self._file("platforms", platform)] + track_files)
        if kind == "arrived" and self._file("phrases", "attention"):
            phrases.insert(0, [self._file("phrases", "attention")])
        return [phrase for phrase in phrases if phrase]

    def files(self, *args) -> List[str]:
        """The phrases' clip files in order."""
        return [file for phrase in self.phrases(*args) for file in phrase]


class StationAnnouncer:
    """Plays one announcement at a time; others wait their turn in a short
    queue (a train's departure soon after its arrival, two trains at once)
    and are dropped once stale. update() every frame starts the next."""

    def __init__(self, asset_dir: Path = ASSET_DIR) -> None:
        self.asset_dir = asset_dir
        self.script: Optional[AnnouncementScript] = None
        self._clips = {}
        self._channel = None
        self._queue = deque()  # (queued at, sound, position, log text)
        try:
            manifest = json.loads((asset_dir / "manifest.json").read_text(encoding="utf-8"))
            self.script = AnnouncementScript(manifest)
            self._pause = self.script._file("connectors", "pause_short")
        except (OSError, ValueError) as exc:
            logger.info("Station announcements unavailable: %s", exc)

    def _clip(self, file: str):
        import pygame

        if file not in self._clips:
            self._clips[file] = pygame.mixer.Sound(str(self.asset_dir / file))
        return self._clips[file]

    def announce(self, audio, kind: str, train, stop, position) -> bool:
        """A train event at a station (stop: the train's stop tuple) - queue
        its announcement, from the platform, if anyone could hear it."""
        if self.script is None or not getattr(audio, "enabled", False) or train.service is None or stop is None:
            return False
        if max(audio.levels("railway.announcement", 1.0, at=position)) <= 0.0:
            return False  # too far from the station to hear
        service = train.service
        phrases = self.script.phrases(kind, service.train_type, service.number, stop[2], service.origin,
                                      service.destination, stop[6] if len(stop) > 6 else "")
        if not phrases:
            return False
        import pygame

        try:
            pause = [self._clip(self._pause).get_raw()] if self._pause else []
            parts = []
            for index, phrase in enumerate(phrases):
                if index:
                    parts += pause
                parts += [self._clip(file).get_raw() for file in phrase]
            sound = pygame.mixer.Sound(buffer=b"".join(parts))
        except (pygame.error, OSError) as exc:
            logger.warning("Could not assemble a station announcement: %s", exc)
            return False
        self._queue.append((time.monotonic(), sound, position,
                            f"{stop[2]}: {service.train_type} {service.number} ({kind})"))
        self.update(audio)
        return True

    def update(self, audio) -> None:
        """Start the next queued announcement once the loudspeakers are free."""
        if self._channel is not None and self._channel.get_busy():
            return
        while self._queue:
            queued_at, sound, position, text = self._queue.popleft()
            if time.monotonic() - queued_at > MAX_WAIT_S:
                continue  # stale: the train is long gone
            left, right = audio.levels("railway.announcement", 1.0, at=position)
            self._channel = sound.play()
            if self._channel is not None:
                self._channel.set_volume(left, right)
                logger.info("Station announcement at %s", text)
            return
