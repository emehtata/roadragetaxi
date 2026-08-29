import logging
import math
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .geo import clamp, dist_point_to_segment, get_oriented_box_corners, point_in_polygon
from .osm import Building, Place, TaxiStop, Way
from .physics import Car, SpatialWayGrid, connected_drivable_ways, is_car_road, is_violating_oneway
from .localization import tr
from .police import SpeedCamera, camera_sees_car

logger = logging.getLogger(__name__)

# Finnish passenger name generator for immersion
FIRST_NAMES = [
    "Matti", "Maija", "Antti", "Liisa", "Juho", "Anna", "Mikko", "Sari",
    "Pekka", "Tuula", "Jari", "Tiina", "Heikki", "Katri", "Kari", "Elina",
    "Ville", "Johanna", "Aleksi", "Laura", "Janne", "Emilia", "Lauri", "Sofia",
    "Markus", "Sanna", "Eero", "Hanna", "Petri", "Maria", "Timo", "Veera"
]


@dataclass
class TaxiTarget:
    """A target destination or pickup point with generated realistic address."""
    x: float
    y: float
    address: str
    way_name: Optional[str] = None
    district_name: Optional[str] = None
    radius_m: float = 20.0  # Pickup/dropoff stop radius


@dataclass
class TaxiPassenger:
    name: str
    pickup: TaxiTarget
    dropoff: TaxiTarget
    # Client pedestrian representation walking into the taxi
    ped_x: float = 0.0
    ped_y: float = 0.0
    ped_heading: float = 0.0
    ped_speed: float = 2.0  # Walking speed to taxi in m/s
    ped_color: Tuple[int, int, int] = (240, 220, 60)  # Bright gold/yellow
    is_walking_to_car: bool = False
    boarded: bool = False


@dataclass
class TaxiOffer:
    """A ride request shown in the driver's phone."""
    passenger: TaxiPassenger
    pickup_distance_m: float


class TaxiState:
    WAITING_FOR_PICKUP = "PICKUP"
    CLIENT_WALKING_TO_CAR = "WALKING"
    DRIVING_TO_DROPOFF = "DROPOFF"
    COMPLETED = "COMPLETED"


def speed_bonus_points(speed_kmh: float) -> int:
    """Return the nonlinear speed bonus: 10 km/h = 100, 50 = 1,000, 100 = 10,000."""
    speed_kmh = max(0.0, speed_kmh)
    if speed_kmh <= 50.0:
        exponent = math.log(10.0) / math.log(5.0)
        return round(100.0 * (speed_kmh / 10.0) ** exponent) if speed_kmh else 0
    exponent = math.log(10.0) / math.log(2.0)
    return round(1000.0 * (speed_kmh / 50.0) ** exponent)


