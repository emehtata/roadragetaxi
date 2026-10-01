"""Station announcements are assembled from the clip manifest."""
from types import SimpleNamespace

from theroadragetrip.station_announcer import AnnouncementScript, StationAnnouncer, number_components


def entry(file, text, **extra):
    return {"file": file, "text": text, **extra}


MANIFEST = {
    "numbers": {
        "units": {str(v): entry(f"numbers/units/{v}.ogg", "") for v in range(10)},
        "teens": {str(v): entry(f"numbers/teens/{v}.ogg", "") for v in range(11, 20)},
        "tens": {str(v): entry(f"numbers/tens/{v}.ogg", "") for v in range(10, 100, 10)},
        "hundreds": {str(v): entry(f"numbers/hundreds/{v}.ogg", "") for v in range(100, 1000, 100)},
    },
    "places": {"helsinki": entry("places/helsinki.ogg", "Helsinki"),
               "oulu": entry("places/oulu.ogg", "Oulu", default_text="Oulu")},
    "places_to": {"helsinki": entry("places/to/helsinki.ogg", "Helsinkiin"), "oulu": entry("places/to/oulu.ogg", "Ouluun")},
    "places_from": {"helsinki": entry("places/from/helsinki.ogg", "Helsingistä"),
                    "oulu": entry("places/from/oulu.ogg", "Oulusta")},
    "train_types": {"intercity": entry("train_types/intercity.ogg", "InterCity", train_type="IC")},
    "platforms": {"raiteelle": entry("platforms/raiteelle.ogg", "raiteelle"),
                  "raiteelta": entry("platforms/raiteelta.ogg", "raiteelta")},
    "phrases": {"attention": entry("phrases/attention.ogg", "Hyvät matkustajat."),
                "arriving": entry("phrases/arriving.ogg", "saapuu"), "departing": entry("phrases/departing.ogg", "lähtee")},
}


def test_finnish_number_parts_keep_the_teens_whole():
    assert number_components(57) == [50, 7]
    assert number_components(519) == [500, 19]
    assert number_components(110) == [100, 10]


def test_an_arrival_says_who_comes_from_where_to_which_track():
    script = AnnouncementScript(MANIFEST)
    assert script.files("arrived", "IC", "57", "Tampere", "Helsinki", "Oulu", "3") == [
        "phrases/attention.ogg", "train_types/intercity.ogg", "numbers/tens/50.ogg", "numbers/units/7.ogg",
        "places/from/helsinki.ogg", "phrases/arriving.ogg", "platforms/raiteelle.ogg", "numbers/units/3.ogg",
    ]


def test_a_departure_says_where_it_goes_and_skips_what_has_no_clip():
    script = AnnouncementScript(MANIFEST)
    assert script.files("departed", "IC", "519", "Tampere", "Helsinki", "Oulu", "") == [
        "train_types/intercity.ogg", "numbers/hundreds/500.ogg", "numbers/teens/19.ogg",
        "places/to/oulu.ogg", "phrases/departing.ogg",  # no track known: no "raiteelta ..."
    ]
    # A number beyond the clip range and an unknown place are simply left out.
    assert script.files("departed", "IC", "8247", "Tampere", "Helsinki", "Kittilä", "2") == [
        "train_types/intercity.ogg", "phrases/departing.ogg", "platforms/raiteelta.ogg", "numbers/units/2.ogg",
    ]
    # Leaving its origin, a train isn't announced as coming "from" there.
    assert "places/from/helsinki.ogg" not in script.files("arrived", "IC", "1", "Helsinki", "Helsinki", "Oulu", "1")


def test_commuter_trains_without_a_type_clip_are_not_announced():
    assert AnnouncementScript(MANIFEST).files("arrived", "K", "8247", "Tikkurila", "Helsinki", "Kerava", "4") == []


