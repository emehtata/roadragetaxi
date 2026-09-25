"""AudioManager's catalog sound groups: random variations, rising-edge
triggers and loops (no real mixer needed)."""
from types import SimpleNamespace

from theroadragetrip.audio import AudioManager


class FakeChannel:
    def __init__(self):
        self.volume, self.busy = None, True

    def set_volume(self, volume):
        self.volume = volume

    def get_busy(self):
        return self.busy

    def stop(self):
        self.busy = False


class FakeSound:
    def __init__(self, log, name):
        self.log, self.name = log, name

    def play(self, loops=0):
        self.log.append((self.name, loops))
        return FakeChannel()


def manager(groups):
    audio = AudioManager.__new__(AudioManager)  # skip the real mixer
    log = []
    audio.enabled, audio.master_volume, audio.effects_volume, audio.music_volume = True, 1.0, 1.0, 1.0
    audio.groups = {gid: [FakeSound(log, f"{gid}#{i}") for i in range(n)] for gid, n in groups.items()}
    audio._last_variation, audio._edges, audio.loop_channels, audio.sounds = {}, {}, {}, {}
    return audio, log


def test_random_variations_never_repeat_back_to_back():
    audio, log = manager({"weather.thunder": 6})
    for _ in range(50):
        audio.play_group("weather.thunder")
    names = [name for name, _ in log]
    assert all(a != b for a, b in zip(names, names[1:]))
    assert len(set(names)) > 3


def test_on_rise_plays_once_per_rising_edge():
    audio, log = manager({"collision.building": 4})
    for touching in (True, True, True, False, True):
        audio.on_rise("crash", touching, "collision.building")
    assert len(log) == 2


def test_loops_start_once_follow_volume_and_stop_at_zero():
    audio, log = manager({"weather.rain": 2})
    audio.set_loop("rain", "weather.rain", 0.5, variation=1)
    audio.set_loop("rain", "weather.rain", 0.8, variation=1)
    assert log == [("weather.rain#1", -1)] and audio.loop_channels["rain"].volume == 0.8
    channel = audio.loop_channels["rain"]
    audio.set_loop("rain", "weather.rain", 0.0)
    assert "rain" not in audio.loop_channels and not channel.busy


def test_every_generated_catalog_group_loads_from_its_files():
    import json
    from theroadragetrip.audio import CATALOG

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    for group in catalog["groups"].values():
        for entry in group["files"]:
            if entry["status"] == "generated":
                assert (CATALOG.parent / entry["file"]).is_file(), entry["file"]
