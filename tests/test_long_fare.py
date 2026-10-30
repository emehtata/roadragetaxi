from theroadragetrip.osm import Way
from theroadragetrip.physics import Car
from theroadragetrip import taxi as taxi_module
from theroadragetrip.taxi import TaxiManager, TaxiPassenger, TaxiState, TaxiTarget


def test_phone_fare_mix(monkeypatch):
    taxi = TaxiManager(ways=[])
    taxi.intercity_fares_enabled = True
    monkeypatch.setattr(taxi,'passenger_waiting_position',lambda pickup:(0,0,0))
    monkeypatch.setattr(taxi,'pick_phone_pickup',lambda *args:TaxiTarget(0,0,'Pickup'))
    monkeypatch.setattr(taxi,'pick_long_dropoff',lambda *args:TaxiTarget(30000,0,'Town'))
    monkeypatch.setattr(taxi,'pick_airport_dropoff',lambda *args:TaxiTarget(12000,0,'Airport'))
    monkeypatch.setattr(taxi,'pick_phone_dropoff',lambda *args:TaxiTarget(1000,0,'Local'))
    destinations = []
    for i in range(100):
        monkeypatch.setattr(taxi_module.random,'random',lambda i=i:(i+.5)/100)
        offers = taxi.generate_offers(0,0,count=1)
        destinations.append(offers[0].passenger.dropoff.address)
    assert destinations.count('Airport') == 10
    assert destinations.count('Town') == 10
    assert destinations.count('Local') == 80


def test_nearest_airport_and_return_to_town(monkeypatch):
    monkeypatch.setattr(taxi_module,'_municipality_points',[
        ('City',0,0,100,None),('Airport',12000,0,100,'airport'),
        ('Far airport',40000,0,100,'airport')])
    taxi = TaxiManager(ways=[])
    assert taxi.pick_airport_dropoff(0,0).address == 'Airport'
    assert taxi.pick_airport_dropoff(12000,0).address == 'City'
    taxi.intercity_places = set()
    assert taxi.pick_airport_dropoff(0,0) is None


def test_intercity_offers_are_opt_in(monkeypatch):
    taxi = TaxiManager(ways=[])
    monkeypatch.setattr(taxi,'passenger_waiting_position',lambda pickup:(0,0,0))
    assert not taxi.intercity_fares_enabled
    monkeypatch.setattr(taxi,"pick_phone_pickup",lambda *args: TaxiTarget(0,0,"Pickup"))
    monkeypatch.setattr(taxi,"pick_phone_dropoff",lambda *args: TaxiTarget(1000,0,"Local"))
    calls = []
    monkeypatch.setattr(taxi,"pick_long_dropoff",lambda *args: calls.append(True))
    monkeypatch.setattr(taxi_module,"LONG_FARE_CHANCE",1.0)
    taxi.generate_offers(0,0,count=1)
    assert not calls
    taxi.intercity_fares_enabled = True
    taxi.generate_offers(0,0,count=1)
    assert calls


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
    target = taxi.pick_airport_dropoff(430_000.0, 7_210_000.0)
    taxi.current_passenger = TaxiPassenger(name="Aino", pickup=TaxiTarget(0, 0, "x"), dropoff=target, boarded=True)
    taxi.state = TaxiState.DRIVING_TO_DROPOFF
    taxi.sync_map_data([Way(points_m=[(airport[0] - 300, airport[1] + 100), (airport[0] + 300, airport[1] + 100)],
                            highway="service", half_width_m=3.0, name="Lentoasemantie")])
    taxi.update(Car(x=airport[0], y=airport[1], heading=0.0, speed=0.0), 3.0)
    dropoff = taxi.current_passenger.dropoff
    assert dropoff.address == "Kemi-Tornion lentoasema" and dropoff.municipality is None
    assert abs(dropoff.y - (airport[1] + 100)) < 1.0


def test_long_fare_to_an_airport_prefers_its_taxi_stand(monkeypatch):
    from theroadragetrip.osm import TaxiStop
    airport = (430_000.0, 7_250_000.0)
    monkeypatch.setattr(taxi_module, "_municipality_points", [("Oulun lentoasema", *airport, 100_000, "airport")])
    stand = TaxiStop(x=airport[0] + 500, y=airport[1])
    taxi = TaxiManager(ways=[], taxi_stops=[stand])
    target = taxi.pick_airport_dropoff(430_000.0, 7_210_000.0)
    taxi.current_passenger = TaxiPassenger(name="Aino", pickup=TaxiTarget(0, 0, "x"), dropoff=target, boarded=True)
    taxi.state = TaxiState.DRIVING_TO_DROPOFF
    taxi.sync_map_data([Way(points_m=[(airport[0] - 50, airport[1]), (airport[0] + 50, airport[1])],
                            highway="service", half_width_m=3.0)])
    taxi.update(Car(x=airport[0], y=airport[1], heading=0.0, speed=0.0), 3.0)
    dropoff = taxi.current_passenger.dropoff
    assert (dropoff.x, dropoff.y) == (stand.x, stand.y) and dropoff.address == "Oulun lentoasema"


def test_an_airport_road_waits_for_the_airport_tile_where_its_stand_may_be(monkeypatch):
    airport = (430_000.0, 7_250_000.0)
    monkeypatch.setattr(taxi_module, "_municipality_points", [("Oulun lentoasema", *airport, 100_000, "airport")])
    taxi = TaxiManager(ways=[])
    loaded = []
    taxi.map_covers = lambda x, y: bool(loaded)
    target = taxi.pick_airport_dropoff(430_000.0, 7_210_000.0)
    taxi.current_passenger = TaxiPassenger(name="Aino", pickup=TaxiTarget(0, 0, "x"), dropoff=target, boarded=True)
    taxi.state = TaxiState.DRIVING_TO_DROPOFF
    taxi.sync_map_data([Way(points_m=[(airport[0] - 300, airport[1] + 300), (airport[0] + 300, airport[1] + 300)],
                            highway="service", half_width_m=3.0)])  # a car park, streamed in first
    car = Car(x=airport[0], y=airport[1], heading=0.0, speed=0.0)
    taxi.update(car, 3.0)
    assert taxi.current_passenger.dropoff is target  # not the car park yet
    from theroadragetrip.osm import TaxiStop
    taxi.taxi_stops.append(TaxiStop(x=airport[0] + 40, y=airport[1]))
    loaded.append(True)
    taxi.update(car, 3.0)
    assert taxi.current_passenger.dropoff.x == airport[0] + 40
