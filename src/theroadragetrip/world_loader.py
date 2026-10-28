"""Building a playable world for one city (the simulation server's start):
OSM data (Overpass, a local .pbf or the cache), the road network, scenery,
traffic, pedestrians, the taxi and trains. Headless - progress goes to a
callback, never a screen."""

from __future__ import annotations

import concurrent.futures
import functools
import logging
import math
import os
import random
import sys
import time
from types import SimpleNamespace

from .arena_crowds import ArenaCrowds
from .career import (load_career_balance, load_career_distance, load_gig_balance, load_gig_fuel,
                     load_gig_odometer, save_gig_odometer)
from .level_routing import LevelRouteGraphs
from .level_transitions import LevelTransitions, resolve_connectors, close_garage_roads
from .map_level import SURFACE_LEVEL, LevelRoadNetworks
from .trams import TramManager
from .competitor_taxis import Dispatcher
from .taxi_brawls import BrawlManager
from .npc import NPCVehicleManager, npc_target_count_for_population
from .osm import (AutoFetchManager, build_ways, fetch_osm_ways,
                  fetch_osm_ways_from_pbf, load_local_sample, local_pbf_available,
                  remove_trees_under_roads)
from .osm.cache import OSM_CACHE_TTL_S
from .parking import generate_detached_house_parking
from .pedestrian import PedestrianManager, PlayerPedestrian
from .physics import Car, SpatialWayGrid, respawn_car
from .residents import ResidentManager
from .roadworks import create_roadworks
from .taxi import TaxiManager
from .traffic_world import TrafficWorld
from .train_compositions import load_compositions, refresh_if_stale as refresh_compositions_if_stale
from .train_timetable import load_timetable, refresh_if_stale
from .trains import RailwayManager
from .world_cache import WorldCacheManager
from .world_places import load_places

logger = logging.getLogger(__name__)


def with_fetch_bbox(elements, fetch_bbox):
    """The elements plus the (south, west, north, east) they were fetched
    for: build_ways clips sea from coastline to it (coastline is complete
    only there; ways reaching out of it are not)."""
    return list(elements) + [{"type": "fetch_bbox", "bounds": list(fetch_bbox)}]


def resolve_osm_fetch_func(args, overpass_endpoints, progress_callback=None):
    """Pick where OSM data comes from: live Overpass, or a local .osm.pbf
    extract via osmium-tool (osm_source=pbf) - no downloads, no rate
    limits, works offline. Falls back to Overpass with a warning if "pbf"
    was requested but the local file or the `osmium` tool aren't actually
    usable, so a missing extract doesn't just crash map loading outright.
    """
    def _use_overpass(fetch_bbox, **fetch_kwargs):
        if progress_callback is not None:
            fetch_kwargs.setdefault("progress_callback", progress_callback)
        return with_fetch_bbox(fetch_osm_ways(fetch_bbox, endpoints=overpass_endpoints, **fetch_kwargs), fetch_bbox)

    if getattr(args, "osm_source", "overpass") == "pbf":
        pbf_path = getattr(args, "osm_pbf_path", None)
        if local_pbf_available(pbf_path):
            def _use_pbf(fetch_bbox, **fetch_kwargs):
                if progress_callback is not None:
                    fetch_kwargs.setdefault("progress_callback", progress_callback)
                return with_fetch_bbox(fetch_osm_ways_from_pbf(fetch_bbox, pbf_path=pbf_path, **fetch_kwargs), fetch_bbox)

            return _use_pbf
        logger.warning(
            "osm_source=pbf requested but no usable local .osm.pbf/osmium-tool "
            "found (path=%s) - falling back to the Overpass API",
            pbf_path or "assets/osm/finland-latest.osm.pbf",
        )
    return _use_overpass


def latlon_to_world_metres():
    """(lat, lon) -> world metres (EPSG:3067, x east / y north), or None
    without pyproj (trains then fall back to the fixed interval)."""
    try:
        from pyproj import Transformer
    except ImportError:
        return None
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3067", always_xy=True)
    return lambda lat, lon: transformer.transform(lon, lat)


def fetched_area_metres(bbox):
    """The metres rectangle a (south, west, north, east) bbox surely covers:
    the rectangle inside its projected corners (EPSG:3067 turns the meridians,
    so the corners don't line up). None without a bbox or pyproj."""
    to_metres = latlon_to_world_metres()
    if not bbox or to_metres is None:
        return None
    south, west, north, east = bbox
    sw, nw, se, ne = to_metres(south, west), to_metres(north, west), to_metres(south, east), to_metres(north, east)
    return (max(sw[0], nw[0]), max(sw[1], se[1]), min(se[0], ne[0]), min(nw[1], ne[1]))


