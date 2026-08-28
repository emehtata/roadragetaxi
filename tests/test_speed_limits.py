"""Tests for Finnish speed limits and NPC speeding/compliance behavior."""
import pytest
from theroadragetrip.osm import DEFAULT_SPEED_LIMITS_KMH, Way, build_ways, parse_speed_limit_kmh
from theroadragetrip.physics import Car
from theroadragetrip.traffic import NPCCar, TrafficManager, calculate_npc_target_speed


def test_finnish_default_speed_limits():
    assert DEFAULT_SPEED_LIMITS_KMH["motorway"] == 100
    assert DEFAULT_SPEED_LIMITS_KMH["primary"] == 80
    assert DEFAULT_SPEED_LIMITS_KMH["secondary"] == 80
    assert DEFAULT_SPEED_LIMITS_KMH["tertiary"] == 60
    assert DEFAULT_SPEED_LIMITS_KMH["unclassified"] == 50
    assert DEFAULT_SPEED_LIMITS_KMH["residential"] == 40
    assert DEFAULT_SPEED_LIMITS_KMH["living_street"] == 20
    assert DEFAULT_SPEED_LIMITS_KMH["service"] == 30


def test_parse_speed_limit_tags():
    # Explicit numerical tag
    assert parse_speed_limit_kmh("60", "primary") == 60
    assert parse_speed_limit_kmh("120", "motorway") == 120
    assert parse_speed_limit_kmh("30 km/h", "residential") == 30

    # Implicit / string zone tags
    assert parse_speed_limit_kmh("FI:urban", "primary") == 50
    assert parse_speed_limit_kmh("FI:rural", "unclassified") == 80
    assert parse_speed_limit_kmh("living_street", "living_street") == 20

    # None / empty fallback to Finnish road type default
    assert parse_speed_limit_kmh(None, "residential") == 40
    assert parse_speed_limit_kmh(None, "motorway") == 100
    assert parse_speed_limit_kmh(None, "primary") == 80


def test_build_ways_attaches_speed_limit():
    elements = [
        {"type": "node", "id": 1, "lat": 65.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 65.001, "lon": 25.0},
        {
            "type": "way",
            "id": 10,
            "nodes": [1, 2],
            "tags": {"highway": "residential", "name": "Kotikatu"},
        },
        {
            "type": "way",
            "id": 11,
            "nodes": [1, 2],
            "tags": {"highway": "primary", "maxspeed": "70", "name": "Valtatie"},
        },
    ]

    res = build_ways(elements)
    ways, waters, buildings, sceneries, places, bounds = res
    res_way = next(w for w in ways if w.highway == "residential")
    prim_way = next(w for w in ways if w.highway == "primary")

    assert res_way.speed_limit_kmh == 40  # Default Finnish residential limit
    assert prim_way.speed_limit_kmh == 70  # Explicit parsed tag


def test_npc_speed_compliance_and_speeders():
    residential_way = Way(
        points_m=[(0.0, 0.0), (500.0, 0.0)],
        highway="residential",
        half_width_m=4.5,
        speed_limit_kmh=40,
    )
    motorway_way = Way(
        points_m=[(0.0, 0.0), (1000.0, 0.0)],
        highway="motorway",
        half_width_m=7.0,
        speed_limit_kmh=100,
    )

    # Compliant driver on residential (factor ~1.0 -> ~11.1 m/s / 40 km/h)
    target_res = calculate_npc_target_speed(residential_way, speed_factor=1.0)
    assert pytest.approx(target_res, rel=0.05) == (40 / 3.6)

    # Speeder on residential (factor 1.4 -> ~15.5 m/s / 56 km/h)
    target_speeder_res = calculate_npc_target_speed(residential_way, speed_factor=1.4)
    assert target_speeder_res > target_res
    assert pytest.approx(target_speeder_res, rel=0.05) == (56 / 3.6)

    # Compliant driver on motorway (~27.7 m/s / 100 km/h)
    target_mway = calculate_npc_target_speed(motorway_way, speed_factor=1.0)
    assert pytest.approx(target_mway, rel=0.05) == (100 / 3.6)


def test_npc_traffic_manager_spawns_speed_variations():
    import random
    random.seed(42)
    way = Way(
        points_m=[(0.0, 0.0), (1000.0, 0.0)],
        highway="primary",
        half_width_m=6.0,
        speed_limit_kmh=80,
    )
    traffic_mgr = TrafficManager([way], target_count=30, spawn_radius_m=400.0, despawn_radius_m=600.0)
    player = Car(x=100.0, y=0.0, heading=0.0, speed=0.0)

    traffic_mgr.update(player, dt=0.1)

    assert len(traffic_mgr.npcs) == 30
    speed_factors = [npc.speed_factor for npc in traffic_mgr.npcs]
    # Verify variations exist
    assert min(speed_factors) < 1.0
    # Speeder presence (> 1.2x)
    assert any(npc.is_speeder or npc.speed_factor >= 1.20 for npc in traffic_mgr.npcs)
