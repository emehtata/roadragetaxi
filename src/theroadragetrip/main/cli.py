import argparse
import logging
import os
from typing import Optional


from ..osm import (
    BBOX_PRESETS,
)


logger = logging.getLogger(__name__)


def parse_args(config=None, city_names=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="The Road Rage Trip (OSM PoC)")
    game = config["game"] if config else {}
    map_config = config["map"] if config else {}
    traffic_config = config["traffic"] if config else {}
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
