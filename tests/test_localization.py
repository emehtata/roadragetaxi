"""Keep both game languages complete and their format arguments compatible."""
from pathlib import Path
import re
from string import Formatter

from theroadragetrip.localization import TRANSLATIONS
from theroadragetrip.npc import NPCState
from theroadragetrip.pedestrian import PedestrianState
from theroadragetrip.vehicles import VEHICLE_DEFINITIONS


def test_server_translation_keys_and_arguments_match():
    fi, en = TRANSLATIONS["fi"], TRANSLATIONS["en"]
    assert fi.keys() == en.keys()
    formatter = Formatter()
    for key in fi:
        arguments = lambda text: sorted(
            (field, spec, conversion)
            for _, field, spec, conversion in formatter.parse(text)
            if field is not None
        )
        assert arguments(fi[key]) == arguments(en[key]), key


def test_client_translates_all_inspected_states_and_vehicle_types():
    source = Path("godot/i18n.gd").read_text(encoding="utf-8")
    states = [value for key, value in vars(NPCState).items() if key.isupper()]
    states += [state.value for state in PedestrianState]
    states += list(VEHICLE_DEFINITIONS)
    for value in states:
        assert source.count(f'"value_{value.lower()}":') == 2, value


def test_client_translates_all_activity_names():
    source = Path("godot/i18n.gd").read_text(encoding="utf-8")
    for plugin in Path("src/theroadragetrip/activities/plugins").glob("*.py"):
        for activity in re.findall(r'\b(?:id|plugin_id)="([a-z_]+)"', plugin.read_text(encoding="utf-8")):
            assert source.count(f'"value_{activity}":') == 2, activity
