"""Taxi driver brawls (rrt-019-brawl-01, docs/taxi-brawls.md): two idle
competitor taxis' drivers get out, argue and may come to blows.

The server decides everything here - who quarrels, every action and its
outcome - on sim-time deadlines, never per frame; the client only draws the
current state (protocol "brawls"). A conflict's participants are existing
NPC taxis (by vehicle id) or, later, the player: no second identity.

States: IDLE (no conflict object) -> TRIGGERED -> CONFRONTATION ->
ESCALATION -> FIGHTING -> RESOLUTION -> COOLDOWN -> removed. Confrontation
and escalation may skip straight to RESOLUTION (someone backs down).
"""
from __future__ import annotations

import logging
import math
import random
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Tuple

from .competitor_taxis import is_competitor, nightlife_peak

logger = logging.getLogger(__name__)

IDLE, TRIGGERED, CONFRONTATION, ESCALATION, FIGHTING, RESOLUTION, COOLDOWN = (
    "IDLE", "TRIGGERED", "CONFRONTATION", "ESCALATION", "FIGHTING", "RESOLUTION", "COOLDOWN")
TRANSITIONS = {
    TRIGGERED: (CONFRONTATION,),
    CONFRONTATION: (ESCALATION, RESOLUTION),
    ESCALATION: (FIGHTING, RESOLUTION),
    FIGHTING: (RESOLUTION,),
    RESOLUTION: (COOLDOWN,),
    COOLDOWN: (),
}
NPC, PLAYER = "npc", "player"

# Tuning. Game estimates, not incident statistics: brawls stay rare.
PLAYER_BRAWLS_ENABLED = True
PLAYER_ENGAGE_M = 15.0  # a rival this near the player (taxi or on foot) can be fought
PROVOKE_REACH_M = 6.0  # on foot, SPACE this near a stopped rival taxi provokes its driver
PLAYER_WAIT_S = 8.0  # an angry driver waits this long at the taxi for the player to get out
PLAYER_LEAVE_M = 8.0  # the player driving this far away ends it ("player_left")
PLAYER_SKILL = 0.55  # the player's fixed fighting skill; rage and timing do the rest
PLAYER_DODGE_BONUS = 0.3  # holding dodge (Shift) when the rival swings: - hit chance
PLAYER_COOLDOWN_S = 60.0
PROVOKE_TAUNT = 0.3  # an NPC driver's rage from the player's on-foot provocation
ENGAGE_RADIUS_M = 30.0  # drivers this far apart (car to car) can walk over to each other
DISPUTE_CHANCE = 0.15  # a rival waiting beside the taxi that got the fare picks a quarrel
RANK_CHECK_INTERVAL_S = 30.0  # idle taxis parked together: one roll per pair this often
RANK_CHANCE = 0.002  # ...this likely on a quiet day (one quarrel per ~4 h per waiting pair)
NIGHT_RANK_CHANCE = 0.02  # ...and at the Friday/Saturday nightlife peak
TAXI_STAND_RADIUS_M = 40.0  # pairs at a taxi stand count as a rank; elsewhere RANK_FALLBACK_FACTOR
RANK_FALLBACK_FACTOR = 0.25
DRIVER_COOLDOWN_S = 600.0  # a driver who just quarrelled is left alone this long
MAX_PENDING_TRIGGERS = 16
PROCESSED_TRIGGER_MEMORY = 256

TRIGGERED_S = 1.0  # doors open, drivers get out
CONFRONTATION_S = 3.0  # shouting
ESCALATION_S = 2.0  # squaring up, shoving
FIGHT_MAX_S = 12.0  # then they are separated (a draw)
ACTION_INTERVAL_S = 0.9  # combat actions never come faster than this
RESOLUTION_S = 4.0  # a knocked-down driver gets up; both walk back
COOLDOWN_S = 1.0  # back in the cars before the lock is released
MAX_LIFETIME_S = 40.0  # hard bound: any conflict still alive is aborted
WALK_MPS = 1.4
STANCE_M = 0.7  # each stands this far from the meeting point
KNOCKDOWN_HITS = 3
KNOCKDOWN_GET_UP_S = 2.0
BASE_HIT_CHANCE = 0.45
HIT_CHANCE_BOUNDS = (0.1, 0.9)  # nobody always hits or always misses, whatever the rage
SURRENDER_PER_HIT = 0.2  # x retreat x hits taken: giving up after a blow

