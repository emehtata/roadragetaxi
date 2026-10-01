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
