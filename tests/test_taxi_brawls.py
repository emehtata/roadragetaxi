"""Taxi driver brawls (taxi_brawls.py, docs/taxi-brawls.md): server-decided
quarrels between idle competitor taxis' drivers."""
import math
import random
from datetime import datetime
from types import SimpleNamespace

import pytest

import theroadragetrip.taxi_brawls as tb
from theroadragetrip.competitor_taxis import Dispatcher, TaxiJob
from theroadragetrip.npc import NPCState
from theroadragetrip.taxi_brawls import (
    COOLDOWN, FIGHTING, NPC, PLAYER, RESOLUTION, TRANSITIONS, TRIGGERED, BrawlManager,
)

DT = 0.1


def _taxi(vehicle_id, x, y=0.0):
    return SimpleNamespace(vehicle_id=vehicle_id, x=x, y=y, heading=0.0, width_m=1.8, state=NPCState.PARKED,
                           taxi_job=None, vehicle_kind="taxi", is_taxi=True, driver_departed=False, layer=0,
                           car=SimpleNamespace(map_level=0, speed=0.0), brawl_id=None, color=(0, 0, 0))


def _npcs(*taxis):
    return SimpleNamespace(vehicles=list(taxis), drivers={t.vehicle_id: object() for t in taxis},
                           road_rage=SimpleNamespace(held=set()), _route_jobs=[])


def _quarrel(brawls, a, b, key="k"):
    brawls.report("rank", (NPC, a.vehicle_id), (NPC, b.vehicle_id), ("test", key))


def _run(brawls, npcs, start, seconds):
    t = start
    while t < start + seconds:
        t += DT
        brawls.update(npcs, DT, t)
    return t


def _fighters(conflict, aggression=1.0, retreat=0.0):
    for p in conflict.participants:
        p.aggression, p.retreat = aggression, retreat


def test_two_idle_taxis_side_by_side_start_a_quarrel_and_their_cars_are_locked():
    a, b = _taxi(1, 0.0), _taxi(2, 10.0)
    brawls, npcs = BrawlManager(random.Random(1)), _npcs(a, b)
    _quarrel(brawls, a, b)
    brawls.update(npcs, DT, 0.0)
    (conflict,) = brawls.conflicts.values()
    assert conflict.state == TRIGGERED and [p.ref for p in conflict.participants] == [1, 2]
    assert a.brawl_id == b.brawl_id == conflict.id
    assert all(p.kind == NPC for p in conflict.participants)


@pytest.mark.parametrize("spoil", [
    lambda a, n: setattr(a, "taxi_job", TaxiJob("Aino", (0, 0), (1, 1), leg="dropoff")),  # a fare aboard
    lambda a, n: setattr(a, "taxi_job", TaxiJob("Aino", (0, 0), (1, 1), state="stopped")),  # boarding
    lambda a, n: setattr(a, "state", NPCState.CRUISING),
    lambda a, n: setattr(a, "state", NPCState.CRASHED),
    lambda a, n: n.drivers.pop(a.vehicle_id),
    lambda a, n: setattr(a, "x", 500.0),  # too far to walk over
    lambda a, n: setattr(a, "vehicle_kind", "car"),  # not a taxi
    lambda a, n: n.road_rage.held.add(a.vehicle_id),
    lambda a, n: n._route_jobs.append({"vehicle": a}),  # about to drive off
    lambda a, n: setattr(a.car, "map_level", -1),
])
def test_ineligible_participants_are_rejected(spoil):
    a, b = _taxi(1, 0.0), _taxi(2, 10.0)
    brawls, npcs = BrawlManager(random.Random(1)), _npcs(a, b)
    spoil(a, npcs)
    _quarrel(brawls, a, b)
    brawls.update(npcs, DT, 0.0)
    assert not brawls.conflicts and brawls.rejected == 1 and a.brawl_id is None and b.brawl_id is None


def test_nobody_quarrels_with_themselves_and_the_player_is_not_yet_playable():
    a, b = _taxi(1, 0.0), _taxi(2, 10.0)
    brawls, npcs = BrawlManager(random.Random(1)), _npcs(a, b)
    brawls.report("rank", (NPC, 1), (NPC, 1), ("self",))
    brawls.report("traffic", (PLAYER, "local_player"), (NPC, 1), ("traffic", 1, 0))
    brawls.report("rank", (NPC, 1), (NPC, 99), ("missing",))
    brawls.update(npcs, DT, 0.0)
    assert not brawls.conflicts and brawls.rejected == 3