class TaxiManager:
    """Manages taxi missions, addresses, pickups, dropoffs, fares, and speed bonuses."""

    def __init__(
        self,
        ways: List[Way],
        places: Optional[List[Place]] = None,
        buildings: Optional[List[Building]] = None,
        taxi_stops: Optional[List[TaxiStop]] = None,
        min_distance_m: float = 300.0,
        max_distance_m: float = 2500.0,
        pickup_radius_m: float = 25.0,
        max_stop_speed_mps: float = 3.0,  # Must slow down below ~10 km/h to pickup/dropoff
        language: str = "fi",
    ):
        # Filter to the largest connected road network to avoid isolated trapped roads
        self.ways = connected_drivable_ways(ways, named=True)
        self.places = places or []
        self.buildings = buildings or []
        self.taxi_stops = taxi_stops or []
        self.min_distance_m = min_distance_m
        self.max_distance_m = max_distance_m
        self.pickup_radius_m = pickup_radius_m
        self.max_stop_speed_mps = max_stop_speed_mps
        self.language = language

        self.current_passenger: Optional[TaxiPassenger] = None
        self.offers: List[TaxiOffer] = []
        self.state: str = TaxiState.WAITING_FOR_PICKUP
        self.total_score: int = 0
        self.completed_fares: int = 0
        self.trip_start_time: float = 0.0
        self.elapsed_time: float = 0.0
        self.trip_distance_m: float = 0.0
        self.last_fare_points: int = 0
        self.notification_msg: str = ""
        self.notification_timer: float = 0.0
        self.next_offer_timer: float = random.uniform(12.0, 28.0)
        self.stand_wait_timer: float = 0.0
        self._passed_red_signals: Dict[int, float] = {}  # signal id -> timestamp cooldown
        self._approaching_red_signals: Dict[int, float] = {}  # signal id -> last signed distance along travel
        self._approaching_red_headings: Dict[int, float] = {}  # signal id -> heading before intersection turn
        self._crashed_npc_cooldowns: Dict[int, float] = {}  # npc id -> timestamp cooldown
        self._crashed_building_cooldowns: Dict[int, float] = {}  # building id -> timestamp cooldown
        self._crashed_tree_cooldowns: Dict[Tuple[int, int], float] = {}
        self._speed_camera_hits: set[int] = set()
        self.tree_effects: Dict[Tuple[int, int], Dict[str, float]] = {}
        self.fallen_trees: set[Tuple[int, int]] = set()
        self.tree_wait_timer: float = 0.0
        self.taxi_smoke_timer: float = 0.0
        self.speed_camera_flash_timer: float = 0.0
        self.speed_camera_flash_index: Optional[int] = None
        self._road_overlap_buildings: set[int] = set()
        self._overlap_ways_ref = None
        self._overlap_buildings_ref = None
        self._overlap_way_count = -1
        self._overlap_building_count = -1
        self.wrong_way_duration: float = 0.0  # seconds continuously driving wrong way
        self.wrong_way_penalty_cooldown: float = 0.0  # timer between recurring penalties (5.0s)

    def set_language(self, language: str) -> None:
        self.language = language

    def check_speed_cameras(self, car: Car, cameras: List[SpeedCamera], penalty: int = 300) -> bool:
        """Fine a speeding car seen in a camera's directional 50-meter zone."""
        hit = False
        visible_ids: set[int] = set()
        for camera_index, camera in enumerate(cameras):
            if not camera_sees_car(camera, car.x, car.y, car.heading):
                continue
            visible_ids.add(camera_index)
            if abs(car.speed) * 3.6 <= camera.speed_limit_kmh:
                continue
            if camera_index in self._speed_camera_hits:
                continue
            self._speed_camera_hits.add(camera_index)
            self.total_score -= penalty
            self.speed_camera_flash_timer = 0.35
            self.speed_camera_flash_index = camera_index
            self.notification_msg = f"Speed camera! -{penalty} pts" if self.language == "en" else f"Peltikamera! -{penalty} pistettä"
            self.notification_timer = 4.0
            logger.info("Speed camera triggered: -%d pts", penalty)
            hit = True
        self._speed_camera_hits.intersection_update(visible_ids)
        return hit

    def check_car_collision(
        self,
        player_car: Car,
        npcs: List[Any],
        sim_time: float,
        penalty: int = 150,
    ) -> bool:
        """Check if player car collided with any NPC vehicle and apply crash physics + penalty."""
        from .geo import boxes_intersect

        # Clean expired crash cooldowns (> 3.0 seconds ago)
        expired = [nid for nid, t in self._crashed_npc_cooldowns.items() if sim_time - t > 3.0]
        for nid in expired:
            del self._crashed_npc_cooldowns[nid]

        p_len = getattr(player_car, "length_m", 4.0)
        p_wid = getattr(player_car, "width_m", 1.8)
        crashed = False

        for npc in npcs:
            if getattr(npc, "layer", 0) != getattr(player_car, "layer", 0):
                continue

            npc_id = id(npc)
            n_len = getattr(npc, "length_m", 4.0)
            n_wid = getattr(npc, "width_m", 1.8)

            if boxes_intersect(
                player_car.x, player_car.y, player_car.heading, p_len, p_wid,
                npc.x, npc.y, npc.heading, n_len, n_wid,
            ):
                # Apply bounce-back / collision impulse physics
                dx = player_car.x - npc.x
                dy = player_car.y - npc.y
                dist = math.hypot(dx, dy)
                if dist > 1e-3:
                    nx = dx / dist
                    ny = dy / dist
                else:
                    nx = math.cos(player_car.heading)
                    ny = math.sin(player_car.heading)

                # Push vehicles apart
                separation = max(0.5, (p_wid + n_wid) * 0.5)
                player_car.x += nx * 0.4
                player_car.y += ny * 0.4
                npc.x -= nx * 0.4
                npc.y -= ny * 0.4

                # Exchange and damp speeds
                impact_speed = max(abs(player_car.speed), abs(npc.speed), 3.0)
                player_car.speed = -player_car.speed * 0.4
                npc.speed = 0.0
                npc.crashed_timer = max(getattr(npc, "crashed_timer", 0.0), 5.0)  # stop & smoke for 5 seconds
                self.taxi_smoke_timer = max(self.taxi_smoke_timer, 5.0)

                crashed = True
                if npc_id not in self._crashed_npc_cooldowns:
                    self._crashed_npc_cooldowns[npc_id] = sim_time
                    self.total_score -= penalty
                    self.notification_msg = f"Crash! -{penalty} pts"
                    self.notification_timer = 3.5
                    logger.info("Player crashed into NPC vehicle: -%d pts penalty (impact speed: %.1f m/s)", penalty, impact_speed)

        return crashed

    def check_building_collision(
        self,
        player_car: Car,
        buildings: List[Building],
        sim_time: float,
        previous_position: Optional[Tuple[float, float]] = None,
        penalty: int = 200,
        ways: Optional[List[Way]] = None,
    ) -> bool:
        """Stop the car at a building footprint and apply one crash penalty per impact."""
        expired = [bid for bid, t in self._crashed_building_cooldowns.items() if sim_time - t > 3.0]
        for bid in expired:
            del self._crashed_building_cooldowns[bid]

        car_radius = math.hypot(player_car.length_m, player_car.width_m) * 0.5
        car_corners = get_oriented_box_corners(
            player_car.x, player_car.y, player_car.heading, player_car.length_m, player_car.width_m
        )

        for building in buildings:
            points = getattr(building, "points_m", [])
            if len(points) < 3:
                continue
            bbox = getattr(building, "bbox", (0.0, 0.0, 0.0, 0.0))
            if bbox != (0.0, 0.0, 0.0, 0.0):
                if (player_car.x < bbox[0] - car_radius or player_car.x > bbox[2] + car_radius
                        or player_car.y < bbox[1] - car_radius or player_car.y > bbox[3] + car_radius):
                    continue

            # OSM occasionally contains building footprints crossed by mapped roads.
            # Ignore that footprint only while the car is actually on the crossing road.
            if ways and any(
                self._road_overlaps_building(way, points, bbox)
                and getattr(way, "layer", 0) == getattr(player_car, "layer", 0)
                and any(
                    dist_point_to_segment(
                        player_car.x, player_car.y,
                        road_start[0], road_start[1], road_end[0], road_end[1],
                    ) <= getattr(way, "half_width_m", 3.0)
                    for road_start, road_end in zip(way.points_m, way.points_m[1:])
                )
                for way in ways
                if is_car_road(way)
            ):
                continue

            intersects = point_in_polygon(player_car.x, player_car.y, points)
            if not intersects:
                intersects = any(point_in_polygon(x, y, points) for x, y in car_corners)
            if not intersects:
                intersects = any(
                    dist_point_to_segment(player_car.x, player_car.y, points[i][0], points[i][1],
                                         points[(i + 1) % len(points)][0], points[(i + 1) % len(points)][1])
                    <= car_radius
                    for i in range(len(points))
                )
            if not intersects:
                continue

            if previous_position is not None:
                player_car.x, player_car.y = previous_position
            player_car.speed = 0.0
            self.taxi_smoke_timer = max(self.taxi_smoke_timer, 5.0)
            building_id = id(building)
            if building_id not in self._crashed_building_cooldowns:
                self._crashed_building_cooldowns[building_id] = sim_time
                self.total_score -= penalty
                self.notification_msg = f"Building crash! -{penalty} pts"
                self.notification_timer = 3.5
                logger.info("Player crashed into building: -%d pts", penalty)
            return True

        return False

    def _refresh_road_overlap_cache(self, ways: List[Way], buildings: List[Building]) -> None:
        """Cache road/building overlaps and refresh only when map lists change."""
        if (
            ways is self._overlap_ways_ref
            and buildings is self._overlap_buildings_ref
            and len(ways) == self._overlap_way_count
            and len(buildings) == self._overlap_building_count
        ):
            return
        drivable_ways = [way for way in ways if is_car_road(way)]
        self._road_overlap_buildings = {
            id(building)
            for building in buildings
            if any(self._road_overlaps_building(way, building.points_m, building.bbox) for way in drivable_ways)
        }
        self._overlap_ways_ref = ways
        self._overlap_buildings_ref = buildings
        self._overlap_way_count = len(ways)
        self._overlap_building_count = len(buildings)

    @staticmethod
    def _road_overlaps_building(
        way: Way,
        building_points: List[Tuple[float, float]],
        building_bbox: Optional[Tuple[float, float, float, float]] = None,
    ) -> bool:
        """Return whether a road corridor intersects a building footprint."""
        half_width = getattr(way, "half_width_m", 3.0)
        road_points = getattr(way, "points_m", [])
        if len(road_points) < 2:
            return False

        road_bbox = getattr(way, "bbox", None)
        if road_bbox is None or road_bbox == (0.0, 0.0, 0.0, 0.0):
            xs = [point[0] for point in road_points]
            ys = [point[1] for point in road_points]
            road_bbox = (min(xs), min(ys), max(xs), max(ys))
        if building_bbox is None or building_bbox == (0.0, 0.0, 0.0, 0.0):
            xs = [point[0] for point in building_points]
            ys = [point[1] for point in building_points]
            building_bbox = (min(xs), min(ys), max(xs), max(ys))
        if (
            road_bbox[2] + half_width < building_bbox[0]
            or road_bbox[0] - half_width > building_bbox[2]
            or road_bbox[3] + half_width < building_bbox[1]
            or road_bbox[1] - half_width > building_bbox[3]
        ):
            return False

        def orientation(a, b, c):
            value = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            if abs(value) < 1e-9:
                return 0
            return 1 if value > 0 else -1

        def on_segment(a, b, c):
            return min(a[0], b[0]) <= c[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= c[1] <= max(a[1], b[1])

        def segments_intersect(a, b, c, d):
            ab_c = orientation(a, b, c)
            ab_d = orientation(a, b, d)
            cd_a = orientation(c, d, a)
            cd_b = orientation(c, d, b)
            if ab_c != ab_d and cd_a != cd_b:
                return True
            return (
                (ab_c == 0 and on_segment(a, b, c))
                or (ab_d == 0 and on_segment(a, b, d))
                or (cd_a == 0 and on_segment(c, d, a))
                or (cd_b == 0 and on_segment(c, d, b))
            )

        for road_start, road_end in zip(road_points, road_points[1:]):
            if point_in_polygon(road_start[0], road_start[1], building_points):
                return True
            for building_start, building_end in zip(building_points, building_points[1:] + building_points[:1]):
                if segments_intersect(road_start, road_end, building_start, building_end):
                    return True
                if (
                    dist_point_to_segment(
                        building_start[0], building_start[1],
                        road_start[0], road_start[1], road_end[0], road_end[1],
                    ) <= half_width
                ):
                    return True
        return False

    def check_tree_collision(
        self,
        player_car: Car,
        sceneries: List[Any],
        sim_time: float,
        previous_position: Optional[Tuple[float, float]] = None,
        penalty: int = 100,
    ) -> bool:
        """Stop the car at a tree and apply one penalty per impact."""
        expired = [key for key, t in self._crashed_tree_cooldowns.items() if sim_time - t > 3.0]
        for key in expired:
            del self._crashed_tree_cooldowns[key]

        radius = math.hypot(player_car.length_m, player_car.width_m) * 0.5 + 1.0
        for scenery in sceneries:
            for tree_index, (tree_x, tree_y) in enumerate(getattr(scenery, "trees", [])):
                if math.hypot(player_car.x - tree_x, player_car.y - tree_y) > radius:
                    continue
                if previous_position is not None:
                    restore_x, restore_y = previous_position
                else:
                    restore_x, restore_y = player_car.x, player_car.y
                away_x = restore_x - tree_x
                away_y = restore_y - tree_y
                away_distance = math.hypot(away_x, away_y)
                if away_distance < radius:
                    if away_distance < 1e-6:
                        away_x = -math.cos(player_car.heading)
                        away_y = -math.sin(player_car.heading)
                        away_distance = 1.0
                    safe_distance = radius + 0.2
                    restore_x = tree_x + away_x / away_distance * safe_distance
                    restore_y = tree_y + away_y / away_distance * safe_distance
                player_car.x, player_car.y = restore_x, restore_y
                impact_speed_kmh = abs(player_car.speed) * 3.6
                player_car.speed = 0.0
                key = (id(scenery), tree_index)
                self.tree_effects[key] = {
                    "shake": 0.55,
                    "leaves": 1.2,
                    "angle": player_car.heading,
                }
                if impact_speed_kmh > 80.0:
                    self.fallen_trees.add(key)
                    self.tree_wait_timer = 5.0
                self.taxi_smoke_timer = max(self.taxi_smoke_timer, 5.0)
                if key not in self._crashed_tree_cooldowns:
                    self._crashed_tree_cooldowns[key] = sim_time
                    self.total_score -= penalty
                    self.notification_msg = f"Tree crash! -{penalty} pts"
                    self.notification_timer = 3.5
                return True
        return False

    def check_red_light_violation(
        self,
        car: Car,
        traffic_lights: List[Any],
        sim_time: float,
        penalty: int = 100,
    ) -> None:
        """Check if player car passes across a red/yellow traffic light line and apply penalty upon crossing."""
        if abs(car.speed) < 2.0:
            return  # Standing or creeping slowly before line is not running a red light

        # Clean expired signal cooldowns (> 10 seconds ago)
        expired = [sid for sid, t in self._passed_red_signals.items() if sim_time - t > 10.0]
        for sid in expired:
            del self._passed_red_signals[sid]

        for tl in traffic_lights:
            tl_id = getattr(tl, "id", id(tl))
            if tl_id in self._passed_red_signals:
                continue

            # Vector from car to traffic light
            dx = tl.x - car.x
            dy = tl.y - car.y
            dist = math.hypot(dx, dy)

            # Only track lights within detection zone (e.g. 15 meters)
            if dist > 15.0:
                self._approaching_red_signals.pop(tl_id, None)
                continue

            approach_heading = self._approaching_red_headings.get(tl_id)
            measured_heading = approach_heading if approach_heading is not None else car.heading
            move_heading = measured_heading if car.speed >= 0 else measured_heading + math.pi
            dir_x = math.cos(move_heading)
            dir_y = math.sin(move_heading)
            perp_x = -math.sin(move_heading)
            perp_y = math.cos(move_heading)

            # Once an approach is tracked, keep its coordinate frame through turns.
            # Otherwise a 90-degree turn can make the same signal look like a new approach.
            if approach_heading is None and getattr(tl, "direction_angle", None) is not None:
                tl_ang = tl.direction_angle
                car_ang = measured_heading % math.pi
                ang_err = abs(tl_ang - car_ang)
                ang_err = min(ang_err, math.pi - ang_err)
                if ang_err > math.radians(45):
                    self._approaching_red_signals.pop(tl_id, None)
                    continue  # Signal is for cross traffic

            # Longitudinal distance along direction of travel:
            # Positive = traffic light is ahead of car
            # Negative = traffic light is behind car (car has crossed the stop line)
            long_dist = dx * dir_x + dy * dir_y
            lat_dist = abs(dx * perp_x + dy * perp_y)

            # Must be reasonably aligned laterally to the traffic light post / stop line (within 8m)
            if lat_dist > 8.0:
                if approach_heading is None:
                    self._approaching_red_signals.pop(tl_id, None)
                    continue

            prev_long_dist = self._approaching_red_signals.get(tl_id)
            self._approaching_red_signals[tl_id] = long_dist
            if long_dist > 0.0 and tl_id not in self._approaching_red_headings:
                self._approaching_red_headings[tl_id] = car.heading

            state = tl.get_state(sim_time)
            is_red = state in ("red", "red+yellow")

            # Crossed line condition:
            # 1) Previously ahead (prev >= 0.0) and now behind (long_dist < 0.0), or
            # 2) Directly at/past line (-4.0 <= long_dist <= 0.0) while driving through at speed
            crossed_line = False
            if prev_long_dist is not None and prev_long_dist >= -1.0 and long_dist < 0.0:
                crossed_line = True
            elif -4.0 <= long_dist <= 0.0 and dist <= 6.0:
                crossed_line = True

            if crossed_line and is_red:
                approach_heading = self._approaching_red_headings.pop(tl_id, car.heading)
                heading_change = abs((car.heading - approach_heading + math.pi) % (2 * math.pi) - math.pi)
                if heading_change > math.radians(45):
                    self._approaching_red_signals.pop(tl_id, None)
                    continue
                self._passed_red_signals[tl_id] = sim_time
                self._approaching_red_signals.pop(tl_id, None)
                self.total_score -= penalty
                self.notification_msg = f"Red Light Violation! -{penalty} pts"
                self.notification_timer = 4.0
                logger.info("Player passed red traffic light %s: -%d pts penalty", tl_id, penalty)
                break

    def get_red_light_assist_speed_limit(
        self,
        car: Car,
        traffic_lights: List[Any],
        sim_time: float,
        detection_distance_m: float = 45.0,
        stop_buffer_m: float = 4.0,
        deceleration_mps2: float = 4.0,
    ) -> Optional[float]:
        """Return a comfortable speed target for the nearest red light ahead."""
        heading_x = math.cos(car.heading)
        heading_y = math.sin(car.heading)
        nearest_light = None

        for tl in traffic_lights:
            dx = tl.x - car.x
            dy = tl.y - car.y
            longitudinal = dx * heading_x + dy * heading_y
            lateral = abs(dx * -heading_y + dy * heading_x)
            if longitudinal <= 0.0 or longitudinal > detection_distance_m or lateral > 8.0:
                continue

            direction_angle = getattr(tl, "direction_angle", None)
            if direction_angle is not None:
                angle_error = abs(direction_angle - (car.heading % math.pi))
                angle_error = min(angle_error, math.pi - angle_error)
                if angle_error > math.radians(45):
                    continue

            if nearest_light is None or longitudinal < nearest_light[0]:
                nearest_light = (longitudinal, tl)

        if nearest_light is None or nearest_light[1].get_state(sim_time) not in ("red", "red+yellow"):
            return None

        available_distance = max(0.0, nearest_light[0] - stop_buffer_m)
        return math.sqrt(2.0 * deceleration_mps2 * available_distance)

    def sees_red_light(
        self,
        car: Car,
        traffic_lights: List[Any],
        sim_time: float,
        detection_distance_m: float = 45.0,
    ) -> bool:
        """Return whether the taxi is approaching a visible red traffic light."""
        heading_x = math.cos(car.heading)
        heading_y = math.sin(car.heading)
        for tl in traffic_lights:
            dx = tl.x - car.x
            dy = tl.y - car.y
            longitudinal = dx * heading_x + dy * heading_y
            lateral = abs(dx * -heading_y + dy * heading_x)
            if longitudinal <= 0.0 or longitudinal > detection_distance_m or lateral > 8.0:
                continue
            direction_angle = getattr(tl, "direction_angle", None)
            if direction_angle is not None:
                angle_error = abs((direction_angle - car.heading + math.pi) % (2.0 * math.pi) - math.pi)
                if angle_error > math.radians(45):
                    continue
            if tl.get_state(sim_time) in ("red", "red+yellow"):
                return True
        return False

    def check_wrong_way_violation(
        self,
        car: Car,
        dt: float,
        ways: Optional[List[Way]] = None,
        spatial_grid: Optional[SpatialWayGrid] = None,
        penalty: int = 50,
        interval_s: float = 5.0,
    ) -> bool:
        """Check if player is driving in wrong direction on a one-way road and apply penalty every 5 seconds."""
        # Only check if car is actually moving (speed > 1.5 m/s)
        if abs(car.speed) < 1.5:
            self.wrong_way_duration = 0.0
            return False

        dx = math.cos(car.heading) * car.speed * dt
        dy = math.sin(car.heading) * car.speed * dt

        is_violating = is_violating_oneway(
            car,
            car.x,
            car.y,
            dx,
            dy,
            ways=ways,
            spatial_grid=spatial_grid,
        )

        if is_violating:
            self.wrong_way_duration += dt
            self.wrong_way_penalty_cooldown += dt
            if self.wrong_way_penalty_cooldown >= interval_s:
                self.wrong_way_penalty_cooldown = 0.0
                self.total_score -= penalty
                self.notification_msg = f"Wrong Way Penalty! -{penalty} pts"
                self.notification_timer = 3.5
                logger.info("Player driving wrong way on one-way road: -%d pts penalty", penalty)
            return True
        else:
            self.wrong_way_duration = 0.0
            self.wrong_way_penalty_cooldown = 0.0
            return False

    def sync_map_data(
        self,
        ways: List[Way],
        places: Optional[List[Place]] = None,
        buildings: Optional[List[Building]] = None,
    ) -> None:
        """Update road and place references when map expands dynamically."""
        self.ways = connected_drivable_ways(ways, named=True)
        if places is not None:
            self.places = places
        if buildings is not None:
            self.buildings = buildings

    def get_nearest_district(self, x: float, y: float) -> Optional[str]:
        """Find the closest named district / suburb / place."""
        if not self.places:
            return None
        best_p = None
        best_dist = float("inf")
        for p in self.places:
            d = math.hypot(p.x - x, p.y - y)
            if d < best_dist:
                best_dist = d
                best_p = p
        if best_p and best_dist < 4000.0:
            return best_p.name
        return None

    def find_nearest_named_road(self, x: float, y: float, max_search_m: float = 600.0) -> Optional[str]:
        """Find the name of the nearest named road to a given position."""
        best_name = None
        best_dist = float("inf")
        for w in self.ways:
            if getattr(w, "name", None) and len(w.points_m) >= 2:
                # Check distance to segments in this way
                for i in range(len(w.points_m) - 1):
                    p1 = w.points_m[i]
                    p2 = w.points_m[i + 1]
                    d = dist_point_to_segment(x, y, p1[0], p1[1], p2[0], p2[1])
                    if d < best_dist:
                        best_dist = d
                        best_name = w.name
        if best_name and best_dist <= max_search_m:
            return best_name
        return None

    def find_nearest_osm_address(
        self, x: float, y: float, street_name: Optional[str] = None, max_search_m: float = 250.0
    ) -> Optional[str]:
        """Look for real OSM house numbers on buildings near (x, y)."""
        if not self.buildings:
            return None

        best_housenumber: Optional[str] = None
        best_dist = float("inf")

        for b in self.buildings:
            if not b.housenumber:
                continue

            # If street name is specified, prioritize buildings on matching street
            if street_name and b.street:
                if b.street.lower() != street_name.lower():
                    continue

            # Check distance to building centroid or bounding box
            if b.points_m:
                cx = sum(p[0] for p in b.points_m) / len(b.points_m)
                cy = sum(p[1] for p in b.points_m) / len(b.points_m)
            else:
                bb = getattr(b, "bbox", (0.0, 0.0, 0.0, 0.0))
                cx = (bb[0] + bb[2]) / 2.0
                cy = (bb[1] + bb[3]) / 2.0

            d = math.hypot(cx - x, cy - y)
            if d < best_dist:
                best_dist = d
                best_housenumber = b.housenumber

        if best_housenumber and best_dist <= max_search_m:
            return best_housenumber
        return None

    def generate_address_for_point(self, x: float, y: float, way_name: Optional[str] = None) -> Optional[str]:
        """Generate a real street address from OSM data with real road name and real house number if present.

        Returns None if no real street name is available.
        """
        street = way_name
        if not street:
            street = self.find_nearest_named_road(x, y)

        if not street:
            return None

        # Look up real OSM house number nearby on buildings
        real_housenumber = self.find_nearest_osm_address(x, y, street_name=street)
        district = self.get_nearest_district(x, y)

        if real_housenumber:
            if district and district.lower() not in street.lower():
                return f"{street} {real_housenumber}, {district}"
            return f"{street} {real_housenumber}"
        else:
            # Only use real street name without fabricated house number
            if district and district.lower() not in street.lower():
                return f"{street}, {district}"
            return f"{street}"

    def pick_random_building_point(
        self,
        ref_x: Optional[float] = None,
        ref_y: Optional[float] = None,
        min_dist: float = 0.0,
        max_dist: float = float("inf"),
        max_road_distance: float = 250.0,
    ) -> Optional[TaxiTarget]:
        """Pick a named building and place its target at the nearest reachable road point."""
        candidates = [
            building for building in self.buildings
            if building.name and len(building.points_m) >= 3
        ]
        random.shuffle(candidates)

        for building in candidates:
            center_x = sum(point[0] for point in building.points_m) / len(building.points_m)
            center_y = sum(point[1] for point in building.points_m) / len(building.points_m)
            nearest: Optional[Tuple[float, float, str, float]] = None

            for way in self.ways:
                if len(way.points_m) < 2 or not way.name:
                    continue
                for start, end in zip(way.points_m, way.points_m[1:]):
                    dx = end[0] - start[0]
                    dy = end[1] - start[1]
                    length_squared = dx * dx + dy * dy
                    if length_squared <= 1e-9:
                        continue
                    fraction = clamp(
                        ((center_x - start[0]) * dx + (center_y - start[1]) * dy) / length_squared,
                        0.0,
                        1.0,
                    )
                    road_x = start[0] + fraction * dx
                    road_y = start[1] + fraction * dy
                    road_distance = math.hypot(center_x - road_x, center_y - road_y)
                    if nearest is None or road_distance < nearest[3]:
                        nearest = (road_x, road_y, way.name, road_distance)

            if nearest is None or nearest[3] > max_road_distance:
                continue
            road_x, road_y, way_name, _ = nearest
            if ref_x is not None and ref_y is not None:
                distance = math.hypot(road_x - ref_x, road_y - ref_y)
                if not min_dist <= distance <= max_dist:
                    continue

            return TaxiTarget(
                x=road_x,
                y=road_y,
                address=building.name,
                way_name=way_name,
                district_name=self.get_nearest_district(road_x, road_y),
                radius_m=self.pickup_radius_m,
            )
        return None

    def pick_random_road_point(
        self,
        ref_x: Optional[float] = None,
        ref_y: Optional[float] = None,
        min_dist: float = 0.0,
        max_dist: float = float("inf"),
    ) -> Optional[TaxiTarget]:
        """Pick a valid road coordinate with a verified real street name within distance constraints."""
        if not self.ways:
            return None

        candidate_ways = self.ways[:]
        random.shuffle(candidate_ways)

        for w in candidate_ways:
            if len(w.points_m) < 2:
                continue

            way_name = getattr(w, "name", None)
            if not way_name:
                continue

            # Pick a random segment in this way
            idx = random.randint(0, len(w.points_m) - 2)
            p1 = w.points_m[idx]
            p2 = w.points_m[idx + 1]
            t = random.uniform(0.1, 0.9)
            px = p1[0] + t * (p2[0] - p1[0])
            py = p1[1] + t * (p2[1] - p1[1])

            if ref_x is not None and ref_y is not None:
                dist = math.hypot(px - ref_x, py - ref_y)
                if not (min_dist <= dist <= max_dist):
                    continue

            addr = self.generate_address_for_point(px, py, way_name)
            if not addr:
                continue

            district = self.get_nearest_district(px, py)
            return TaxiTarget(
                x=px,
                y=py,
                address=addr,
                way_name=way_name,
                district_name=district,
                radius_m=self.pickup_radius_m,
            )

        # If strict distance search didn't match, pick any named way
        for w in candidate_ways:
            way_name = getattr(w, "name", None)
            if not way_name or len(w.points_m) < 2:
                continue
            idx = random.randint(0, len(w.points_m) - 2)
            p1 = w.points_m[idx]
            p2 = w.points_m[idx + 1]
            t = random.uniform(0.1, 0.9)
            px = p1[0] + t * (p2[0] - p1[0])
            py = p1[1] + t * (p2[1] - p1[1])
            addr = self.generate_address_for_point(px, py, way_name)
            if addr:
                return TaxiTarget(
                    x=px,
                    y=py,
                    address=addr,
                    way_name=way_name,
                    district_name=self.get_nearest_district(px, py),
                    radius_m=self.pickup_radius_m,
                )
        return None

    def pick_random_taxi_stop(
        self,
        ref_x: Optional[float] = None,
        ref_y: Optional[float] = None,
        min_dist: float = 0.0,
        max_dist: float = float("inf"),
    ) -> Optional[TaxiTarget]:
        stops = self.taxi_stops[:]
        random.shuffle(stops)
        for stop in stops:
            if ref_x is not None and ref_y is not None:
                distance = math.hypot(stop.x - ref_x, stop.y - ref_y)
                if not min_dist <= distance <= max_dist:
                    continue
            way_name = self.find_nearest_named_road(stop.x, stop.y)
            address = self.generate_address_for_point(stop.x, stop.y, way_name) or "Taxi stop"
            return TaxiTarget(
                x=stop.x,
                y=stop.y,
                address=address,
                way_name=way_name,
                district_name=self.get_nearest_district(stop.x, stop.y),
                radius_m=self.pickup_radius_m,
            )
        return None

    def make_target(self, x: float, y: float) -> TaxiTarget:
        """Create a pickup target at an already known position."""
        way_name = self.find_nearest_named_road(x, y)
        return TaxiTarget(
            x=x,
            y=y,
            address=self.generate_address_for_point(x, y, way_name) or "Taxi stop",
            way_name=way_name,
            district_name=self.get_nearest_district(x, y),
            radius_m=self.pickup_radius_m,
        )

    def spawn_mission(self, car_x: float, car_y: float) -> None:
        """Spawn a new passenger pickup and dropoff destination."""
        pickup_target = self.pick_random_building_point(
            ref_x=car_x,
            ref_y=car_y,
            min_dist=150.0,
            max_dist=1200.0,
        )
        if not pickup_target:
            pickup_target = self.pick_random_taxi_stop(
            ref_x=car_x,
            ref_y=car_y,
            min_dist=150.0,
            max_dist=1200.0,
            )
        if not pickup_target:
            pickup_target = self.pick_random_road_point(
                ref_x=car_x,
                ref_y=car_y,
                min_dist=150.0,
                max_dist=1200.0,
            )
        if not pickup_target:
            return

        dropoff_target = self.pick_random_building_point(
            ref_x=pickup_target.x,
            ref_y=pickup_target.y,
            min_dist=self.min_distance_m,
            max_dist=self.max_distance_m,
        )
        if not dropoff_target:
            dropoff_target = self.pick_random_taxi_stop(
            ref_x=pickup_target.x,
            ref_y=pickup_target.y,
            min_dist=self.min_distance_m,
            max_dist=self.max_distance_m,
            )
        if not dropoff_target:
            dropoff_target = self.pick_random_road_point(
            ref_x=pickup_target.x,
            ref_y=pickup_target.y,
            min_dist=self.min_distance_m,
            max_dist=self.max_distance_m,
            )
        if not dropoff_target:
            dropoff_target = pickup_target

        passenger_name = random.choice(FIRST_NAMES)
        self.current_passenger = TaxiPassenger(
            name=passenger_name,
            pickup=pickup_target,
            dropoff=dropoff_target,
            ped_x=pickup_target.x,
            ped_y=pickup_target.y,
            ped_heading=0.0,
            ped_speed=2.2,
            is_walking_to_car=False,
            boarded=False,
        )
        self.state = TaxiState.WAITING_FOR_PICKUP
        self.elapsed_time = 0.0
        self.notification_msg = f"New Fare! Pickup {passenger_name} at {pickup_target.address}"
        self.notification_timer = 5.0

    def generate_offers(self, car_x: float, car_y: float, count: int = 3) -> List[TaxiOffer]:
        """Create ride requests without activating one until the player accepts it."""
        offers: List[TaxiOffer] = []
        for _ in range(max(1, count)):
            pickup = self.pick_random_taxi_stop(car_x, car_y, min_dist=150.0, max_dist=1200.0)
            if not pickup:
                pickup = self.pick_random_road_point(car_x, car_y, min_dist=150.0, max_dist=1200.0)
            if not pickup:
                continue
            dropoff = self.pick_random_taxi_stop(pickup.x, pickup.y, self.min_distance_m, self.max_distance_m)
            if not dropoff:
                dropoff = self.pick_random_road_point(pickup.x, pickup.y, self.min_distance_m, self.max_distance_m)
            if not dropoff:
                continue
            passenger = TaxiPassenger(
                name=random.choice(FIRST_NAMES),
                pickup=pickup,
                dropoff=dropoff,
                ped_x=pickup.x,
                ped_y=pickup.y,
                ped_speed=2.2,
            )
            offers.append(TaxiOffer(
                passenger=passenger,
                pickup_distance_m=math.hypot(car_x - pickup.x, car_y - pickup.y),
            ))
        self.offers = offers
        return offers

    def accept_offer(self, index: int, car_x: float, car_y: float) -> bool:
        """Activate one phone offer and remove the offer list."""
        if index < 0 or index >= len(self.offers):
            return False
        self.current_passenger = self.offers[index].passenger
        self.offers = []
        self.state = TaxiState.WAITING_FOR_PICKUP
        self.elapsed_time = 0.0
        self.notification_msg = (
            f"New Fare! Pickup {self.current_passenger.name} at {self.current_passenger.pickup.address}"
        )
        self.notification_timer = 5.0
        return True

    def reject_offer(self, index: int = 0, car_x: float = 0.0, car_y: float = 0.0) -> bool:
        """Reject one pending phone request without starting its fare."""
        if index < 0 or index >= len(self.offers):
            return False
        self.offers.pop(index)
        self.next_offer_timer = random.uniform(12.0, 28.0)
        self.notification_msg = tr(self.language, "no_requests")
        self.notification_timer = 2.0
        return True

    def _board_waiting_pedestrian(
        self,
        pedestrian: Any,
        pickup: TaxiTarget,
        message_key: str,
        walk_to_car: bool = False,
    ) -> bool:
        """Turn a nearby waiting pedestrian into a fare, optionally walking to the car first."""
        dropoff = self.pick_random_taxi_stop(pickup.x, pickup.y, self.min_distance_m, self.max_distance_m)
        if not dropoff:
            dropoff = self.pick_random_road_point(pickup.x, pickup.y, self.min_distance_m, self.max_distance_m)
        if not dropoff:
            return False
        passenger = TaxiPassenger(
            name=random.choice(FIRST_NAMES),
            pickup=pickup,
            dropoff=dropoff,
            ped_x=pedestrian.x,
            ped_y=pedestrian.y,
            ped_heading=pedestrian.heading,
            boarded=True,
        )
        self.current_passenger = passenger
        self.offers = []
        if walk_to_car:
            passenger.boarded = False
            passenger.is_walking_to_car = True
            self.state = TaxiState.CLIENT_WALKING_TO_CAR
        else:
            self.state = TaxiState.DRIVING_TO_DROPOFF
        self.elapsed_time = 0.0
        self.trip_distance_m = math.hypot(dropoff.x - pickup.x, dropoff.y - pickup.y)
        notification_key = "walking_named" if walk_to_car else message_key
        self.notification_msg = tr(self.language, notification_key, name=passenger.name, address=dropoff.address)
        self.notification_timer = 5.0
        return True

    def check_waiting_pickup(self, car: Car, pedestrians: List[Any], dt: float) -> Optional[Any]:
        """Let a stopped taxi pick up a pedestrian at a stand or by a rare street hail."""
        if self.current_passenger or abs(car.speed) > self.max_stop_speed_mps:
            self.stand_wait_timer = 0.0
            return None
        self.stand_wait_timer += dt
        if self.stand_wait_timer < 2.0:
            return None
        pickup = None
        message_key = "stand_boarded"
        if self.taxi_stops:
            nearby_stops = [stop for stop in self.taxi_stops if math.hypot(car.x - stop.x, car.y - stop.y) <= 22.0]
            if nearby_stops:
                pickup = self.make_target(nearby_stops[0].x, nearby_stops[0].y)
        candidates = [ped for ped in pedestrians if math.hypot(car.x - ped.x, car.y - ped.y) <= 15.0]
        if pickup is None and not self.taxi_stops and candidates and random.random() < min(1.0, dt * 0.08):
            pickup = self.make_target(candidates[0].x, candidates[0].y)
            message_key = "hail_boarded"
        if pickup is None or not candidates or random.random() >= min(1.0, dt * 0.35):
            return None
        pedestrian = candidates[0]
        if self._board_waiting_pedestrian(
            pedestrian,
            pickup,
            message_key,
            walk_to_car=message_key == "stand_boarded",
        ):
            self.stand_wait_timer = 0.0
            return pedestrian
        return None

    def calculate_score(self, distance_m: float, elapsed_sec: float) -> int:
        """Calculate points based on distance and speed (distance / time)."""
        base_points = int(distance_m * 0.5)  # 500 points per km base
        elapsed_sec = max(1.0, elapsed_sec)
        speed_mps = distance_m / elapsed_sec
        speed_kmh = speed_mps * 3.6

        fare = base_points + speed_bonus_points(speed_kmh)
        return max(50, fare)

    def get_current_target(self) -> Optional[TaxiTarget]:
        """Return currently active target (pickup or dropoff)."""
        if not self.current_passenger:
            return None
        if self.state in (TaxiState.WAITING_FOR_PICKUP, TaxiState.CLIENT_WALKING_TO_CAR):
            return self.current_passenger.pickup
        elif self.state == TaxiState.DRIVING_TO_DROPOFF:
            return self.current_passenger.dropoff
        return None

    def discard_mission(self, car_x: float, car_y: float, penalty: int = 150, reason: str = "Fare cancelled") -> int:
        """Discard the active pickup or onboard passenger mission with a score penalty."""
        if not self.current_passenger:
            return 0
        p_name = self.current_passenger.name
        self.total_score -= penalty
        if self.state in (TaxiState.DRIVING_TO_DROPOFF, TaxiState.CLIENT_WALKING_TO_CAR):
            msg = f"{reason}! Client {p_name} abandoned (-{penalty} pts)"
        else:
            msg = f"{reason}! Pickup for {p_name} cancelled (-{penalty} pts)"
        self.notification_msg = msg
        self.notification_timer = 5.0
        self.current_passenger = None
        self.state = TaxiState.WAITING_FOR_PICKUP
        self.generate_offers(car_x, car_y)
        return penalty

    def handle_respawn(self, car_x: float, car_y: float) -> None:
        """Handle car respawn: discard fare and apply penalty if a passenger is onboard."""
        if self.current_passenger and self.state in (TaxiState.DRIVING_TO_DROPOFF, TaxiState.CLIENT_WALKING_TO_CAR):
            self.discard_mission(car_x, car_y, penalty=200, reason="Respawned while transporting passenger")

    def update(self, car: Car, dt: float) -> None:
        """Update mission timers, pickup/dropoff collision, and fare progression."""
        self.speed_camera_flash_timer = max(0.0, self.speed_camera_flash_timer - dt)
        if self.speed_camera_flash_timer <= 0.0:
            self.speed_camera_flash_index = None
        self.tree_wait_timer = max(0.0, self.tree_wait_timer - dt)
        self.taxi_smoke_timer = max(0.0, self.taxi_smoke_timer - dt)
        for key, effect in list(self.tree_effects.items()):
            effect["shake"] = max(0.0, effect["shake"] - dt)
            effect["leaves"] = max(0.0, effect["leaves"] - dt)
            if effect["shake"] <= 0.0 and effect["leaves"] <= 0.0 and key not in self.fallen_trees:
                del self.tree_effects[key]
        if self.notification_timer > 0.0:
            self.notification_timer -= dt

        if not self.current_passenger and not self.offers:
            self.next_offer_timer -= dt
            if self.next_offer_timer <= 0.0:
                self.generate_offers(car.x, car.y, count=1)
                self.next_offer_timer = random.uniform(18.0, 40.0)
                if self.offers:
                    self.notification_msg = tr(self.language, "new_request")
                    self.notification_timer = 5.0

        if not self.current_passenger:
            return

        target = self.get_current_target()
        if not target:
            return

        dist_to_target = math.hypot(car.x - target.x, car.y - target.y)
        is_stopped = abs(car.speed) <= self.max_stop_speed_mps

        if self.state == TaxiState.WAITING_FOR_PICKUP:
            if dist_to_target <= target.radius_m:
                if is_stopped:
                    # Car arrived at pickup area and stopped: client begins walking to taxi
                    self.state = TaxiState.CLIENT_WALKING_TO_CAR
                    self.current_passenger.is_walking_to_car = True
                    self.notification_msg = tr(self.language, "walking_named", name=self.current_passenger.name)
                    self.notification_timer = 3.0
                else:
                    self.notification_msg = "Slow down to pick up passenger!"
                    self.notification_timer = 1.0

        elif self.state == TaxiState.CLIENT_WALKING_TO_CAR:
            # Passenger walks towards the passenger side door of the taxi
            p = self.current_passenger
            # Passenger door position (side offset relative to car heading)
            door_offset_side = 1.2
            door_offset_long = -0.5
            door_x = car.x + math.cos(car.heading) * door_offset_long + math.sin(car.heading) * door_offset_side
            door_y = car.y - math.sin(car.heading) * door_offset_long - math.cos(car.heading) * door_offset_side

            dx = door_x - p.ped_x
            dy = door_y - p.ped_y
            dist_to_door = math.hypot(dx, dy)

            # If player drives away too fast while passenger is boarding, passenger cancels/abandons
            if dist_to_target > target.radius_m * 1.8:
                self.discard_mission(car.x, car.y, penalty=100, reason="Drove away during pickup")
                return

            if dist_to_door <= 0.8:
                # Client reached taxi door and boarded!
                p.boarded = True
                p.is_walking_to_car = False
                self.state = TaxiState.DRIVING_TO_DROPOFF
                self.elapsed_time = 0.0
                self.trip_distance_m = math.hypot(p.dropoff.x - p.pickup.x, p.dropoff.y - p.pickup.y)
                self.notification_msg = tr(
                    self.language, "boarded_destination", name=p.name, address=p.dropoff.address
                )
                self.notification_timer = 6.0
            else:
                p.ped_heading = math.atan2(dy, dx)
                step = p.ped_speed * dt
                if step < dist_to_door:
                    p.ped_x += math.cos(p.ped_heading) * step
                    p.ped_y += math.sin(p.ped_heading) * step
                else:
                    p.ped_x = door_x
                    p.ped_y = door_y

        elif self.state == TaxiState.DRIVING_TO_DROPOFF:
            self.elapsed_time += dt
            if dist_to_target <= target.radius_m:
                if is_stopped:
                    # Completed fare!
                    p = self.current_passenger
                    earned = self.calculate_score(self.trip_distance_m, self.elapsed_time)
                    self.total_score += earned
                    self.completed_fares += 1
                    self.last_fare_points = earned
                    avg_kmh = (self.trip_distance_m / max(1.0, self.elapsed_time)) * 3.6
                    self.notification_msg = tr(
                        self.language, "fare_complete_points", earned=earned, avg=avg_kmh, seconds=self.elapsed_time
                    )
                    self.notification_timer = 6.0
                    # New requests are selected through the phone.
                    self.current_passenger = None
                    self.generate_offers(car.x, car.y)
                else:
                    self.notification_msg = "Slow down at destination to drop off!"
                    self.notification_timer = 1.0
