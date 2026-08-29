import logging
from pathlib import Path
from typing import Optional

import pygame

logger = logging.getLogger(__name__)


class AudioManager:
    """Load and play optional game sounds without making audio a runtime requirement."""

    def __init__(self) -> None:
        self.enabled = False
        self.sounds: dict[str, pygame.mixer.Sound] = {}
        self.acceleration_channel: Optional[pygame.mixer.Channel] = None

        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            sounds_dir = Path(__file__).with_name("sounds")
            for name in ("accelerate", "car-crash", "carhorn_takes", "city-traffic-outdoor"):
                path = next(
                    (
                        sounds_dir / f"{name}{extension}"
                        for extension in (".wav", ".ogg", ".mp3", ".aiff")
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
                self.sounds["city-traffic-outdoor"].set_volume(0.2)
                self.sounds["city-traffic-outdoor"].play(loops=-1)
            self.enabled = bool(self.sounds)
        except (pygame.error, OSError) as exc:
            logger.info("Audio unavailable: %s", exc)

    def play(self, name: str, volume: float = 1.0) -> None:
        sound = self.sounds.get(name)
        if sound is not None and self.enabled:
            sound.set_volume(volume)
            sound.play()

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

    def close(self) -> None:
        self.update_acceleration(False)
        if self.enabled:
            pygame.mixer.stop()