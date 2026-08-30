import base64
import configparser
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

from .osm import bbox_from_center


USER_AGENT_KEY = "user_agent_id"
DEFAULT_OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
)


def _default_config_path() -> Path:
    if sys.platform.startswith("win"):
        config_dir = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        config_dir = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_dir / "RoadRageTrip" / "roadragetrip.ini"


CONFIG_PATH = _default_config_path()
CITY_CATALOG_PATH = Path(__file__).with_name("assets") / "paikkadesi.json"

DEFAULT_CONFIG = {
    "game": {
        "language": "",
        "preset": "",
        "bbox": "",
        "no_menu": "false",
        "use_sample": "false",
        "force_refresh": "false",
        "no_cache": "false",
        "px_per_m": "9.0",
        "log_level": "INFO",
        "file_logging": "false",
        "taxi_brawls": "false",
    },
    "map": {
        "overpass_endpoints": ", ".join(DEFAULT_OVERPASS_ENDPOINTS),
        "auto_fetch": "true",
        "fetch_margin": "350.0",
        "fetch_tile_size": "2500.0",
        "build_in_process": "true",
    },
    "traffic": {
        "traffic_count": "",
        "pedestrian_count": "20",
        "cyclist_count": "8",
    },
    "audio": {
        "master_volume": "1.0",
        "music_volume": "0.2",
        "effects_volume": "1.0",
        "comments_enabled": "true",
        "subtitles_enabled": "true",
    },
    "speech": {
        "min_interval": "5.0",
        "max_interval": "20.0",
    },
    "experimental": {
        "enable_two_wheelers": "false",
    },
    "cities": {
        "helsinki": "60.169525, 24.935446",
        "espoo": "60.205000, 24.652000",
        "tampere": "61.499113, 23.787117",
        "vantaa": "60.294000, 25.041000",
        "oulu": "65.012000, 25.468000",
        "turku": "60.451483, 22.268686",
        "jyväskylä": "62.241470, 25.720880",
        "kuopio": "62.892382, 27.677028",
        "lahti": "60.982674, 25.661509",
        "sysmä": "61.502271, 25.680613",
    },
}


def load_config(path: Path = CONFIG_PATH) -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    config.read_dict(DEFAULT_CONFIG)
    if not path.exists():
        user_agent_id = _new_user_agent_id()
        config.set("game", USER_AGENT_KEY, user_agent_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_format_defaults(user_agent_id), encoding="utf-8")
    else:
        config.read(path, encoding="utf-8")
        file_config = configparser.ConfigParser()
        file_config.read(path, encoding="utf-8")
        user_agent_id = file_config.get("game", USER_AGENT_KEY, fallback="").strip()
        if not user_agent_id:
            user_agent_id = _new_user_agent_id()
            config.set("game", USER_AGENT_KEY, user_agent_id)
            with path.open("w", encoding="utf-8") as config_file:
                config.write(config_file)
        elif not _is_valid_user_agent_id(user_agent_id):
            raise ValueError(
                f"Invalid {USER_AGENT_KEY} in {path}; delete the entire INI file to create a new identity."
            )
        if file_config.has_section("cities") and file_config.items("cities"):
            config.remove_section("cities")
            config.add_section("cities")
            for name, coordinates in file_config.items("cities"):
                config.set("cities", name, coordinates)
        elif not file_config.has_section("cities"):
            with path.open("a", encoding="utf-8") as config_file:
                config_file.write("\n[cities]\n")
                for name, coordinates in DEFAULT_CONFIG["cities"].items():
                    config_file.write(f"{name} = {coordinates}\n")
    return config


def _format_defaults(user_agent_id: str = "") -> str:
    config = configparser.ConfigParser()
    config.read_dict(DEFAULT_CONFIG)
    lines = [
        "; The Road Rage Trip settings. Restart the game after changing values.",
        "; Command-line options override these values for one launch.",
        "",
    ]
    for section in config.sections():
        lines.append(f"[{section}]")
        for key, value in config[section].items():
            lines.append(f"{key} = {value}")
        if section == "game":
            lines.append(f"{USER_AGENT_KEY} = {user_agent_id}")
        lines.append("")
    return "\n".join(lines)