def test_a_driver_is_in_one_quarrel_at_a_time():
    a, b, c = _taxi(1, 0.0), _taxi(2, 10.0), _taxi(3, 20.0)
    brawls, npcs = BrawlManager(random.Random(1)), _npcs(a, b, c)
    _quarrel(brawls, a, b, "first")
    _quarrel(brawls, c, b, "second")
    brawls.update(npcs, DT, 0.0)
    assert len(brawls.conflicts) == 1 and c.brawl_id is None and brawls.rejected == 1


def test_the_same_event_never_starts_two_quarrels():
    a, b = _taxi(1, 0.0), _taxi(2, 10.0)
    brawls, npcs = BrawlManager(random.Random(1)), _npcs(a, b)
    _quarrel(brawls, a, b)
    _quarrel(brawls, a, b)  # a duplicate in the same tick
    brawls.update(npcs, DT, 0.0)
    assert len(brawls.conflicts) == 1
    t = _run(brawls, npcs, 0.0, tb.MAX_LIFETIME_S + 1)
    brawls.cooldown_until.clear()
    _quarrel(brawls, a, b)  # replayed after the quarrel is over
    brawls.update(npcs, DT, t)
    assert not brawls.conflicts and len(brawls.history) == 1


def _play_out(seed, fight=True):
    a, b = _taxi(1, 0.0), _taxi(2, 10.0)
    brawls, npcs = BrawlManager(random.Random(seed)), _npcs(a, b)
    _quarrel(brawls, a, b)
    brawls.update(npcs, DT, 0.0)
    conflict = next(iter(brawls.conflicts.values()))
    if fight:
        _fighters(conflict)
    states, actions, t = [conflict.state], [], 0.0
    while brawls.conflicts and t < 60.0:
        t += DT
        brawls.update(npcs, DT, t)
        if conflict.state != states[-1]:
            states.append(conflict.state)
        if conflict.action and (not actions or actions[-1]["seq"] != conflict.action["seq"]):
            actions.append(dict(conflict.action, t=round(t, 2)))
    return brawls, conflict, states, actions, (a, b), t


def test_a_fight_follows_the_state_machine_and_ends_with_everyone_back_in_their_cars():
    brawls, conflict, states, actions, (a, b), t = _play_out(3)
    assert states[0] == TRIGGERED and states[-1] == COOLDOWN and FIGHTING in states
    assert all(after in TRANSITIONS[before] for before, after in zip(states, states[1:]))
    assert not brawls.conflicts and a.brawl_id is None and b.brawl_id is None  # cleaned up
    assert len(brawls.history) == 1 and brawls.history[0]["outcome"] in ("knockout", "surrender", "separated")
    assert t < tb.MAX_LIFETIME_S


def test_combat_actions_never_come_faster_than_the_action_interval():
    _, _, _, actions, _, _ = _play_out(5)
    strikes = [x["t"] for x in actions if x["kind"] in ("strike", "dodge")]
    assert strikes and all(later - earlier >= tb.ACTION_INTERVAL_S - 1e-6 for earlier, later in zip(strikes, strikes[1:]))
    assert all(x["actor"] != x["target"] for x in actions)


def test_the_same_seed_plays_out_the_same_fight():
    first, second = _play_out(11), _play_out(11)
    assert first[2:4] == second[2:4] and list(first[0].history) == list(second[0].history)


def test_a_knockout_resolves_once_and_nobody_is_hit_after_it():
    for seed in range(40):
        brawls, conflict, states, actions, _, _ = _play_out(seed)
        if conflict.outcome == "knockout":
            break
    else:
        pytest.fail("no knockout in 40 seeds")
    loser = conflict.participants[1 - conflict.winner]
    assert loser.hits_taken == tb.KNOCKDOWN_HITS
    hits = [x for x in actions if x["hit"]]
    assert sum(1 for x in hits if x["target"] == 1 - conflict.winner) == tb.KNOCKDOWN_HITS
    history = list(brawls.history)
    brawls._resolve(conflict, "separated", None, 99.0)  # a stale second resolution
    assert list(brawls.history) == history and conflict.outcome == "knockout"


