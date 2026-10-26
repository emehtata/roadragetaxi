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


def test_nobody_quarrels_with_themselves_or_with_an_absent_player():
    a, b = _taxi(1, 0.0), _taxi(2, 10.0)
    brawls, npcs = BrawlManager(random.Random(1)), _npcs(a, b)
    brawls.report("rank", (NPC, 1), (NPC, 1), ("self",))
    brawls.report("traffic", (PLAYER, "local_player"), (NPC, 1), ("traffic", 1, 0))  # no player view this tick
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
    assert set(fighter) == {"kind", "id", "x", "y", "heading", "down", "moving", "curse_timer", "curse_text", "rage", "in_car"}
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


# -- road rage in combat (rrt-019-brawl-02) ---------------------------------

def _person(kind=NPC, skill=0.5, aggression=0.5, retreat=0.5):
    return tb.Participant(kind, 1, aggression=aggression, skill=skill, retreat=retreat)


def test_no_rage_is_the_baseline():
    calm = tb.rage_modifiers(0.0)
    assert calm == tb.RageModifiers(0.0, 0.0, 0.0, 0.0, 0.0)
    assert tb.hit_chance(_person(), _person(), 0.0, 0.0) == pytest.approx(tb.BASE_HIT_CHANCE)


def test_rage_raises_offence_smoothly():
    steps = [tb.rage_modifiers(r / 10) for r in range(11)]
    for earlier, later in zip(steps, steps[1:]):
        assert later.attack > earlier.attack and later.initiative > earlier.initiative
        assert later.intimidation > earlier.intimidation and later.stagger_resist > earlier.stagger_resist
        assert later.attack - earlier.attack < 0.02  # no jumps at thresholds
    assert steps[-1].attack == pytest.approx(tb.RAGE_ATTACK_BONUS)


def test_only_extreme_rage_drops_the_guard_and_smoothly():
    assert tb.rage_modifiers(tb.RAGE_EXTREME).defense == 0.0
    assert tb.rage_modifiers(0.5).defense == 0.0
    curve = [tb.rage_modifiers(tb.RAGE_EXTREME + i * 0.03).defense for i in range(11)]
    assert all(later < earlier or earlier == later == 0.0 for earlier, later in zip(curve, curve[1:]))
    assert tb.rage_modifiers(1.0).defense == pytest.approx(-tb.RAGE_DEFENSE_PENALTY)
    # An enraged defender is easier to hit than a calm one.
    assert tb.hit_chance(_person(), _person(), 0.0, 1.0) > tb.hit_chance(_person(), _person(), 0.0, 0.0)


@pytest.mark.parametrize("rage", [-5.0, -0.1, 0.0, 0.3, 1.0, 1.5, 99.0, float("nan"), float("inf"), None, "x"])
def test_modifiers_stay_in_bounds_whatever_the_rage(rage):
    m = tb.rage_modifiers(rage)
    assert 0.0 <= m.attack <= tb.RAGE_ATTACK_BONUS and 0.0 <= m.initiative <= tb.RAGE_INITIATIVE
    assert 0.0 <= m.intimidation <= tb.RAGE_INTIMIDATION and 0.0 <= m.stagger_resist <= tb.RAGE_STAGGER_RESIST
    assert -tb.RAGE_DEFENSE_PENALTY <= m.defense <= 0.0
    for a_skill, d_skill in ((1.0, 0.0), (0.0, 1.0)):
        chance = tb.hit_chance(_person(skill=a_skill), _person(skill=d_skill), rage, rage)
        assert tb.HIT_CHANCE_BOUNDS[0] <= chance <= tb.HIT_CHANCE_BOUNDS[1]
    assert 0.0 <= tb.back_down_chance(_person(retreat=1.0), _person(aggression=0.0), rage) <= tb.BACK_DOWN_MAX


def test_full_rage_never_guarantees_a_hit_and_skill_still_counts():
    raging_novice = tb.hit_chance(_person(skill=0.0), _person(skill=1.0), 1.0, 0.0)
    calm_expert = tb.hit_chance(_person(skill=1.0), _person(skill=0.0), 0.0, 0.0)
    assert raging_novice < calm_expert  # rage does not buy skill
    assert tb.hit_chance(_person(skill=1.0), _person(skill=0.0), 1.0, 1.0) <= tb.HIT_CHANCE_BOUNDS[1] < 1.0
    # ...and the opponent's temperament still decides intimidation.
    assert (tb.back_down_chance(_person(retreat=0.1), _person(aggression=0.9), 1.0)
            < tb.back_down_chance(_person(retreat=0.9), _person(aggression=0.1), 0.0))


