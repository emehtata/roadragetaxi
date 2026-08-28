"""Tests for busways, bus lanes, and living street (pihatie) accessibility."""
from theroadragetrip.osm import build_ways
from theroadragetrip.physics import is_car_road


def test_busway_and_living_street_are_drivable():
    elements = [
        {"type": "node", "id": 1, "lat": 65.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 65.001, "lon": 25.0},
        {"type": "node", "id": 3, "lat": 65.0, "lon": 25.001},
        {"type": "node", "id": 4, "lat": 65.001, "lon": 25.001},
        {"type": "node", "id": 5, "lat": 65.0, "lon": 25.002},
        {"type": "node", "id": 6, "lat": 65.001, "lon": 25.002},
        # Dedicated busway (highway=busway)
        {
            "type": "way",
            "id": 101,
            "nodes": [1, 2],
            "tags": {"highway": "busway", "name": "Joukkoliikennekatu"},
        },
        # Road with bus/psv/taxi access
        {
            "type": "way",
            "id": 102,
            "nodes": [3, 4],
            "tags": {"highway": "service", "bus": "yes", "motorcar": "no"},
        },
        # Living street (pihatie)
        {
            "type": "way",
            "id": 103,
            "nodes": [5, 6],
            "tags": {"highway": "living_street", "name": "Pihakatu"},
        },
    ]

    ways, _, _, _, _, _ = build_ways(elements)
    assert len(ways) == 3

    busway = next(w for w in ways if w.highway == "busway")
    bus_service = next(w for w in ways if w.highway == "service")
    living_street = next(w for w in ways if w.highway == "living_street")

    assert busway.is_drivable and is_car_road(busway)
    assert busway.is_busway is True

    assert bus_service.is_drivable and is_car_road(bus_service)
    assert bus_service.is_busway is True

    assert living_street.is_drivable and is_car_road(living_street)