def test_no_announcement_out_of_earshot_or_without_clips(tmp_path):
    announcer = StationAnnouncer(asset_dir=tmp_path)  # no manifest at all
    assert announcer.script is None
    audio = SimpleNamespace(enabled=True, levels=lambda *a, **k: (0.0, 0.0))
    train = SimpleNamespace(service=SimpleNamespace(train_type="IC", number="57", origin="Helsinki", destination="Oulu"))
    assert not announcer.announce(audio, "arrived", train, (0, 60, "Tampere", 0, 0, (0, 0), "3"), (0.0, 0.0))
    announcer.script = AnnouncementScript(MANIFEST)
    assert not announcer.announce(audio, "arrived", train, (0, 60, "Tampere", 0, 0, (0, 0), "3"), (0.0, 0.0))


def test_numbers_are_never_split_by_a_pause():
    """Regression: a pause after every clip made "kaksikymmentä kaksi" (22)
    sound like "20 ... 2"."""
    phrases = AnnouncementScript(MANIFEST).phrases("arrived", "IC", "22", "Oulu", "Helsinki", "Rovaniemi", "13")
    assert ["train_types/intercity.ogg", "numbers/tens/20.ogg", "numbers/units/2.ogg"] in phrases
    assert ["platforms/raiteelle.ogg", "numbers/teens/13.ogg"] in phrases


class FakeChannel:
    """The reserved announcement channel: busy until the test finishes the clip."""

    def __init__(self):
        self.playing, self.queued, self.volume, self.started = None, None, None, []

    def get_busy(self):
        return self.playing is not None

    def get_queue(self):
        return self.queued

    def play(self, sound):
        assert self.playing is None, "a clip was started over another one"
        self.playing = sound
        self.started.append(sound)

    def queue(self, sound):
        assert self.playing is not None and self.queued is None, "one clip lined up behind the playing one"
        self.queued = sound
        self.started.append(sound)

    def set_volume(self, left, right):
        self.volume = (left, right)

    def finish(self):
        """The playing clip ends; a queued one takes over at once, gaplessly."""
        self.playing, self.queued = self.queued, None


def announcer_with_fake_audio(monkeypatch, levels=lambda *a, **k: (1.0, 1.0)):
    import theroadragetrip.station_announcer as sa

    announcer = StationAnnouncer.__new__(StationAnnouncer)
    announcer.script = AnnouncementScript(MANIFEST)
    announcer._pause, announcer._clips, announcer._playing = "connectors/pause_short.ogg", {}, None
    announcer._queue, announcer._channel = sa.deque(), FakeChannel()
    announcer.platforms = []
    announcer._clip = lambda file: file  # a clip "sound" is its file name here
    now = [100.0]
    monkeypatch.setattr(sa.time, "monotonic", lambda: now[0])
    audio = SimpleNamespace(enabled=True, levels=levels)
    return announcer, audio, now


def play_all(announcer, audio, frames=200):
    for _ in range(frames):
        announcer.update(audio)
        announcer._channel.finish()  # each clip ends before the next frame
    return announcer._channel.started


STOP = (0, 60, "Tampere", 0, 0, (0, 0), "3")


def train(number="57"):
    return SimpleNamespace(service=SimpleNamespace(train_type="IC", number=number, origin="Helsinki", destination="Oulu"))


def test_clips_play_one_by_one_with_pauses_only_between_phrases(monkeypatch):
    announcer, audio, _ = announcer_with_fake_audio(monkeypatch)
    assert announcer.announce(audio, "arrived", train("22"), STOP, (0, 0))
    assert play_all(announcer, audio) == [
        "phrases/attention.ogg", "connectors/pause_short.ogg",
        "train_types/intercity.ogg", "numbers/tens/20.ogg", "numbers/units/2.ogg",  # 22: no pause inside
        "connectors/pause_short.ogg", "places/from/helsinki.ogg",
        "connectors/pause_short.ogg", "phrases/arriving.ogg",
        "connectors/pause_short.ogg", "platforms/raiteelle.ogg", "numbers/units/3.ogg",
    ]
    announcer.announce(audio, "departed", train("519"), STOP, (0, 0))
    assert play_all(announcer, audio)[12:15] == [  # after the 12 arrival clips
        "train_types/intercity.ogg", "numbers/hundreds/500.ogg", "numbers/teens/19.ogg",  # 19: one clip
    ]