def test_players_and_npcs_share_the_same_formulas():
    npc, player = _person(NPC, skill=0.6), _person(PLAYER, skill=0.6)
    opponent = _person(skill=0.4)
    assert tb.hit_chance(npc, opponent, 0.8, 0.2) == tb.hit_chance(player, opponent, 0.8, 0.2)
    taxi = _taxi(1, 0.0)
    tb.provoke(taxi, 0.8, 0.0)
    brawls = BrawlManager(random.Random(1))
    brawls._vehicles = {1: taxi}
    brawls.player_rage = 0.8
    assert brawls.rage(tb.Participant(NPC, 1), 0.0) == brawls.rage(tb.Participant(PLAYER, "local_player"), 0.0)


def test_npc_rage_is_provoked_calms_lazily_and_stays_bounded():
    taxi = _taxi(1, 0.0)
    assert tb.npc_rage(taxi, 100.0) == 0.0  # never provoked
    tb.provoke(taxi, tb.PROVOKE_BUMP, 10.0)
    assert tb.npc_rage(taxi, 10.0) == pytest.approx(tb.PROVOKE_BUMP)
    assert tb.npc_rage(taxi, 10.0 + tb.NPC_RAGE_CALM_S / 4) == pytest.approx(tb.PROVOKE_BUMP - 0.25)
    for _ in range(10):
        tb.provoke(taxi, 0.5, 20.0)
    assert tb.npc_rage(taxi, 20.0) == 1.0
    assert tb.npc_rage(taxi, 20.0 + tb.NPC_RAGE_CALM_S * 2) == 0.0
    taxi.rage = float("nan")
    assert tb.npc_rage(taxi, 20.0) == 0.0


def _fight_scene(seed, rage_a=0.0, rage_b=0.0):
    a, b = _taxi(1, 0.0), _taxi(2, 10.0)
    brawls, npcs = BrawlManager(random.Random(seed)), _npcs(a, b)
    _quarrel(brawls, a, b)
    brawls.update(npcs, DT, 0.0)
    conflict = next(iter(brawls.conflicts.values()))
    _fighters(conflict)
    for p in conflict.participants:
        p.skill = 0.5
    t = 0.0
    while conflict.state != FIGHTING:
        t += DT
        brawls.update(npcs, DT, t)
    for taxi, rage in ((a, rage_a), (b, rage_b)):
        taxi.rage, taxi.rage_at = rage, t
    return brawls, npcs, conflict, (a, b), t


def test_the_same_situation_and_seed_give_the_same_actions():
    runs = []
    for _ in range(2):
        brawls, npcs, conflict, _, t = _fight_scene(7, 0.9, 0.1)
        actions = []
        while conflict.state == FIGHTING:
            t += DT
            brawls.update(npcs, DT, t)
            if conflict.action and (not actions or actions[-1]["seq"] != conflict.action["seq"]):
                actions.append(dict(conflict.action))
        runs.append((actions, conflict.outcome, conflict.winner))
    assert runs[0] == runs[1]


def test_enraged_fighters_strike_first_and_land_more_over_many_fights():
    def tally(rage):
        first = landed = swings = 0
        for seed in range(150):
            brawls, npcs, conflict, _, t = _fight_scene(seed, rage, 0.0)
            brawls._act(conflict, t)
            action = conflict.action
            first += action["actor"] == 0
            if action["actor"] == 0:
                swings += 1
                landed += action["hit"]
        return first, landed / max(1, swings)
    calm, angry = tally(0.0), tally(1.0)
    assert angry[0] > calm[0] and angry[1] > calm[1]
    assert angry[1] < 1.0  # not a sure thing


def test_a_rage_change_mid_fight_counts_from_the_next_action():
    brawls, npcs, conflict, (a, b), t = _fight_scene(5)
    first = brawls.rage(conflict.participants[0], t)
    a.rage, a.rage_at = 1.0, t  # provoked mid-fight
    assert first == 0.0 and brawls.rage(conflict.participants[0], t) == 1.0
    expected = tb.hit_chance(conflict.participants[0], conflict.participants[1], 1.0, 0.0)
    assert expected == pytest.approx(tb.BASE_HIT_CHANCE + tb.RAGE_ATTACK_BONUS)


