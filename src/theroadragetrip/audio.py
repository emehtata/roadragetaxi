from __future__ import annotations

import logging
import json
import random
import time
from pathlib import Path
from typing import Optional

import pygame

try:
    import pygame.mixer as pygame_mixer
except (ImportError, AttributeError):
    pygame_mixer = None

logger = logging.getLogger(__name__)

CATALOG = Path(__file__).with_name("assets") / "audio" / "audio_catalog.json"
MIXER_CHANNELS = 48  # one-shots plus about a dozen simultaneous ambience loops


class AudioManager:
    """Load and play optional game sounds without making audio a runtime requirement."""

    def __init__(
        self,
        master_volume: float = 0.9,
        music_volume: float = 0.2,
        effects_volume: float = 0.9,
        comments_enabled: bool = True,
        speech_min_interval: float = 5.0,
        speech_max_interval: float = 20.0,
    ) -> None:
        self.enabled = False
        self.master_volume = max(0.0, min(1.0, master_volume))
        self.music_volume = max(0.0, min(1.0, music_volume))
        self.effects_volume = max(0.0, min(1.0, effects_volume))
        self.comments_enabled = comments_enabled
        self.comment_text: Optional[str] = None
        self.comment_speaker = "driver"
        self.comment_speaker_name: Optional[str] = None
        self.comment_timer = 0.0
        self.sounds: dict[str, pygame.mixer.Sound] = {}
        self.passenger_sounds: dict[tuple[str, str, str], pygame.mixer.Sound] = {}
        self.driver_sounds: dict[tuple[str, str, str], pygame.mixer.Sound] = {}
        self._driver_speech_times: dict[str, float] = {}
        self.comment_channel: Optional[pygame.mixer.Channel] = None
        self.acceleration_channel: Optional[pygame.mixer.Channel] = None
        self.police_siren_channel: Optional[pygame.mixer.Channel] = None
        # Sound groups from assets/audio/audio_catalog.json: group id ->
        # its generated variations (a loop group's variations are layers).
        self.groups: dict[str, list[pygame.mixer.Sound]] = {}
        self._last_variation: dict[str, int] = {}
        self._edges: dict[str, bool] = {}
        self.loop_channels: dict[str, pygame.mixer.Channel] = {}
        self._step_timer = 0.0
        self.speech_interval = random.uniform(speech_min_interval, speech_max_interval)
        self.speech_min_interval = speech_min_interval
        self.speech_max_interval = speech_max_interval
        self._speech_lines = self._load_speech_lines()
        self._driver_lines = self._load_driver_lines()

        mixer = pygame_mixer
        if mixer is None:
            logger.info("Audio unavailable: pygame.mixer is not included")
            return
        try:
            if not mixer.get_init():
                mixer.init()
            mixer.set_num_channels(MIXER_CHANNELS)
            sounds_dir = Path(__file__).with_name("sounds")
            for name in ("accelerate", "car-door-open", "censored-cursing", "city-traffic-outdoor", "police_car_siren-esp"):
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
                        self.sounds[name] = mixer.Sound(str(path))
                    except pygame.error as exc:
                        logger.warning("Could not load sound %s: %s", path.name, exc)
            self._load_groups(mixer)
            chatter_dir = sounds_dir / "passenger_chatter"
            for path in chatter_dir.glob("*.wav"):
                parts = path.stem.split("_", 2)
                if len(parts) != 3 or parts[0] not in ("f", "m") or parts[1] not in ("fi", "en"):
                    continue
                try:
                    self.passenger_sounds[(parts[0], parts[1], parts[2])] = mixer.Sound(str(path))
                except pygame.error as exc:
                    logger.warning("Could not load passenger chatter %s: %s", path.name, exc)
            driver_chatter_dir = sounds_dir / "driver_chatter"
            for path in driver_chatter_dir.glob("*.wav"):
                parts = path.stem.split("_", 2)
                if len(parts) != 3 or parts[0] not in ("f", "m") or parts[1] not in ("fi", "en"):
                    continue
                try:
                    self.driver_sounds[(parts[0], parts[1], parts[2])] = mixer.Sound(str(path))
                except pygame.error as exc:
                    logger.warning("Could not load driver chatter %s: %s", path.name, exc)
            self.enabled = bool(self.sounds or self.groups or self.passenger_sounds or self.driver_sounds)
            self.update_ambience()
        except (pygame.error, OSError) as exc:
            logger.info("Audio unavailable: %s", exc)

    def _load_groups(self, mixer) -> None:
        try:
            catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not load the audio catalog: %s", exc)
            return
        for group_id, group in catalog.get("groups", {}).items():
            sounds = []
            for entry in group.get("files", ()):
                if entry.get("status") != "generated":
                    continue
                try:
                    sounds.append(mixer.Sound(str(CATALOG.parent / entry["file"])))
                except (pygame.error, FileNotFoundError) as exc:
                    logger.warning("Could not load sound %s: %s", entry["file"], exc)
            if sounds:
                self.groups[group_id] = sounds

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

    @staticmethod
    def _load_driver_lines() -> list[dict[str, object]]:
        path = Path(__file__).with_name("assets") / "driver_chatter.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            lines = data.get("lines", [])
            return lines if isinstance(lines, list) else []
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not load driver chatter: %s", exc)
            return []

    def play_driver_line(self, situation: str, language: str, gender: str = "man") -> None:
        if self.comment_channel is not None and self.comment_channel.get_busy():
            return
        now = time.monotonic()
        if now - self._driver_speech_times.get(situation, 0.0) < 3.0:
            return
        candidates = [
            line for line in self._driver_lines
            if isinstance(line, dict) and line.get("situation") == situation and line.get(language)
        ]
        if not candidates:
            return
        entry = random.choice(candidates)
        audio_hash = str(entry.get("hash", ""))
        gender_code = "f" if gender == "woman" else "m"
        sound = self.driver_sounds.get((gender_code, language, audio_hash))
        if sound is None and language != "fi":
            sound = self.driver_sounds.get((gender_code, "fi", audio_hash))
        if sound is None or not self.enabled or not self.comments_enabled:
            return
        if not self._play_comment_sound(sound):
            return
        self._set_comment(str(entry.get(language, "")), "driver")
        self._driver_speech_times[situation] = now
        sound.set_volume(self.master_volume * self.effects_volume)
        logger.info("Driver chatter played: situation=%s mood=%s hash=%s", situation, entry.get("mood"), audio_hash)

    def play_passenger_line_for_situation(self, situation: str, gender: str, language: str, speaker_name: Optional[str] = None) -> None:
        moods_by_situation = {
            "collision": {"anxious", "stressed", "bad"},
            "nausea": {"nausea", "anxious"},
            "water": {"anxious", "stressed", "bad"},
            "pickup": {"good", "neutral", "curious"},
            "dropoff": {"good", "sad", "neutral"},
        }
        moods = moods_by_situation.get(situation)
        candidates = [
            line for line in self._speech_lines
            if isinstance(line, dict)
            and line.get(language)
            and (moods is None or line.get("mood") in moods)
        ]
        if not candidates:
            return
        entry = random.choice(candidates)
        audio_hash = str(entry.get("hash"))
        sound = self.passenger_sounds.get(("f" if gender == "woman" else "m", language, audio_hash))
        if sound is None or not self.enabled or not self.comments_enabled:
            return
        sound.set_volume(self.master_volume * self.effects_volume)
        if not self._play_comment_sound(sound):
            return
        self._set_comment(str(entry.get(language, "")), "passenger", speaker_name)

    def update_passenger_speech(self, active: bool, gender: str, language: str, dt: float, speaker_name: Optional[str] = None) -> None:
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
        if sound is not None and self.enabled and self.comments_enabled and self._play_comment_sound(sound):
            self._set_comment(str(entry.get(language, "")), "passenger", speaker_name)
            sound.set_volume(self.master_volume * self.effects_volume)
            logger.info("Passenger chatter played: gender=%s language=%s hash=%s", gender, language, audio_hash)
        self.speech_interval = random.uniform(self.speech_min_interval, self.speech_max_interval)

    def play_passenger_line(self, finnish_text: str, gender: str, language: str, speaker_name: Optional[str] = None) -> None:
        """Play one specific pre-rendered passenger line."""
        entry = next(
            (line for line in self._speech_lines if line.get("fi") == finnish_text),
            None,
        )
        if entry is None:
            return
        audio_hash = entry.get("hash")
        sound = self.passenger_sounds.get(("f" if gender == "woman" else "m", language, str(audio_hash)))
        if sound is None or not self.enabled or not self.comments_enabled:
            return
        sound.set_volume(self.master_volume * self.effects_volume)
        if not self._play_comment_sound(sound):
            return
        self._set_comment(str(entry.get(language, "")), "passenger", speaker_name)

    def _play_comment_sound(self, sound: pygame.mixer.Sound) -> bool:
        if self.comment_channel is not None and self.comment_channel.get_busy():
            return False
        self.comment_channel = sound.play()
        return self.comment_channel is not None

    def _set_comment(self, text: str, speaker: str, speaker_name: Optional[str] = None) -> None:
        if text:
            self.comment_text = text
            self.comment_speaker = speaker
            self.comment_speaker_name = speaker_name
            self.comment_timer = 4.0

    def update_comments(self, dt: float) -> None:
        self.comment_timer = max(0.0, self.comment_timer - dt)
        if self.comment_timer <= 0.0:
            self.comment_text = None

    def set_comments_enabled(self, enabled: bool) -> None:
        self.comments_enabled = enabled

    def play_group(self, group_id: str, volume: float = 1.0, variation: Optional[int] = None) -> None:
        """One variation of a catalog group: the given one (0-based) or a
        random one, never the same twice in a row."""
        sounds = self.groups.get(group_id)
        if not sounds or not self.enabled or volume <= 0.0:
            return
        if variation is None:
            choices = [i for i in range(len(sounds)) if i != self._last_variation.get(group_id)] or [0]
            variation = random.choice(choices)
        self._last_variation[group_id] = variation
        channel = sounds[min(variation, len(sounds) - 1)].play()
        if channel is not None:
            channel.set_volume(min(1.0, self.master_volume * self.effects_volume * volume))

    def on_rise(self, key: str, active: bool, group_id: str, volume: float = 1.0) -> bool:
        """Play group_id when `active` turns true (not every frame it stays true)."""
        rose = active and not self._edges.get(key, False)
        self._edges[key] = active
        if rose:
            self.play_group(group_id, volume)
        return rose

    def set_loop(self, key: str, group_id: str, volume: float, variation: int = 0, music: bool = False) -> None:
        """Keep a looping layer of group_id running at `volume` (0 stops it).
        Music-volume loops are the background beds; the rest are effects."""
        channel = self.loop_channels.get(key)
        sounds = self.groups.get(group_id)
        if volume <= 0.01 or not sounds or not self.enabled:
            if channel is not None:
                channel.stop()
                del self.loop_channels[key]
            return
        if channel is None or not channel.get_busy():
            channel = sounds[min(variation, len(sounds) - 1)].play(loops=-1)
            if channel is None:
                return
            self.loop_channels[key] = channel
        channel.set_volume(min(1.0, self.master_volume * (self.music_volume if music else self.effects_volume) * volume))

    def update_ambience(
        self, night: float = 0.0, rain: float = 0.0, heavy_rain: float = 0.0, wind: float = 0.0,
        strong_wind: float = 0.0, wet_tires: float = 0.0, slush: bool = False,
    ) -> None:
        """Background loops, each 0..1: the day city bed (existing asset)
        crossfades into the night one; rain, wind and wet tyres layer on."""
        day_bed = self.sounds.get("city-traffic-outdoor")
        if day_bed is not None and self.enabled:
            channel = self.loop_channels.get("city_day")
            if channel is None or not channel.get_busy():
                channel = day_bed.play(loops=-1)
                if channel is not None:
                    self.loop_channels["city_day"] = channel
            if channel is not None:
                channel.set_volume(self.master_volume * self.music_volume * (1.0 - night))
        self.set_loop("city_night", "ambient.city_night", night, music=True)
        self.set_loop("rain", "weather.rain", rain, variation=0)
        self.set_loop("rain_heavy", "weather.rain", heavy_rain, variation=1)
        self.set_loop("wind", "weather.wind", wind, variation=0)
        self.set_loop("wind_strong", "weather.wind", strong_wind, variation=1)
        self.set_loop("wet_tires", "weather.wet_road", wet_tires, variation=1 if slush else 0)

    def update_footsteps(self, speed_mps: float, dt: float, running: bool) -> None:
        """The driver's steps on foot: walking steps (variations 1-3) about
        twice a second, running steps (4) faster."""
        if abs(speed_mps) < 0.5:
            self._step_timer = 0.0
            return
        self._step_timer -= dt
        if self._step_timer <= 0.0:
            self.play_group("pedestrian.footsteps", 0.5, 3 if running else random.randrange(3))
            self._step_timer = 0.3 if running else 0.5

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
        # Loops pick up the new volumes on their next update (every frame).

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
        if self.comment_channel is not None:
            self.comment_channel.stop()
            self.comment_channel = None
        self.update_acceleration(False)
        self.update_police_siren(False)
        for channel in self.loop_channels.values():
            channel.stop()
        self.loop_channels.clear()
        mixer = pygame_mixer
        if self.enabled and mixer is not None:
            mixer.stop()
