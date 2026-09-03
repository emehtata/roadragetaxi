import base64
import configparser
import gzip
import hashlib
import json
import math
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
CITY_CATALOG_PATH = Path(__file__).with_name("assets") / "kunnat.json.gz"
LEGACY_DEFAULT_CITY_NAMES = {
    "helsinki",
    "espoo",
    "tampere",
    "vantaa",
    "oulu",
    "turku",
    "jyväskylä",
    "kuopio",
    "lahti",
    "sysmä",
}


def _default_city_names() -> list[str]:
    with gzip.open(CITY_CATALOG_PATH, "rt", encoding="utf-8") as source:
        data = json.load(source)
    places = data.get("places", [])
    selected_places: list[dict[str, Any]] = []
    latitude_zones = sorted(
        {math.floor(float(place["koordinaatit"]["latitude"])) for place in places}
    )
    for zone in latitude_zones:
        zone_places = [
            place
            for place in places
            if math.floor(float(place["koordinaatit"]["latitude"])) == zone
        ]
        selected_places.extend(
            sorted(
                zone_places,
                key=lambda place: (-int(place["väkiluku"]), place["taajama"].casefold()),
            )[:2]
        )

    sysma = next((place for place in places if place["taajama"] == "Sysmä"), None)
    if sysma is not None and all(place["taajama"] != "Sysmä" for place in selected_places):
        least_populous = min(selected_places, key=lambda place: int(place["väkiluku"]))
        selected_places.remove(least_populous)
        selected_places.append(sysma)
    return [place["taajama"] for place in selected_places]

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
        "roadworks_enabled": "false",
        "bus_stops": "false",
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
        "parking_density": "0.5",
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
        name.casefold(): "" for name in _default_city_names()
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
            has_legacy_city_values = False
            for name, value in file_config.items("cities"):
                config.set("cities", name, "")
                has_legacy_city_values |= bool(value.strip())
            if has_legacy_city_values:
                save_config(config, path)
        elif not file_config.has_section("cities"):
            with path.open("a", encoding="utf-8") as config_file:
                config_file.write("\n[cities]\n")
                for name in DEFAULT_CONFIG["cities"]:
                    config_file.write(f"{name} =\n")
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
    """Load city names with coordinates from the bundled municipality data."""
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as source:
            data = json.load(source)
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
    if "places" in data:
        return {
            place["taajama"]: (
                float(place["koordinaatit"]["latitude"]),
                float(place["koordinaatit"]["longitude"]),
            )
            for place in data["places"]
        }
    return {
        city["name"]: (float(city["latitude"]), float(city["longitude"]))
        for city in data.get("countries", {}).get("SUOMI", [])
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
    items[index] = (city_key, "")
    section = config["cities"]
    section.clear()
    for key, value in items:
        section[key] = value


def cities_from_config(config: configparser.ConfigParser) -> tuple[dict[str, tuple[float, float]], dict[str, tuple[float, float, float, float]]]:
    catalog = load_city_catalog()
    configured_items = list(config.items("cities")) if config.has_section("cities") else []
    configured_names = {raw_name.replace("_", " ").casefold() for raw_name, _ in configured_items}
    catalog_names = {name.casefold() for name in catalog}
    valid_configured_names = configured_names & catalog_names
    default_names = _default_city_names()
    if configured_names == LEGACY_DEFAULT_CITY_NAMES:
        configured_items = [(name.casefold(), "") for name in default_names]

    centers: dict[str, tuple[float, float]] = {}
    for raw_name, _ in configured_items:
        name = raw_name.replace("_", " ").title()
        if name not in catalog:
            continue
        centers[name] = catalog[name]
    presets = {name.lower(): bbox_from_center(*center, size_km=4.0) for name, center in centers.items()}
    return centers, presets


def default_city_configuration() -> tuple[dict[str, tuple[float, float]], dict[str, tuple[float, float, float, float]]]:
    """Return the original city list, independent of user customizations."""
    defaults = configparser.ConfigParser()
    defaults.read_dict({"cities": DEFAULT_CONFIG["cities"]})
    return cities_from_config(defaults)