def test_blows_taken_anger_an_npc_but_never_touch_the_players_meter():
    brawls, npcs, conflict, (a, b), t = _fight_scene(3)
    brawls.player_rage = 0.4
    hits_before = sum(p.hits_taken for p in conflict.participants)
    while conflict.state == FIGHTING and sum(p.hits_taken for p in conflict.participants) == hits_before:
        t += DT
        brawls.update(npcs, DT, t, player_rage=0.4)
    struck = [p for p in conflict.participants if p.hits_taken][0]
    taxi = a if struck.ref == 1 else b
    assert tb.npc_rage(taxi, t) >= tb.PROVOKE_HIT - 1e-9
    assert brawls.player_rage == 0.4


def test_a_staggered_fighter_loses_the_next_initiative():
    brawls, npcs, conflict, _, t = _fight_scene(1)
    conflict.participants[0].staggered = True
    brawls._act(conflict, t)
    assert conflict.action["actor"] == 1 and not conflict.participants[0].staggered


def test_a_rival_that_lost_the_fare_is_angry_and_fights_angrier(monkeypatch):
    monkeypatch.setattr(tb, "DISPUTE_CHANCE", 0.0)
    a, b = _taxi(1, 0.0), _taxi(2, 12.0)
    target = SimpleNamespace(x=0.0, y=0.0)
    phone = SimpleNamespace(offers=[SimpleNamespace(passenger=SimpleNamespace(name="Aino", pickup=target,
                                                                              dropoff=SimpleNamespace(x=900, y=0)))],
                            language="en", notification_msg="", notification_timer=0.0)
    dispatcher = Dispatcher(rng=random.Random(1))
    for _ in range(600):
        dispatcher.update(phone, _npcs(a, b), 1.0, BrawlManager(), sim_time=30.0)
        if not phone.offers:
            break
    assert a.taxi_job is not None and tb.npc_rage(b, 30.0) == tb.PROVOKE_LOST_FARE and tb.npc_rage(a, 30.0) == 0.0


# -- the player in a brawl -----------------------------------------------------

ME = (PLAYER, "local_player")


def _view(on_foot=False, x=0.0, y=0.0, car=(0.0, 0.0), **inputs):
    return tb.PlayerView(x, y, on_foot, car[0], car[1], 0.0, **inputs)


def _player_scene(seed=1, on_foot=False, rival_x=8.0, state=NPCState.CRUISING):
    rival = _taxi(1, rival_x)
    rival.state, rival.turn_signal = state, "none"
    brawls, npcs = BrawlManager(random.Random(seed)), _npcs(rival)
    brawls.report("traffic", ME, (NPC, 1), ("traffic", 1, 0))
    brawls.update(npcs, DT, 0.0, player=_view(on_foot))
    return brawls, npcs, rival


def _step(brawls, npcs, t, view, seconds=DT):
    end = t + seconds
    while t < end - 1e-9:
        t += DT
        brawls.update(npcs, DT, t, player=view)
    return t


def test_bumping_a_rival_brings_its_angry_driver_to_the_taxi_door():
    brawls, npcs, rival = _player_scene()
    (conflict,) = brawls.conflicts.values()
    player = conflict.participants[0]
    assert player.kind == PLAYER and player.in_car and rival.brawl_id == conflict.id
    assert rival.turn_signal == "hazard"  # stopped in traffic: hazard lights
    assert brawls.player_notice == "brawl_challenge"
    t = _step(brawls, npcs, 0.0, _view(), 7.0)
    driver = conflict.participants[1]
    assert math.dist((driver.x, driver.y), (player.x, player.y)) < 2.0  # at the window
    assert brawls.player_locked() is None  # at the wheel the player can still drive off
    assert not any(row["fighters"][0]["in_car"] is False for row in brawls.to_dicts(t))


def test_driving_away_ends_it_and_frees_the_rival():
    brawls, npcs, rival = _player_scene()
    t = _step(brawls, npcs, 0.0, _view(), 2.0)
    t = _step(brawls, npcs, t, _view(car=(tb.PLAYER_LEAVE_M + 1.0, 0.0)))
    assert brawls.history[-1]["outcome"] == "player_left" and brawls.player_notice == "brawl_left"
    _step(brawls, npcs, t, _view(car=(50.0, 0.0)), tb.RESOLUTION_S + tb.COOLDOWN_S + 4.0)
    assert not brawls.conflicts and rival.brawl_id is None and rival.turn_signal == "none"


