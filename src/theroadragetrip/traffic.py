import logging
import math
import random
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .geo import boxes_intersect
from .osm import TrafficLight, Way
from .physics import Car, connected_drivable_ways

logger = logging.getLogger(__name__)

NPC_COLORS = [
    (60, 140, 230),   # Blue
    (230, 200, 50),   # Yellow
    (240, 240, 240),  # White
    (50, 50, 50),     # Dark gray
    (50, 180, 80),    # Green
    (220, 120, 40),   # Orange
    (160, 60, 180),   # Purple
    (180, 180, 190),  # Silver
]
MAX_TRAFFIC_COUNT = 50
NPC_TAXI_COLOR = (245, 205, 35)


def recommended_traffic_count(ways: List[Way], minimum: int = 5, maximum: int = MAX_TRAFFIC_COUNT) -> int:
    """Choose a traffic population from the number of connected drivable road ways."""
    road_count = len(connected_drivable_ways(ways))
    return max(minimum, min(maximum, round(road_count / 10)))


def traffic_count_for_zoom(base_count: int, px_per_m: float, minimum: int = 5) -> int:
    """Use fewer active NPCs when zoomed in, where less traffic is visible."""
    zoom_factor = min(1.0, 3.0 / max(0.1, px_per_m))
    return max(0, min(base_count, max(minimum, round(base_count * zoom_factor))))


@dataclass
class NPCCar:
    """Autonomous traffic vehicle driving along real-world road networks."""
    x: float
    y: float
    heading: float
    speed: float
    way: Way
    segment_idx: int
    direction: int  # 1 for forward along points_m, -1 for reverse
    target_speed: float
    color: Tuple[int, int, int]
    lane_offset: float = 0.0  # Lateral offset in meters (positive = right of centerline)
    target_lane_offset: float = 0.0
    layer: int = 0
    length_m: float = 4.0
    width_m: float = 1.8
    # Personality traits: compliance multiplier (1.0 = exact limit, >1.25 = speeder / kaahari)
    speed_factor: float = 1.0
    is_speeder: bool = False
    # Overhaul/passing state
    overtaking: bool = False
    overtake_timer: float = 0.0
    # Crash / disable state
    crashed_timer: float = 0.0
    blocked_timer: float = 0.0
    escape_timer: float = 0.0
    rage_timer: float = 0.0
    turn_signal: str = ""  # "left" or "right" while completing a turn
    turn_signal_elapsed: float = 0.0
    is_taxi: bool = False
    taxi_pickup_timer: float = 0.0


def calculate_npc_target_speed(way: Way, speed_factor: float) -> float:
    """Compute realistic driving target speed in m/s based on Finnish road limit and vehicle personality."""
    limit_kmh = getattr(way, "speed_limit_kmh", 50)
    # Target speed = speed limit * speed_factor (m/s)
    base_mps = (limit_kmh / 3.6) * speed_factor
    return max(4.0, base_mps)


def compute_desired_lane_offset(way: Way, is_overtaking: bool = False, travel_direction: int = 1) -> float:
    """Calculate lateral lane offset (meters) to keep right or pass on multi-lane roads."""
    half_w = getattr(way, "half_width_m", 4.0)
    oneway = getattr(way, "oneway", 0)

    # On two-way roads (oneway == 0), right side is half_w * 0.45
    # If overtaking on two-way or multi-lane, move towards left/center
    if oneway == 0:
        base_offset = max(1.2, half_w * 0.45)
        if is_overtaking:
            offset = -base_offset * 0.7  # Passing lane in oncoming / middle
        else:
            offset = base_offset
    else:
        # On wide one-way roads (e.g. half_w >= 5.0m), default to right lane, overtake on left
        if half_w >= 5.0:
            right_lane = half_w * 0.5
            left_lane = -half_w * 0.5
            offset = left_lane if is_overtaking else right_lane
        else:
            offset = 0.0
    return offset


