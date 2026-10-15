from theroadragetrip.osm import Way
from theroadragetrip.physics import Car
from theroadragetrip import taxi as taxi_module
from theroadragetrip.taxi import TaxiManager, TaxiPassenger, TaxiState, TaxiTarget


def test_long_fare_goes_to_a_town_then_its_address(monkeypatch):
    oulu = (430_000.0, 7_210_000.0)
    monkeypatch.setattr(taxi_module, "_municipality_points", [
        ("Oulu", *oulu, 200_000, None), ("Kempele", oulu[0], oulu[1] - 15_000, 20_000, None),  # too near
        ("Muhos", oulu[0] + 35_000, oulu[1] - 10_000, 9_000, None), ("Kemi", oulu[0], oulu[1] + 105_000, 20_000, None),  # too far
    ])
    taxi = TaxiManager(ways=[])
    town = taxi.pick_long_dropoff(*oulu)
    assert town.municipality == "Muhos" and town.address == "Muhos"

    taxi.current_passenger = TaxiPassenger(name="Aino", pickup=TaxiTarget(*oulu, "Kauppatori"), dropoff=town, boarded=True)
    taxi.state = TaxiState.DRIVING_TO_DROPOFF
    car = Car(x=town.x, y=town.y, heading=0.0, speed=0.0)  # stopped at the bare town centre: no fare end
    taxi.update(car, 0.1)
    assert taxi.current_passenger.dropoff is town and taxi.completed_fares == 0

    # The town's map streams in: the next search finds a street address.
    taxi.sync_map_data([Way(points_m=[(town.x - 200, town.y), (town.x + 200, town.y)], highway="residential", half_width_m=4.5, name="Kirkkotie")])
    taxi.update(car, 3.0)
    dropoff = taxi.current_passenger.dropoff
    assert dropoff.municipality is None and dropoff.address.endswith(", " + town.municipality)


def test_long_fare_to_an_airport_keeps_its_name(monkeypatch):
    airport = (430_000.0, 7_250_000.0)
    monkeypatch.setattr(taxi_module, "_municipality_points", [("Kemi-Tornion lentoasema", *airport, 100_000, "airport")])
    taxi = TaxiManager(ways=[])
    target = taxi.pick_long_dropoff(430_000.0, 7_210_000.0)
    taxi.current_passenger = TaxiPassenger(name="Aino", pickup=TaxiTarget(0, 0, "x"), dropoff=target, boarded=True)
    taxi.state = TaxiState.DRIVING_TO_DROPOFF
    taxi.sync_map_data([Way(points_m=[(airport[0] - 300, airport[1] + 100), (airport[0] + 300, airport[1] + 100)],
                            highway="service", half_width_m=3.0, name="Lentoasemantie")])
    taxi.update(Car(x=airport[0], y=airport[1], heading=0.0, speed=0.0), 3.0)
    dropoff = taxi.current_passenger.dropoff
    assert dropoff.address == "Kemi-Tornion lentoasema" and dropoff.municipality is None
    assert abs(dropoff.y - (airport[1] + 100)) < 1.0