def test_ignored_at_the_wheel_the_driver_gives_up():
    brawls, npcs, rival = _player_scene()
    _step(brawls, npcs, 0.0, _view(), tb.TRIGGERED_S + tb.PLAYER_WAIT_S + 1.0)
    assert brawls.history[-1]["outcome"] == "ignored"
    assert not any(h["outcome"] == "knockout" for h in brawls.history)


def test_out_of_the_taxi_space_throws_the_first_punch_and_holds_the_player():
    brawls, npcs, rival = _player_scene(on_foot=True)
    (conflict,) = brawls.conflicts.values()
    assert brawls.player_notice == "brawl_provoked"
    t = _step(brawls, npcs, 0.0, _view(on_foot=True), tb.TRIGGERED_S + 0.5)
    assert conflict.state == tb.CONFRONTATION and brawls.player_engaged()
    assert brawls.player_locked() is not None  # squaring up: held in place
    t = _step(brawls, npcs, t, _view(on_foot=True, strike=True))
    assert conflict.state in (FIGHTING, RESOLUTION) and conflict.action["actor"] == 0  # the player struck first


def test_without_input_the_rival_swings_and_the_player_is_never_rolled_to_back_down():
    for seed in range(20):
        brawls, npcs, rival = _player_scene(seed, on_foot=True)
        (conflict,) = brawls.conflicts.values()
        _step(brawls, npcs, 0.0, _view(on_foot=True), tb.MAX_LIFETIME_S)
        actions = brawls.history[-1]
        assert not (actions["outcome"] == "backed_down" and actions["winner"] == 1)  # the rival backed down, never the player
        if conflict.action and conflict.action["kind"] in ("strike", "dodge"):
            assert conflict.action["actor"] == 1  # the idle player never strikes


class _Even(random.Random):
    def random(self):
        return 0.5


def test_holding_dodge_makes_the_rivals_blow_likelier_to_miss(monkeypatch):
    monkeypatch.setattr(tb, "hit_chance", lambda *a: 0.6)  # 0.5 < 0.6 hits; minus the dodge it misses
    for dodge, expect_hit in ((False, True), (True, False)):
        brawls, npcs, rival = _player_scene(on_foot=True)
        brawls.rng = _Even()
        (conflict,) = brawls.conflicts.values()
        conflict.state, conflict.next_action_at = FIGHTING, 0.0
        conflict.intent = "dodge" if dodge else ""
        brawls._act(conflict, 0.0)
        assert conflict.action["actor"] == 1 and conflict.action["hit"] is expect_hit


def test_f_runs_from_the_fight_and_frees_the_player():
    brawls, npcs, rival = _player_scene(on_foot=True)
    t = _step(brawls, npcs, 0.0, _view(on_foot=True), tb.TRIGGERED_S + 0.5)
    t = _step(brawls, npcs, t, _view(on_foot=True, flee=True))
    assert brawls.history[-1]["outcome"] == "fled" and brawls.player_notice == "brawl_fled"
    assert brawls.player_locked() is None and not brawls.player_engaged()


def test_a_knocked_out_player_lies_down_a_moment_then_can_move():
    brawls, npcs, rival = _player_scene(on_foot=True)
    (conflict,) = brawls.conflicts.values()
    t = _step(brawls, npcs, 0.0, _view(on_foot=True), tb.TRIGGERED_S + 0.5)
    conflict.participants[0].hits_taken = tb.KNOCKDOWN_HITS - 1
    monkeypatched = tb.hit_chance
    try:
        tb.hit_chance = lambda *a: 0.9
        brawls.rng = _Even()
        conflict.state, conflict.next_action_at = FIGHTING, t
        conflict.deadline = t + tb.FIGHT_MAX_S
        t = _step(brawls, npcs, t, _view(on_foot=True))
    finally:
        tb.hit_chance = monkeypatched
    assert conflict.outcome == "knockout" and conflict.winner == 1 and brawls.player_notice == "brawl_lost"
    assert conflict.participants[0].down and brawls.player_locked() is not None
    _step(brawls, npcs, t, _view(on_foot=True), tb.KNOCKDOWN_GET_UP_S + 0.2)
    assert brawls.player_locked() is None


def test_no_brawl_with_a_fare_aboard_or_from_far_away():
    rival = _taxi(1, 8.0)
    for view in (_view(carrying=True), _view(car=(100.0, 0.0), x=100.0)):
        brawls, npcs = BrawlManager(random.Random(1)), _npcs(rival)
        brawls.report("traffic", ME, (NPC, 1), ("traffic", 1, 0))
        brawls.update(npcs, DT, 0.0, player=view)
        assert not brawls.conflicts and rival.brawl_id is None