class TrafficManager:
    """Manages autonomous NPC traffic simulation around the player."""

    def __init__(
        self,
        ways: List[Way],
        target_count: int = 15,
        spawn_radius_m: float = 300.0,
        despawn_radius_m: float = 450.0,
        traffic_lights: Optional[List[TrafficLight]] = None,
        crossings: Optional[List] = None,
    ):
        self.ways = connected_drivable_ways(ways)
        self.target_count = max(0, min(MAX_TRAFFIC_COUNT, target_count))
        self.spawn_radius_m = spawn_radius_m
        self.despawn_radius_m = despawn_radius_m
        self.min_spawn_dist_to_player_m: float = 12.0
        self.min_spawn_dist_to_npc_m: float = 6.0
        self.traffic_lights = traffic_lights if traffic_lights is not None else []
        self.crossings = crossings if crossings is not None else []
        self.npcs: List[NPCCar] = []
        self._log_timer: float = 0.0
        self.sim_time: float = 0.0
        self._junction_grid_cell_size: float = 60.0
        self._junction_grid: dict = {}
        self._way_grid_cell_size: float = 200.0
        self._way_grid: dict = {}
        self._signal_grid_cell_size: float = 60.0
        self._traffic_light_grid: dict[Tuple[int, int], List[TrafficLight]] = {}
        self._crossing_grid: dict[Tuple[int, int], List] = {}
        self._npc_grid_cell_size: float = 32.0
        self._npc_grid: dict[Tuple[int, int], List[NPCCar]] = {}
        self._build_spatial_indices()

    def _build_npc_spatial_grid(self) -> None:
        cell_size = self._npc_grid_cell_size
        self._npc_grid.clear()
        for npc in self.npcs:
            cell = (int(math.floor(npc.x / cell_size)), int(math.floor(npc.y / cell_size)))
            self._npc_grid.setdefault(cell, []).append(npc)

    def _nearby_npcs(self, npc: NPCCar) -> List[NPCCar]:
        cell_size = self._npc_grid_cell_size
        cell_x = int(math.floor(npc.x / cell_size))
        cell_y = int(math.floor(npc.y / cell_size))
        nearby: List[NPCCar] = []
        for offset_x in (-1, 0, 1):
            for offset_y in (-1, 0, 1):
                nearby.extend(self._npc_grid.get((cell_x + offset_x, cell_y + offset_y), []))
        return nearby

    def _resolve_npc_collisions(self) -> None:
        """Separate overlapping nearby NPC cars so traffic cannot occupy the same space."""
        self._build_npc_spatial_grid()
        resolved_pairs = set()
        for npc in self.npcs:
            for other in self._nearby_npcs(npc):
                if other is npc or other.layer != npc.layer:
                    continue
                pair = tuple(sorted((id(npc), id(other))))
                if pair in resolved_pairs:
                    continue
                resolved_pairs.add(pair)

                if not boxes_intersect(
                    npc.x, npc.y, npc.heading, npc.length_m, npc.width_m,
                    other.x, other.y, other.heading, other.length_m, other.width_m,
                ):
                    continue

                dx = npc.x - other.x
                dy = npc.y - other.y
                distance = math.hypot(dx, dy)
                if distance <= 1e-6:
                    dx = math.cos(npc.heading)
                    dy = math.sin(npc.heading)
                    normalizing_distance = 1.0
                else:
                    normalizing_distance = distance

                min_distance = (npc.length_m + other.length_m) * 0.5 + 1.0
                push = max(0.5, min(8.0, min_distance - distance)) * 0.5
                nx = dx / normalizing_distance
                ny = dy / normalizing_distance
                npc.x += nx * push
                npc.y += ny * push
                other.x -= nx * push
                other.y -= ny * push
                npc.speed = 0.0
                other.speed = 0.0

    def _build_spatial_indices(self) -> None:
        """Build spatial index for instant junction lookups and spawning."""
        self._junction_grid.clear()
        self._way_grid.clear()
        self._traffic_light_grid.clear()
        self._crossing_grid.clear()
        j_cs = self._junction_grid_cell_size
        w_cs = self._way_grid_cell_size
        signal_cs = self._signal_grid_cell_size

        for traffic_light in self.traffic_lights:
            cell = (
                int(math.floor(traffic_light.x / signal_cs)),
                int(math.floor(traffic_light.y / signal_cs)),
            )
            self._traffic_light_grid.setdefault(cell, []).append(traffic_light)
        for crossing in self.crossings:
            cell = (
                int(math.floor(crossing.x / signal_cs)),
                int(math.floor(crossing.y / signal_cs)),
            )
            self._crossing_grid.setdefault(cell, []).append(crossing)

        for w in self.ways:
            layer = getattr(w, "layer", 0)
            pts = w.points_m
            n_pts = len(pts)
            for i, pt in enumerate(pts):
                cx = int(math.floor(pt[0] / j_cs))
                cy = int(math.floor(pt[1] / j_cs))
                self._junction_grid.setdefault((cx, cy), []).append((w, i, pt, layer, n_pts))

            bb = getattr(w, "bbox", None)
            if not bb or bb == (0.0, 0.0, 0.0, 0.0):
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                bb = (min(xs), min(ys), max(xs), max(ys))
            min_cx = int(math.floor(bb[0] / w_cs))
            max_cx = int(math.floor(bb[2] / w_cs))
            min_cy = int(math.floor(bb[1] / w_cs))
            max_cy = int(math.floor(bb[3] / w_cs))
            for cx in range(min_cx, max_cx + 1):
                for cy in range(min_cy, max_cy + 1):
                    self._way_grid.setdefault((cx, cy), []).append(w)

    def _nearby_traffic_lights(self, x: float, y: float) -> List[TrafficLight]:
        cell_size = self._signal_grid_cell_size
        cell_x = int(math.floor(x / cell_size))
        cell_y = int(math.floor(y / cell_size))
        nearby: List[TrafficLight] = []
        for offset_x in (-1, 0, 1):
            for offset_y in (-1, 0, 1):
                nearby.extend(self._traffic_light_grid.get((cell_x + offset_x, cell_y + offset_y), []))
        return nearby

    def _nearby_crossings(self, x: float, y: float) -> List:
        cell_size = self._signal_grid_cell_size
        cell_x = int(math.floor(x / cell_size))
        cell_y = int(math.floor(y / cell_size))
        nearby = []
        for offset_x in (-1, 0, 1):
            for offset_y in (-1, 0, 1):
                nearby.extend(self._crossing_grid.get((cell_x + offset_x, cell_y + offset_y), []))
        return nearby

    @staticmethod
    def _turn_signal_for_route(old_heading: float, npc: NPCCar) -> str:
        """Return turn direction for a newly selected route."""
        points = npc.way.points_m
        if len(points) < 2:
            return ""
        if npc.direction == 1 and npc.segment_idx + 1 < len(points):
            target = points[npc.segment_idx + 1]
        elif npc.direction == -1 and npc.segment_idx < len(points):
            target = points[npc.segment_idx]
        else:
            return ""
        new_heading = math.atan2(target[1] - npc.y, target[0] - npc.x)
        turn = (new_heading - old_heading + math.pi) % (2 * math.pi) - math.pi
        if math.radians(20) < turn < math.radians(160):
            return "left"
        if -math.radians(160) < turn < -math.radians(20):
            return "right"
        return ""

    def sync_map_data(
        self,
        ways: List[Way],
        traffic_lights: Optional[List[TrafficLight]] = None,
        crossings: Optional[List] = None,
    ) -> None:
        """Update road references when dynamic tiles expand."""
        self.ways = connected_drivable_ways(ways)
        if traffic_lights is not None:
            self.traffic_lights = traffic_lights
        if crossings is not None:
            self.crossings = crossings
        self._build_spatial_indices()

    def set_target_count(self, target_count: int, player_car: Optional[Car] = None) -> None:
        """Adjust active traffic count and discard farthest cars when zoom reduces it."""
        self.target_count = max(0, min(MAX_TRAFFIC_COUNT, target_count))
        if len(self.npcs) > self.target_count:
            if player_car is not None:
                self.npcs.sort(key=lambda npc: math.hypot(npc.x - player_car.x, npc.y - player_car.y))
            del self.npcs[self.target_count:]

    def let_taxi_pick_up_waiter(self, taxi_stops: List, pedestrians: List, dt: float = 1.0 / 60.0) -> None:
        """Let a nearby NPC taxi collect one waiting customer at a time."""
        for npc in self.npcs:
            if not npc.is_taxi:
                continue
            for pedestrian in pedestrians[:]:
                if getattr(pedestrian, "rival_taxi", None) is not npc:
                    continue
                dx = npc.x - pedestrian.x
                dy = npc.y - pedestrian.y
                distance = math.hypot(dx, dy)
                if distance <= 1.5:
                    pedestrians.remove(pedestrian)
                    npc.taxi_pickup_timer = 0.8
                else:
                    pedestrian.heading = math.atan2(dy, dx)
                    step = min(distance, 2.2 * dt)
                    pedestrian.x += math.cos(pedestrian.heading) * step
                    pedestrian.y += math.sin(pedestrian.heading) * step
                break
            if npc.taxi_pickup_timer > 0.0:
                continue
            for stop in taxi_stops:
                if math.hypot(npc.x - stop.x, npc.y - stop.y) > 8.0:
                    continue
                for pedestrian in pedestrians:
                    if not getattr(pedestrian, "is_taxi_stop_waiter", False):
                        continue
                    if math.hypot(pedestrian.x - stop.x, pedestrian.y - stop.y) > 5.0:
                        continue
                    npc.speed = 0.0
                    npc.taxi_pickup_timer = 1.5
                    pedestrian.rival_taxi = npc
                    pedestrian.is_walking_to_car = True
                    break
                if npc.taxi_pickup_timer > 0.0:
                    break

    def rage_shout(self, player_car: Car, radius_m: float = 50.0) -> int:
        """Move NPCs ahead of the player toward their road edge immediately."""
        moved = 0
        player_heading_x = math.cos(player_car.heading)
        player_heading_y = math.sin(player_car.heading)

        for npc in self.npcs:
            if npc.layer != player_car.layer:
                continue
            delta_x = npc.x - player_car.x
            delta_y = npc.y - player_car.y
            distance = math.hypot(delta_x, delta_y)
            if distance > radius_m or delta_x * player_heading_x + delta_y * player_heading_y <= 0.0:
                continue

            road_half_width = getattr(npc.way, "half_width_m", 4.0)
            edge_offset = road_half_width + max(1.0, npc.width_m * 0.75)
            segment_index = min(max(npc.segment_idx, 0), len(npc.way.points_m) - 2)
            start = npc.way.points_m[segment_index]
            end = npc.way.points_m[segment_index + 1]
            segment_x = end[0] - start[0]
            segment_y = end[1] - start[1]
            segment_length = math.hypot(segment_x, segment_y)
            if segment_length <= 1e-3:
                continue

            normal_x = segment_y / segment_length
            normal_y = -segment_x / segment_length
            center_delta_x = npc.x - start[0]
            center_delta_y = npc.y - start[1]
            current_offset = center_delta_x * normal_x + center_delta_y * normal_y
            edge_sign = 1.0 if current_offset >= 0.0 else -1.0
            npc.target_lane_offset = edge_sign * edge_offset
            npc.lane_offset = npc.target_lane_offset
            npc.x += normal_x * (npc.target_lane_offset - current_offset)
            npc.y += normal_y * (npc.target_lane_offset - current_offset)
            npc.rage_timer = 5.0
            npc.escape_timer = max(npc.escape_timer, 5.0)
            moved += 1

        return moved

    def _find_next_way_and_segment(
        self,
        current_way: Way,
        at_point: Tuple[float, float],
        incoming_heading: Optional[float] = None,
        exclude_reverse: bool = False,
    ) -> Optional[Tuple[Way, int, int]]:
        """Find a connected way at junction point to continue driving seamlessly using spatial grid."""
        tol = 3.0  # 3 meter connection tolerance
        tol_sq = tol * tol
        current_layer = getattr(current_way, "layer", 0)
        candidates: List[Tuple[Way, int, int]] = []

        j_cs = self._junction_grid_cell_size
        cx = int(math.floor(at_point[0] / j_cs))
        cy = int(math.floor(at_point[1] / j_cs))
        at_x, at_y = at_point

        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                cell = self._junction_grid.get((cx + dx, cy + dy))
                if not cell:
                    continue
                for w, i, pt, layer, n_pts in cell:
                    same_layer = layer == current_layer
                    current_endpoint = any(
                        math.hypot(at_point[0] - endpoint[0], at_point[1] - endpoint[1]) <= tol
                        for endpoint in (current_way.points_m[0], current_way.points_m[-1])
                    )
                    candidate_endpoint = i in (0, n_pts - 1)
                    layer_transition = (
                        current_endpoint
                        and candidate_endpoint
                        and (
                            getattr(current_way, "is_bridge", False)
                            or getattr(current_way, "is_tunnel", False)
                            or getattr(w, "is_bridge", False)
                            or getattr(w, "is_tunnel", False)
                        )
                    )
                    if not same_layer and not layer_transition:
                        continue
                    dist_sq = (pt[0] - at_x) ** 2 + (pt[1] - at_y) ** 2
                    if dist_sq <= tol_sq:
                        oneway = getattr(w, "oneway", 0)
                        # Can travel forward from vertex i (if not at the end)
                        if i < n_pts - 1 and oneway >= 0:
                            candidates.append((w, i, 1))
                        # Can travel backward from vertex i (if not at the start)
                        if i > 0 and oneway <= 0:
                            candidates.append((w, i - 1, -1))

        if not candidates:
            return None

        # Filter candidates based on incoming heading to prevent 180-degree U-turns unless no other option
        if incoming_heading is not None:
            forward_candidates = []
            for cand in candidates:
                cand_way, cand_seg_idx, cand_dir = cand
                cand_pts = cand_way.points_m
                if cand_dir == 1:
                    p1 = cand_pts[cand_seg_idx]
                    p2 = cand_pts[cand_seg_idx + 1]
                else:
                    p1 = cand_pts[cand_seg_idx + 1]
                    p2 = cand_pts[cand_seg_idx]
                out_heading = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
                angle_diff = abs((out_heading - incoming_heading + math.pi) % (2 * math.pi) - math.pi)
                # Angle difference > 135 deg (~2.35 rad) is considered a 180-deg reversal/U-turn
                if angle_diff < math.radians(135):
                    forward_candidates.append(cand)
            if forward_candidates:
                candidates = forward_candidates

        # Filter out exact same way if alternatives exist to encourage turns
        alternatives = [c for c in candidates if c[0] is not current_way]
        if alternatives:
            if any(getattr(c[0], "layer", 0) != current_layer for c in alternatives):
                return random.choice(alternatives)
            # 70% chance to turn into another intersecting street if available
            if random.random() < 0.7:
                return random.choice(alternatives)

        # If asked to exclude reverse on the same segment
        valid_candidates = candidates
        if exclude_reverse:
            valid_candidates = [c for c in candidates if c[0] is not current_way]
            if not valid_candidates:
                return None

        return random.choice(valid_candidates)

    def _junction_at_point(self, point: Tuple[float, float], layer: int) -> Optional[Tuple[float, float]]:
        """Return a shared same-layer way vertex when point belongs to a junction."""
        tol = 3.0
        cx = int(math.floor(point[0] / self._junction_grid_cell_size))
        cy = int(math.floor(point[1] / self._junction_grid_cell_size))
        matches = []
        way_ids = set()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for way, _, vertex, vertex_layer, _ in self._junction_grid.get((cx + dx, cy + dy), []):
                    if vertex_layer == layer and math.hypot(point[0] - vertex[0], point[1] - vertex[1]) <= tol:
                        way_ids.add(id(way))
                        matches.append(vertex)
        if len(way_ids) < 2 or not matches:
            return None
        return matches[0]

    def _junction_is_occupied(self, junction_point: Tuple[float, float], npc: NPCCar) -> bool:
        """Check whether another same-layer NPC is still inside a junction."""
        for other in self.npcs:
            if other is npc or other.layer != npc.layer:
                continue
            if math.hypot(other.x - junction_point[0], other.y - junction_point[1]) < 12.0:
                return True
        return False

    def _junction_near_point(self, point: Tuple[float, float], layer: int) -> bool:
        """Return whether point is inside a shared same-layer junction."""
        cx = int(math.floor(point[0] / self._junction_grid_cell_size))
        cy = int(math.floor(point[1] / self._junction_grid_cell_size))
        nearby_ways = set()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for way, _, vertex, vertex_layer, _ in self._junction_grid.get((cx + dx, cy + dy), []):
                    if vertex_layer == layer and math.hypot(point[0] - vertex[0], point[1] - vertex[1]) <= 10.0:
                        nearby_ways.add(id(way))
        return len(nearby_ways) >= 2

    def spawn_npc(
        self,
        near_x: float,
        near_y: float,
        viewport_bounds: Optional[Tuple[float, float, float, float]] = None,
    ) -> Optional[NPCCar]:
        """Spawn a new NPC car near the given location just outside the viewport edge."""
        if not self.ways:
            return None

        # Query nearby ways from spatial grid
        w_cs = self._way_grid_cell_size
        r = self.spawn_radius_m
        min_cx = int(math.floor((near_x - r) / w_cs))
        max_cx = int(math.floor((near_x + r) / w_cs))
        min_cy = int(math.floor((near_y - r) / w_cs))
        max_cy = int(math.floor((near_y + r) / w_cs))

        nearby_ways = []
        seen = set()
        for cx in range(min_cx, max_cx + 1):
            for cy in range(min_cy, max_cy + 1):
                cell = self._way_grid.get((cx, cy))
                if cell:
                    for w in cell:
                        wid = id(w)
                        if wid not in seen:
                            seen.add(wid)
                            nearby_ways.append(w)

        if not nearby_ways:
            return None

        # Filter ways that actually pass within spawn_radius_m of (near_x, near_y)
        valid_ways = []
        for w in nearby_ways:
            for p in w.points_m:
                if (p[0] - near_x) ** 2 + (p[1] - near_y) ** 2 <= r * r:
                    valid_ways.append(w)
                    break

        if not valid_ways:
            return None

        # Try up to 30 candidate ways/segments to place car outside viewport
        random.shuffle(valid_ways)
        for chosen_way in valid_ways[:30]:
            if len(chosen_way.points_m) < 2:
                continue

            # Pick a candidate segment
            candidate_segments = []
            for s_idx in range(len(chosen_way.points_m) - 1):
                sp1 = chosen_way.points_m[s_idx]
                sp2 = chosen_way.points_m[s_idx + 1]
                smx = (sp1[0] + sp2[0]) * 0.5
                smy = (sp1[1] + sp2[1]) * 0.5
                if (smx - near_x) ** 2 + (smy - near_y) ** 2 <= (r * 1.5) ** 2:
                    candidate_segments.append(s_idx)

            if not candidate_segments:
                candidate_segments = list(range(len(chosen_way.points_m) - 1))

            random.shuffle(candidate_segments)
            for seg_idx in candidate_segments:
                p1 = chosen_way.points_m[seg_idx]
                p2 = chosen_way.points_m[seg_idx + 1]

                for _ in range(8):  # Try multiple random points along segment
                    t = random.uniform(0.1, 0.9)
                    x = p1[0] + t * (p2[0] - p1[0])
                    y = p1[1] + t * (p2[1] - p1[1])

                    # When viewport bounds are supplied, enforce spawning just outside view edges
                    if viewport_bounds:
                        vminx, vminy, vmaxx, vmaxy = viewport_bounds
                        if vminx <= x <= vmaxx and vminy <= y <= vmaxy:
                            continue

                    oneway = getattr(chosen_way, "oneway", 0)
                    direction = 1 if oneway >= 0 else -1
                    if oneway == 0:
                        direction = 1 if random.random() < 0.5 else -1

                    if direction == 1:
                        heading = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
                    else:
                        heading = math.atan2(p1[1] - p2[1], p1[0] - p2[0])

                    lane_offset = compute_desired_lane_offset(
                        chosen_way, is_overtaking=False, travel_direction=direction
                    )

                    # Apply lane offset perpendicularly to heading (positive = to the right)
                    right_perp_x = math.sin(heading)
                    right_perp_y = -math.cos(heading)
                    x += right_perp_x * lane_offset
                    y += right_perp_y * lane_offset

                    # Re-verify position is outside viewport after lane offset
                    if viewport_bounds:
                        vminx, vminy, vmaxx, vmaxy = viewport_bounds
                        if vminx <= x <= vmaxx and vminy <= y <= vmaxy:
                            continue

                    layer = getattr(chosen_way, "layer", 0)

                    # Keep initial traffic out of junction conflict zones.
                    junction_ids = set()
                    j_cx = int(math.floor(x / self._junction_grid_cell_size))
                    j_cy = int(math.floor(y / self._junction_grid_cell_size))
                    for jdx in (-1, 0, 1):
                        for jdy in (-1, 0, 1):
                            for junction_way, _, junction_point, junction_layer, _ in self._junction_grid.get(
                                (j_cx + jdx, j_cy + jdy), []
                            ):
                                if junction_layer == layer and math.hypot(
                                    x - junction_point[0], y - junction_point[1]
                                ) < 18.0:
                                    junction_ids.add(id(junction_way))
                    near_junction = len(junction_ids) > 1
                    if near_junction:
                        continue

                    # Sanity check: do not spawn right on top of player
                    dist_to_player = math.hypot(x - near_x, y - near_y)
                    if dist_to_player < self.min_spawn_dist_to_player_m:
                        continue

                    # Sanity check: do not spawn too close to existing NPC cars on same layer
                    too_close_to_npc = False
                    for existing_npc in self.npcs:
                        if existing_npc.layer == layer:
                            distance = math.hypot(x - existing_npc.x, y - existing_npc.y)
                            lateral_distance = abs(
                                -math.sin(heading) * (existing_npc.x - x)
                                + math.cos(heading) * (existing_npc.y - y)
                            )
                            same_lane = lateral_distance < (1.8 + existing_npc.width_m) * 0.75
                            if distance < self.min_spawn_dist_to_npc_m and same_lane:
                                too_close_to_npc = True
                                break
                    if too_close_to_npc:
                        continue

                    # Speed behavior distribution:
                    # ~15% are aggressive speeders (kaaharit, 1.25x - 1.55x limit)
                    # ~70% follow limits closely (0.92x - 1.05x limit)
                    # ~15% are cautious/slow drivers (0.78x - 0.90x limit)
                    r_prof = random.random()
                    if r_prof < 0.18:
                        is_speeder = True
                        speed_factor = random.uniform(1.25, 1.55)
                    elif r_prof < 0.85:
                        is_speeder = False
                        speed_factor = random.uniform(0.92, 1.05)
                    else:
                        is_speeder = False
                        speed_factor = random.uniform(0.78, 0.90)

                    target_spd = calculate_npc_target_speed(chosen_way, speed_factor)
                    initial_spd = target_spd * random.uniform(0.85, 1.0)
                    color = random.choice(NPC_COLORS)
                    length_m = random.uniform(3.5, 5.0)
                    # Width proportional to length (approx 1.4m to 2.0m)
                    width_m = max(1.7, min(2.0, length_m * 0.45))

                    npc = NPCCar(
                        x=x,
                        y=y,
                        heading=heading,
                        speed=initial_spd,
                        way=chosen_way,
                        segment_idx=seg_idx,
                        direction=direction,
                        target_speed=target_spd,
                        color=color,
                        lane_offset=lane_offset,
                        target_lane_offset=lane_offset,
                        layer=layer,
                        length_m=length_m,
                        width_m=width_m,
                        speed_factor=speed_factor,
                        is_speeder=is_speeder,
                        is_taxi=random.random() < 0.12,
                    )
                    if npc.is_taxi:
                        npc.color = NPC_TAXI_COLOR
                    self.npcs.append(npc)
                    return npc

        return None

    def update(
        self,
        player_car: Car,
        dt: float,
        viewport_bounds: Optional[Tuple[float, float, float, float]] = None,
    ) -> None:
        """Update all NPC cars, manage spawning/despawning around player."""
        self.sim_time += dt

        # Despawn distant NPCs
        surviving = []
        for npc in self.npcs:
            d = math.hypot(npc.x - player_car.x, npc.y - player_car.y)
            if d <= self.despawn_radius_m:
                surviving.append(npc)
        self.npcs = surviving

        # Spawn new NPCs up to target_count (preferring just outside viewport)
        attempts = 0
        max_attempts = max(200, self.target_count * 20)
        while len(self.npcs) < self.target_count and attempts < max_attempts:
            attempts += 1
            npc = self.spawn_npc(player_car.x, player_car.y, viewport_bounds=viewport_bounds)
            if not npc and viewport_bounds:
                # Fallback without strict viewport boundary if road network is very sparse
                npc = self.spawn_npc(player_car.x, player_car.y, viewport_bounds=None)
            if not npc:
                break

        self._build_npc_spatial_grid()

        # Periodic log of active NPC traffic count (total and in-view)
        self._log_timer += dt
        if self._log_timer >= 5.0:
            self._log_timer = 0.0
            if viewport_bounds:
                vminx, vminy, vmaxx, vmaxy = viewport_bounds
                in_view_count = sum(
                    1 for npc in self.npcs
                    if vminx <= npc.x <= vmaxx and vminy <= npc.y <= vmaxy
                )
                logger.info(f"Traffic active: {len(self.npcs)} NPC cars on roads ({in_view_count} in view)")
            else:
                logger.info(f"Traffic active: {len(self.npcs)} NPC cars on roads")

        # Check vehicle-ahead distances and manage overtaking / slowing down behind player or other NPCs
        p_len = getattr(player_car, "length_m", 4.0)
        p_wid = getattr(player_car, "width_m", 1.8)

        for i, npc in enumerate(self.npcs):
            if npc.taxi_pickup_timer > 0.0:
                npc.taxi_pickup_timer = max(0.0, npc.taxi_pickup_timer - dt)
                npc.speed = 0.0
                continue
            npc.escape_timer = max(0.0, npc.escape_timer - dt)
            npc.rage_timer = max(0.0, npc.rage_timer - dt)
            if npc.turn_signal:
                npc.turn_signal_elapsed += dt
            if getattr(npc.way, "oneway", 0) == 0 and npc.rage_timer <= 0.0:
                npc.overtaking = False
                npc.overtake_timer = 0.0
                npc.target_lane_offset = compute_desired_lane_offset(
                    npc.way, is_overtaking=False, travel_direction=npc.direction
                )
                npc.lane_offset = npc.target_lane_offset
            if npc.overtaking:
                npc.overtake_timer -= dt
                if npc.overtake_timer <= 0:
                    npc.overtaking = False
                    npc.target_lane_offset = compute_desired_lane_offset(
                        npc.way, is_overtaking=False, travel_direction=npc.direction
                    )
            else:
                # Check if there is a slower car or player car ahead in same lane
                car_ahead = False
                # Check against other NPCs
                for other in self._nearby_npcs(npc):
                    if other is npc or other.layer != npc.layer:
                        continue
                    dx = other.x - npc.x
                    dy = other.y - npc.y
                    dist = math.hypot(dx, dy)
                    if 3.0 < dist < 25.0:
                        angle_to_other = math.atan2(dy, dx)
                        angle_diff = (angle_to_other - npc.heading + math.pi) % (2 * math.pi) - math.pi
                        if abs(angle_diff) < 0.6:  # Ahead within ~35 degrees
                            if npc.speed > other.speed:
                                car_ahead = True
                                break

                # Also check player car ahead
                if not car_ahead and player_car.layer == npc.layer:
                    p_dx = player_car.x - npc.x
                    p_dy = player_car.y - npc.y
                    p_dist = math.hypot(p_dx, p_dy)
                    if 3.0 < p_dist < 25.0:
                        angle_to_p = math.atan2(p_dy, p_dx)
                        angle_diff = (angle_to_p - npc.heading + math.pi) % (2 * math.pi) - math.pi
                        if abs(angle_diff) < 0.6:
                            if npc.speed > player_car.speed:
                                car_ahead = True

                if car_ahead:
                    # Initiate overtaking maneuver
                    if getattr(npc.way, "oneway", 0) != 0:
                        npc.overtaking = True
                        npc.overtake_timer = random.uniform(3.0, 6.0)
                        npc.target_lane_offset = compute_desired_lane_offset(
                            npc.way, is_overtaking=True, travel_direction=npc.direction
                        )

            # Smoothly interpolate lane_offset towards target_lane_offset
            offset_diff = npc.target_lane_offset - npc.lane_offset
            if abs(offset_diff) > 0.01:
                shift_speed = 3.0  # meters per second lateral shift
                npc.lane_offset += math.copysign(min(abs(offset_diff), shift_speed * dt), offset_diff)

        # Vehicle-vehicle collision avoidance and emergency braking between NPCs and obstacles
        for i, npc in enumerate(self.npcs):
            if npc.crashed_timer > 0.0:
                continue

            blocked_by_npc = False

            # Check for leading NPC in close proximity (same direction or blocking path)
            for other in self._nearby_npcs(npc):
                if other is npc or other.layer != npc.layer:
                    continue

                dx = other.x - npc.x
                dy = other.y - npc.y
                dist = math.hypot(dx, dy)

                min_gap = (npc.length_m + other.length_m) * 0.5 + 2.0  # ~5-6 meters minimum distance
                if dist < 28.0:
                    angle_to_other = math.atan2(dy, dx)
                    angle_diff = abs((angle_to_other - npc.heading + math.pi) % (2 * math.pi) - math.pi)

                    # Other car is in the cone ahead (within 45 degrees)
                    if angle_diff < math.radians(45):
                        # Lateral offset relative to npc heading
                        lat_offset = abs(-math.sin(npc.heading) * dx + math.cos(npc.heading) * dy)
                        # Check if cars share the same corridor/lane laterally
                        if lat_offset < (npc.width_m + other.width_m) * 0.75:
                            if dist < min_gap:
                                # Emergency hard braking / yield
                                if npc.escape_timer <= 0.0:
                                    npc.speed = 0.0
                                blocked_by_npc = True
                            elif dist < min_gap + 10.0 and npc.speed > other.speed:
                                # Match or follow leader speed smoothly
                                target_follow_speed = max(0.0, other.speed * 0.9)
                                if npc.escape_timer <= 0.0:
                                    npc.speed = max(target_follow_speed, npc.speed - 16.0 * dt)
                                blocked_by_npc = True

            # Also check player car collision avoidance
            if player_car.layer == npc.layer:
                p_dx = player_car.x - npc.x
                p_dy = player_car.y - npc.y
                p_dist = math.hypot(p_dx, p_dy)
                min_p_gap = (npc.length_m + p_len) * 0.5 + 2.0

                if p_dist < 28.0:
                    angle_to_p = math.atan2(p_dy, p_dx)
                    angle_diff = abs((angle_to_p - npc.heading + math.pi) % (2 * math.pi) - math.pi)
                    if angle_diff < math.radians(45):
                        lat_p_offset = abs(-math.sin(npc.heading) * p_dx + math.cos(npc.heading) * p_dy)
                        if lat_p_offset < (npc.width_m + p_wid) * 0.75:
                            if p_dist < min_p_gap:
                                npc.speed = max(0.0, npc.speed - 22.0 * dt)
                            elif p_dist < min_p_gap + 10.0 and npc.speed > max(0.0, player_car.speed):
                                target_p_speed = max(0.0, player_car.speed * 0.9)
                                npc.speed = max(target_p_speed, npc.speed - 16.0 * dt)

            if blocked_by_npc and npc.speed < 1.0:
                npc.blocked_timer += dt
            else:
                npc.blocked_timer = max(0.0, npc.blocked_timer - dt * 0.5)

            if npc.blocked_timer >= 2.0 and npc.escape_timer <= 0.0:
                npc.escape_timer = 2.0
                npc.blocked_timer = 0.0
                npc.overtaking = True
                npc.overtake_timer = npc.escape_timer
                npc.target_lane_offset = compute_desired_lane_offset(
                    npc.way,
                    is_overtaking=getattr(npc.way, "oneway", 0) != 0,
                    travel_direction=npc.direction,
                )
                npc.speed = max(npc.speed, min(npc.target_speed, 4.0))

        # Check red traffic lights ahead and adjust speed
        for npc in self.npcs:
            must_stop = False
            junction_blocked = False
            nearest_light = None
            stop_distance = None
            heading_x = math.cos(npc.heading)
            heading_y = math.sin(npc.heading)
            for tl in self._nearby_traffic_lights(npc.x, npc.y):
                if tl.layer != npc.layer:
                    continue
                dx = tl.x - npc.x
                dy = tl.y - npc.y
                dist = math.hypot(dx, dy)
                # Traffic light ahead within 25m. Use longitudinal/lateral
                # distance so lane offset does not hide a nearby signal.
                longitudinal = dx * heading_x + dy * heading_y
                lateral = abs(dx * -heading_y + dy * heading_x)
                if -2.0 < longitudinal < 25.0 and lateral <= 8.0:
                        # If traffic light has orientation, check alignment with NPC heading
                        if tl.direction_angle is not None:
                            tl_ang = tl.direction_angle
                            npc_ang = npc.heading % math.pi
                            ang_err = abs(tl_ang - npc_ang)
                            ang_err = min(ang_err, math.pi - ang_err)
                            if ang_err > math.radians(45):
                                continue  # Signal is for cross traffic, skip

                        if nearest_light is None or longitudinal < nearest_light[0]:
                            nearest_light = (longitudinal, tl)

            if nearest_light is not None:
                state = nearest_light[1].get_state(self.sim_time)
                if state in ("red", "red+yellow", "yellow"):
                    stop_distance = nearest_light[0] - 1.5
                    nearest_crossing = None
                    for crossing in self._nearby_crossings(npc.x, npc.y):
                        if getattr(crossing, "layer", 0) != npc.layer:
                            continue
                        crossing_dx = crossing.x - npc.x
                        crossing_dy = crossing.y - npc.y
                        crossing_longitudinal = crossing_dx * heading_x + crossing_dy * heading_y
                        crossing_lateral = abs(crossing_dx * -heading_y + crossing_dy * heading_x)
                        if 0.0 < crossing_longitudinal < nearest_light[0] and crossing_lateral <= 8.0:
                            if nearest_crossing is None or crossing_longitudinal > nearest_crossing:
                                nearest_crossing = crossing_longitudinal
                    if nearest_crossing is not None:
                        stop_distance = nearest_crossing - 2.0
                    must_stop = stop_distance >= -1.0

            pts = npc.way.points_m
            target_pt = None
            if len(pts) >= 2:
                if npc.direction == 1 and npc.segment_idx + 1 < len(pts):
                    target_pt = pts[npc.segment_idx + 1]
                elif npc.direction == -1 and npc.segment_idx < len(pts):
                    target_pt = pts[npc.segment_idx]
            if target_pt is not None:
                junction_point = self._junction_at_point(target_pt, npc.layer)
                if junction_point is not None:
                    distance_to_junction = math.hypot(npc.x - junction_point[0], npc.y - junction_point[1])
                    junction_blocked = (
                        7.0 < distance_to_junction < 20.0
                        and self._junction_is_occupied(junction_point, npc)
                    )

            # Continue through the junction if the NPC has already entered it.
            if self._junction_near_point((npc.x, npc.y), npc.layer):
                must_stop = False

            # Calculate cornering speed limit based on heading angle to next vertex / sharp curves
            turn_limit_speed = npc.target_speed
            if target_pt is not None:
                to_x = target_pt[0] - npc.x
                to_y = target_pt[1] - npc.y
                d_to = math.hypot(to_x, to_y)
                if d_to > 0.5:
                    tgt_head = math.atan2(to_y, to_x)
                    angle_err = abs((tgt_head - npc.heading + math.pi) % (2 * math.pi) - math.pi)
                    # Steep turn (> 30 deg): scale allowable speed inversely with angle (down to 3.5-5.0 m/s for 90 deg turns)
                    if angle_err > math.radians(25):
                        turn_factor = max(0.25, math.cos(min(math.pi / 2, angle_err)))
                        turn_limit_speed = max(3.5, npc.target_speed * turn_factor)

            # Check if NPC is in crashed recovery state
            if npc.crashed_timer > 0.0:
                npc.crashed_timer = max(0.0, npc.crashed_timer - dt)
                npc.speed = 0.0
                continue

            if must_stop or junction_blocked:
                # Decelerate to stop at red light
                if must_stop and stop_distance is not None:
                    target_stop_speed = math.sqrt(2.0 * 15.0 * max(0.0, stop_distance))
                    if npc.speed > target_stop_speed:
                        npc.speed = max(target_stop_speed, npc.speed - 15.0 * dt)
                    else:
                        npc.speed = min(target_stop_speed, npc.speed + 8.0 * dt)
                    if stop_distance >= 0.0:
                        npc.speed = min(npc.speed, stop_distance / max(dt, 1e-6))
                    if npc.speed < 0.05:
                        npc.speed = 0.0
                else:
                    npc.speed = max(0.0, npc.speed - 15.0 * dt)
            else:
                desired_speed = min(npc.target_speed, turn_limit_speed)
                if npc.speed < desired_speed and not npc.overtaking:
                    # Accelerate towards desired speed if not blocked
                    npc.speed = min(desired_speed, npc.speed + 8.0 * dt)
                elif npc.speed > desired_speed:
                    # Brake for steep turn
                    npc.speed = max(desired_speed, npc.speed - 14.0 * dt)

        # Move each NPC along its way segments
        finished_npcs = set()
        for npc in self.npcs:
            if npc.speed <= 0.0:
                continue
            pts = npc.way.points_m
            if len(pts) < 2:
                continue

            dist_step = npc.speed * dt
            step_limit = 10  # Prevent infinite loop on degenerate/zero-length segments

            while dist_step > 0 and step_limit > 0:
                step_limit -= 1
                if npc.direction == 1:
                    target_pt = pts[npc.segment_idx + 1]
                    seg_start = pts[npc.segment_idx]
                else:
                    target_pt = pts[npc.segment_idx]
                    seg_start = pts[npc.segment_idx + 1]

                # Centerline vector and normal
                seg_dx = target_pt[0] - seg_start[0]
                seg_dy = target_pt[1] - seg_start[1]
                seg_len = math.hypot(seg_dx, seg_dy)

                if seg_len > 1e-3:
                    seg_dir_x = seg_dx / seg_len
                    seg_dir_y = seg_dy / seg_len
                    # Right perpendicular normal
                    norm_x = seg_dir_y
                    norm_y = -seg_dir_x
                else:
                    seg_dir_x, seg_dir_y = 1.0, 0.0
                    norm_x, norm_y = 0.0, 1.0

                # Target point adjusted with lateral lane offset
                shifted_target_x = target_pt[0] + norm_x * npc.lane_offset
                shifted_target_y = target_pt[1] + norm_y * npc.lane_offset

                to_tgt_x = shifted_target_x - npc.x
                to_tgt_y = shifted_target_y - npc.y
                dist_to_tgt = math.hypot(to_tgt_x, to_tgt_y)

                    # Smooth heading towards target vertex with angular rate limiting
                if dist_to_tgt > 1e-3:
                    target_heading = math.atan2(to_tgt_y, to_tgt_x)
                    heading_diff = (target_heading - npc.heading + math.pi) % (2 * math.pi) - math.pi
                    # Limit turn rate so junction turns are visibly gradual.
                    max_turn = 1.8 * dt
                    if abs(heading_diff) <= max_turn:
                        npc.heading = target_heading
                    else:
                        npc.heading += math.copysign(max_turn, heading_diff)
                    if npc.turn_signal and abs(heading_diff) < 0.12:
                        npc.turn_signal = ""

                if dist_step < dist_to_tgt:
                    # Advance partially along current segment
                    ratio = dist_step / dist_to_tgt
                    npc.x += to_tgt_x * ratio
                    npc.y += to_tgt_y * ratio
                    dist_step = 0.0
                else:
                    # Reach the vertex
                    npc.x = shifted_target_x
                    npc.y = shifted_target_y
                    dist_step -= dist_to_tgt

                    # Advance to next segment or next connected way
                    if npc.direction == 1:
                        # At intermediate vertices, check if there is an intersecting road to turn onto
                        turned = False
                        if npc.segment_idx + 1 < len(pts) - 1:
                            # 35% chance to make a turn at an intersection along the way
                            if random.random() < 0.35:
                                turn_route = self._find_next_way_and_segment(
                                    npc.way, target_pt, exclude_reverse=True, incoming_heading=npc.heading
                                )
                                if turn_route and turn_route[0] is not npc.way:
                                    old_heading = npc.heading
                                    npc.way, npc.segment_idx, npc.direction = turn_route
                                    npc.turn_signal = self._turn_signal_for_route(old_heading, npc)
                                    npc.turn_signal_elapsed = 0.0
                                    npc.layer = getattr(npc.way, "layer", 0)
                                    npc.target_speed = calculate_npc_target_speed(npc.way, npc.speed_factor)
                                    npc.target_lane_offset = compute_desired_lane_offset(
                                        npc.way, npc.overtaking, npc.direction
                                    )
                                    pts = npc.way.points_m
                                    turned = True
                            if not turned:
                                npc.segment_idx += 1
                        else:
                            # Reached end of way, find connecting road
                            next_route = self._find_next_way_and_segment(
                                npc.way, target_pt, incoming_heading=npc.heading
                            )
                            if next_route:
                                old_heading = npc.heading
                                npc.way, npc.segment_idx, npc.direction = next_route
                                npc.turn_signal = self._turn_signal_for_route(old_heading, npc)
                                npc.turn_signal_elapsed = 0.0
                                npc.layer = getattr(npc.way, "layer", 0)
                                npc.target_speed = calculate_npc_target_speed(npc.way, npc.speed_factor)
                                npc.target_lane_offset = compute_desired_lane_offset(
                                    npc.way, npc.overtaking, npc.direction
                                )
                                pts = npc.way.points_m
                            else:
                                # Reverse on two-way or loop (dead end)
                                if getattr(npc.way, "oneway", 0) == 0:
                                    npc.direction = -1
                                    npc.segment_idx = len(pts) - 2
                                    npc.target_speed = calculate_npc_target_speed(npc.way, npc.speed_factor)
                                    npc.target_lane_offset = compute_desired_lane_offset(
                                        npc.way, npc.overtaking, npc.direction
                                    )
                                else:
                                    dist_step = 0.0
                                    finished_npcs.add(id(npc))
                                    break
                    else:
                        turned = False
                        if npc.segment_idx > 0:
                            if random.random() < 0.35:
                                turn_route = self._find_next_way_and_segment(
                                    npc.way, target_pt, exclude_reverse=True, incoming_heading=npc.heading
                                )
                                if turn_route and turn_route[0] is not npc.way:
                                    old_heading = npc.heading
                                    npc.way, npc.segment_idx, npc.direction = turn_route
                                    npc.turn_signal = self._turn_signal_for_route(old_heading, npc)
                                    npc.turn_signal_elapsed = 0.0
                                    npc.layer = getattr(npc.way, "layer", 0)
                                    npc.target_speed = calculate_npc_target_speed(npc.way, npc.speed_factor)
                                    npc.target_lane_offset = compute_desired_lane_offset(
                                        npc.way, npc.overtaking, npc.direction
                                    )
                                    pts = npc.way.points_m
                                    turned = True
                            if not turned:
                                npc.segment_idx -= 1
                        else:
                            # Reached start of way in reverse
                            next_route = self._find_next_way_and_segment(
                                npc.way, target_pt, incoming_heading=npc.heading
                            )
                            if next_route:
                                old_heading = npc.heading
                                npc.way, npc.segment_idx, npc.direction = next_route
                                npc.turn_signal = self._turn_signal_for_route(old_heading, npc)
                                npc.turn_signal_elapsed = 0.0
                                npc.layer = getattr(npc.way, "layer", 0)
                                npc.target_speed = calculate_npc_target_speed(npc.way, npc.speed_factor)
                                npc.target_lane_offset = compute_desired_lane_offset(
                                    npc.way, npc.overtaking, npc.direction
                                )
                                pts = npc.way.points_m
                            else:
                                if getattr(npc.way, "oneway", 0) == 0:
                                    npc.direction = 1
                                    npc.segment_idx = 0
                                    npc.target_speed = calculate_npc_target_speed(npc.way, npc.speed_factor)
                                    npc.target_lane_offset = compute_desired_lane_offset(
                                        npc.way, npc.overtaking, npc.direction
                                    )
                                else:
                                    dist_step = 0.0
                                    finished_npcs.add(id(npc))
                                    break

        if finished_npcs:
            self.npcs = [npc for npc in self.npcs if id(npc) not in finished_npcs]
        self._resolve_npc_collisions()
