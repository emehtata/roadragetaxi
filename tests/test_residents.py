from datetime import date

from theroadragetrip import residents as residents_module
from theroadragetrip.residents import ResidentManager


def test_resident_lod_uses_distance_bands():
    manager = ResidentManager()
    resident = manager.create()

    assert manager.update_lod(resident.resident_id, 100.0, 0.0, 0.0, 0.0, 0.1) == 0
    assert resident.lod_update_due is True

    assert manager.update_lod(resident.resident_id, 1000.0, 0.0, 0.0, 0.0, 0.1) == 1
    assert manager.update_lod(resident.resident_id, 2000.0, 0.0, 0.0, 0.0, 0.1) == 2


def test_city_resident_gets_birth_date_from_age_distribution():
    manager = ResidentManager("Tampere")
    resident = manager.create()

    age = date.today().year - resident.birth_date.year
    assert 0 <= age <= 100
    assert resident.birth_date <= date.today()


def test_city_density_is_higher_near_city_center():
    manager = ResidentManager("Tampere")
    manager.set_city_center_m(0.0, 0.0)

    assert manager.density_spawn_probability(0.0, 0.0) > manager.density_spawn_probability(10000.0, 0.0)


def test_minor_is_created_with_an_adult_parent():
    manager = ResidentManager()
    child = manager.create(age=12)

    assert child.parent_ids
    parent_id = next(iter(child.parent_ids))
    parent = manager.get(parent_id)
    assert parent is not None
    assert manager.age_of(parent) >= 18
    assert manager.age_of(parent) - manager.age_of(child) <= 44
    assert child.resident_id in parent.child_ids


def test_existing_adult_becomes_parent_of_minor():
    manager = ResidentManager()
    parent = manager.create(age=42)
    child = manager.create(age=7)

    assert child.parent_ids == {parent.resident_id}
    assert parent.child_ids == {child.resident_id}
    assert child.surname == parent.surname


def test_creating_adult_does_not_create_a_child():
    manager = ResidentManager()
    adult = manager.create(age=42)

    assert len(manager.residents) == 1
    assert adult.child_ids == set()


def test_minor_parent_age_gap_is_between_18_and_44_years():
    manager = ResidentManager()
    parent = manager.create(age=44)
    child = manager.create(age=10)

    parent_age_gap = manager.age_of(parent) - manager.age_of(child)
    assert 18 <= parent_age_gap <= 44


def test_weighted_name_cache_is_reused_across_calls():
    """Regression: _weighted_name() used to rebuild its filtered-and-
    weighted candidate list (a full scan plus a max()/int() per entry)
    from scratch on *every single call*, against the full FIRST_NAMES/
    SURNAMES datasets (thousands of entries each, fixed at import time,
    never mutated). During a pedestrian population-update burst that
    creates several residents in one pass, this measurably added up on
    top of the ped_ways bug in the same burst (see test_pedestrians.py).
    _weighted_name_cache must hold one (candidates, weights) pair per
    (id(entries), group) and reuse the same object across calls, not
    rebuild it every time."""
    residents_module._weighted_name_cache.clear()
    entries = [
        {"name": "Testi", "group": "a", "people": 5},
        {"name": "Toinen", "group": "b", "people": 3},
    ]

    residents_module._weighted_name(entries, "a")
    assert (id(entries), "a") in residents_module._weighted_name_cache
    cached_first = residents_module._weighted_name_cache[(id(entries), "a")]

    residents_module._weighted_name(entries, "a")
    cached_second = residents_module._weighted_name_cache[(id(entries), "a")]
    assert cached_first is cached_second, (
        "candidates/weights were rebuilt on the second call instead of reused from cache"
    )