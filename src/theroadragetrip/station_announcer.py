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
        # (timetable type code, timetable category or None for any) -> clip.
        # Two H: long-distance H (Iisalmi-Ylivieska) is a "taajamajuna",
        # commuter H the Hanko line, said as "lähijuna" + its letter.
        self.train_types = {
            (entry.get("train_type"), entry.get("train_category")): entry["file"]
            for entry in manifest.get("train_types", {}).values()
        }
        self.lines = {entry["line"]: entry["file"] for entry in manifest.get("lines", {}).values() if "line" in entry}
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

    def train_phrase(self, train_type: str, category: str = "") -> List[str]:
        """The clips naming the train: "InterCity", "taajamajuna" (H,
        long-distance), "lähijuna" + line letter (commuter). [] for a type
        with no clip - never some other type."""
        if category == "commuter":
            commuter, line = self.train_types.get(("", "commuter")), self.lines.get(train_type)
            return [commuter, line] if commuter and line else []
        file = self.train_types.get((train_type, category)) or self.train_types.get((train_type, None))
        return [file] if file else []

    def phrases(self, kind: str, train_type: str, number, station: str, origin: str, destination: str,
                track: str, category: str = "") -> List[List[str]]:
        """The announcement as phrases (clip files said together, a short
        pause between phrases - never inside a number, which would turn
        "kaksikymmentä kaksi" into "20 ... 2"). kind "arrived": [attention]
        [type number] [from origin] [saapuu] [raiteelle track]; "departed":
        [type number] [to destination] [lähtee] [raiteelta track]. [] when
        the train type has no clip (commuter trains) - no announcement."""
        train = self.train_phrase(train_type, category)
        if not train:
            return []
        if kind == "arrived":
            place = self._place(origin, "places_from") if origin and origin != station else []
            verb, platform = "arriving", "raiteelle"
        else:
            place = self._place(destination, "places_to") if destination and destination != station else []
            verb, platform = "departing", "raiteelta"
        phrases = [train + self._number(number), place, [f for f in (self._file("phrases", verb),) if f]]
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
    """Plays announcements clip by clip on the mixer's reserved
    announcement channel (audio.ANNOUNCEMENT_CHANNEL): each asset is its own
    cached Sound, the next one starts only when the channel has finished the
    previous one, with a short connector pause between phrases. Whole
    announcements queue (an arrival and its train's departure, two trains
    at once); one still waiting after MAX_WAIT_S is dropped as stale.
    update() runs every frame and never blocks."""

    def __init__(self, asset_dir: Path = ASSET_DIR) -> None:
        self.asset_dir = asset_dir
        self.script: Optional[AnnouncementScript] = None
        self._pause = None
        self._clips = {}  # asset file -> pygame.mixer.Sound, loaded once
        self._channel = None
        self._queue = deque()  # waiting announcements: (queued at, clip files, position, log text)
        self._playing = None  # the announcement on air: [remaining clip files, position]
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

    def _announcement_channel(self):
        if self._channel is None:
            import pygame

            from .audio import ANNOUNCEMENT_CHANNEL

            self._channel = pygame.mixer.Channel(ANNOUNCEMENT_CHANNEL)
        return self._channel

    def clips(self, phrases: List[List[str]]) -> List[str]:
        """The clip files in playing order: a connector pause between
        phrases, none inside one (a number stays one word: "kaksikymmentä
        kaksi")."""
        clips = []
        for index, phrase in enumerate(phrases):
            if index and self._pause:
                clips.append(self._pause)
            clips.extend(phrase)
        return clips

    def announce(self, audio, kind: str, train, stop, position) -> bool:
        """A train event at a station (stop: the train's stop tuple) - queue
        its announcement, from the platform, if anyone could hear it."""
        if self.script is None or not getattr(audio, "enabled", False) or train.service is None or stop is None:
            return False
        if max(audio.levels("railway.announcement", 1.0, at=position)) <= 0.0:
            return False  # too far from the station to hear
        service = train.service
        phrases = self.script.phrases(kind, service.train_type, service.number, stop[2], service.origin,
                                      service.destination, stop[6] if len(stop) > 6 else "",
                                      getattr(service, "category", ""))
        if not phrases:
            return False
        self._queue.append((time.monotonic(), self.clips(phrases), position,
                            f"{stop[2]}: {service.train_type} {service.number} ({kind})"))
        self.update(audio)
        return True

    def update(self, audio) -> None:
        """Every frame: while a clip plays, nothing; when it has finished,
        start the next clip of the announcement on air, else the next
        announcement still worth playing."""
        channel = self._announcement_channel()
        if channel.get_busy():
            return
        if not (self._playing and self._playing[0]):
            self._playing = None
            while self._queue:
                queued_at, files, position, text = self._queue.popleft()
                if time.monotonic() - queued_at <= MAX_WAIT_S:
                    self._playing = [deque(files), position]
                    logger.info("Station announcement at %s", text)
                    break  # older ones: stale, the train is long gone
            if self._playing is None:
                return
        files, position = self._playing
        try:
            sound = self._clip(files.popleft())
        except Exception as exc:  # pygame.error/OSError: a missing or broken clip is skipped, the rest still plays
            logger.warning("Station announcement clip unavailable: %s", exc)
            return
        channel.play(sound)
        # Volume of where the station is now, seen from where the player is now.
        channel.set_volume(*audio.levels("railway.announcement", 1.0, at=position))
