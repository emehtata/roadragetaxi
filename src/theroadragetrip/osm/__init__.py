"""The Road Rage Trip OSM data package.

Split from a single monolithic osm.py into per-concern submodules; this
__init__ re-exports the full previous public surface (data models,
Overpass fetching, disk cache, tree placement, the ``build_ways``
assembly function, and ``AutoFetchManager``) so existing imports
(``from .osm import X`` / ``from theroadragetrip.osm import X``) keep
working unchanged.

A couple of names (``CACHE_DIR``, ``load_osm_cache``, ``save_osm_cache``)
are read back dynamically from this package by their callers in other
submodules (rather than imported once and cached) specifically so that
tests can keep monkeypatching them as ``theroadragetrip.osm.<name>`` and
have that patch actually take effect, matching the original flat module.
"""

from .constants import (
    BBOX_PRESETS,
    DEFAULT_BBOX,
    DEFAULT_ROAD_HALF_WIDTH_M,
    DEFAULT_SPEED_LIMITS_KMH,
    HIGHWAY_HALF_WIDTH,
    bbox_from_center,
    parse_speed_limit_kmh,
)

from .overpass import (
    DEFAULT_OVERPASS_ENDPOINTS,
    OVERPASS_HEADERS,
    _overpass_stats,
    _overpass_stats_lock,
    configure_user_agent,
    fetch_osm_ways,
    get_overpass_diagnostics,
)

from .cache import (
    CACHE_DIR,
    CACHE_VERSION,
    _bbox_cache_path,
    _bbox_from_cache_name,
    _default_cache_dir,
    _legacy_bbox_cache_path,
    clear_osm_cache,
    has_outdated_osm_cache,
    load_local_sample,
    load_osm_cache,
    save_osm_cache,
)

from .models import (
    Building,
    BusStop,
    Crossing,
    Curb,
    IntersectionApproach,
    LogicalIntersection,
    MapData,
    ParkingSpace,
    Place,
    Scenery,
    SignalGroup,
    StopSign,
    TaxiStop,
    TrafficLight,
    Water,
    Way,
    YieldSign,
    _building_height,
    _building_levels,
    associate_places_with_buildings,
)

from .traffic_signals import (
    build_traffic_light_system,
)

from .trees import (
    plant_trees,
    remove_trees_under_roads,
)

from .build import (
    _stitch_member_ways_into_rings,
    build_ways,
)

from .autofetch import (
    AutoFetchManager,
    _extend_unique,
    _map_object_key,
    _snap_projected_bbox,
)

import requests
import time