def _new_user_agent_id() -> str:
    identity = str(uuid.uuid4())
    checksum = hashlib.sha256(f"TheRoadRageTrip:{identity}".encode("ascii")).hexdigest()[:16]
    encoded = base64.urlsafe_b64encode(f"{identity}.{checksum}".encode("ascii"))
    return encoded.decode("ascii")


def _is_valid_user_agent_id(value: str) -> bool:
    try:
        decoded = base64.urlsafe_b64decode(value.encode("ascii")).decode("ascii")
        identity, checksum = decoded.split(".", 1)
        uuid.UUID(identity)
    except (ValueError, UnicodeDecodeError, TypeError):
        return False
    expected = hashlib.sha256(f"TheRoadRageTrip:{identity}".encode("ascii")).hexdigest()[:16]
    return checksum == expected


def get_optional_int(config: configparser.ConfigParser, section: str, key: str) -> Any:
    value = config.get(section, key, fallback="").strip()
    return int(value) if value else None


def save_config(config: configparser.ConfigParser, path: Path = CONFIG_PATH) -> None:
    """Persist user-editable settings while keeping the existing INI identity."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as config_file:
        config.write(config_file)


def get_overpass_endpoints(config: configparser.ConfigParser) -> list[str]:
    """Return configured Overpass endpoints, falling back to built-in defaults."""
    raw = config.get("map", "overpass_endpoints", fallback="")
    endpoints = [endpoint.strip() for endpoint in raw.split(",") if endpoint.strip()]
    return endpoints or list(DEFAULT_OVERPASS_ENDPOINTS)


def load_city_catalog(path: Path = CITY_CATALOG_PATH) -> dict[str, tuple[float, float]]:
    """Load city names with (latitude, longitude) coordinates from the bundled catalog."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        city["name"]: (float(city["latitude"]), float(city["longitude"]))
        for cities in data.get("countries", {}).values()
        for city in cities
    }


def city_suggestions(query: str, limit: int = 8, catalog: Optional[dict[str, tuple[float, float]]] = None) -> list[str]:
    """Return catalog cities matching the typed text, with prefix matches first."""
    query_key = query.strip().casefold()
    names = catalog if catalog is not None else load_city_catalog()
    matches = [name for name in names if not query_key or query_key in name.casefold()]
    return sorted(matches, key=lambda name: (not name.casefold().startswith(query_key), name.casefold()))[:limit]


def replace_city_in_config(
    config: configparser.ConfigParser,
    index: int,
    city_name: str,
    latitude: float,
    longitude: float,
) -> None:
    """Replace one configured city while preserving the list order."""
    if not config.has_section("cities"):
        config.add_section("cities")
    items = list(config.items("cities"))
    if not 0 <= index < len(items):
        raise IndexError("city index out of range")
    city_key = city_name.strip().casefold().replace(" ", "_")
    if not city_key:
        raise ValueError("city name cannot be empty")
    items[index] = (city_key, f"{latitude:.6f}, {longitude:.6f}")
    section = config["cities"]
    section.clear()
    for key, value in items:
        section[key] = value


def cities_from_config(config: configparser.ConfigParser) -> tuple[dict[str, tuple[float, float]], dict[str, tuple[float, float, float, float]]]:
    centers: dict[str, tuple[float, float]] = {}
    for raw_name, raw_coords in config.items("cities") if config.has_section("cities") else []:
        try:
            latitude, longitude = (float(value.strip()) for value in raw_coords.split(","))
            if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                raise ValueError("coordinates out of range")
        except (TypeError, ValueError):
            continue
        name = raw_name.replace("_", " ").title()
        centers[name] = (latitude, longitude)
    presets = {name.lower(): bbox_from_center(*center, size_km=4.0) for name, center in centers.items()}
    return centers, presets


def default_city_configuration() -> tuple[dict[str, tuple[float, float]], dict[str, tuple[float, float, float, float]]]:
    """Return the original city list, independent of user customizations."""
    defaults = configparser.ConfigParser()
    defaults.read_dict({"cities": DEFAULT_CONFIG["cities"]})
    return cities_from_config(defaults)