# Road rage in combat (rrt-019-brawl-02). Rage is 0..1: the player's meter
# (simulation rage_power) or an NPC driver's temporary rage (npc_rage).
# Every modifier grows smoothly with it; extreme rage costs defence.
RAGE_ATTACK_BONUS = 0.12  # + hit chance at full rage
RAGE_INITIATIVE = 0.6  # + strike-first weight at full rage (aggression + 0.1 without)
RAGE_INTIMIDATION = 0.8  # the opponent's back-down chance x (1 + this x rage)
RAGE_STAGGER_RESIST = 0.6  # chance a blow does not cost the next initiative; also damps surrender
RAGE_EXTREME = 0.7  # above this the guard drops...
RAGE_DEFENSE_PENALTY = 0.15  # ...up to this much easier to hit at full rage
BACK_DOWN_MAX = 0.95
# NPC drivers' temporary rage: raised by provocations, calming linearly.
# Computed when read (npc_rage), so a calm or idle NPC costs nothing per tick.
NPC_RAGE_CALM_S = 180.0  # full rage to calm in three minutes
PROVOKE_BUMP = 0.5  # the player's taxi bumped it
PROVOKE_CLEARANCE = 0.3  # shoved aside by the player's rage clearance
PROVOKE_LOST_FARE = 0.3  # a rival took the fare it was waiting for
PROVOKE_HIT = 0.15  # each blow taken in a fight
CURSES = ["@#*!%", "#$@&!", "!%#&*", "%$!#@", "@!*#$"]


@dataclass
class Participant:
    kind: str  # NPC or PLAYER
    ref: object  # an NPC's vehicle_id; the player's id
    aggression: float = 0.5  # 0..1: picks fights, strikes first
    skill: float = 0.5  # 0..1: lands and dodges blows
    retreat: float = 0.5  # 0..1: backs down, gives up
    home: Tuple[float, float] = (0.0, 0.0)  # beside its car (the curb side)
    x: float = 0.0
    y: float = 0.0
    heading: float = 0.0
    hits_taken: int = 0
    down: bool = False
    moving: bool = False
    curse_until: float = 0.0
    curse_text: str = ""
    staggered: bool = False  # the last blow cost its next initiative
    along: float = 0.0  # metres walked from home towards the meeting point
    in_car: bool = False  # the player, still at the wheel

    @property
    def key(self) -> Tuple[str, object]:
        return self.kind, self.ref


@dataclass
class Conflict:
    id: int
    trigger: str  # "passenger", "traffic", "rank"
    participants: List[Participant]
    x: float
    y: float
    started: float
    state: str = TRIGGERED
    state_since: float = 0.0
    deadline: float = 0.0
    next_action_at: float = 0.0
    action: Optional[dict] = None  # the latest: {"seq", "kind", "actor", "target", "hit"}
    action_seq: int = 0
    outcome: Optional[str] = None  # "backed_down", "surrender", "knockout", "separated", "aborted",
    # and with the player: "fled", "player_left", "ignored"
    winner: Optional[int] = None  # participant index
    meet: Tuple[float, float] = (0.0, 0.0)  # where they face off
    player_car_at: Optional[Tuple[float, float]] = None  # the player's taxi when it began
    intent: str = ""  # the player's next move: "strike" or "dodge" (from existing inputs only)


@dataclass
class PlayerView:
    """What the simulation tells the brawls about the player each tick. The
    inputs are the existing, validated command fields: SPACE (strike),
    Shift held (dodge), F (flee) - never a result from the client."""
    x: float
    y: float
    on_foot: bool
    car_x: float
    car_y: float
    car_heading: float
    car_width: float = 1.8
    map_level: int = 0
    carrying: bool = False  # a fare in or for the taxi: no fights then
    strike: bool = False
    dodge: bool = False
    flee: bool = False


