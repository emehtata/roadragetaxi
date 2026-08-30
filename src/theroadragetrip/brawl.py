"""Taxi-driver confrontations at taxi stands."""

import math
import random
import logging
from dataclasses import dataclass
from typing import Callable, Optional

from .osm import TaxiStop
from .physics import Car
from .traffic import NPC_TAXI_COLOR, NPCCar, TrafficManager

logger = logging.getLogger(__name__)


@dataclass
class Brawl:
    opponent: NPCCar
    state: str = "challenge"
    timer: float = 3.0
    player_x: float = 0.0
    player_y: float = 0.0
    opponent_x: float = 0.0
    opponent_y: float = 0.0
    player_car_x: float = 0.0
    player_car_y: float = 0.0
    opponent_car_x: float = 0.0
    opponent_car_y: float = 0.0
    stop_x: float = 0.0
    stop_y: float = 0.0
    winner: Optional[str] = None
    curse_timer: float = 0.0
    dust_timer: float = 0.0
    approach_path: Optional[list[tuple[float, float]]] = None
    approach_index: int = 1


class TaxiBrawlManager:
    """Run one visible driver confrontation at a time."""

    def __init__(self) -> None:
        self.brawl: Optional[Brawl] = None
        self._stand_cooldown = 0.0
        self._active_traffic_npcs: list[NPCCar] = []

    def update(
        self,
        player_car: Car,
        traffic: TrafficManager,
        taxi_stops: list[TaxiStop],
        rage_power: float,
        dt: float,
        viewport_bounds: Optional[tuple[float, float, float, float]] = None,
        score_callback: Optional[Callable[[int], None]] = None,
    ) -> None:
        self._active_traffic_npcs = traffic.npcs
        self._stand_cooldown = max(0.0, self._stand_cooldown - dt)
        if self.brawl is None:
            if self._stand_cooldown > 0.0 or abs(player_car.speed) > 1.5:
                return
            nearby_stops = [
                stop for stop in taxi_stops
                if math.hypot(stop.x - player_car.x, stop.y - player_car.y) <= 30.0
            ]
            stop = min(
                nearby_stops,
                key=lambda candidate: math.hypot(candidate.x - player_car.x, candidate.y - player_car.y),
                default=None,
            )
            if stop is None:
                return
            opponent = traffic.spawn_npc(
                stop.x,
                stop.y,
                viewport_bounds=viewport_bounds,
                near_heading=player_car.heading,
                max_distance_m=250.0 if viewport_bounds is not None else 35.0,
            )
            if opponent is None:
                return
            opponent.is_taxi = True
            opponent.color = NPC_TAXI_COLOR
            opponent.speed = 0.0
            opponent.target_speed = 0.0
            opponent.rage_timer = 999.0
            opponent.blocked_timer = 999.0
            approach_path = traffic.plan_route(
                (opponent.x, opponent.y),
                (stop.x, stop.y),
                layer=opponent.layer,
            )
            if viewport_bounds is not None and not approach_path:
                logger.warning("Taxi brawl cancelled: no road route to taxi stop")
                if opponent in traffic.npcs:
                    traffic.npcs.remove(opponent)
                return
            self.brawl = Brawl(
                opponent=opponent,
                state="approach" if viewport_bounds is not None else "challenge",
                player_x=player_car.x,
                player_y=player_car.y,
                opponent_x=opponent.x,
                opponent_y=opponent.y,
                player_car_x=player_car.x,
                player_car_y=player_car.y,
                opponent_car_x=opponent.x,
                opponent_car_y=opponent.y,
                stop_x=stop.x,
                stop_y=stop.y,
                approach_path=approach_path,
            )
            logger.info(
                "Taxi brawl challenged: stop=(%.1f, %.1f) opponent=(%.1f, %.1f) distance=%.1fm rage=%.0f%%",
                stop.x,
                stop.y,
                opponent.x,
                opponent.y,
                math.hypot(opponent.x - stop.x, opponent.y - stop.y),
                rage_power * 100.0,
            )
            return

        brawl = self.brawl
        opponent = brawl.opponent
        opponent.speed = 0.0
        opponent.target_speed = 0.0
        if brawl.state == "approach":
            if math.hypot(player_car.x - brawl.player_x, player_car.y - brawl.player_y) > 30.0:
                logger.info("Taxi brawl cancelled: player left before challenger arrived")
                self._finish(opponent, escaped=True)
                return
            if not brawl.approach_path:
                self._finish(opponent, escaped=True)
                return
            while brawl.approach_index < len(brawl.approach_path):
                waypoint_x, waypoint_y = brawl.approach_path[brawl.approach_index]
                dx = waypoint_x - opponent.x
                dy = waypoint_y - opponent.y
                distance = math.hypot(dx, dy)
                if distance > 1e-6:
                    break
                brawl.approach_index += 1
            if brawl.approach_index >= len(brawl.approach_path):
                distance = 0.0
            else:
                distance = math.hypot(dx, dy)
            if distance <= 8.0:
                brawl.opponent_x = opponent.x
                brawl.opponent_y = opponent.y
                brawl.opponent_car_x = opponent.x
                brawl.opponent_car_y = opponent.y
                brawl.state = "challenge"
                brawl.timer = 3.0
                visible = viewport_bounds is None or (
                    viewport_bounds[0] <= opponent.x <= viewport_bounds[2]
                    and viewport_bounds[1] <= opponent.y <= viewport_bounds[3]
                )
                logger.info(
                    "Taxi brawl challenger arrived at taxi stop: position=(%.1f, %.1f) "
                    "distance_to_player=%.1fm visible=%s",
                    opponent.x,
                    opponent.y,
                    math.hypot(opponent.x - player_car.x, opponent.y - player_car.y),
                    visible,
                )
                return
            step = min(distance, 12.0 * dt)
            opponent.heading = math.atan2(dy, dx)
            opponent.x += dx / distance * step
            opponent.y += dy / distance * step
            brawl.opponent_x = opponent.x
            brawl.opponent_y = opponent.y
            return
        if brawl.state == "challenge":
            distance_to_player = math.hypot(opponent.x - player_car.x, opponent.y - player_car.y)
            if (
                math.hypot(player_car.x - brawl.player_x, player_car.y - brawl.player_y) > 30.0
                or distance_to_player > 40.0
                or abs(player_car.speed) > 1.5
            ):
                logger.info(
                    "Taxi brawl cancelled: challenger too far or player moved "
                    "distance_to_player=%.1fm",
                    distance_to_player,
                )
                logger.info("Taxi brawl declined: player drove away")
                self._finish(opponent, escaped=True)
                return
            if viewport_bounds is not None:
                vmin_x, vmin_y, vmax_x, vmax_y = viewport_bounds
                if not (vmin_x <= opponent.x <= vmax_x and vmin_y <= opponent.y <= vmax_y):
                    brawl.timer = 3.0
                    return
            brawl.timer -= dt
            if brawl.timer <= 0.0:
                brawl.state = "fight"
                brawl.timer = 5.0
                brawl.dust_timer = 5.0
                brawl.player_x = player_car.x
                logger.info("Taxi brawl started: drivers exited cars")
            return
        if brawl.state == "fight":
            brawl.timer -= dt
            brawl.dust_timer = max(0.0, brawl.dust_timer - dt)
            player_to_opponent_x = brawl.opponent_x - brawl.player_x
            player_to_opponent_y = brawl.opponent_y - brawl.player_y
            distance = math.hypot(player_to_opponent_x, player_to_opponent_y)
            if distance > 1e-6:
                step = min(distance * 0.5, 2.5 * dt)
                brawl.player_x += player_to_opponent_x / distance * step
                brawl.player_y += player_to_opponent_y / distance * step
                brawl.opponent_x -= player_to_opponent_x / distance * step
                brawl.opponent_y -= player_to_opponent_y / distance * step
            if brawl.timer <= 0.0:
                brawl.winner = "player" if rage_power >= 1.0 else ("player" if random.random() < rage_power else "opponent")
                brawl.state = "return"
                brawl.timer = max(
                    2.0,
                    math.hypot(brawl.player_car_x - brawl.player_x, brawl.player_car_y - brawl.player_y) / 2.0,
                    math.hypot(brawl.opponent_car_x - brawl.opponent_x, brawl.opponent_car_y - brawl.opponent_y) / 2.0,
                )
                brawl.curse_timer = 2.0 if brawl.winner == "player" else 0.0
                if score_callback is not None:
                    score_callback(1000 if brawl.winner == "player" else -500)
                logger.info(
                    "Taxi brawl result: winner=%s score_delta=%d rage=%.0f%%",
                    brawl.winner,
                    1000 if brawl.winner == "player" else -500,
                    rage_power * 100.0,
                )
            return
        if brawl.state == "return":
            brawl.timer -= dt
            brawl.curse_timer = max(0.0, brawl.curse_timer - dt)
            walk_step = 2.0 * dt
            player_distance = math.hypot(brawl.player_car_x - brawl.player_x, brawl.player_car_y - brawl.player_y)
            opponent_distance = math.hypot(brawl.opponent_car_x - brawl.opponent_x, brawl.opponent_car_y - brawl.opponent_y)
            if player_distance > 1e-6:
                step = min(walk_step, player_distance)
                brawl.player_x += (brawl.player_car_x - brawl.player_x) / player_distance * step
                brawl.player_y += (brawl.player_car_y - brawl.player_y) / player_distance * step
            if opponent_distance > 1e-6:
                step = min(walk_step, opponent_distance)
                brawl.opponent_x += (brawl.opponent_car_x - brawl.opponent_x) / opponent_distance * step
                brawl.opponent_y += (brawl.opponent_car_y - brawl.opponent_y) / opponent_distance * step
            if brawl.timer <= 0.0:
                brawl.state = "drive"
                brawl.timer = 0.0
                logger.info("Taxi brawl drivers returned to cars: winner=%s", brawl.winner)
            return
        if brawl.state == "drive":
            winner_x = player_car.x if brawl.winner == "player" else opponent.x
            winner_y = player_car.y if brawl.winner == "player" else opponent.y
            dx = brawl.stop_x - winner_x
            dy = brawl.stop_y - winner_y
            distance = math.hypot(dx, dy)
            if distance > 1e-6:
                step = min(distance, 12.0 * dt)
                heading = math.atan2(dy, dx)
                if brawl.winner == "player":
                    player_car.heading = heading
                    player_car.x += dx / distance * step
                    player_car.y += dy / distance * step
                    brawl.player_x = player_car.x
                    brawl.player_y = player_car.y
                else:
                    opponent.heading = heading
                    opponent.x += dx / distance * step
                    opponent.y += dy / distance * step
                    brawl.opponent_x = opponent.x
                    brawl.opponent_y = opponent.y
                return
            logger.info("Taxi brawl finished: winner=%s loser_departing=%s", brawl.winner, brawl.winner == "player")
            self._finish(opponent, escaped=False, keep_opponent=brawl.winner == "opponent")
            return

    def _finish(self, opponent: NPCCar, escaped: bool, keep_opponent: bool = False) -> None:
        if keep_opponent:
            opponent.speed = 0.0
            opponent.target_speed = 0.0
            opponent.rage_timer = 0.0
            opponent.blocked_timer = 0.0
            opponent.waiting_at_taxi_stop = True
        elif opponent in self._active_traffic_npcs:
            self._active_traffic_npcs.remove(opponent)
        self._stand_cooldown = 20.0 if escaped else 45.0
        logger.info(
            "Taxi brawl cleanup: escaped=%s cooldown=%.1fs opponent_removed=%s waiting_at_stop=%s",
            escaped,
            self._stand_cooldown,
            opponent not in self._active_traffic_npcs,
            getattr(opponent, "waiting_at_taxi_stop", False),
        )
        self.brawl = None

    def bind_traffic(self, traffic: TrafficManager) -> None:
        self._active_traffic_npcs = traffic.npcs

    def draw_data(self) -> Optional[Brawl]:
        return self.brawl
