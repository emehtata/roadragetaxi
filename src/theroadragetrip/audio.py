import logging
import json
import random
import shutil
import subprocess
import tempfile
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Optional, Tuple

import pygame

logger = logging.getLogger(__name__)


class AudioManager:
    """Load and play optional game sounds without making audio a runtime requirement."""

    def __init__(
        self,
        master_volume: float = 1.0,
        music_volume: float = 0.2,
        effects_volume: float = 1.0,
        speech_enabled: bool = False,
        piper_command: str = "piper",
        piper_fi_model: str = "",
        piper_en_model: str = "",
        speech_min_interval: float = 18.0,
        speech_max_interval: float = 35.0,
    ) -> None:
        self.enabled = False
        self.master_volume = max(0.0, min(1.0, master_volume))
        self.music_volume = max(0.0, min(1.0, music_volume))
        self.effects_volume = max(0.0, min(1.0, effects_volume))
        self.sounds: dict[str, pygame.mixer.Sound] = {}
        self.acceleration_channel: Optional[pygame.mixer.Channel] = None
        self.police_siren_channel: Optional[pygame.mixer.Channel] = None
        self.speech_enabled = speech_enabled
        self.piper_command = piper_command
        self.piper_models = {
            "fi": self._find_piper_model("fi", piper_fi_model),
            "en": self._find_piper_model("en", piper_en_model),
        }
        self.speech_interval = random.uniform(speech_min_interval, speech_max_interval)
        self.speech_min_interval = speech_min_interval
        self.speech_max_interval = speech_max_interval
        self._speech_lines = self._load_speech_lines()
        self._speech_executor: Optional[ThreadPoolExecutor] = None
        self._speech_future: Optional[Future[str]] = None
        self._speech_sound: Optional[pygame.mixer.Sound] = None

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
            if "city-traffic-outdoor" in self.sounds:
                self.sounds["city-traffic-outdoor"].set_volume(self.master_volume * self.music_volume)
                self.sounds["city-traffic-outdoor"].play(loops=-1)
            self.enabled = bool(self.sounds)
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

    @staticmethod
    def _find_piper_model(language: str, configured_path: str) -> str:
        if configured_path:
            return configured_path
        voice_name = {
            "fi": "fi_FI-harri-medium.onnx",
            "en": "en_US-lessac-medium.onnx",
        }.get(language, "")
        default_path = Path.home() / ".local" / "share" / "RoadRageTrip" / "voices" / voice_name
        return str(default_path) if default_path.is_file() else ""

    def update_passenger_speech(self, active: bool, language: str, dt: float) -> None:
        """Generate and play occasional passenger chatter through Piper."""
        self._finish_speech()
        if not active:
            self.speech_interval = random.uniform(self.speech_min_interval, self.speech_max_interval)
            return
        self.speech_interval -= dt
        if self.speech_interval > 0.0 or self._speech_future is not None:
            return
        model = self.piper_models.get(language, self.piper_models.get("fi", ""))
        if not self.speech_enabled or not model or not Path(model).is_file():
            self.speech_interval = random.uniform(self.speech_min_interval, self.speech_max_interval)
            return
        if shutil.which(self.piper_command) is None:
            logger.warning("Piper command not found: %s", self.piper_command)
            self.speech_enabled = False
            return
        candidates = [line for line in self._speech_lines if isinstance(line, dict) and line.get(language)]
        if not candidates:
            return
        text = str(random.choice(candidates)[language])
        self._speech_executor = self._speech_executor or ThreadPoolExecutor(max_workers=1)
        self._speech_future = self._speech_executor.submit(self._synthesize_speech, text, model)
        self.speech_interval = random.uniform(self.speech_min_interval, self.speech_max_interval)

    def _synthesize_speech(self, text: str, model: str) -> str:
        output = tempfile.NamedTemporaryFile(prefix="roadrage-speech-", suffix=".wav", delete=False)
        output_path = output.name
        output.close()
        try:
            subprocess.run(
                [self.piper_command, "--model", model, "--output_file", output_path],
                input=text,
                text=True,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            return output_path
        except (OSError, subprocess.CalledProcessError) as exc:
            Path(output_path).unlink(missing_ok=True)
            logger.warning("Piper speech generation failed: %s", exc)
            return ""

    def _finish_speech(self) -> None:
        if self._speech_future is None or not self._speech_future.done():
            return
        output_path = self._speech_future.result()
        self._speech_future = None
        if not output_path:
            return
        try:
            self._speech_sound = pygame.mixer.Sound(output_path)
            self._speech_sound.set_volume(self.master_volume * self.effects_volume)
            if self.enabled:
                self._speech_sound.play()
        except (OSError, pygame.error) as exc:
            logger.warning("Could not play Piper speech: %s", exc)
        finally:
            Path(output_path).unlink(missing_ok=True)

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
        if self._speech_executor is not None:
            self._speech_executor.shutdown(wait=False, cancel_futures=True)
            self._speech_executor = None
        self.update_acceleration(False)
        self.update_police_siren(False)
        if self.enabled:
            pygame.mixer.stop()