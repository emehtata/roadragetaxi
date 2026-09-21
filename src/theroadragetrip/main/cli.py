import argparse
import logging
import os
from typing import Optional


from ..config import get_vehicle_distribution
from ..osm import (
    BBOX_PRESETS,
)


logger = logging.getLogger(__name__)


def parse_args(config=None, city_names=None, parser: Optional[argparse.ArgumentParser] = None) -> argparse.Namespace:
    """Builds (or extends, if `parser` is given) the shared argparse
    surface for world-selection flags. `server/cli.py` passes its own
    parser in, with --host/--port/--tick-rate already added, so both
    processes accept identical world arguments from one definition."""
    p = parser if parser is not None else argparse.ArgumentParser(description="The Road Rage Trip (OSM PoC)")
    game = config["game"] if config else {}
    map_config = config["map"] if config else {}
    traffic_config = config["traffic"] if config else {}
    experimental_config = config["experimental"] if config else {}
    p.add_argument("--bbox", type=str, default=game.get("bbox") or None, help="south,west,north,east (lat/lon)")
    p.add_argument(
        "--preset",
        type=str,
        choices=city_names or list(BBOX_PRESETS.keys()),
        default=game.get("preset") or None,
        help="Named bounding box preset (e.g., oulu, helsinki, tampere, espoo)",
    )
    p.add_argument("--no-menu", action="store_true", default=game.getboolean("no_menu", fallback=False), help="Skip interactive city menu")
    p.add_argument("--force-refresh", action="store_true", default=game.getboolean("force_refresh", fallback=False), help="Force refresh from Overpass (ignore cache)")
    p.add_argument("--use-sample", action="store_true", default=game.getboolean("use_sample", fallback=False), help="Use bundled sample OSM data and skip Overpass")
    p.add_argument("--px-per-m", type=float, default=game.getfloat("px_per_m", fallback=9.0), help="Initial pixels per meter (zoom)")
    p.add_argument("--log-level", type=str, default=game.get("log_level", "INFO"), help="Logging level (DEBUG/INFO/WARNING)")
    p.add_argument(
        "--headless",
        type=int,
        default=0,
        metavar="N",
        help="Run N simulation ticks with no rendering/input and exit (proof-of-concept for a future server/headless mode)",
    )
    p.add_argument(
        "--connect",
        type=str,
        default=None,
        metavar="HOST:PORT",
        help="Connect to an already-running `python -m theroadragetrip.server` instead of embedding one",
    )
    p.add_argument("--no-cache", action="store_true", default=game.getboolean("no_cache", fallback=False), help="Disable cache usage (treated like force-refresh)")
    p.add_argument(
        "--osm-source",
        choices=["overpass", "pbf"],
        default=map_config.get("osm_source", "overpass"),
        help="Where to fetch OSM data from: live Overpass API, or a local .osm.pbf extract via osmium-tool (no downloads)",
    )
    p.add_argument(
        "--osm-pbf-path",
        type=str,
        default=map_config.get("osm_pbf_path", "") or None,
        help="Path to a local .osm.pbf file for --osm-source=pbf (default: assets/osm/finland-latest.osm.pbf)",
    )

    # Auto-fetching nearby map tiles when the car approaches the bbox edge
    p.add_argument("--no-auto-fetch", dest="auto_fetch", action="store_false", default=map_config.getboolean("auto_fetch", fallback=True), help="Disable on-demand map expansion")
    p.add_argument(
        "--fetch-margin",
        type=float,
        default=map_config.getfloat("fetch_margin", fallback=350.0),
        help="Distance in meters from bbox edge that triggers auto-fetch",
    )
    p.add_argument("--fetch-tile-size", type=float, default=map_config.getfloat("fetch_tile_size", fallback=500.0), help="Base auto-fetch bbox size in meters")
    p.add_argument(
        "--build-in-process",
        action="store_true",
        default=map_config.getboolean("build_in_process", fallback=True),
        help="Build auto-fetched map data outside the gameplay process",
    )
    p.add_argument("--pedestrian-count", type=int, default=traffic_config.getint("pedestrian_count", fallback=60), help="Target number of pedestrians")
    p.add_argument(
        "--npc-vehicle-count", type=int,
        # Not traffic_config.getint(..., fallback=40): an existing
        # config.ini saved before this option existed may have persisted
        # the old placeholder empty string, which getint's fallback does
        # not cover (fallback only applies to a missing *key*, not an
        # empty *value*).
        default=int(traffic_config.get("traffic_count") or 40),
        help="Target NPC vehicle population (NPC-003)",
    )
    p.add_argument(
        "--npc-vehicle-min", type=int,
        default=int(traffic_config.get("traffic_count_min") or 0) or None,
        help="Minimum NPC vehicle population (default: derived from --npc-vehicle-count)",
    )
    p.add_argument(
        "--npc-vehicle-max", type=int,
        default=int(traffic_config.get("traffic_count_max") or 0) or None,
        help="Maximum NPC vehicle population (default: derived from --npc-vehicle-count)",
    )
    p.add_argument(
        "--enable-two-wheelers", action="store_true",
        default=experimental_config.getboolean("enable_two_wheelers", fallback=False),
        help="Include motorcycles in the NPC vehicle population (NPC-003, experimental)",
    )
    # No CLI flag - [traffic] vehicle_distribution is a config-file-only
    # knob (a comma-separated "id:weight" list has no clean single-flag
    # CLI shape); attached here so main/__init__.py's NPCVehicleManager
    # construction doesn't need config threaded through separately.
    p.set_defaults(vehicle_distribution=get_vehicle_distribution(config) if config else None)

    return p.parse_args()


def configure_logging(level: Optional[str] = None, file_logging: bool = False) -> None:
    lvl = os.getenv("LOG_LEVEL", level or "INFO").upper()
    log_level = getattr(logging, lvl, logging.INFO)
    log_format = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    handlers = [logging.StreamHandler()]
    handlers[0].setFormatter(logging.Formatter(log_format))
    if file_logging:
        file_handler = logging.FileHandler("roadragetrip.log", encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(log_format))
        handlers.append(file_handler)
    logging.basicConfig(level=log_level, handlers=handlers, force=True)