def load_world(
    chosen_city: str,
    camera_city_name: str,
    bbox,
    city_centers,
    args,
    force_refresh: bool,
    overpass_endpoints,
    bus_stops_enabled: bool,
    roadworks_enabled: bool,
    career,
    career_file,
    gig_odometer_file,
    language: str,
    progress=None,
):
    """Load OSM data for `bbox` and build every world/gameplay-manager object
    a game needs. `progress(fraction, message)` hears how it goes (called
    from the loading thread too; None: nobody listens).

    Exits the process if the OSM data fails to load or the bbox contains no
    map features.
    """
    bbox_center = ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)
    # A custom start (--bbox) can be far from its nearest catalog city:
    # sun and weather follow the map actually loaded.
    sun_latitude, sun_longitude = bbox_center if getattr(args, "bbox", None) else city_centers.get(chosen_city, bbox_center)

    def on_load_progress(fraction: float, message: str) -> None:
        loading_state[0] = max(0.0, min(1.0, fraction))
        loading_state[1] = message
        if progress is not None:
            progress(loading_state[0], message)

    loading_state = [0.05, "Initializing scenery engine..."]
    on_load_progress(0.05, "Initializing scenery engine...")

    def on_build_progress(fraction: float, message: str) -> None:
        on_load_progress(0.05 + min(1.0, fraction) * 0.65, message)

    # Load map
    try:
        elements_count = 0
        world_cache = WorldCacheManager(
            cache_ttl=float(os.getenv("OSM_CACHE_TTL", OSM_CACHE_TTL_S)),
            fetch_func=resolve_osm_fetch_func(args, overpass_endpoints, progress_callback=on_load_progress),
            build_func=lambda raw: build_ways(
                raw, progress_callback=on_build_progress, include_bus_stops=bus_stops_enabled
            ),
        )
        area_id = world_cache.area_id(bbox)

        def load_map_data():
            if args.use_sample:
                on_load_progress(0.2, "Loading bundled offline sample data...")
                elements = load_local_sample()
                if elements is None:
                    raise Exception("No local sample file found")
                logger.info("Using local sample (via --use-sample)")
                on_load_progress(0.5, f"Loaded {len(elements)} sample elements")
                result = build_ways(
                    elements, progress_callback=on_build_progress, include_bus_stops=bus_stops_enabled
                )
                return result, len(elements)
            return world_cache.load_area(  # any cached area holding the start (the taxi spawns at the centre)
                area_id, bbox, force_refresh=force_refresh or args.no_cache, point=bbox_center,
            ), 0

        load_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="startup-map")
        load_future = load_executor.submit(load_map_data)
        while not load_future.done():
            on_load_progress(loading_state[0], loading_state[1])
            time.sleep(1.0 / 30.0)
        res, elements_count = load_future.result()
        load_executor.shutdown(wait=True)
        if args.build_in_process:
            # Startup reports detailed progress in-process. Streaming cache
            # misses use a worker after that, so they cannot stall ticks.
            process_build = functools.partial(build_ways, include_bus_stops=bus_stops_enabled)
            if getattr(args, "osm_source", "overpass") == "pbf" and local_pbf_available(
                getattr(args, "osm_pbf_path", None),
            ):
                world_cache.enable_process_pbf_pipeline(
                    process_build, getattr(args, "osm_pbf_path", None),
                )
            else:
                world_cache.enable_process_build(process_build)
        crossings = getattr(res, "crossings", [])
        stop_signs = getattr(res, "stop_signs", [])
        yield_signs = getattr(res, "yield_signs", [])
        logical_intersections = getattr(res, "logical_intersections", [])
        curbs = getattr(res, "curbs", [])
        if len(res) == 8:
            ways, waters, buildings, sceneries, places, bounds, traffic_lights, crossings = res
        elif len(res) == 7:
            ways, waters, buildings, sceneries, places, bounds, traffic_lights = res
        else:
            ways, waters, buildings, sceneries, places, bounds = res[:6]
            traffic_lights = getattr(res, "traffic_lights", [])
            yield_signs = getattr(res, "yield_signs", [])
    except Exception as e:
        logger.error("Failed to load OSM data: %s", e)
        sys.exit(1)

    if not ways and not waters and not buildings and not sceneries and not places:
        logger.error("No map features found in bbox. Try a different bbox.")
        sys.exit(1)

    minx, miny, maxx, maxy = bounds
    taxi_stops = getattr(res, "taxi_stops", [])
    bus_stops = getattr(res, "bus_stops", [])
    parking_spaces = getattr(res, "parking_spaces", [])
    scenery_objects = getattr(res, "scenery_objects", [])
    # lights.md: explicit OSM lamp-pole positions (highway=street_lamp),
    # when mapped, are the primary source street-light placement uses instead
    # of its own lit=*-driven fixed-spacing synthesis - see osm/build.py's
    # _scenery_object_kind.
    street_lamps = [obj for obj in scenery_objects if obj.kind == "street_lamp"]
    speed_bumps = getattr(res, "speed_bumps", [])
    railways = getattr(res, "railways", [])
    railings = getattr(res, "railings", [])
    parking_garages = getattr(res, "parking_garages", [])  # data only for now (garage-00.md)
    level_ways = getattr(res, "level_ways", [])  # underground roads for the level render gate (garage-03.md)
    level_connectors = getattr(res, "level_connectors", [])  # data only: parking entrances (garage-07.md)
    close_garage_roads((*ways, *level_ways))
    roadworks, roadwork_lights = create_roadworks(ways) if roadworks_enabled else ([], [])
    traffic_lights.extend(roadwork_lights)
    logger.info(
        "Created %d random roadworks (%d temporary lights), enabled=%s",
        len(roadworks),
        len(roadwork_lights),
        roadworks_enabled,
    )
    on_load_progress(0.70, "Preparing road index...")
    remove_trees_under_roads(sceneries, ways)
    # Spatial index for fast O(1) road collision detection
    spatial_grid = SpatialWayGrid(map_level=SURFACE_LEVEL)  # surface driving network (map_level.py)
    spatial_grid.rebuild(ways)
    on_load_progress(0.72, "Preparing house parking...")
    generated_house_bays = generate_detached_house_parking(
        buildings, ways, parking_spaces, spatial_grid
    )
    if generated_house_bays:
        logger.info("Generated %d detached-house residential parking bays", generated_house_bays)
    on_load_progress(0.74, "Preparing building and scenery indexes...")
    building_grid = SpatialWayGrid()
    building_grid.rebuild(buildings)
    scenery_grid = SpatialWayGrid()
    scenery_grid.rebuild(sceneries)
    street_lamp_grid = SpatialWayGrid()
    street_lamp_grid.rebuild(street_lamps)
    water_grid = SpatialWayGrid()
    water_grid.rebuild(waters)
    crossing_grid = SpatialWayGrid()
    crossing_grid.rebuild(crossings)
    traffic_light_grid = SpatialWayGrid()
    traffic_light_grid.rebuild(traffic_lights)
    curb_grid = SpatialWayGrid()
    curb_grid.rebuild(curbs)
    railway_grid = SpatialWayGrid()
    railway_grid.rebuild(railways)
    railing_grid = SpatialWayGrid()
    railing_grid.rebuild(railings)

    # Spawn car on a road near center (avoiding water)
    car = Car(x=(minx + maxx) / 2, y=(miny + maxy) / 2, heading=0.0, speed=0.0)
    if ways:
        to_metres = latlon_to_world_metres()
        pin = to_metres(sun_latitude, sun_longitude) if to_metres else None
        respawn_car(car, ways, near_center=True, bounds=bounds, waters=waters, taxi_stops=taxi_stops, start_point=pin)
        car.engine_on = False  # the driver starts on foot; E starts it after getting in
    career_total_distance_m = None
    if career is not None:
        career_total_distance_m = load_career_distance(career_file)
        car.odometer_m = career_total_distance_m
    else:
        car.odometer_m = load_gig_odometer(gig_odometer_file)
        saved_fuel_l = load_gig_fuel(gig_odometer_file)
        if saved_fuel_l is not None:
            # The gig car keeps whatever was left in the tank last session.
            car.fuel_l = min(car.fuel_capacity_l, saved_fuel_l)
        if car.odometer_m == 0.0:
            car.odometer_m = float(random.randint(100000, 600000))
            save_gig_odometer(gig_odometer_file, car.odometer_m, car.fuel_l)

    # Initialize Taxi Manager for game mode
    on_load_progress(0.80, "Preparing taxi missions...")
    residents = ResidentManager(city_name=chosen_city)
    # Build-time dataset (tools/osm/extract_places.py), not the PBF.
    nearby_places = load_places().within(sun_latitude, sun_longitude, NEARBY_PLACES_RADIUS_M)
    logger.info(
        "World places within %.0f km: %s", NEARBY_PLACES_RADIUS_M / 1000.0,
        ", ".join(f"{place.name} ({place.type})" for place in nearby_places) or "none",
    )
    taxi_mgr = TaxiManager(
        ways,
        places=places,
        buildings=buildings,
        taxi_stops=taxi_stops,
        language=language,
        resident_manager=residents,
    )
    intercity_database = None
    if getattr(args, "intercity_fares", False):
        from pathlib import Path
        from .intercity import prepare_database
        from .osm.cache import default_cache_root
        from .osm.pbf_source import DEFAULT_FINLAND_PBF_PATH
        source = Path(getattr(args, "osm_pbf_path", None) or DEFAULT_FINLAND_PBF_PATH)
        if not local_pbf_available(source):
            raise RuntimeError("Intercity fares require a downloaded Finland PBF and osmium-tool. Download it in Settings or disable intercity fares.")
        message = "Initializing intercity navigation database..."
        on_load_progress(0.81, message)
        # The client translates the text before "|" and shows the step counter after it.
        intercity_database = prepare_database(source,Path(default_cache_root())/"finland.intercity.sqlite",
                                              progress=lambda step: on_load_progress(0.81, f"{message}|{step}"))
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(intercity_database)) as database, database:  # commit, then close: Windows cannot move or delete an open file
            taxi_mgr.intercity_places = {row[0] for row in database.execute("SELECT id FROM places")}
        taxi_mgr.intercity_fares_enabled = True
    if career is None:
        saved_balance_cents = load_gig_balance(gig_odometer_file)
        if saved_balance_cents is not None:
            taxi_mgr.balance_cents = saved_balance_cents
    else:
        taxi_mgr.balance_cents = load_career_balance(career_file)
    speed_cameras = []  # created gradually during gameplay, not in the opening tiles
    # Keep road, signal, and resident services for taxi missions.
    on_load_progress(0.86, "Preparing taxi world...")
    traffic_mgr = TrafficWorld(
        ways,
        stop_signs=stop_signs, yield_signs=yield_signs,
        traffic_lights=traffic_lights,
        crossings=crossings,
        parking_spaces=parking_spaces,
        residents=residents,
        logical_intersections=logical_intersections,
    )
    # vehicle-population: a real, persistent, gradually-filled NPC vehicle
    # population (replaces autonomous-driving's single deterministic demo car).
    # Filled here, during loading, so an initial population exists the
    # moment gameplay starts - see NPCVehicleManager.populate_initial's
    # own docstring for why a plain loop is fine at load time even though
    # ongoing top-up during play is deliberately staggered.
    on_load_progress(0.88, "Preparing NPC traffic...")
    npc_manager = NPCVehicleManager(
        target_count=args.npc_vehicle_count or npc_target_count_for_population(
            (residents.city_data or {}).get("väkiluku")
        ),
        min_count=args.npc_vehicle_min,
        max_count=args.npc_vehicle_max,
        vehicle_distribution=args.vehicle_distribution,
        include_experimental=args.enable_two_wheelers,
        motorcycle_season=getattr(args, "motorcycle_season", None),
    )
    npc_manager.populate_initial(
        car.x, car.y, residents, ways, spatial_grid=spatial_grid,
        parking_spaces=parking_spaces, sceneries=sceneries, buildings=buildings,
        curbs=curbs, curb_grid=curb_grid, building_grid=building_grid,
        progress_callback=lambda fraction: on_load_progress(0.88 + 0.06 * fraction, "Preparing NPC traffic..."),
    )
    logger.info(
        "vehicle-population: populated %d/%d NPC vehicles (%d household, %d autonomous), by type: %s",
        len(npc_manager.vehicles), npc_manager.target_count,
        npc_manager.population_counts()["household"], npc_manager.population_counts()["autonomous"],
        npc_manager.population_counts_by_type(),
    )
    # Same list/dict objects for the life of the session - npc_manager's
    # own population-tick spawns/despawns stay visible through
    # traffic_mgr.npcs without needing to re-set this on every change.
    npcs = npc_manager.vehicles
    npc_drivers = npc_manager.drivers
    traffic_mgr.npcs = npcs
    # Initialize autonomous Pedestrian Manager
    on_load_progress(0.92, "Preparing pedestrians...")
    pedestrian_mgr = PedestrianManager(
        ways,
        target_count=args.pedestrian_count,
        traffic_lights=traffic_lights,
        crossings=crossings,
        logical_intersections=logical_intersections,
        traffic_manager=traffic_mgr,
        residents=residents,
        venue_buildings=buildings,
        scenery_objects=scenery_objects,
        sceneries=sceneries,
        bus_stops=bus_stops,
    )
    # Cyclists are disabled until their traffic interactions are complete.
    player_pedestrian = PlayerPedestrian(
        car.x - math.sin(car.heading) * getattr(car, "width_m", 1.8) * 0.85
        + math.cos(car.heading) * getattr(car, "length_m", 4.0) * 0.2,
        car.y + math.cos(car.heading) * getattr(car, "width_m", 1.8) * 0.85
        + math.sin(car.heading) * getattr(car, "length_m", 4.0) * 0.2,
        heading=car.heading,
    )
    player_pedestrian.is_player = True
    base_pedestrian_count = pedestrian_mgr.target_count

    # Prepare transformer for meters->latlon display
    try:
        from pyproj import Transformer

        transformer_to_ll = Transformer.from_crs("EPSG:3067", "EPSG:4326", always_xy=True)
    except Exception:
        transformer_to_ll = None
        logger.debug("pyproj not available; lat/lon display disabled")

    from .static_world import inherit_part_colours
    inherit_part_colours(buildings)  # a building:part takes its colour-named building's colour

    # Auto fetch manager (background)
    on_load_progress(0.97, "Starting game...")
    auto_fetch_manager = AutoFetchManager(
        ways,
        bounds,
        transformer_to_ll,
        waters=waters,
        buildings=buildings,
        sceneries=sceneries,
        places=places,
        traffic_lights=traffic_lights,
        stop_signs=stop_signs,
        crossings=crossings,
        parking_spaces=parking_spaces,
        taxi_stops=taxi_stops,
        logical_intersections=logical_intersections,
        yield_signs=yield_signs,
        curbs=curbs,
        scenery_objects=scenery_objects,
        speed_bumps=speed_bumps,
        railways=railways,
        railings=railings,
        parking_garages=parking_garages,
        level_ways=level_ways,
        level_connectors=level_connectors,
        fetch_func=resolve_osm_fetch_func(args, overpass_endpoints),
        build_func=build_ways,
        build_in_process=args.build_in_process,
        world_cache_manager=world_cache,
        # The cooldown between tile fetches spares public Overpass servers. A local
        # extract has none to spare: the lookahead tile follows the core window at
        # once, and one map sync covers both (map_sync.SYNC_WAIT_FOR_FETCH_S).
        cooldown_s=0.0 if getattr(args, "osm_source", "overpass") == "pbf"
        and local_pbf_available(getattr(args, "osm_pbf_path", None)) else 5.0,
    )
    auto_fetch_manager.initialize_player_tile(car.x, car.y, fetched_area_metres(bbox))
    auto_fetch_manager.soft_boundary_enabled = args.auto_fetch

    # Trains are simulation (advance_simulation updates them): built with the
    # world so a headless server has them too.
    # The real timetable (Digitraffic), or - turned off - trains at a fixed interval.
    on_load_progress(0.99, "Preparing railways and timetables...")
    timetable = load_timetable() if getattr(args, "train_timetable", True) else None
    if getattr(args, "train_timetable", True):
        refresh_if_stale(timetable)  # weekly, in the background: the next start gets it
    compositions = load_compositions()
    if getattr(args, "train_timetable", True):
        refresh_compositions_if_stale(compositions)
    railway_mgr = RailwayManager(railways, timetable, latlon_to_world_metres(), compositions)
    railway_mgr.associate_taxi_stands(taxi_mgr.taxi_stops)
    railway_mgr.bookings.destination_for = lambda stand: taxi_mgr.pick_phone_dropoff(stand.x, stand.y)
    taxi_mgr.rail_bookings = railway_mgr.bookings
    arena_crowds = ArenaCrowds(
        pedestrian_mgr, taxi_stops, chosen_city, to_metres=latlon_to_world_metres(),
    )
    on_load_progress(1.0, "Ready")
    logger.info("World preparation complete")

    return SimpleNamespace(
        intercity_database=intercity_database,
        arena_crowds=arena_crowds,
        railway_mgr=railway_mgr,
        tram_mgr=TramManager(railways, chosen_city),  # trams on their rails where the city has them (trams.py)
        auto_fetch_manager=auto_fetch_manager,
        base_pedestrian_count=base_pedestrian_count,
        bounds=bounds,
        building_grid=building_grid,
        buildings=buildings,
        bus_stops=bus_stops,
        car=car,
        career_total_distance_m=career_total_distance_m,
        crossing_grid=crossing_grid,
        crossings=crossings,
        curb_grid=curb_grid,
        curbs=curbs,
        railway_grid=railway_grid,
        railways=railways,
        railing_grid=railing_grid,
        railings=railings,
        elements_count=elements_count,
        logical_intersections=logical_intersections,
        npc_drivers=npc_drivers,
        npcs=npcs,
        npc_manager=npc_manager,
        competitor_dispatcher=Dispatcher(),  # competitor taxis take phone fares (competitor_taxis.py)
        taxi_brawls=BrawlManager(),  # competitor drivers' quarrels and fights (taxi_brawls.py)
        parking_garages=parking_garages,
        level_ways=level_ways,
        level_connectors=level_connectors,
        # Off-surface driving networks (garage-05.md) and parking-entrance
        # level changes (garage-08.md); both rebuilt when map sync finishes.
        **level_structures(ways, level_ways, level_connectors),
        parking_spaces=parking_spaces,
        pedestrian_mgr=pedestrian_mgr,
        places=places,
        player_pedestrian=player_pedestrian,
        residents=residents,
        roadworks=roadworks,
        sceneries=sceneries,
        scenery_grid=scenery_grid,
        scenery_objects=scenery_objects,
        street_lamps=street_lamps,
        street_lamp_grid=street_lamp_grid,
        spatial_grid=spatial_grid,
        speed_bumps=speed_bumps,
        speed_cameras=speed_cameras,
        stop_signs=stop_signs,
        yield_signs=yield_signs,
        sun_latitude=sun_latitude,
        sun_longitude=sun_longitude,
        taxi_mgr=taxi_mgr,
        taxi_stops=taxi_stops,
        traffic_light_grid=traffic_light_grid,
        traffic_lights=traffic_lights,
        traffic_mgr=traffic_mgr,
        transformer_to_ll=transformer_to_ll,
        water_grid=water_grid,
        waters=waters,
        ways=ways,
        world_cache=world_cache,
    )


