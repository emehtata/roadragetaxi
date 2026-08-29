import pytest

from theroadragetrip.config import load_config, save_config
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