def test_a_backed_down_quarrel_never_comes_to_blows():
    for seed in range(40):
        brawls, conflict, states, actions, _, _ = _play_out(seed, fight=False)
        if conflict.outcome == "backed_down":
            break
    else:
        pytest.fail("nobody backed down in 40 seeds")
    assert FIGHTING not in states and not any(x["hit"] for x in actions)


def test_cooldown_keeps_the_same_drivers_apart_for_a_while():
    a, b = _taxi(1, 0.0), _taxi(2, 10.0)
    brawls, npcs = BrawlManager(random.Random(1)), _npcs(a, b)
    _quarrel(brawls, a, b, "1")
    brawls.update(npcs, DT, 0.0)
    t = _run(brawls, npcs, 0.0, tb.MAX_LIFETIME_S + 1)
    assert not brawls.conflicts
    _quarrel(brawls, a, b, "2")
    brawls.update(npcs, DT, t)
    assert not brawls.conflicts
    _quarrel(brawls, a, b, "3")
    brawls.update(npcs, DT, t + tb.DRIVER_COOLDOWN_S)
    assert brawls.conflicts


@pytest.mark.parametrize("vanish", [
    lambda a, n: n.vehicles.remove(a),  # despawned
    lambda a, n: setattr(a, "driver_departed", True),  # crashed into by someone
    lambda a, n: n.drivers.pop(a.vehicle_id),
])
def test_a_participant_disappearing_aborts_the_quarrel_and_frees_the_other(vanish):
    a, b = _taxi(1, 0.0), _taxi(2, 10.0)
    brawls, npcs = BrawlManager(random.Random(1)), _npcs(a, b)
    _quarrel(brawls, a, b)
    brawls.update(npcs, DT, 0.0)
    _run(brawls, npcs, 0.0, 2.0)
    vanish(a, npcs)
    brawls.update(npcs, DT, 2.1)
    assert not brawls.conflicts and b.brawl_id is None and brawls.history[-1]["outcome"] == "aborted"


def test_every_quarrel_ends_within_its_lifetime():
    a, b = _taxi(1, 0.0), _taxi(2, 10.0)
    brawls, npcs = BrawlManager(random.Random(1)), _npcs(a, b)
    _quarrel(brawls, a, b)
    brawls.update(npcs, DT, 0.0)
    next(iter(brawls.conflicts.values())).deadline = float("inf")  # stuck in TRIGGERED
    _run(brawls, npcs, 0.0, tb.MAX_LIFETIME_S + 1)
    assert not brawls.conflicts and a.brawl_id is None and brawls.history[-1]["outcome"] == "aborted"


def test_invalid_transitions_are_refused():
    a, b = _taxi(1, 0.0), _taxi(2, 10.0)
    brawls, npcs = BrawlManager(random.Random(1)), _npcs(a, b)
    _quarrel(brawls, a, b)
    brawls.update(npcs, DT, 0.0)
    with pytest.raises(ValueError):
        brawls._enter(next(iter(brawls.conflicts.values())), FIGHTING, 0.0, 1.0)


def test_the_client_sees_the_current_state_only_and_nothing_once_they_are_back_in():
    brawls, npcs = BrawlManager(random.Random(3)), _npcs(_taxi(1, 0.0), _taxi(2, 10.0))
    _quarrel(brawls, *npcs.vehicles)
    brawls.update(npcs, DT, 0.0)
    conflict = next(iter(brawls.conflicts.values()))
    _fighters(conflict)
    t = 0.0
    while conflict.state != FIGHTING:
        t += DT
        brawls.update(npcs, DT, t)
    (row,) = brawls.to_dicts(t)
    assert row["state"] == FIGHTING and len(row["fighters"]) == 2 and "history" not in row
    fighter = row["fighters"][0]
    assert set(fighter) == {"kind", "id", "x", "y", "heading", "down", "moving", "curse_timer", "curse_text"}
    assert math.hypot(fighter["x"] - row["fighters"][1]["x"], fighter["y"] - row["fighters"][1]["y"]) < 10.0  # walked over
    while conflict.state != COOLDOWN:
        t += DT
        brawls.update(npcs, DT, t)
    assert brawls.to_dicts(t) == []


