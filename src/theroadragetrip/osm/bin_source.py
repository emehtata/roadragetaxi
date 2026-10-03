"""Load a predefined city's road network from a prebuilt V2 `.bin` (see
tools/osm/build_finland_roads.py, benchmark_oulu.py, benchmark_cities.py).

This is a fast, deterministic alternative to fetching+building road ways
from Overpass/PBF (osm/overpass.py, osm/pbf_source.py) for the handful of
cities that have a pre-generated binary. It supplies `Way` objects only
(no buildings/water/scenery/etc.) - `main/__init__.py` uses this to
replace the *road* ways for a predefined city's world while buildings,
water, scenery, etc. keep coming from the existing OSM fetch, unchanged.

If no binary exists for a city, or `tools/osm` isn't importable (it is
dev tooling, not part of the packaged game - see pyproject.toml's
`[tool.setuptools.packages.find]`), or the binary fails to load, callers
must treat that as "no prebuilt data available" and keep using the
existing OSM/PBF/Overpass path - never as a fatal error.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import List, Optional, Tuple

from .constants import parse_road_half_width_m
from .models import Way

logger = logging.getLogger(__name__)

# Mirrors src/theroadragetrip/assets/osm/ (the bundled Finland PBF) - city
# binaries are bundled game data, not build tooling, so they live under the
# package's own assets/ directory rather than under tools/osm/.
CITY_BIN_DIR = Path(__file__).resolve().parents[1] / "assets" / "roads"


def _city_slug(city_name: str) -> str:
    """Same normalization as config.py's replace_city_in_config, so a BIN
    file placed for a catalog city name resolves regardless of case/spacing."""
    return city_name.strip().casefold().replace(" ", "_")


def city_bin_path(city_name: str) -> Path:
    return CITY_BIN_DIR / f"{_city_slug(city_name)}.bin"


def city_bin_available(city_name: str) -> bool:
    return city_bin_path(city_name).is_file()


class CityBinUnavailableError(Exception):
    """Raised when a city's prebuilt road binary can't be used - missing,
    unreadable, or the V2 reader (tools/osm) isn't importable. Callers
    catch this and fall back to the existing OSM/PBF/Overpass path."""


def load_city_ways(
    city_name: str, bin_path: Optional[Path] = None,
) -> Tuple[List[Way], int, int, float]:
    """Build `Way` objects from a city's prebuilt V2 binary.

    Returns (ways, node_count, geometry_point_count, load_seconds).
    Raises CityBinUnavailableError if the binary is missing, unreadable,
    or the V2 reader can't be imported - never returns a partial result.
    """
    path = bin_path or city_bin_path(city_name)
    if not path.is_file():
        raise CityBinUnavailableError(f"no prebuilt road binary at {path}")

    try:
        from tools.osm.build_finland_roads import RoadDatasetError, decode_coordinate, load_road_dataset
    except ImportError as exc:
        raise CityBinUnavailableError(f"V2 road binary reader unavailable: {exc}") from exc

    started = time.perf_counter()
    try:
        dataset = load_road_dataset(path)
    except (OSError, RoadDatasetError) as exc:
        raise CityBinUnavailableError(f"failed to load {path}: {exc}") from exc

    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3067", always_xy=True)
    local_indices = sorted(dataset.nodes)
    lons = [decode_coordinate(dataset.nodes[index][1]) for index in local_indices]
    lats = [decode_coordinate(dataset.nodes[index][0]) for index in local_indices]
    # Same batch-then-per-point fallback as osm/build.py's build_ways(): a
    # transformer that can't accept list input (e.g. a test double) still
    # works, just slower.
    try:
        xs, ys = transformer.transform(lons, lats)
        if not (hasattr(xs, "__len__") and len(xs) == len(local_indices)):
            raise TypeError("transform() did not return batched output")
    except Exception:
        xs, ys = zip(*(transformer.transform(lon, lat) for lon, lat in zip(lons, lats)))
    points_by_index = dict(zip(local_indices, zip(xs, ys)))

    ways: List[Way] = []
    geometry_points = 0
    for road in dataset.ways:
        points_m = [points_by_index[index] for index in road.node_ids]
        pxs = [p[0] for p in points_m]
        pys = [p[1] for p in points_m]
        ways.append(Way(
            points_m=points_m,
            highway=road.highway,
            half_width_m=parse_road_half_width_m(None, road.highway),
            name=road.name or None,
            surface=road.surface or None,
            is_drivable=True,  # every V2 highway type is already drivable-only (build_finland_roads.DRIVABLE_HIGHWAY_TYPES)
            oneway=road.oneway,
            lanes=road.lanes,
            layer=road.layer,
            is_bridge=road.bridge,
            is_tunnel=road.tunnel,
            speed_limit_kmh=road.maxspeed_kmh,
            bbox=(min(pxs), min(pys), max(pxs), max(pys)),
            osm_id=road.osm_id,
            is_roundabout=road.junction == "roundabout",
            priority_road=road.junction == "priority",
        ))
        geometry_points += len(road.node_ids)

    load_seconds = time.perf_counter() - started
    return ways, len(dataset.nodes), geometry_points, load_seconds
