import gzip
import json
import logging
import math
import os
import shutil
import sys
import tempfile
import time
from typing import List, Optional, Tuple



logger = logging.getLogger(__name__)


CACHE_VERSION = "v0.19.1alpha.1"  # Include individual natural=shrub nodes.
# How long downloaded map data is reused before refetching; OSM_CACHE_TTL (seconds) overrides.
OSM_CACHE_TTL_S = 14 * 24 * 3600


def default_cache_root() -> str:
    if sys.platform.startswith("win"):
        data_dir = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or os.path.expanduser("~")
    else:
        data_dir = os.getenv("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(data_dir, "RoadRageTrip")


def _default_cache_dir() -> str:
    return os.path.join(default_cache_root(), "osm_cache")


CACHE_DIR = _default_cache_dir()


def load_local_sample(path: str = "sample_osm.json.gz") -> Optional[List[dict]]:
    """Load a small local sample OSM 'elements' list for offline testing.

    Tries the provided path, package-relative samples, and `sample_osm_large.json.gz`.
    """
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    bundle_dir = getattr(sys, "_MEIPASS", "")
    candidates = [
        path,
        os.path.join(root_dir, path),
        os.path.join(root_dir, "sample_osm.json.gz"),
        "sample_osm_large.json.gz",
        os.path.join(root_dir, "sample_osm_large.json.gz"),
    ]
    if bundle_dir:
        candidates.extend([
            os.path.join(bundle_dir, path),
            os.path.join(bundle_dir, "sample_osm.json.gz"),
            os.path.join(bundle_dir, "sample_osm_large.json.gz"),
        ])
    for p in candidates:
        if not os.path.exists(p):
            continue
        opener = gzip.open if p.endswith(".gz") else open
        with opener(p, "rt", encoding="utf-8") as f:
            d = json.load(f)
        return d.get("elements")
    return None


def _bbox_cache_path(bbox: Tuple[float, float, float, float]) -> str:
    from . import CACHE_DIR  # re-read each call so tests can monkeypatch theroadragetrip.osm.CACHE_DIR

    south, west, north, east = bbox
    # Keep tiny projection/float differences from creating duplicate cache files.
    precision = 5
    south = math.floor(south * 10**precision) / 10**precision
    west = math.floor(west * 10**precision) / 10**precision
    north = math.ceil(north * 10**precision) / 10**precision
    east = math.ceil(east * 10**precision) / 10**precision
    fname = f"bbox_{south}_{west}_{north}_{east}.json"
    stem, extension = os.path.splitext(fname)
    safe = stem.replace(".", "p").replace("-", "m") + extension
    return os.path.join(CACHE_DIR, safe)


def _bbox_from_cache_name(name: str) -> Optional[Tuple[float, float, float, float]]:
    if not name.startswith("bbox_"):
        return None
    try:
        suffix_length = 5 if name.endswith((".json", "pjson")) else 0
        if suffix_length == 0:
            return None
        values = name[5:-suffix_length].split("_")
        if len(values) != 4:
            return None
        return tuple(float(value.replace("p", ".").replace("m", "-")) for value in values)
    except ValueError:
        return None


def _legacy_bbox_cache_path(path: str) -> str:
    """Return the corrected .json path for a legacy pjson cache file."""
    if not path.endswith("pjson"):
        return path
    return path[:-5] + ".json"


def load_osm_cache(
    bbox: Tuple[float, float, float, float],
    point: Optional[Tuple[float, float]] = None,
    max_cover_ratio: Optional[float] = None,
) -> Optional[List[dict]]:
    """The cached elements for `bbox`: its own file, or one covering it (or
    `point`) - one covering more than max_cover_ratio times its area is skipped."""
    from . import CACHE_DIR  # re-read each call so tests can monkeypatch theroadragetrip.osm.CACHE_DIR

    requested_south, requested_west, requested_north, requested_east = bbox
    point_lat, point_lon = point if point is not None else (None, None)
    paths = [_bbox_cache_path(bbox)]
    if os.path.isdir(CACHE_DIR):
        paths.extend(
            entry.path
            for entry in os.scandir(CACHE_DIR)
            if entry.is_file() and entry.path != paths[0] and _bbox_from_cache_name(entry.name) is not None
        )

    for path in paths:
        try:
            cache_bbox = _bbox_from_cache_name(os.path.basename(path))
            if cache_bbox is not None:
                south, west, north, east = cache_bbox
                covers_point = (
                    point_lat is not None
                    and south <= point_lat <= north
                    and west <= point_lon <= east
                )
                covers_request = (
                    south <= requested_south
                    and west <= requested_west
                    and north >= requested_north
                    and east >= requested_east
                )
                if point is not None:
                    if not covers_point:
                        logger.info(
                            "Cache skip %s: point (%.6f, %.6f) outside bbox %s",
                            os.path.basename(path), point_lat, point_lon, cache_bbox,
                        )
                        continue
                elif not covers_request:
                    continue
                if max_cover_ratio is not None and path != paths[0]:
                    ratio = (north - south) * (east - west) / max(
                        1e-12, (requested_north - requested_south) * (requested_east - requested_west))
                    if ratio > max_cover_ratio:
                        logger.info("Cache skip %s: %.0fx the requested area", os.path.basename(path), ratio)
                        continue
                logger.info(
                    "Cache candidate %s: point=%s request_covered=%s",
                    os.path.basename(path), covers_point, covers_request,
                )
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
        except FileNotFoundError:
            # The exact bbox is checked before covering cache entries. It is
            # normal for that file not to exist yet, so do not report a
            # routine cold-cache lookup as a warning.
            logger.debug("Cache miss %s", path)
            continue
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to read cache %s: %s", path, e)
            continue
        ts = d.get("fetched_at", 0)
        if d.get("version") != CACHE_VERSION:
            logger.info(
                "Cache skip %s: version %s != %s",
                os.path.basename(path),
                d.get("version", "missing"),
                CACHE_VERSION,
            )
            try:
                os.remove(path)
            except OSError as e:
                logger.warning("Failed to remove outdated cache %s: %s", path, e)
            continue
        ttl = int(os.getenv("OSM_CACHE_TTL", str(OSM_CACHE_TTL_S)))
        age = time.time() - ts
        if age <= ttl:
            if path.endswith("pjson"):
                migrated_path = _legacy_bbox_cache_path(path)
                try:
                    if not os.path.exists(migrated_path):
                        os.replace(path, migrated_path)
                        path = migrated_path
                        logger.info("Migrated OSM cache to %s", path)
                except OSError as e:
                    logger.warning("Failed to migrate legacy cache %s: %s", path, e)
            if cache_bbox is not None:
                logger.info(
                    "CACHE HIT: %s | bbox=%s | reason=%s | elements=%d | age=%.1fh",
                    path,
                    cache_bbox,
                    "car point" if point is not None else "request covered",
                    len(d.get("elements", [])),
                    age / 3600.0,
                )
            return d.get("elements")
        logger.info(
            "Cache skip %s: expired (age %.1fh, TTL %.1fh)",
            os.path.basename(path), age / 3600.0, ttl / 3600.0,
        )
    return None


def save_osm_cache(bbox: Tuple[float, float, float, float], elements: List[dict]) -> None:
    from . import CACHE_DIR  # re-read each call so tests can monkeypatch theroadragetrip.osm.CACHE_DIR

    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _bbox_cache_path(bbox)
    # Atomic: written beside it under a unique name, then renamed over it, so
    # an interrupted save (or two threads saving one bbox) never leaves a
    # truncated file that looks like a cache.
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=CACHE_DIR)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"version": CACHE_VERSION, "fetched_at": time.time(), "elements": elements}, f)
        os.replace(temporary, path)
        temporary = None
        logger.info("Saved OSM cache to %s", path)
    except Exception as e:
        logger.warning("Failed to save cache %s: %s", path, e)
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def clear_osm_cache() -> int:
    """Delete all files stored in the OSM cache directory - the map data;
    the FMI weather history kept there is not map data and stays."""
    from . import CACHE_DIR  # re-read each call so tests can monkeypatch theroadragetrip.osm.CACHE_DIR

    if not os.path.isdir(CACHE_DIR):
        return 0
    removed = 0
    for entry in os.scandir(CACHE_DIR):
        if entry.name.startswith("weather_history.db"):
            continue
        try:
            if entry.is_dir():
                shutil.rmtree(entry.path)
            else:
                os.remove(entry.path)
            removed += 1
        except OSError as e:
            logger.warning("Failed to remove OSM cache entry %s: %s", entry.path, e)
    logger.info("Cleared OSM cache (%d entries)", removed)
    return removed


def has_outdated_osm_cache() -> bool:
    """Return whether the cache contains data from an older cache format."""
    from . import CACHE_DIR  # re-read each call so tests can monkeypatch theroadragetrip.osm.CACHE_DIR

    if not os.path.isdir(CACHE_DIR):
        return False
    for entry in os.scandir(CACHE_DIR):
        if not entry.is_file() or _bbox_from_cache_name(entry.name) is None:
            continue
        try:
            with open(entry.path, "r", encoding="utf-8") as f:
                if json.load(f).get("version") != CACHE_VERSION:
                    return True
        except (OSError, json.JSONDecodeError):
            continue
    return False
