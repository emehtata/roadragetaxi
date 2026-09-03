import configparser

from theroadragetrip.config import (
    city_suggestions,
    cities_from_config,
    default_city_configuration,
    load_config,
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
    assert config.get("cities", "new_york") == ""


def test_catalog_matches_game_city_coordinates():
    catalog = load_city_catalog()

    assert catalog["Tampere"] == (61.499113, 23.787117)
    assert catalog["Oulu"] == (65.012, 25.468)


def test_catalog_loads_only_finnish_places(tmp_path):
    catalog_path = tmp_path / "paikkadesi.json"
    catalog_path.write_text(
        '{"countries": {"SUOMI": [{"name": "Oulu", "latitude": 65, "longitude": 25}], '
        '"RUOTSI": [{"name": "Stockholm", "latitude": 59, "longitude": 18}]}}',
        encoding="utf-8",
    )

    assert load_city_catalog(catalog_path) == {"Oulu": (65.0, 25.0)}


def test_default_city_configuration_ignores_customized_config():
    centers, presets = default_city_configuration()

    assert list(centers) == [
        "Helsinki", "Turku", "Tampere", "Pori", "Jyväskylä", "Kuopio",
        "Vaasa", "Kokkola", "Kajaani", "Raahe", "Oulu", "Kemi",
        "Rovaniemi", "Kemijärvi", "Sodankylä", "Kittilä", "Inari", "Sysmä",
    ]
    assert set(presets) == {name.lower() for name in centers}


def test_old_default_city_list_falls_back_to_generated_list():
    config = configparser.ConfigParser()
    config.read_dict(
        {
            "cities": {
                "helsinki": "",
                "espoo": "",
                "tampere": "",
                "vantaa": "",
                "oulu": "",
                "turku": "",
                "jyväskylä": "",
                "kuopio": "",
                "lahti": "",
                "sysmä": "",
            }
        }
    )

    centers, _ = cities_from_config(config)

    assert list(centers) == list(default_city_configuration()[0])


def test_load_config_migrates_coordinate_values_to_name_only(tmp_path):
    path = tmp_path / "roadragetrip.ini"
    path.write_text(
        "[game]\nuser_agent_id =\n[cities]\nhelsinki = 60.169525, 24.935446\n",
        encoding="utf-8",
    )

    load_config(path)

    migrated = configparser.ConfigParser()
    migrated.read(path, encoding="utf-8")
    assert migrated.get("cities", "helsinki") == ""