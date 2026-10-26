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
PLAYER_BRAWLS_ENABLED = False  # player participants are modelled, not yet playable
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
    outcome: Optional[str] = None  # "backed_down", "surrender", "knockout", "separated", "aborted"
    winner: Optional[int] = None  # participant index


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

    def _eligible_npc(self, vehicle, npc_manager, sim_time: float) -> bool:
        from .npc import NPCState
        if vehicle is None:
            return False  # unknown id: despawned, or never a taxi
        job = vehicle.taxi_job
        return (
            is_competitor(vehicle)
            and vehicle.state == NPCState.PARKED
            and npc_manager.drivers.get(vehicle.vehicle_id) is not None
            and not vehicle.driver_departed
            and getattr(vehicle, "brawl_id", None) is None
            and vehicle.vehicle_id not in npc_manager.road_rage.held
            # A fare aboard, or one boarding or leaving at a stop: no quarrel then.
            and (job is None or (not job.passenger_aboard and job.state != "stopped"))
            and not any(j["vehicle"] is vehicle for j in npc_manager._route_jobs)
            and self.cooldown_until.get((NPC, vehicle.vehicle_id), 0.0) <= sim_time
        )

    def _start(self, trigger: str, first, second, npc_manager, sim_time: float) -> Optional[Conflict]:
        if first == second:
            return None
        vehicles = {v.vehicle_id: v for v in npc_manager.vehicles if is_competitor(v)}
        cars = []
        for kind, ref in (first, second):
            if kind == PLAYER and not PLAYER_BRAWLS_ENABLED:
                return None
            if kind != NPC or not self._eligible_npc(vehicles.get(ref), npc_manager, sim_time):
                return None
            cars.append(vehicles[ref])
        a, b = cars
        if (math.hypot(a.x - b.x, a.y - b.y) > ENGAGE_RADIUS_M or a.layer != b.layer
                or a.car.map_level != b.car.map_level):
            return None
        conflict = Conflict(self._next_id, trigger, [], (a.x + b.x) / 2, (a.y + b.y) / 2, sim_time,
                            state_since=sim_time, deadline=sim_time + TRIGGERED_S)
        self._next_id += 1
        for vehicle in cars:
            aggression, skill, retreat = driver_traits(vehicle.vehicle_id)
            home = _entry_point(vehicle)
            conflict.participants.append(Participant(NPC, vehicle.vehicle_id, aggression, skill, retreat,
                                                     home, home[0], home[1]))
            vehicle.brawl_id = conflict.id
            vehicle.car.speed = 0.0
        for participant, other in zip(conflict.participants, reversed(conflict.participants)):
            participant.heading = math.atan2(other.y - participant.y, other.x - participant.x)
        self.conflicts[conflict.id] = conflict
        self.sound_events.append(("vehicle.door_open", (conflict.x, conflict.y)))
        logger.info("Brawl %d (%s) between taxis %s and %s", conflict.id, trigger, a.vehicle_id, b.vehicle_id)
        return conflict

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

    def _curse(self, participant: Participant, sim_time: float) -> None:
        participant.curse_until = sim_time + 1.5
        participant.curse_text = self.rng.choice(CURSES)

    def _act(self, conflict: Conflict, sim_time: float) -> None:
        """One combat action: the server's roll, never the client's."""
        people = conflict.participants
        weights = [p.aggression + 0.1 for p in people]
        actor = 0 if self.rng.random() * sum(weights) < weights[0] else 1
        target = 1 - actor
        attacker, defender = people[actor], people[target]
        hit = self.rng.random() < max(0.1, min(0.9, BASE_HIT_CHANCE + 0.5 * (attacker.skill - defender.skill)))
        conflict.action_seq += 1
        conflict.action = {"seq": conflict.action_seq, "kind": "strike" if hit else "dodge",
                           "actor": actor, "target": target, "hit": hit}
        if not hit:
            return
        defender.hits_taken += 1
        self.sound_events.append(("collision.fence", (defender.x, defender.y)))  # ponytail: no punch sound in the catalog yet
        if defender.hits_taken >= KNOCKDOWN_HITS:
            defender.down = True
            self._resolve(conflict, "knockout", actor, sim_time)
        elif self.rng.random() < defender.retreat * defender.hits_taken * 0.2:
            self._resolve(conflict, "surrender", actor, sim_time)

    def _advance(self, conflict: Conflict, sim_time: float) -> None:
        people = conflict.participants
        if conflict.state == TRIGGERED and sim_time >= conflict.deadline:
            self._enter(conflict, CONFRONTATION, sim_time, CONFRONTATION_S)
            for participant in people:
                self._curse(participant, sim_time)
            self.sound_events.append(("pedestrian.curse", (conflict.x, conflict.y)))
        elif conflict.state == CONFRONTATION and sim_time >= conflict.deadline:
            softer = max(range(2), key=lambda i: people[i].retreat - people[i].aggression)
            if self.rng.random() < people[softer].retreat * (1.0 - people[1 - softer].aggression):
                self._resolve(conflict, "backed_down", 1 - softer, sim_time)
            else:
                self._enter(conflict, ESCALATION, sim_time, ESCALATION_S)
                conflict.action_seq += 1
                conflict.action = {"seq": conflict.action_seq, "kind": "threaten",
                                   "actor": 1 - softer, "target": softer, "hit": False}
        elif conflict.state == ESCALATION and sim_time >= conflict.deadline:
            threatened = conflict.action["target"]
            if self.rng.random() < people[threatened].retreat * 0.5:
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
                self._curse(participant, sim_time)
        self._place(conflict, sim_time)

    def _place(self, conflict: Conflict, sim_time: float) -> None:
        """The drivers' poses: over to the meeting point, then back."""
        for index, participant in enumerate(conflict.participants):
            other = conflict.participants[1 - index]
            dx, dy = other.home[0] - participant.home[0], other.home[1] - participant.home[1]
            gap = math.hypot(dx, dy) or 1.0
            reach = max(0.0, gap / 2 - STANCE_M)
            if conflict.state in (CONFRONTATION, ESCALATION, FIGHTING):
                along = min(reach, WALK_MPS * (sim_time - conflict.started - TRIGGERED_S))
            elif conflict.state == RESOLUTION:
                knocked_down = conflict.outcome == "knockout" and index != conflict.winner
                getting_up = KNOCKDOWN_GET_UP_S if knocked_down else 0.0
                participant.down = knocked_down and sim_time - conflict.state_since < getting_up
                reached = min(reach, WALK_MPS * (conflict.state_since - conflict.started - TRIGGERED_S))
                along = max(0.0, reached - WALK_MPS * max(0.0, sim_time - conflict.state_since - getting_up))
            else:
                along = 0.0
            x, y = participant.home[0] + dx / gap * along, participant.home[1] + dy / gap * along
            participant.moving = abs(x - participant.x) + abs(y - participant.y) > 1e-3
            participant.x, participant.y = x, y
            facing = math.atan2(dy, dx)
            walking_home = conflict.state == RESOLUTION and participant.moving
            participant.heading = facing + (math.pi if walking_home else 0.0)

    def _release(self, conflict: Conflict, vehicles: dict, sim_time: float) -> None:
        for participant in conflict.participants:
            vehicle = vehicles.get(participant.ref) if participant.kind == NPC else None
            if vehicle is not None and getattr(vehicle, "brawl_id", None) == conflict.id:
                vehicle.brawl_id = None
            self.cooldown_until[participant.key] = sim_time + DRIVER_COOLDOWN_S
        self.conflicts.pop(conflict.id, None)

    def update(self, npc_manager, dt: float, sim_time: float, taxi_stops=(), moment=None) -> None:
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
        for conflict in list(self.conflicts.values()):
            gone = any(p.kind == NPC and (vehicles.get(p.ref) is None or vehicles[p.ref].driver_departed
                                          or npc_manager.drivers.get(p.ref) is None)
                       for p in conflict.participants)
            if gone or sim_time - conflict.started > MAX_LIFETIME_S:
                if conflict.outcome is None:
                    conflict.outcome = "aborted"
                    self.history.append({"id": conflict.id, "trigger": conflict.trigger, "outcome": "aborted",
                                         "winner": None, "participants": [p.ref for p in conflict.participants]})
                self._release(conflict, vehicles, sim_time)
                continue
            self._advance(conflict, sim_time)
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
                    "down": p.down, "moving": p.moving,
                    "curse_timer": round(max(0.0, p.curse_until - sim_time), 2), "curse_text": p.curse_text,
                })
            rows.append({"id": conflict.id, "state": conflict.state, "action": conflict.action,
                         "outcome": conflict.outcome, "winner": conflict.winner, "fighters": fighters})
        return rows

