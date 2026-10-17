"""godot-final-07: shared speech selection, the server's speech and
announcement events, and state.railway."""

import random
import pytest
from datetime import datetime
from types import SimpleNamespace

from theroadragetrip import protocol, speech
from theroadragetrip.server import EventAudio
from theroadragetrip.station_announcer import StationAnnouncer


def test_chatter_ogg_duration_is_read_without_decoding():
    recording = next(speech.SOUND_DIRS["driver"].glob("*.ogg"))
    assert 0.1 < speech.ogg_duration(recording) < 30.0


def test_driver_line_event_falls_back_to_the_finnish_recording_with_the_english_text():
    audio = EventAudio(rng=random.Random(4))
    audio.play_driver_line("pickup", "en")
    (event,) = audio.take_events()
    assert event["type"] == "speech" and event["speaker"] == "driver" and event["speaker_name"] is None
    assert event["gender"] == "m" and event["language"] == "fi"  # only Finnish driver recordings exist
    entry = next(line for line in speech.load_lines("driver") if line["hash"] == event["hash"])
    assert entry["situation"] == "pickup" and event["text"] == entry["en"] and event["duration_s"] == speech.SUBTITLE_S
    assert audio.take_events() == []  # drained once


def test_one_line_at_a_time_and_the_driver_cooldown_on_simulation_time():
    audio = EventAudio(rng=random.Random(1))
    audio.play_driver_line("collision", "fi")
    first = audio.take_events()
    clip = audio._clips["driver"][("m", "fi", first[0]["hash"])]
    audio.play_passenger_line_for_situation("collision", "woman", "fi", "Aino")
    assert audio.take_events() == []  # the driver is still talking
    audio._busy_until = 0.0  # as if the clip had ended at once
    audio.advance(speech.DRIVER_COOLDOWN_S - 0.1)
    audio.play_driver_line("collision", "fi")
    assert audio.take_events() == []  # the same situation within 3 s
    audio.advance(max(0.2, clip))
    audio.play_driver_line("collision", "fi")
    assert len(audio.take_events()) == 1


def test_passenger_situation_moods_and_the_specific_line():
    audio = EventAudio(rng=random.Random(2))
    for _ in range(20):
        audio.play_passenger_line_for_situation("nausea", "woman", "fi", "Aino")
        for event in audio.take_events():
            entry = next(line for line in speech.load_lines("passenger") if line["hash"] == event["hash"])
            assert entry["mood"] in speech.MOODS_BY_SITUATION["nausea"]
            assert event["speaker"] == "passenger" and event["speaker_name"] == "Aino" and event["gender"] == "f"
        audio.advance(30.0)
    audio.play_passenger_line("Nyt alkaa jo helpottaa.", "man", "fi", "Pekka")
    (event,) = audio.take_events()
    assert event["text"] == "Nyt alkaa jo helpottaa." and event["gender"] == "m"


def test_passenger_chatter_waits_its_random_interval():
    audio = EventAudio(rng=random.Random(3))
    audio.update_passenger_speech(False, "woman", "fi", 1 / 30, "Aino")  # off the meter: the interval restarts
    interval = audio._speech.interval
    assert 45.0 <= interval <= 120.0
    ticks = 0
    while not audio.events and ticks < 30 * 125:
        audio.update_passenger_speech(True, "woman", "fi", 1 / 30, "Aino")
        audio.advance(1 / 30)
        ticks += 1
    assert audio.events and abs(ticks / 30 - interval) < 0.05
    audio.take_events()
    assert 45.0 <= audio._speech.interval <= 120.0
    for _ in range(30 * 44):
        audio.advance(1 / 30)
        audio.update_passenger_speech(True, "woman", "fi", 1 / 30, "Aino")
    assert audio.take_events() == []


def test_no_catalog_or_no_recording_is_quiet(monkeypatch):
    monkeypatch.setattr(speech, "load_lines", lambda speaker: [])
    audio = EventAudio()
    audio.play_driver_line("pickup", "fi")
    audio.play_passenger_line("Nyt alkaa jo helpottaa.", "woman", "fi")
    assert audio.take_events() == []
    silent = speech.Speech(lambda speaker, key: False)
    assert silent.driver("pickup", "fi", "man", 0.0, False) is None


