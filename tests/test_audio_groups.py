"""AudioManager's catalog sound groups: random variations, rising-edge
triggers and loops (no real mixer needed)."""
from types import SimpleNamespace

from theroadragetrip.audio import SPATIAL_RANGES_M, AudioManager, spatial_levels


class FakeChannel:
    def __init__(self):
        self.volume, self.busy = None, True

    def set_volume(self, left, right=None):
        self.volume = left if right is None or right == left else (left, right)

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
    audio.listener = audio.player_position = None
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


def test_engine_layers_crossfade_with_speed_and_stop_standing_still():
    audio, log = manager({"vehicle.engine_accelerate": 3})

    def playing():
        return {key: round(ch.volume, 2) for key, ch in audio.loop_channels.items()}

    audio.update_engine(True, 20.0 / 3.6, throttle=1.0)
    assert set(playing()) == {"engine_0"}  # city speed: low revs only
    audio.update_engine(True, 55.0 / 3.6, throttle=0.0)
    assert playing()["engine_1"] > playing()["engine_0"]  # coasting quieter, mid revs lead
    audio.update_engine(True, 100.0 / 3.6, throttle=1.0)
    assert set(playing()) == {"engine_2"} and playing()["engine_2"] == 0.7  # motorway: high revs, full throttle
    audio.update_engine(True, 0.0, throttle=1.0)
    assert playing() == {}  # standing still: the idle loop's job


def test_distant_sounds_fade_gradually_to_silence_and_pan_to_their_side():
    full_m, silent_m = SPATIAL_RANGES_M["railway.train_running"]
    heard = [max(spatial_levels((0.0, 0.0), (0.0, d), full_m, silent_m)) for d in range(0, 260, 10)]
    assert heard[0] == heard[1] == 1.0  # full volume up close
    assert all(a >= b for a, b in zip(heard, heard[1:]))  # never louder further away
    assert 0.1 < heard[5] < 0.5  # 50 m: clearly quieter, still there
    assert heard[20] == 0.0 and heard[25] == 0.0  # 200 m and beyond: silent
    left, right = spatial_levels((0.0, 0.0), (-40.0, 0.0), full_m, silent_m)
    assert left > right > 0.0  # on the left, mostly from the left speaker


def test_train_across_town_is_not_heard_but_the_taxi_is():
    audio, log = manager({"railway.train_running": 2, "vehicle.engine_idle": 1})
    audio.listener = audio.player_position = (0.0, 0.0)
    audio.set_loop("train", "railway.train_running", 1.0, at=(2000.0, 0.0))
    assert "train" not in audio.loop_channels
    audio.set_loop("train", "railway.train_running", 1.0, at=(10.0, 0.0))
    assert "train" in audio.loop_channels
    audio.set_loop("idle", "vehicle.engine_idle", 0.5)  # at the taxi, under the camera
    assert audio.loop_channels["idle"].volume == 0.5
    audio.listener = (1000.0, 0.0)  # camera panned far away from the taxi
    audio.set_loop("idle", "vehicle.engine_idle", 0.5)
    assert "idle" not in audio.loop_channels
