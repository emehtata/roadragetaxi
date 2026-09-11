import pytest

from theroadragetrip.config import (
    DEFAULT_OVERPASS_ENDPOINTS,
    _default_city_names,
    cities_from_config,
    get_overpass_endpoints,
    load_config,
    save_config,
)
from theroadragetrip.osm import OVERPASS_HEADERS, configure_user_agent


def test_user_agent_identity_persists_and_rejects_tampering(tmp_path):
    config_path = tmp_path / "nested" / "roadragetrip.ini"

    first = load_config(config_path).get("game", "user_agent_id")
    second = load_config(config_path).get("game", "user_agent_id")

    assert first == second
    configure_user_agent(first)
    assert f"id={first}" in OVERPASS_HEADERS["User-Agent"]

    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(first, first[:-2] + "xx"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="delete the entire INI file"):
        load_config(config_path)


def test_save_config_creates_user_config_directory(tmp_path):
    config_path = tmp_path / "user" / "RoadRageTrip" / "roadragetrip.ini"

    config = load_config(config_path)
    save_config(config, config_path)

    assert config_path.is_file()


def test_overpass_endpoints_are_trimmed_and_have_defaults(tmp_path):
    config = load_config(tmp_path / "roadragetrip.ini")
    config.set("map", "overpass_endpoints", " https://one.test , https://two.test ")

    assert get_overpass_endpoints(config) == ["https://one.test", "https://two.test"]

    config.set("map", "overpass_endpoints", "")
    assert get_overpass_endpoints(config) == list(DEFAULT_OVERPASS_ENDPOINTS)


def test_custom_city_section_replaces_default_city_section(tmp_path):
    config_path = tmp_path / "roadragetrip.ini"
    config = load_config(config_path)
    user_agent_id = config.get("game", "user_agent_id")
    config_path.write_text(
        f"[game]\nuser_agent_id = {user_agent_id}\n\n[cities]\nkorpilahti = 62.017, 25.562\n",
        encoding="utf-8",
    )

    loaded = load_config(config_path)

    assert list(loaded.items("cities")) == [("korpilahti", "")]


def test_regenerating_a_missing_user_agent_id_does_not_inflate_the_city_list(tmp_path):
    # Regression test: load_config used to reconcile the [cities] section
    # AFTER saving a regenerated user_agent_id, so the save persisted
    # config.read()'s union of "current defaults" + "whatever the file
    # already had" instead of the file's own (smaller) set - permanently
    # baking leftover names from an older default city list into the file.
    config_path = tmp_path / "roadragetrip.ini"
    default_names = [name.casefold() for name in _default_city_names()]
    lines = ["[game]", "language = fi", "", "[cities]"]
    lines.extend(f"{name} = " for name in default_names)
    lines.append("lahti = ")  # a name no longer in the current defaults
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    config = load_config(config_path)  # missing user_agent_id triggers a save

    centers, _ = cities_from_config(config)
    assert len(centers) == len(default_names)

    disk_names = [name for name, _ in load_config(config_path).items("cities")]
    assert len(disk_names) == len(default_names) + 1  # the file's own content, not further inflated


def test_stale_legacy_name_pruning_does_not_touch_a_genuinely_customized_list():
    # If the user has deliberately dropped a default city, the configured
    # set is no longer a superset of the current defaults, so a leftover
    # legacy name (here "lahti") must be left alone rather than pruned.
    import configparser

    default_names = [name.casefold() for name in _default_city_names()]
    customized = default_names[1:]  # drop one default city on purpose
    customized.append("lahti")
    config = configparser.ConfigParser()
    config.read_dict({"cities": {name: "" for name in customized}})

    centers, _ = cities_from_config(config)

    assert "Lahti" in centers
    assert len(centers) == len(customized)