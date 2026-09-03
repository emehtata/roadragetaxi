import pytest

from theroadragetrip.config import DEFAULT_OVERPASS_ENDPOINTS, get_overpass_endpoints, load_config, save_config
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