from types import SimpleNamespace

import pytest

from theroadragetrip.osm import Way
from theroadragetrip.physics import Car
from theroadragetrip.protocol import _passenger_to_dict
from theroadragetrip.residents import ResidentManager
from theroadragetrip.simulation import passenger_steps_out
from theroadragetrip.taxi import TaxiManager, TaxiOffer, TaxiPassenger, TaxiState, TaxiTarget


def family(monkeypatch):
    residents = ResidentManager()
    parent = residents.create(age=40)
    child = residents.create(age=9)
    assert parent.resident_id in child.parent_ids
    manager = TaxiManager([Way(points_m=[(0, 0), (2000, 0)], highway="residential", half_width_m=4.5)],
                         resident_manager=residents)
    pickup, dropoff = TaxiTarget(0, 0, "Pickup"), TaxiTarget(1000, 0, "Dropoff")
    monkeypatch.setattr(manager, "pick_random_building_point", lambda *a, **kw: dropoff)
    monkeypatch.setattr(manager, "generate_offers", lambda *a, **kw: [])
    ped = SimpleNamespace(resident_id=child.resident_id, x=0.0, y=-2.0, heading=0.0)
    parent_ped = SimpleNamespace(resident_id=parent.resident_id, x=1.0, y=-2.0, heading=0.0)
    return manager, parent, child, pickup, dropoff, ped, parent_ped


@pytest.mark.parametrize("accompaniment", ["none", "stranger", "distant", "driving"])
def test_child_cannot_hail_without_own_available_nearby_parent(monkeypatch, accompaniment):
    manager, parent, child, pickup, _, ped, parent_ped = family(monkeypatch)
    people = [ped]
    if accompaniment == "stranger":
        parent_ped.resident_id = manager.residents.create(age=40).resident_id
    if accompaniment == "distant":
        parent_ped.x = 100.0
    if accompaniment == "driving":
        parent.active_vehicle_id = 123
    if accompaniment != "none":
        people.append(parent_ped)
    assert not manager._board_waiting_pedestrian(ped, pickup, "hail_boarded", pedestrians=people)
    assert manager.current_passenger is None
    assert people[0] is ped


def test_family_walks_boards_and_exits_as_same_residents(monkeypatch):
    manager, parent, child, pickup, dropoff, ped, parent_ped = family(monkeypatch)
    people = [ped, parent_ped]
    assert manager._board_waiting_pedestrian(ped, pickup, "hail_boarded", walk_to_car=True, pedestrians=people)
    assert parent_ped not in people  # parent is now represented in the fare, not duplicated
    party = manager.current_passenger
    assert {p.resident_id for p in party.members} == {parent.resident_id, child.resident_id}
    car = Car(0, 0, 0, 0)
    party.ped_x, party.ped_y = manager._door_position(car)
    party.companions[0].ped_x = 10.0
    manager.update(car, 0.1)
    assert manager.state == TaxiState.CLIENT_WALKING_TO_CAR
    assert not any(p.boarded for p in party.members)
    for _ in range(200):
        manager.update(car, 0.05)
    assert manager.state == TaxiState.DRIVING_TO_DROPOFF
    assert all(p.boarded for p in party.members)
    wire = _passenger_to_dict(party)
    assert wire["passenger_count"] == 2
    assert wire["companions"][0]["resident_id"] == parent.resident_id
    car.x = dropoff.x
    manager.update(car, 0.1)
    assert manager.completed_fares == 1 and manager.current_passenger is None
    spawned = []
    def spawn(x, y, **kwargs):
        spawned.append(kwargs["resident_id"])
        return SimpleNamespace(resident_id=kwargs["resident_id"])
    pedestrians = SimpleNamespace(spawn_pedestrian_at=spawn, pedestrians=[])
    passenger_steps_out(pedestrians, party, car.x, car.y, car.heading)
    assert set(spawned) == {parent.resident_id, child.resident_id}
    assert len(pedestrians.pedestrians) == 2
    assert not any(p.boarded for p in party.members)


def test_generated_fares_include_groups_and_parented_children(monkeypatch):
    manager, parent, _, pickup, dropoff, _, _ = family(monkeypatch)
    name, gender, rid, weight = manager._new_passenger_identity(parent)
    party = TaxiPassenger(name, pickup, dropoff, gender=gender, resident_id=rid, weight_kg=weight)
    monkeypatch.setattr("theroadragetrip.taxi.random.random", lambda: 0.0)
    monkeypatch.setattr("theroadragetrip.taxi.random.randint", lambda low, high: low)
    assert manager._make_party(party, generated=True)
    assert 2 <= len(party.members) <= 4
    assert manager._party_valid(party)
    minors = [manager.residents.get(p.resident_id) for p in party.members
              if manager.residents.age_of(manager.residents.get(p.resident_id)) < 18]
    assert minors and all(parent.resident_id in child.parent_ids for child in minors)


def test_parent_hail_includes_nearby_child(monkeypatch):
    manager, parent, child, pickup, _, ped, parent_ped = family(monkeypatch)
    people = [parent_ped, ped]
    assert manager._board_waiting_pedestrian(parent_ped, pickup, "stand_boarded", pedestrians=people)
    assert {p.resident_id for p in manager.current_passenger.members} == {parent.resident_id, child.resident_id}
    assert people == [parent_ped]


def test_boarded_child_requires_parent_actually_aboard(monkeypatch):
    manager, parent, child, pickup, dropoff, _, _ = family(monkeypatch)
    passenger = TaxiPassenger("Child", pickup, dropoff, resident_id=child.resident_id, boarded=True)
    passenger.companions = [TaxiPassenger("Parent", pickup, dropoff, resident_id=parent.resident_id)]
    assert not manager._party_valid(passenger)
    passenger.companions[0].boarded = True
    assert manager._party_valid(passenger)
    parent.active_vehicle_id = 123
    assert not manager._party_valid(passenger)


def test_offer_rejects_child_without_parent_and_overcapacity(monkeypatch):
    manager, parent, child, pickup, dropoff, _, _ = family(monkeypatch)
    party = TaxiPassenger("Child", pickup, dropoff, resident_id=child.resident_id)
    manager.offers = [TaxiOffer(party, 0)]
    assert not manager.accept_offer(0, 0, 0)
    party.companions = [TaxiPassenger("Parent", pickup, dropoff, resident_id=parent.resident_id)]
    assert manager._party_valid(party)
    party.companions *= 4
    assert not manager.accept_offer(0, 0, 0)


@pytest.mark.parametrize("release", ["cancel", "vomit"])
def test_family_release_does_not_leave_child_in_taxi(monkeypatch, release):
    manager, parent, child, pickup, _, ped, parent_ped = family(monkeypatch)
    assert manager._board_waiting_pedestrian(ped, pickup, "stand_boarded", pedestrians=[ped, parent_ped])
    party = manager.current_passenger
    if release == "cancel":
        manager.discard_mission(0, 0)
        assert manager.released_parties == [party]
    else:
        party.nausea_vomited = True
        assert manager.take_vomited_passenger(Car(0, 0, 0, 0)) is party
    assert manager.current_passenger is None
    assert {p.resident_id for p in party.members} == {parent.resident_id, child.resident_id}