def test_a_rival_waiting_beside_the_taxi_that_got_the_fare_picks_a_quarrel(monkeypatch):
    monkeypatch.setattr(tb, "DISPUTE_CHANCE", 1.0)
    a, b = _taxi(1, 0.0), _taxi(2, 12.0)
    npcs = _npcs(a, b)
    target = SimpleNamespace(x=0.0, y=0.0)
    phone = SimpleNamespace(offers=[SimpleNamespace(passenger=SimpleNamespace(name="Aino", pickup=target,
                                                                              dropoff=SimpleNamespace(x=900, y=0)))],
                            language="en", notification_msg="", notification_timer=0.0)
    brawls = BrawlManager(random.Random(1))
    dispatcher = Dispatcher(rng=random.Random(1))
    for _ in range(600):
        dispatcher.update(phone, npcs, 1.0, brawls)
        if not phone.offers:
            break
    assert a.taxi_job is not None  # the nearer one got the fare
    brawls.update(npcs, DT, 0.0)
    (conflict,) = brawls.conflicts.values()
    assert conflict.trigger == "passenger" and [p.ref for p in conflict.participants] == [2, 1]


@pytest.mark.parametrize("moment,quarrel", [(datetime(2026, 10, 17, 2), True), (datetime(2026, 10, 14, 14), False)])
def test_idle_taxis_at_a_stand_quarrel_more_at_the_nightlife_peak(monkeypatch, moment, quarrel):
    monkeypatch.setattr(tb, "NIGHT_RANK_CHANCE", 1.0)
    monkeypatch.setattr(tb, "RANK_CHANCE", 0.0)
    a, b = _taxi(1, 0.0), _taxi(2, 10.0)
    brawls, npcs = BrawlManager(random.Random(1)), _npcs(a, b)
    stand = [SimpleNamespace(x=5.0, y=0.0)]
    brawls.update(npcs, tb.RANK_CHECK_INTERVAL_S, 0.0, stand, moment)  # the check queues the trigger
    brawls.update(npcs, DT, 0.1, stand, moment)
    assert bool(brawls.conflicts) == quarrel


@pytest.mark.timing
def test_npc_taxis_stay_put_while_their_drivers_fight_then_drive_on(monkeypatch):
    """End to end on real roads with the real NPC manager: the Saturday-night
    rivals would cruise after their dispatch stop, but not while quarrelling."""
    import theroadragetrip.npc as npc
    from theroadragetrip.competitor_taxis import make_competitor
    from theroadragetrip.npc import NPCVehicleManager, spawn_npc
    from theroadragetrip.physics import SpatialWayGrid
    from theroadragetrip.residents import ResidentManager
    from theroadragetrip.traffic_world import TrafficWorld
    from test_competitor_taxis import _city_block_grid

    random.seed(4)
    monkeypatch.setattr(npc, "people_within", lambda *args: 1500)
    ways = _city_block_grid()
    traffic = TrafficWorld(ways)
    residents = ResidentManager()
    manager = NPCVehicleManager(target_count=2, max_count=2, spawn_radius_m=300, vehicle_distribution={"car": 1.0})
    manager.clock = datetime(2026, 10, 17, 3)
    for vehicle_id, start in ((1, (30, 0)), (2, (45, 0))):
        _, driver, taxi = spawn_npc(vehicle_id, residents, traffic, ways, start, (90, 0))
        make_competitor(taxi)
        taxi.state = NPCState.PARKED
        manager.vehicles.append(taxi)
        manager.drivers[taxi.vehicle_id] = driver
    a, b = manager.vehicles
    starts = {v.vehicle_id: (v.x, v.y) for v in manager.vehicles}
    brawls = BrawlManager(random.Random(3))
    _quarrel(brawls, a, b)
    buildings = SpatialWayGrid([])
    fought, moved_during = False, False
    for i in range(30 * 120):
        traffic.advance_time(1 / 30)
        manager.update(1 / 30, 210, 210, residents, traffic, ways, building_grid=buildings)
        brawls.update(manager, 1 / 30, traffic.sim_time)
        if brawls.conflicts:
            fought = True
            moved_during |= any(math.dist((v.x, v.y), starts[v.vehicle_id]) > 0.5 for v in (a, b))
        elif fought and all(math.dist((v.x, v.y), starts[v.vehicle_id]) > 15 for v in (a, b)):
            break
    assert fought and not moved_during
    assert a.brawl_id is None and b.brawl_id is None and brawls.history[-1]["outcome"] != "aborted"
    assert all(math.dist((v.x, v.y), starts[v.vehicle_id]) > 15 for v in (a, b)), "they cruise again afterwards"
    assert all(manager.drivers.get(v.vehicle_id) is not None and v.state != NPCState.CRASHED for v in (a, b))