def test_a_moving_rival_is_not_stopped_for_a_quarrel():
    rival = _taxi(1, 8.0)
    rival.state, rival.car.speed = NPCState.CRUISING, 8.0
    brawls, npcs = BrawlManager(random.Random(1)), _npcs(rival)
    brawls.report("traffic", ME, (NPC, 1), ("traffic", 1, 0))
    brawls.update(npcs, DT, 0.0, player=_view())
    assert not brawls.conflicts


def test_the_players_quarrel_ends_if_the_player_vanishes():
    brawls, npcs, rival = _player_scene(on_foot=True)
    brawls.update(npcs, DT, 0.1, player=None)  # e.g. a session ends mid-fight
    assert not brawls.conflicts and rival.brawl_id is None and brawls.history[-1]["outcome"] == "aborted"


def test_a_client_command_cannot_carry_a_brawl_result():
    from theroadragetrip.protocol import command_from_message
    command, _ = command_from_message({"command": {"road_rage": True, "winner": 0, "hit": True,
                                                   "outcome": "knockout", "rage_power": 1.0}})
    assert command.road_rage is True
    assert not any(hasattr(command, name) for name in ("winner", "hit", "outcome", "rage_power"))


def test_an_on_foot_shout_at_a_rival_taxi_picks_the_fight():
    from theroadragetrip.simulation import _provoke_rival
    rival = _taxi(1, 3.0)
    npcs = _npcs(rival)
    npcs.nearby_vehicles_at = lambda x, y, r: [v for v in npcs.vehicles if math.hypot(v.x - x, v.y - y) <= r]
    brawls = BrawlManager(random.Random(1))
    _provoke_rival(brawls, npcs, SimpleNamespace(x=0.0, y=0.0), 5.0)
    assert tb.npc_rage(rival, 5.0) == tb.PROVOKE_TAUNT
    brawls.update(npcs, DT, 5.0, player=_view(on_foot=True))
    (conflict,) = brawls.conflicts.values()
    assert conflict.trigger == "provoke" and conflict.participants[0].kind == PLAYER


@pytest.mark.timing
def test_a_rival_stopped_on_the_road_stays_put_for_the_quarrel_then_drives_on():
    """Real NPC manager: the brawl lock freezes a driving rival in place."""
    from theroadragetrip.competitor_taxis import make_competitor
    from theroadragetrip.npc import NPCVehicleManager, spawn_npc
    from theroadragetrip.residents import ResidentManager
    from theroadragetrip.traffic_world import TrafficWorld
    from test_competitor_taxis import _city_block_grid

    random.seed(4)
    ways = _city_block_grid()
    traffic = TrafficWorld(ways)
    residents = ResidentManager()
    _, driver, taxi = spawn_npc(1, residents, traffic, ways, (30.0, 0.0), (300.0, 240.0))
    make_competitor(taxi)
    manager = NPCVehicleManager(target_count=1, max_count=1, spawn_radius_m=300, vehicle_distribution={"car": 1.0})
    manager.competitor_taxis = 0
    manager.vehicles.append(taxi)
    manager.drivers[taxi.vehicle_id] = driver
    for _ in range(30 * 3):  # get it moving
        traffic.advance_time(1 / 30)
        manager.update(1 / 30, 210, 210, residents, traffic, ways)
    taxi.car.speed = 0.0  # just bumped to a stop
    brawls = BrawlManager(random.Random(2))
    brawls.report("traffic", ME, (NPC, 1), ("traffic", 1, 0))
    view = _view(car=(taxi.x - 6.0, taxi.y))
    brawls.update(manager, 1 / 30, traffic.sim_time, player=view)
    assert taxi.brawl_id is not None
    at = (taxi.x, taxi.y)
    while brawls.conflicts:
        traffic.advance_time(1 / 30)
        manager.update(1 / 30, 210, 210, residents, traffic, ways)
        brawls.update(manager, 1 / 30, traffic.sim_time, player=view)
        assert (taxi.x, taxi.y) == at
    for _ in range(30 * 10):
        traffic.advance_time(1 / 30)
        manager.update(1 / 30, 210, 210, residents, traffic, ways)
    assert math.dist((taxi.x, taxi.y), at) > 5.0 and taxi.state != NPCState.CRASHED