def test_the_next_clip_is_lined_up_behind_the_playing_one_gaplessly(monkeypatch):
    announcer, audio, _ = announcer_with_fake_audio(monkeypatch)
    announcer.announce(audio, "arrived", train("22"), STOP, (0, 0))
    for _ in range(10):
        announcer.update(audio)  # the first clip still playing: exactly one more lined up
    assert announcer._channel.started == ["phrases/attention.ogg", "connectors/pause_short.ogg"]
    announcer._channel.finish()  # the pause starts the instant the attention clip ends
    assert announcer._channel.playing == "connectors/pause_short.ogg"
    announcer.update(audio)
    announcer._channel.finish()
    announcer.update(audio)
    # train + number, back to back: "InterCity kaksikymmentä kaksi"
    assert announcer._channel.playing == "train_types/intercity.ogg"
    assert announcer._channel.queued == "numbers/tens/20.ogg"


def test_a_departure_soon_after_the_arrival_waits_its_turn(monkeypatch):
    announcer, audio, _ = announcer_with_fake_audio(monkeypatch)
    announcer.announce(audio, "arrived", train(), STOP, (0, 0))
    announcer.announce(audio, "departed", train(), STOP, (0, 0))
    started = play_all(announcer, audio)
    arrival_end = started.index("platforms/raiteelle.ogg") + 1
    assert started[0] == "phrases/attention.ogg" and started[arrival_end + 1] == "train_types/intercity.ogg"
    assert started[arrival_end:].count("phrases/departing.ogg") == 1 and "phrases/departing.ogg" not in started[:arrival_end]


def test_a_stale_waiting_announcement_is_dropped_but_the_one_on_air_finishes(monkeypatch):
    announcer, audio, now = announcer_with_fake_audio(monkeypatch)
    announcer.announce(audio, "arrived", train(), STOP, (0, 0))
    announcer.announce(audio, "departed", train(), STOP, (0, 0))
    now[0] += 30.0  # the arrival talks on; the departure has waited too long
    started = play_all(announcer, audio)
    assert started[-1] == "numbers/units/3.ogg" and "phrases/arriving.ogg" in started
    assert "phrases/departing.ogg" not in started


def test_each_clip_starts_at_the_volume_of_the_current_distance(monkeypatch):
    level = [(1.0, 1.0)]
    announcer, audio, _ = announcer_with_fake_audio(monkeypatch, levels=lambda *a, **k: level[0])
    announcer.announce(audio, "arrived", train(), STOP, (0, 0))
    announcer.update(audio)
    assert announcer._channel.volume == (1.0, 1.0)
    announcer._channel.finish()
    level[0] = (0.2, 0.4)  # the player drove away and to the side
    announcer.update(audio)
    assert announcer._channel.volume == (0.2, 0.4)


def test_each_clip_file_is_loaded_once(monkeypatch, tmp_path):
    import pygame

    loads = []
    monkeypatch.setattr(pygame.mixer, "Sound", lambda path: loads.append(path) or object())
    announcer = StationAnnouncer(asset_dir=tmp_path)
    first = announcer._clip("numbers/units/3.ogg")
    assert announcer._clip("numbers/units/3.ogg") is first and len(loads) == 1


# -- every train type of the timetable, against the real clip set ---------

import json as _json

from theroadragetrip.station_announcer import ASSET_DIR

REAL = _json.loads((ASSET_DIR / "manifest.json").read_text(encoding="utf-8"))
REAL_SCRIPT = AnnouncementScript(REAL)


def spoken(files):
    """The (default) Finnish text of each clip, as the manifest records it."""
    texts = {}

    def walk(node):
        if isinstance(node, dict):
            if "file" in node and "text" in node:
                texts[node["file"]] = node.get("default_text", node["text"])
            for value in node.values():
                walk(value)
    walk(REAL)
    return [texts[file] for file in files]


def test_long_distance_types_say_their_finnish_name_and_the_clips_exist():
    expected = {"SP": "Pendolino Plus", "S": "Pendolino", "IC": "InterCity", "PYO": "yöjuna",
                "HDM": "kiskobussi", "H": "taajamajuna", "MUS": "museojuna"}
    for code, name in expected.items():
        files = REAL_SCRIPT.train_phrase(code, "long_distance")
        assert spoken(files) == [name], code
        assert all((ASSET_DIR / file).is_file() for file in files), code


