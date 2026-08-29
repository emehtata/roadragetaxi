"""Tests for largest connected road component extraction and spawning."""
from theroadragetrip.osm import TaxiStop, Way
from theroadragetrip.physics import (
    Car,
    compute_largest_connected_road_component,
    respawn_car,
)


def test_respawn_chooses_largest_connected_network():
    # Large connected network (3 connected segments)
    net1 = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="residential",
        half_width_m=4.0,
        name="Main St 1",
    )
    net2 = Way(
        points_m=[(100.0, 0.0), (200.0, 0.0)],
        highway="residential",
        half_width_m=4.0,
        name="Main St 2",
    )
    net3 = Way(
        points_m=[(200.0, 0.0), (300.0, 0.0)],
        highway="residential",
        half_width_m=4.0,
        name="Main St 3",
    )

    # Isolated detached road in the middle of nowhere
    isolated = Way(
        points_m=[(500.0, 500.0), (510.0, 500.0)],
        highway="residential",
        half_width_m=4.0,
        name="Isolated Alley",
    )

    ways = [isolated, net1, net2, net3]

    largest = compute_largest_connected_road_component(ways)
    assert len(largest) == 3
    assert isolated not in largest
    assert net1 in largest and net2 in largest and net3 in largest

    car = Car(x=0.0, y=0.0, heading=0.0, speed=0.0)
    # Respawn car and ensure it never spawns on isolated road
    for _ in range(10):
        respawn_car(car, ways)
        # Position should be on Main St (0 <= x <= 300, y == 0), not on isolated road (x >= 500)
        assert 0.0 <= car.x <= 300.0
        assert car.y == 0.0


def test_respawn_uses_taxi_stop_when_available():
    road = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=4.0)
    car = Car(x=0.0, y=0.0, heading=0.0, speed=0.0)

    respawn_car(car, [road], taxi_stops=[TaxiStop(42.0, 1.0)])

    assert (car.x, car.y) == (42.0, 0.0)
    assert car.speed == 0.0


def test_center_respawn_varies_without_taxi_stops():
    roads = [
        Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=4.0),
        Way(points_m=[(0.0, 100.0), (100.0, 100.0)], highway="residential", half_width_m=4.0),
    ]
    bounds = (0.0, 0.0, 100.0, 100.0)
    positions = set()

    for _ in range(10):
        car = Car(x=0.0, y=0.0, heading=0.0, speed=0.0)
        respawn_car(car, roads, near_center=True, bounds=bounds)
        positions.add((car.x, car.y))

    assert len(positions) > 1
