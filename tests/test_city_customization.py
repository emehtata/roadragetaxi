import configparser

from theroadragetrip.config import (
    city_suggestions,
    default_city_configuration,
    load_city_catalog,
    replace_city_in_config,
)


def test_city_suggestions_prioritize_prefix_matches():
    catalog = {
        "New York": (40.7, -74.0),
        "York": (53.9, -1.1),
        "Newcastle": (54.9, -1.6),
    }

    assert city_suggestions("new", catalog=catalog) == ["New York", "Newcastle"]


def test_replace_city_preserves_position_and_uses_catalog_coordinates():
    config = configparser.ConfigParser()
    config.read_dict({"cities": {"first": "60.0, 24.0", "second": "61.0, 25.0"}})

    replace_city_in_config(config, 0, "New York", 40.7, -74.0)

    assert list(config["cities"]) == ["new_york", "second"]
    assert config.get("cities", "new_york") == "40.700000, -74.000000"


def test_catalog_matches_game_city_coordinates():
    catalog = load_city_catalog()

    assert catalog["Helsinki"] == (60.169525, 24.935446)
    assert catalog["Oulu"] == (65.012, 25.468)


def test_default_city_configuration_ignores_customized_config():
    centers, presets = default_city_configuration()

    assert list(centers) == [
        "Helsinki", "Espoo", "Tampere", "Vantaa", "Oulu",
        "Turku", "Jyväskylä", "Kuopio", "Lahti", "Sysmä",
    ]
    assert set(presets) == {name.lower() for name in centers}