@pytest.mark.parametrize("speaker", ["driver", "passenger"])
@pytest.mark.parametrize("gender,code", [("woman", "f"), ("man", "m")])
def test_missing_voice_uses_finnish_but_keeps_requested_subtitle(speaker, gender, code):
    selector = speech.Speech(lambda who, key: key[1] == "fi", rng=random.Random(1))
    entry = {"hash": "abc", "fi": "Hei!", "de": "Hallo!", "situation": "pickup", "mood": "good"}
    selector.lines = {"driver": [entry], "passenger": [entry]}
    if speaker == "driver":
        result = selector.driver("pickup", "de", gender, 0.0, False)
    else:
        result = selector.passenger_for_situation("pickup", gender, "de", "Aino", False)
        assert selector.passenger_line("Hei!", gender, "de", "Aino", False)["key"] == (code, "fi", "abc")
        selector.interval = 0.0
        assert selector.passenger_tick(True, gender, "de", 0.1, "Aino", False)["key"] == (code, "fi", "abc")
    assert result["key"] == (code, "fi", "abc") and result["text"] == "Hallo!"


def test_native_voice_is_preferred_and_missing_both_is_silent():
    selector = speech.Speech(lambda who, key: True)
    entry = {"hash": "abc", "fi": "Hei!", "de": "Hallo!"}
    assert selector._passenger(entry, "woman", "de", "Aino", False)["key"][1] == "de"
    selector.available = lambda who, key: False
    assert selector._passenger(entry, "woman", "de", "Aino", False) is None


def test_german_subtitles_exist_for_every_shipped_line_and_finnish_audio_plays():
    for speaker in ("driver", "passenger"):
        assert all(line.get("de") for line in speech.load_lines(speaker))
    audio = EventAudio(rng=random.Random(4))
    audio.play_driver_line("pickup", "de")
    (event,) = audio.take_events()
    assert event["language"] == "fi"
    entry = next(line for line in speech.load_lines("driver") if line["hash"] == event["hash"])
    assert event["text"] == entry["de"]
    audio.advance(30.0)
    audio.play_passenger_line_for_situation("pickup", "woman", "de", "Aino")
    (event,) = audio.take_events()
    assert event["language"] == "fi" and event["gender"] == "f"
    entry = next(line for line in speech.load_lines("passenger") if line["hash"] == event["hash"])
    assert event["text"] == entry["de"]


def _train(kind_number="28"):
    service = SimpleNamespace(train_type="IC", number=kind_number, origin="Rovaniemi", destination="Helsinki", category="")
    return SimpleNamespace(service=service)


def test_the_announcement_event_is_the_whole_ordered_clip_list():
    announcer = StationAnnouncer()
    stop = (0, 0, "Oulu", 0, 0, None, "1")
    event = announcer.event("arrived", _train(), stop, (100.0, 200.0), listener=(0.0, 0.0))
    phrases = announcer.script.phrases("arrived", "IC", "28", "Oulu", "Rovaniemi", "Helsinki", "1", "")
    assert event["clips"] == announcer.clips(phrases) and event["text"] == announcer.script.sentence(phrases)
    assert event["at"] == [100.0, 200.0] and event["type"] == "station_announcement"  # no platform: the stop
    assert all(not clip.startswith("/") and ".." not in clip for clip in event["clips"])
    assert announcer.event("arrived", SimpleNamespace(service=None), stop, (0, 0)) is None
    assert announcer.event("arrived", _train(), None, (0, 0)) is None


def test_railway_state_is_the_nearest_stations_next_five_and_json_safe():
    calls = [SimpleNamespace(train_type="IC", number=str(n), origin="Kemi", destination="Oulu", track="2" if n % 2 else "")
             for n in range(7)]
    now = datetime(2026, 10, 8, 18, 0)
    mgr = SimpleNamespace(
        stations=[("Oulu", (0.0, 0.0), None, None), ("Kempele", (9000.0, 0.0), None, None)],
        passengers=SimpleNamespace(waiting_count=lambda name: 12 if name == "Oulu" else 0),
        next_arrivals=lambda x, y, when, count: [(datetime(2026, 10, 8, 18, i), c) for i, c in enumerate(calls)][:count],
        next_departures=lambda x, y, when, count: [(datetime(2026, 10, 8, 19, i), c) for i, c in enumerate(calls)][:count],
    )
    state = protocol.railway_state(mgr, 10.0, 0.0, now)
    assert state["nearest_station"] == "Oulu" and state["stations"][0] == {"name": "Oulu", "x": 0.0, "y": 0.0, "waiting": 12}
    assert len(state["arrivals"]) == 5 and state["arrivals"][1] == {"time": "18:01", "train_type": "IC", "number": "1", "origin": "Kemi", "track": "2"}
    assert state["departures"][0]["destination"] == "Oulu" and state["departures"][0]["track"] == ""
    assert protocol.decode(protocol.encode({"type": "state", "version": protocol.PROTOCOL_VERSION, "s": state}))["s"] == state
    assert protocol.railway_state(None, 0, 0, now) == {} and protocol.railway_state(SimpleNamespace(stations=[]), 0, 0, now) == {}