def level_structures(ways, level_ways, level_connectors) -> dict:
    """Everything derived from map levels, built at startup and on every
    map sync (never per frame): off-surface driving networks (garage-05),
    connector topology for level changes (garage-08) and per-level route
    graphs joined by those connectors (garage-10_11)."""
    level_roads = LevelRoadNetworks(ways, level_ways)
    topologies = resolve_connectors(level_connectors, ways, level_ways)[0]
    return {
        "level_roads": level_roads,
        "level_transitions": LevelTransitions(topologies, enabled=False, entrances=level_connectors),
        "level_routes": LevelRouteGraphs(level_roads, ()),
    }


NEARBY_PLACES_RADIUS_M = 50_000.0


def resolve_city(args, city_centers, bbox_presets) -> SimpleNamespace:
    """The city a gig game plays, from the command line: --preset (else
    Oulu) and its bbox, or an explicit --bbox."""
    from .osm.constants import DEFAULT_BBOX

    preset_key = args.preset.lower() if args.preset else "oulu"
    chosen_city = args.preset or preset_key
    bbox = bbox_presets.get(preset_key, DEFAULT_BBOX)
    if args.bbox:
        try:
            parts = [float(p.strip()) for p in args.bbox.split(",")]
            if len(parts) == 4:
                bbox = (parts[0], parts[1], parts[2], parts[3])
        except Exception:
            logger.warning("Invalid bbox provided, using default preset (%s)", preset_key)
    return SimpleNamespace(
        chosen_city=chosen_city, camera_city_name=chosen_city, bbox=bbox, city_centers=city_centers,
        bbox_presets=bbox_presets, game_mode="gig_driver", career=None, force_refresh=args.force_refresh,
        cities_list=list(city_centers.keys()), selected_city_idx=0, language=None,
    )