def test_commuter_lines_say_lahijuna_and_the_letter():
    letters = {"D": "dee", "G": "gee", "H": "hoo", "M": "äm", "O": "oo", "R": "är", "T": "tee", "Z": "tset"}
    for line, name in letters.items():
        files = REAL_SCRIPT.train_phrase(line, "commuter")
        assert spoken(files) == ["lähijuna", name], line
        assert all((ASSET_DIR / file).is_file() for file in files), line


def test_the_two_meanings_of_h_come_from_the_timetable_category():
    assert spoken(REAL_SCRIPT.train_phrase("H", "long_distance")) == ["taajamajuna"]  # Iisalmi-Ylivieska
    assert spoken(REAL_SCRIPT.train_phrase("H", "commuter")) == ["lähijuna", "hoo"]  # the Hanko line


def test_unsupported_types_are_not_announced_as_something_else():
    assert REAL_SCRIPT.train_phrase("K", "commuter") == []  # no clip for line K yet
    assert REAL_SCRIPT.train_phrase("XYZ", "long_distance") == []
    assert REAL_SCRIPT.phrases("arrived", "K", "8247", "Tikkurila", "Helsinki", "Kerava", "4", "commuter") == []


def test_train_numbers_stay_composed_after_the_train_type():
    ic = REAL_SCRIPT.phrases("departed", "IC", "519", "Oulu", "Helsinki", "Rovaniemi", "", "long_distance")[0]
    assert spoken(ic) == ["InterCity", "viisisataa", "yhdeksäntoista"]
    pyo = REAL_SCRIPT.phrases("arrived", "PYO", "273", "Oulu", "Helsinki", "Rovaniemi", "", "long_distance")[1]
    assert spoken(pyo) == ["yöjuna", "kaksisataa", "seitsemänkymmentä", "kolme"]
    r = REAL_SCRIPT.phrases("departed", "R", "123", "Tikkurila", "Helsinki", "Riihimäki", "4", "commuter")[0]
    assert spoken(r) == ["lähijuna", "är", "sata", "kaksikymmentä", "kolme"]


def test_the_log_line_says_the_announcement_in_finnish():
    phrases = REAL_SCRIPT.phrases("arrived", "IC", "22", "Oulu", "Rovaniemi", "Helsinki", "1", "long_distance")
    assert REAL_SCRIPT.sentence(phrases) == "Hyvät matkustajat. InterCity kaksikymmentä kaksi Rovaniemeltä saapuu raiteelle yksi"


def test_announcements_come_from_the_station_platforms_not_the_train(monkeypatch):
    """The loudspeaker heard is the platform point nearest the player."""
    heard_at = []
    announcer, audio, _ = announcer_with_fake_audio(
        monkeypatch, levels=lambda name, volume, at=None: heard_at.append(at) or (1.0, 1.0))
    platform = SimpleNamespace(points_m=[(0.0, 10.0), (100.0, 10.0)])   # along the track, 10 m off it
    far_platform = SimpleNamespace(points_m=[(0.0, 900.0), (100.0, 900.0)])  # another station
    announcer.platforms = [platform, far_platform]
    audio.listener = (80.0, 40.0)
    train_stop = (50.0, 0.0)  # where the train stops
    assert announcer.announce(audio, "arrived", train(), STOP, train_stop)
    assert heard_at[-1] == (80.0, 10.0)  # straight across from the player, on the platform
    audio.listener = (5.0, 40.0)  # the player walks along: so does the nearest loudspeaker
    announcer._channel.finish()
    announcer.update(audio)
    assert heard_at[-1] == (5.0, 10.0)


def test_a_station_without_mapped_platforms_announces_from_the_stop(monkeypatch):
    heard_at = []
    announcer, audio, _ = announcer_with_fake_audio(
        monkeypatch, levels=lambda name, volume, at=None: heard_at.append(at) or (1.0, 1.0))
    audio.listener = (80.0, 40.0)
    announcer.announce(audio, "arrived", train(), STOP, (50.0, 0.0))
    assert heard_at[-1] == (50.0, 0.0)