def _unit(value) -> float:
    """0..1; anything else (NaN, None, out of range) made safe."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if value != value else max(0.0, min(1.0, value))


@dataclass(frozen=True)
class RageModifiers:
    attack: float  # + hit chance
    initiative: float  # + strike-first weight
    intimidation: float  # opponent's back-down chance x (1 + this)
    stagger_resist: float  # chance a blow does not stagger
    defense: float  # <= 0: + to the chance of being hit is -defense


def rage_modifiers(rage) -> RageModifiers:
    """The one place rage turns into combat modifiers, for players and NPCs
    alike. Linear in rage, but defence: smoothstep above RAGE_EXTREME."""
    r = _unit(rage)
    over = max(0.0, (r - RAGE_EXTREME) / (1.0 - RAGE_EXTREME))
    return RageModifiers(RAGE_ATTACK_BONUS * r, RAGE_INITIATIVE * r, RAGE_INTIMIDATION * r,
                         RAGE_STAGGER_RESIST * r, -RAGE_DEFENSE_PENALTY * over * over * (3.0 - 2.0 * over))


def hit_chance(attacker: "Participant", defender: "Participant", attacker_rage, defender_rage) -> float:
    chance = (BASE_HIT_CHANCE + 0.5 * (attacker.skill - defender.skill)
              + rage_modifiers(attacker_rage).attack - rage_modifiers(defender_rage).defense)
    return max(HIT_CHANCE_BOUNDS[0], min(HIT_CHANCE_BOUNDS[1], chance))


def back_down_chance(person: "Participant", opponent: "Participant", opponent_rage, scale: float = 1.0) -> float:
    chance = person.retreat * scale * (1.0 - opponent.aggression) * (1.0 + rage_modifiers(opponent_rage).intimidation)
    return max(0.0, min(BACK_DOWN_MAX, chance))


def npc_rage(vehicle, sim_time: float) -> float:
    """An NPC driver's rage now: what it was last provoked to, calmed since."""
    rage = _unit(getattr(vehicle, "rage", 0.0))
    return max(0.0, rage - max(0.0, sim_time - getattr(vehicle, "rage_at", sim_time)) / NPC_RAGE_CALM_S)


def provoke(vehicle, amount: float, sim_time: float) -> None:
    vehicle.rage = _unit(npc_rage(vehicle, sim_time) + amount)
    vehicle.rage_at = sim_time


def driver_traits(vehicle_id) -> Tuple[float, float, float]:
    """A driver's temperament, stable per driver: (aggression, skill, retreat)."""
    rng = random.Random(f"brawl-{vehicle_id}")
    return rng.uniform(0.2, 0.9), rng.uniform(0.2, 0.9), rng.uniform(0.2, 0.8)


def _entry_point(vehicle) -> Tuple[float, float]:
    from .pedestrian import PedestrianManager  # lazy: pedestrian imports npc
    return PedestrianManager._vehicle_entry_position(vehicle)


