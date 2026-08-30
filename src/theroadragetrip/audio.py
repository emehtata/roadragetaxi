import logging
import json
import random
from pathlib import Path
from typing import Optional

import pygame

logger = logging.getLogger(__name__)


class AudioManager:
    """Load and play optional game sounds without making audio a runtime requirement."""

    def __init__(
        self,
        master_volume: float = 0.9,
        music_volume: float = 0.2,
        effects_volume: float = 0.9,
        speech_min_interval: float = 5.0,
        speech_max_interval: float = 20.0,
    ) -> None:
        self.enabled = False
        self.master_volume = max(0.0, min(1.0, master_volume))
        self.music_volume = max(0.0, min(1.0, music_volume))
        self.effects_volume = max(0.0, min(1.0, effects_volume))
        self.sounds: dict[str, pygame.mixer.Sound] = {}
        self.passenger_sounds: dict[tuple[str, str, str], pygame.mixer.Sound] = {}
        self.acceleration_channel: Optional[pygame.mixer.Channel] = None
        self.police_siren_channel: Optional[pygame.mixer.Channel] = None
        self.speech_interval = random.uniform(speech_min_interval, speech_max_interval)
        self.speech_min_interval = speech_min_interval
        self.speech_max_interval = speech_max_interval
        self._speech_lines = self._load_speech_lines()

        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            sounds_dir = Path(__file__).with_name("sounds")
            for name in ("accelerate", "car-crash", "carhorn_takes", "car-door-open", "city-traffic-outdoor", "police_car_siren-esp"):
                path = next(
                    (
                        sounds_dir / f"{name}{extension}"
                        for extension in (".wav", ".ogg", ".mp3", ".aiff", ".flac")
                        if (sounds_dir / f"{name}{extension}").exists()
                    ),
                    None,
                )
                if path is not None:
                    try:
                        self.sounds[name] = pygame.mixer.Sound(str(path))
                    except pygame.error as exc:
                        logger.warning("Could not load sound %s: %s", path.name, exc)
            chatter_dir = sounds_dir / "passenger_chatter"
            for path in chatter_dir.glob("*.wav"):
                parts = path.stem.split("_", 2)
                if len(parts) != 3 or parts[0] not in ("f", "m") or parts[1] not in ("fi", "en"):
                    continue
                try:
                    self.passenger_sounds[(parts[0], parts[1], parts[2])] = pygame.mixer.Sound(str(path))
                except pygame.error as exc:
                    logger.warning("Could not load passenger chatter %s: %s", path.name, exc)
            if "city-traffic-outdoor" in self.sounds:
                self.sounds["city-traffic-outdoor"].set_volume(self.master_volume * self.music_volume)
                self.sounds["city-traffic-outdoor"].play(loops=-1)
            self.enabled = bool(self.sounds or self.passenger_sounds)
        except (pygame.error, OSError) as exc:
            logger.info("Audio unavailable: %s", exc)

    @staticmethod
    def _load_speech_lines() -> list[dict[str, object]]:
        path = Path(__file__).with_name("assets") / "passenger_chatter.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            lines = data.get("lines", [])
            return lines if isinstance(lines, list) else []
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not load passenger chatter: %s", exc)
            return []

    def update_passenger_speech(self, active: bool, gender: str, language: str, dt: float) -> None:
        """Play occasional pre-rendered chatter matching the passenger's gender."""
        if not active:
            self.speech_interval = random.uniform(self.speech_min_interval, self.speech_max_interval)
            return
        self.speech_interval -= dt
        if self.speech_interval > 0.0:
            return
        candidates = [line for line in self._speech_lines if isinstance(line, dict) and line.get(language)]
        if not candidates:
            return
        entry = random.choice(candidates)
        gender_code = "f" if gender == "woman" else "m"
        audio_hash = entry.get("hash")
        sound = self.passenger_sounds.get((gender_code, language, str(audio_hash)))
        if sound is not None and self.enabled:
            sound.set_volume(self.master_volume * self.effects_volume)
            sound.play()
            logger.info("Passenger chatter played: gender=%s language=%s hash=%s", gender, language, audio_hash)
        self.speech_interval = random.uniform(self.speech_min_interval, self.speech_max_interval)

    def play_passenger_line(self, finnish_text: str, gender: str, language: str) -> None:
        """Play one specific pre-rendered passenger line."""
        entry = next(
            (line for line in self._speech_lines if line.get("fi") == finnish_text),
            None,
        )
        if entry is None:
            return
        audio_hash = entry.get("hash")
        sound = self.passenger_sounds.get(("f" if gender == "woman" else "m", language, str(audio_hash)))
        if sound is None or not self.enabled:
            return
        sound.set_volume(self.master_volume * self.effects_volume)
        sound.play()

    def play(self, name: str, volume: float = 1.0) -> None:
        sound = self.sounds.get(name)
        if sound is not None and self.enabled:
            sound.set_volume(self.master_volume * self.effects_volume * volume)
            sound.play()

    def set_volume(self, kind: str, value: float) -> None:
        value = max(0.0, min(1.0, value))
        if kind == "master":
            self.master_volume = value
        elif kind == "music":
            self.music_volume = value
        elif kind == "effects":
            self.effects_volume = value
        if "city-traffic-outdoor" in self.sounds:
            self.sounds["city-traffic-outdoor"].set_volume(self.master_volume * self.music_volume)

    def update_acceleration(self, active: bool) -> None:
        sound = self.sounds.get("accelerate")
        if sound is None or not self.enabled:
            return
        if active:
            if self.acceleration_channel is None or not self.acceleration_channel.get_busy():
                self.acceleration_channel = sound.play(loops=-1)
        elif self.acceleration_channel is not None:
            self.acceleration_channel.stop()
            self.acceleration_channel = None

    def update_police_siren(self, active: bool) -> None:
        sound = self.sounds.get("police_car_siren-esp")
        if sound is None or not self.enabled:
            return
        if active:
            if self.police_siren_channel is None or not self.police_siren_channel.get_busy():
                self.police_siren_channel = sound.play(loops=-1)
        elif self.police_siren_channel is not None:
            self.police_siren_channel.stop()
            self.police_siren_channel = None

    def close(self) -> None:
        self.update_acceleration(False)
        self.update_police_siren(False)
        if self.enabled:
            pygame.mixer.stop()