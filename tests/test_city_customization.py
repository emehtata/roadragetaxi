import configparser

from theroadragetrip.config import (
    cities_from_config,
    default_city_configuration,
    load_config,
    load_city_catalog,
)


def test_catalog_matches_game_city_coordinates():
    catalog = load_city_catalog()

    assert catalog["Tampere"] == (61.499113, 23.787117)
    assert catalog["Oulu"] == (65.012, 25.468)


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