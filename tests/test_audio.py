import pygame

import theroadragetrip.audio as audio
from theroadragetrip.audio import AudioManager


class FakeChannel:
    def __init__(self, busy):
        self.busy = busy

    def get_busy(self):
        return self.busy

    def stop(self):
        self.busy = False


class FakeSound:
    def __init__(self, channel):
        self.channel = channel
        self.play_count = 0

    def play(self):
        self.play_count += 1
        return self.channel


def test_audio_manager_handles_missing_pygame_mixer(monkeypatch):
    monkeypatch.setattr(audio, "pygame_mixer", None)

    manager = AudioManager()

    assert manager.enabled is False


def test_comment_sound_does_not_overlap_existing_comment():
    manager = object.__new__(AudioManager)
    manager.comment_channel = FakeChannel(busy=True)
    sound = FakeSound(FakeChannel(busy=False))

    assert manager._play_comment_sound(sound) is False
    assert sound.play_count == 0


def test_comment_sound_uses_free_channel():
    manager = object.__new__(AudioManager)
    manager.comment_channel = FakeChannel(busy=False)
    sound = FakeSound(FakeChannel(busy=True))

    assert manager._play_comment_sound(sound) is True
    assert sound.play_count == 1
    assert manager.comment_channel is sound.channel