class BrawlManager:
    """Owns the active conflicts. update() costs nothing while none is
    active and no trigger is queued, apart from the rank check's
    competitor-taxi filter every RANK_CHECK_INTERVAL_S."""

    def __init__(self, rng: Optional[random.Random] = None) -> None:
        self.rng = rng or random.Random()  # seeded by tests
        self.conflicts: Dict[int, Conflict] = {}
        self.pending: Deque[tuple] = deque(maxlen=MAX_PENDING_TRIGGERS)
        self.processed: "OrderedDict[tuple, None]" = OrderedDict()
        self.cooldown_until: Dict[Tuple[str, object], float] = {}
        self.history: Deque[dict] = deque(maxlen=20)  # resolved outcomes (debug snapshot)
        self.sound_events: List[Tuple[str, Tuple[float, float]]] = []  # drained by the simulation
        self.rejected = 0
        self.player_rage = 0.0  # the player's meter, from the simulation (never from a client)
        self.player_notice: Optional[str] = None  # a localization key for the player; drained by the simulation
        self._player: Optional[PlayerView] = None
        self._vehicles: dict = {}  # this tick's locked NPC taxis, by id
        self._next_id = 1
        self._rank_timer = 0.0

    # -- triggers ---------------------------------------------------------

    def report(self, trigger: str, first: Tuple[str, object], second: Tuple[str, object], key: tuple) -> None:
        """Queue a trigger from an existing event; validated in update().
        `key` identifies the event: the same event never fights twice."""
        if key not in self.processed:
            self.pending.append((trigger, first, second, key))

    def _remember(self, key: tuple) -> None:
        self.processed[key] = None
        while len(self.processed) > PROCESSED_TRIGGER_MEMORY:
            self.processed.popitem(last=False)

    def busy(self, kind: str, ref) -> bool:
        return any(p.key == (kind, ref) for c in self.conflicts.values() for p in c.participants)

    def player_conflict(self) -> Optional[Conflict]:
        return next((c for c in self.conflicts.values() if any(p.kind == PLAYER for p in c.participants)), None)

    def player_engaged(self) -> bool:
        """The player is in a quarrel on foot: SPACE strikes, Shift dodges, F flees."""
        conflict = self.player_conflict()
        return (conflict is not None and conflict.outcome is None
                and not next(p for p in conflict.participants if p.kind == PLAYER).in_car)

    def player_locked(self) -> Optional[Tuple[float, float]]:
        """The heading the player faces while held in place (a fight on foot,
        or lying knocked down), else None: then they move freely."""
        conflict = self.player_conflict()
        if conflict is None:
            return None
        player = next(p for p in conflict.participants if p.kind == PLAYER)
        if player.in_car or not (self.player_engaged() or player.down):
            return None
        return player.heading

    def _eligible_npc(self, vehicle, npc_manager, sim_time: float, with_player: bool = False) -> bool:
        from .npc import NPCState
        if vehicle is None:
            return False  # unknown id: despawned, or never a taxi
        job = vehicle.taxi_job
        return (
            is_competitor(vehicle)
            # NPC rivals quarrel parked; the player can stop one anywhere (bumped, provoked)
            and (vehicle.state == NPCState.PARKED if not with_player
                 else vehicle.state != NPCState.CRASHED and abs(vehicle.car.speed) < 0.5)
            and npc_manager.drivers.get(vehicle.vehicle_id) is not None
            and not vehicle.driver_departed
            and getattr(vehicle, "brawl_id", None) is None
            and vehicle.vehicle_id not in npc_manager.road_rage.held
            # A fare aboard, or one boarding or leaving at a stop: no quarrel then.
            and (job is None or (not job.passenger_aboard and job.state != "stopped"))
            and (with_player or not any(j["vehicle"] is vehicle for j in npc_manager._route_jobs))
            and self.cooldown_until.get((NPC, vehicle.vehicle_id), 0.0) <= sim_time
        )

    def _player_eligible(self, ref, sim_time: float) -> bool:
        player = self._player
        return (PLAYER_BRAWLS_ENABLED and player is not None and not player.carrying
                and not self.busy(PLAYER, ref)
                and self.cooldown_until.get((PLAYER, ref), 0.0) <= sim_time)

    def _player_spot(self) -> Tuple[float, float]:
        """Where the player stands: on foot, or by the taxi's driver door."""
        player = self._player
        if player.on_foot:
            return player.x, player.y
        side = player.car_width * 0.85
        return (player.car_x - math.sin(player.car_heading) * side,
                player.car_y + math.cos(player.car_heading) * side)

    def _start(self, trigger: str, first, second, npc_manager, sim_time: float) -> Optional[Conflict]:
        if first == second or (first[0] == second[0] == PLAYER):
            return None
        with_player = PLAYER in (first[0], second[0])
        vehicles = {v.vehicle_id: v for v in npc_manager.vehicles if is_competitor(v)}
        people: List[Participant] = []
        for kind, ref in (first, second):
            if kind == PLAYER:
                if not self._player_eligible(ref, sim_time):
                    return None
                spot = self._player_spot()
                people.append(Participant(PLAYER, ref, 0.5, PLAYER_SKILL, 0.0, spot, spot[0], spot[1],
                                          in_car=not self._player.on_foot))
                continue
            vehicle = vehicles.get(ref)
            if kind != NPC or not self._eligible_npc(vehicle, npc_manager, sim_time, with_player):
                return None
            aggression, skill, retreat = driver_traits(ref)
            home = _entry_point(vehicle)
            people.append(Participant(NPC, ref, aggression, skill, retreat, home, home[0], home[1]))
        cars = [vehicles[p.ref] for p in people if p.kind == NPC]
        if with_player:
            car, spot = cars[0], people[[p.kind for p in people].index(PLAYER)].home
            if (math.hypot(car.x - spot[0], car.y - spot[1]) > PLAYER_ENGAGE_M
                    or car.car.map_level != self._player.map_level):
                return None
        else:
            a, b = cars
            if (math.hypot(a.x - b.x, a.y - b.y) > ENGAGE_RADIUS_M or a.layer != b.layer
                    or a.car.map_level != b.car.map_level):
                return None
        homes = [p.home for p in people]
        conflict = Conflict(self._next_id, trigger, people, (homes[0][0] + homes[1][0]) / 2,
                            (homes[0][1] + homes[1][1]) / 2, sim_time,
                            state_since=sim_time, deadline=sim_time + TRIGGERED_S)
        if with_player:
            conflict.player_car_at = (self._player.car_x, self._player.car_y)
            self.player_notice = "brawl_challenge" if self._player.on_foot is False else "brawl_provoked"
        self._next_id += 1
        for vehicle in cars:
            from .npc import NPCState
            vehicle.brawl_id = conflict.id
            vehicle.car.speed = 0.0
            if vehicle.state != NPCState.PARKED:  # stopped in traffic: warn the others
                vehicle.turn_signal, vehicle.turn_signal_elapsed = "hazard", 0.0
        for participant, other in zip(people, reversed(people)):
            participant.heading = math.atan2(other.y - participant.y, other.x - participant.x)
        self._meet(conflict)
        self.conflicts[conflict.id] = conflict
        self.sound_events.append(("vehicle.door_open", (conflict.x, conflict.y)))
        logger.info("Brawl %d (%s) between %s and %s", conflict.id, trigger, people[0].key, people[1].key)
        return conflict

    def _meet(self, conflict: Conflict) -> None:
        """The meeting point: the player where they stand, else halfway."""
        people = conflict.participants
        player = next((p for p in people if p.kind == PLAYER), None)
        if player is not None:
            conflict.meet = (player.x, player.y)
        else:
            conflict.meet = ((people[0].home[0] + people[1].home[0]) / 2, (people[0].home[1] + people[1].home[1]) / 2)

    def _rank_check(self, npc_manager, taxi_stops, moment, sim_time: float) -> None:
        from .npc import NPCState
        idle = [v for v in npc_manager.vehicles
                if is_competitor(v) and v.state == NPCState.PARKED and v.taxi_job is None
                and getattr(v, "brawl_id", None) is None]
        chance = NIGHT_RANK_CHANCE if nightlife_peak(moment) else RANK_CHANCE
        for i, a in enumerate(idle):  # ponytail: pairs of idle taxis, a handful at most (COMPETITOR_TAXIS)
            for b in idle[i + 1:]:
                if math.hypot(a.x - b.x, a.y - b.y) > ENGAGE_RADIUS_M:
                    continue
                at_stand = any(math.hypot(s.x - a.x, s.y - a.y) <= TAXI_STAND_RADIUS_M for s in taxi_stops or ())
                if self.rng.random() < chance * (1.0 if at_stand else RANK_FALLBACK_FACTOR):
                    self.report("rank", (NPC, a.vehicle_id), (NPC, b.vehicle_id),
                                ("rank", a.vehicle_id, b.vehicle_id, int(sim_time // RANK_CHECK_INTERVAL_S)))

    # -- the state machine ------------------------------------------------

    def _enter(self, conflict: Conflict, state: str, sim_time: float, duration: float) -> None:
        if state not in TRANSITIONS[conflict.state]:
            raise ValueError(f"brawl {conflict.id}: {conflict.state} -> {state}")
        conflict.state, conflict.state_since, conflict.deadline = state, sim_time, sim_time + duration

    def _resolve(self, conflict: Conflict, outcome: str, winner: Optional[int], sim_time: float) -> None:
        if conflict.outcome is not None:
            return  # resolves once
        conflict.outcome, conflict.winner = outcome, winner
        self._enter(conflict, RESOLUTION, sim_time, RESOLUTION_S)
        self.history.append({"id": conflict.id, "trigger": conflict.trigger, "outcome": outcome,
                             "winner": None if winner is None else conflict.participants[winner].ref,
                             "participants": [p.ref for p in conflict.participants]})
        logger.info("Brawl %d ended: %s", conflict.id, outcome)
        player = next((i for i, p in enumerate(conflict.participants) if p.kind == PLAYER), None)
        if player is not None:
            mine = winner == player
            self.player_notice = {
                "knockout": "brawl_won" if mine else "brawl_lost", "surrender": "brawl_won" if mine else "brawl_lost",
                "backed_down": "brawl_backed_down", "fled": "brawl_fled", "player_left": "brawl_left",
                "ignored": "brawl_ignored", "separated": "brawl_separated",
            }.get(outcome)

    def _curse(self, participant: Participant, sim_time: float) -> None:
        participant.curse_until = sim_time + 1.5
        participant.curse_text = self.rng.choice(CURSES)

    def rage(self, participant: Participant, sim_time: float) -> float:
        """A participant's current rage, read at each decision (so a change
        mid-fight counts from the next action on)."""
        if participant.kind == PLAYER:
            return _unit(self.player_rage)
        vehicle = self._vehicles.get(participant.ref)
        return npc_rage(vehicle, sim_time) if vehicle is not None else 0.0

    def _act(self, conflict: Conflict, sim_time: float) -> None:
        """One combat action: the server's roll, never the client's."""
        people = conflict.participants
        rages = [self.rage(p, sim_time) for p in people]
        staggered = [p.staggered for p in people]
        player = next((i for i, p in enumerate(people) if p.kind == PLAYER), None)
        intent, conflict.intent = conflict.intent, ""
        if staggered[0] != staggered[1]:  # the one staggered by the last blow cannot strike now
            actor = 1 if staggered[0] else 0
        elif player is not None:  # the player strikes when they choose to; otherwise the rival does
            actor = player if intent == "strike" else 1 - player
        else:
            weights = [p.aggression + 0.1 + rage_modifiers(r).initiative for p, r in zip(people, rages)]
            actor = 0 if self.rng.random() * sum(weights) < weights[0] else 1
        for p in people:
            p.staggered = False
        target = 1 - actor
        attacker, defender = people[actor], people[target]
        chance = hit_chance(attacker, defender, rages[actor], rages[target])
        if target == player and intent == "dodge":
            chance = max(HIT_CHANCE_BOUNDS[0], chance - PLAYER_DODGE_BONUS)
        hit = self.rng.random() < chance
        conflict.action_seq += 1
        conflict.action = {"seq": conflict.action_seq, "kind": "strike" if hit else "dodge",
                           "actor": actor, "target": target, "hit": hit}
        if not hit:
            return
        defender.hits_taken += 1
        defender.staggered = self.rng.random() >= rage_modifiers(rages[target]).stagger_resist
        if defender.kind == NPC and defender.ref in self._vehicles:  # pain feeds an NPC's rage (the player's meter is its own)
            provoke(self._vehicles[defender.ref], PROVOKE_HIT, sim_time)
        self.sound_events.append(("collision.fence", (defender.x, defender.y)))  # ponytail: no punch sound in the catalog yet
        if defender.hits_taken >= KNOCKDOWN_HITS:
            defender.down = True
            self._resolve(conflict, "knockout", actor, sim_time)
        elif defender.kind == NPC and self.rng.random() < (defender.retreat * defender.hits_taken * SURRENDER_PER_HIT
                                  * (1.0 - rage_modifiers(rages[target]).stagger_resist)):
            self._resolve(conflict, "surrender", actor, sim_time)

    def _player_turn(self, conflict: Conflict, sim_time: float) -> bool:
        """The player's own choices this tick; True when they decided the step."""
        people = conflict.participants
        index = next((i for i, p in enumerate(people) if p.kind == PLAYER), None)
        if index is None or conflict.outcome is not None:
            return False
        player, view = people[index], self._player
        player.in_car = not view.on_foot
        if player.in_car:
            player.x, player.y = self._player_spot()
            if conflict.player_car_at and math.hypot(view.car_x - conflict.player_car_at[0],
                                                     view.car_y - conflict.player_car_at[1]) > PLAYER_LEAVE_M:
                self._resolve(conflict, "player_left", 1 - index, sim_time)
                return True
            if conflict.state == CONFRONTATION and sim_time >= conflict.deadline:
                if sim_time - conflict.state_since < PLAYER_WAIT_S:
                    return True  # still waiting for them to get out
                self._resolve(conflict, "ignored", None, sim_time)
                return True
            return conflict.state in (ESCALATION, FIGHTING)  # nothing happens until they are out
        player.x, player.y = view.x, view.y
        if math.hypot(view.x - conflict.meet[0], view.y - conflict.meet[1]) > ENGAGE_RADIUS_M:
            self._resolve(conflict, "fled", 1 - index, sim_time)  # somehow far away: gone
            return True
        if view.flee and conflict.state in (CONFRONTATION, ESCALATION, FIGHTING):
            self._resolve(conflict, "fled", 1 - index, sim_time)
            return True
        if view.strike:
            conflict.intent = "strike"
        elif view.dodge and conflict.intent != "strike":
            conflict.intent = "dodge"
        if conflict.intent == "strike" and conflict.state in (CONFRONTATION, ESCALATION):
            if conflict.state == CONFRONTATION:  # the player swings first: straight to blows
                self._enter(conflict, ESCALATION, sim_time, 0.0)
            self._enter(conflict, FIGHTING, sim_time, FIGHT_MAX_S)
            conflict.next_action_at = sim_time
            return False
        return False

    def _advance(self, conflict: Conflict, sim_time: float, dt: float = 0.0) -> None:
        people = conflict.participants
        if self._player_turn(conflict, sim_time):
            self._place(conflict, sim_time, dt)
            return
        player = next((i for i, p in enumerate(people) if p.kind == PLAYER), None)
        if conflict.state == TRIGGERED and sim_time >= conflict.deadline:
            self._enter(conflict, CONFRONTATION, sim_time, CONFRONTATION_S)
            for participant in people:
                if participant.kind == NPC:  # the player's words are their own
                    self._curse(participant, sim_time)
            self.sound_events.append(("pedestrian.curse", (conflict.x, conflict.y)))
        elif conflict.state == CONFRONTATION and sim_time >= conflict.deadline:
            # The player is never made to back down by the dice: only the rival rolls.
            softer = (1 - player if player is not None
                      else max(range(2), key=lambda i: people[i].retreat - people[i].aggression))
            if self.rng.random() < back_down_chance(people[softer], people[1 - softer],
                                                    self.rage(people[1 - softer], sim_time)):
                self._resolve(conflict, "backed_down", 1 - softer, sim_time)
            else:
                self._enter(conflict, ESCALATION, sim_time, ESCALATION_S)
                conflict.action_seq += 1
                conflict.action = {"seq": conflict.action_seq, "kind": "threaten",
                                   "actor": 1 - softer, "target": softer, "hit": False}
        elif conflict.state == ESCALATION and sim_time >= conflict.deadline:
            threatened = conflict.action["target"] if player is None else 1 - player
            if self.rng.random() < back_down_chance(people[threatened], people[1 - threatened],
                                                    self.rage(people[1 - threatened], sim_time), scale=0.5):
                self._resolve(conflict, "backed_down", 1 - threatened, sim_time)
            else:
                self._enter(conflict, FIGHTING, sim_time, FIGHT_MAX_S)
                conflict.next_action_at = sim_time
        elif conflict.state == FIGHTING:
            if sim_time >= conflict.deadline:
                self._resolve(conflict, "separated", None, sim_time)
            elif sim_time >= conflict.next_action_at:
                conflict.next_action_at = sim_time + ACTION_INTERVAL_S
                self._act(conflict, sim_time)
        elif conflict.state == RESOLUTION and sim_time >= conflict.deadline:
            self._enter(conflict, COOLDOWN, sim_time, COOLDOWN_S)
            self.sound_events.append(("vehicle.door_close", (conflict.x, conflict.y)))
        if conflict.state == CONFRONTATION and sim_time >= people[0].curse_until:
            for participant in people:
                if participant.kind == NPC:
                    self._curse(participant, sim_time)
        self._place(conflict, sim_time, dt)

    def _place(self, conflict: Conflict, sim_time: float, dt: float = 0.0) -> None:
        """The drivers' poses: over to the meeting point, then back. The
        player is not moved: they stand where they are (or sit in the taxi)."""
        if conflict.state != RESOLUTION:
            self._meet(conflict)
        with_player = any(p.kind == PLAYER for p in conflict.participants)
        for index, participant in enumerate(conflict.participants):
            other = conflict.participants[1 - index]
            knocked_down = conflict.outcome == "knockout" and index != conflict.winner
            if conflict.state == RESOLUTION:
                participant.down = knocked_down and sim_time - conflict.state_since < KNOCKDOWN_GET_UP_S
            if participant.kind == PLAYER:
                participant.moving = False
                participant.heading = math.atan2(other.y - participant.y, other.x - participant.x)
                continue
            dx, dy = conflict.meet[0] - participant.home[0], conflict.meet[1] - participant.home[1]
            gap = math.hypot(dx, dy) or 1.0
            reach = max(0.0, gap - (2.0 * STANCE_M if with_player else STANCE_M))
            if conflict.state in (CONFRONTATION, ESCALATION, FIGHTING):
                along = min(reach, participant.along + WALK_MPS * dt)
            elif conflict.state == RESOLUTION and not participant.down:
                along = max(0.0, participant.along - WALK_MPS * dt)
            else:
                along = participant.along if conflict.state == RESOLUTION else 0.0
            x, y = participant.home[0] + dx / gap * along, participant.home[1] + dy / gap * along
            participant.moving = abs(along - participant.along) > 1e-4
            walking_home = conflict.state == RESOLUTION and along < participant.along
            participant.along, participant.x, participant.y = along, x, y
            participant.heading = math.atan2(dy, dx) + (math.pi if walking_home else 0.0)

    def _release(self, conflict: Conflict, vehicles: dict, sim_time: float) -> None:
        for participant in conflict.participants:
            vehicle = vehicles.get(participant.ref) if participant.kind == NPC else None
            if vehicle is not None and getattr(vehicle, "brawl_id", None) == conflict.id:
                vehicle.brawl_id = None
                if getattr(vehicle, "turn_signal", None) == "hazard":
                    vehicle.turn_signal = "none"
            self.cooldown_until[participant.key] = sim_time + (
                PLAYER_COOLDOWN_S if participant.kind == PLAYER else DRIVER_COOLDOWN_S)
        self.conflicts.pop(conflict.id, None)

    def update(self, npc_manager, dt: float, sim_time: float, taxi_stops=(), moment=None,
               player_rage: float = 0.0, player: Optional[PlayerView] = None) -> None:
        self.player_rage = _unit(player_rage)
        self._player = player
        self._rank_timer += dt
        if self._rank_timer >= RANK_CHECK_INTERVAL_S:
            self._rank_timer = 0.0
            self._rank_check(npc_manager, taxi_stops, moment, sim_time)
        while self.pending:
            trigger, first, second, key = self.pending.popleft()
            if key in self.processed:
                continue
            self._remember(key)
            if self._start(trigger, first, second, npc_manager, sim_time) is None:
                self.rejected += 1
        if self.cooldown_until and len(self.cooldown_until) > 64:
            self.cooldown_until = {k: t for k, t in self.cooldown_until.items() if t > sim_time}
        if not self.conflicts:
            return
        vehicles = {v.vehicle_id: v for v in npc_manager.vehicles if getattr(v, "brawl_id", None) is not None}
        self._vehicles = vehicles
        for conflict in list(self.conflicts.values()):
            gone = any((p.kind == NPC and (vehicles.get(p.ref) is None or vehicles[p.ref].driver_departed
                                           or npc_manager.drivers.get(p.ref) is None))
                       or (p.kind == PLAYER and player is None)
                       for p in conflict.participants)
            if gone or sim_time - conflict.started > MAX_LIFETIME_S:
                if conflict.outcome is None:
                    conflict.outcome = "aborted"
                    self.history.append({"id": conflict.id, "trigger": conflict.trigger, "outcome": "aborted",
                                         "winner": None, "participants": [p.ref for p in conflict.participants]})
                self._release(conflict, vehicles, sim_time)
                continue
            self._advance(conflict, sim_time, dt)
            if conflict.state == COOLDOWN and sim_time >= conflict.deadline:
                self._release(conflict, vehicles, sim_time)

    def to_dicts(self, sim_time: float) -> list:
        """What the client draws: the current state only, no history. Drivers
        are back in their cars in COOLDOWN, so it is not shown."""
        rows = []
        for conflict in self.conflicts.values():
            if conflict.state == COOLDOWN:
                continue
            fighters = []
            for p in conflict.participants:
                fighters.append({
                    "kind": p.kind, "id": p.ref, "x": round(p.x, 2), "y": round(p.y, 2), "heading": round(p.heading, 3),
                    "down": p.down, "moving": p.moving, "in_car": p.in_car,  # the player at the wheel: not drawn
                    "rage": round(self.rage(p, sim_time) * 20.0) / 20.0,  # looks only: an enraged face
                    "curse_timer": round(max(0.0, p.curse_until - sim_time), 2), "curse_text": p.curse_text,
                })
            rows.append({"id": conflict.id, "state": conflict.state, "action": conflict.action,
                         "outcome": conflict.outcome, "winner": conflict.winner, "fighters": fighters})
        return rows

