"""Keep all game languages complete and their format arguments compatible."""
from pathlib import Path
import re
from string import Formatter

import pytest

from theroadragetrip.localization import TRANSLATIONS, SUPPORTED_LANGUAGES, normalize_language, tr
from theroadragetrip.npc import NPCState
from theroadragetrip.pedestrian import PedestrianState
from theroadragetrip.vehicles import VEHICLE_DEFINITIONS


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
def test_server_translation_keys_and_arguments_match(language):
    fi, translated = TRANSLATIONS["fi"], TRANSLATIONS[language]
    assert fi.keys() == translated.keys()
    formatter = Formatter()
    for key in fi:
        arguments = lambda text: sorted(
            (field, spec, conversion)
            for _, field, spec, conversion in formatter.parse(text)
            if field is not None
        )
        assert arguments(fi[key]) == arguments(translated[key]), key


def test_client_translates_all_inspected_states_and_vehicle_types():
    source = Path("godot/i18n.gd").read_text(encoding="utf-8")
    states = [value for key, value in vars(NPCState).items() if key.isupper()]
    states += [state.value for state in PedestrianState]
    states += list(VEHICLE_DEFINITIONS)
    for value in states:
        assert source.count(f'"value_{value.lower()}":') == len(SUPPORTED_LANGUAGES), value


def test_client_translates_all_activity_names():
    source = Path("godot/i18n.gd").read_text(encoding="utf-8")
    for plugin in Path("src/theroadragetrip/activities/plugins").glob("*.py"):
        for activity in re.findall(r'\b(?:id|plugin_id)="([a-z_]+)"', plugin.read_text(encoding="utf-8")):
            assert source.count(f'"value_{activity}":') == len(SUPPORTED_LANGUAGES), activity


def test_german_notifications_and_currency():
    from theroadragetrip.fare import format_euros
    assert normalize_language("de") == "de"
    assert tr("de", "boarded_destination", name="Aino", address="Kirkkokatu 4") == "Aino ist eingestiegen! Fahrtziel: Kirkkokatu 4"
    assert format_euros(1234, "de") == "12,34 €"


def test_german_server_language_argument(monkeypatch):
    from theroadragetrip.server.cli import parse_server_args
    monkeypatch.setattr("sys.argv", ["server", "--language", "de", "--use-sample"])
    args, _ = parse_server_args()
    assert args.language == "de"
