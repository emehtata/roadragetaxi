import logging
import math
import random
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .osm import TrafficLight, Way
from .physics import Car, compute_largest_connected_road_component, is_car_road

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


def calculate_npc_target_speed(way: Way, speed_factor: float) -> float:
    """Compute realistic driving target speed in m/s based on Finnish road limit and vehicle personality."""
    limit_kmh = getattr(way, "speed_limit_kmh", 50)
    # Target speed = speed limit * speed_factor (m/s)
    base_mps = (limit_kmh / 3.6) * speed_factor
    return max(4.0, base_mps)


def compute_desired_lane_offset(way: Way, is_overtaking: bool = False) -> float:
    """Calculate lateral lane offset (meters) to keep right or pass on multi-lane roads."""
    half_w = getattr(way, "half_width_m", 4.0)
    oneway = getattr(way, "oneway", 0)

    # On two-way roads (oneway == 0), right side is half_w * 0.45
    # If overtaking on two-way or multi-lane, move towards left/center
    if oneway == 0:
        base_offset = max(1.2, half_w * 0.45)
        if is_overtaking:
            return -base_offset * 0.7  # Passing lane in oncoming / middle
        return base_offset
    else:
        # On wide one-way roads (e.g. half_w >= 5.0m), default to right lane, overtake on left
        if half_w >= 5.0:
            right_lane = half_w * 0.5
            left_lane = -half_w * 0.5
            return left_lane if is_overtaking else right_lane
        return 0.0


class TrafficManager:
    """Manages autonomous NPC traffic simulation around the player."""

    def __init__(
        self,
        ways: List[Way],
        target_count: int = 15,
        spawn_radius_m: float = 300.0,
        despawn_radius_m: float = 450.0,
        traffic_lights: Optional[List[TrafficLight]] = None,
    ):
        connected_ways = compute_largest_connected_road_component(ways) if ways else []
        self.ways = [w for w in connected_ways if is_car_road(w) and len(w.points_m) >= 2]
        if not self.ways and ways:
            self.ways = [w for w in ways if is_car_road(w) and len(w.points_m) >= 2]
        self.target_count = target_count
        self.spawn_radius_m = spawn_radius_m
        self.despawn_radius_m = despawn_radius_m
        self.min_spawn_dist_to_player_m: float = 12.0
        self.min_spawn_dist_to_npc_m: float = 6.0
        self.traffic_lights = traffic_lights if traffic_lights is not None else []
        self.npcs: List[NPCCar] = []
        self._log_timer: float = 0.0
        self.sim_time: float = 0.0
        self._junction_grid_cell_size: float = 60.0
        self._junction_grid: dict = {}
        self._way_grid_cell_size: float = 200.0
        self._way_grid: dict = {}
        self._build_spatial_indices()

    def _build_spatial_indices(self) -> None:
        """Build spatial index for instant junction lookups and spawning."""
        self._junction_grid.clear()
        self._way_grid.clear()
        j_cs = self._junction_grid_cell_size
        w_cs = self._way_grid_cell_size

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

    def sync_map_data(self, ways: List[Way], traffic_lights: Optional[List[TrafficLight]] = None) -> None:
        """Update road references when dynamic tiles expand."""
        connected_ways = compute_largest_connected_road_component(ways) if ways else []
        self.ways = [w for w in connected_ways if is_car_road(w) and len(w.points_m) >= 2]
        if not self.ways and ways:
            self.ways = [w for w in ways if is_car_road(w) and len(w.points_m) >= 2]
        if traffic_lights is not None:
            self.traffic_lights = traffic_lights
        self._build_spatial_indices()

    def _find_next_way_and_segment(
        self,
        current_way: Way,
        at_point: Tuple[float, float],
        exclude_reverse: bool = False,
        incoming_heading: Optional[float] = None,
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
                    if layer != current_layer:
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

                    lane_offset = compute_desired_lane_offset(chosen_way, is_overtaking=False)

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

                    # Sanity check: do not spawn right on top of player
                    dist_to_player = math.hypot(x - near_x, y - near_y)
                    if dist_to_player < self.min_spawn_dist_to_player_m:
                        continue

                    # Sanity check: do not spawn too close to existing NPC cars on same layer
                    too_close_to_npc = False
                    for existing_npc in self.npcs:
                        if existing_npc.layer == layer:
                            if math.hypot(x - existing_npc.x, y - existing_npc.y) < self.min_spawn_dist_to_npc_m:
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
                    )
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
        max_attempts = max(50, self.target_count * 5)
        while len(self.npcs) < self.target_count and attempts < max_attempts:
            attempts += 1
            npc = self.spawn_npc(player_car.x, player_car.y, viewport_bounds=viewport_bounds)
            if not npc and viewport_bounds:
                # Fallback without strict viewport boundary if road network is very sparse
                npc = self.spawn_npc(player_car.x, player_car.y, viewport_bounds=None)
            if not npc:
                break

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
            if npc.overtaking:
                npc.overtake_timer -= dt
                if npc.overtake_timer <= 0:
                    npc.overtaking = False
                    npc.target_lane_offset = compute_desired_lane_offset(npc.way, is_overtaking=False)
            else:
                # Check if there is a slower car or player car ahead in same lane
                car_ahead = False
                # Check against other NPCs
                for j, other in enumerate(self.npcs):
                    if i == j or other.layer != npc.layer:
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
                    npc.overtaking = True
                    npc.overtake_timer = random.uniform(3.0, 6.0)
                    npc.target_lane_offset = compute_desired_lane_offset(npc.way, is_overtaking=True)

            # Smoothly interpolate lane_offset towards target_lane_offset
            offset_diff = npc.target_lane_offset - npc.lane_offset
            if abs(offset_diff) > 0.01:
                shift_speed = 3.0  # meters per second lateral shift
                npc.lane_offset += math.copysign(min(abs(offset_diff), shift_speed * dt), offset_diff)

        # Vehicle-vehicle collision avoidance and emergency braking between NPCs and obstacles
        for i, npc in enumerate(self.npcs):
            if npc.crashed_timer > 0.0:
                continue

            # Check for leading NPC in close proximity (same direction or blocking path)
            for j, other in enumerate(self.npcs):
                if i == j or other.layer != npc.layer:
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
                                npc.speed = max(0.0, npc.speed - 22.0 * dt)
                            elif dist < min_gap + 10.0 and npc.speed > other.speed:
                                # Match or follow leader speed smoothly
                                target_follow_speed = max(0.0, other.speed * 0.9)
                                npc.speed = max(target_follow_speed, npc.speed - 16.0 * dt)

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

        # Check red traffic lights ahead and adjust speed
        for npc in self.npcs:
            must_stop = False
            for tl in self.traffic_lights:
                if tl.layer != npc.layer:
                    continue
                dx = tl.x - npc.x
                dy = tl.y - npc.y
                dist = math.hypot(dx, dy)
                # Traffic light ahead within 25m
                if 2.0 < dist < 25.0:
                    angle_to_tl = math.atan2(dy, dx)
                    angle_diff = (angle_to_tl - npc.heading + math.pi) % (2 * math.pi) - math.pi
                    if abs(angle_diff) < 0.7:  # Directly ahead
                        # If traffic light has orientation, check alignment with NPC heading
                        if tl.direction_angle is not None:
                            tl_ang = tl.direction_angle
                            npc_ang = npc.heading % math.pi
                            ang_err = abs(tl_ang - npc_ang)
                            ang_err = min(ang_err, math.pi - ang_err)
                            if ang_err > math.radians(45):
                                continue  # Signal is for cross traffic, skip

                        state = tl.get_state(self.sim_time)
                        if state in ("red", "red+yellow", "yellow"):
                            must_stop = True
                            break

            # Calculate cornering speed limit based on heading angle to next vertex / sharp curves
            pts = npc.way.points_m
            target_pt = None
            if len(pts) >= 2:
                if npc.direction == 1 and npc.segment_idx + 1 < len(pts):
                    target_pt = pts[npc.segment_idx + 1]
                elif npc.direction == -1 and npc.segment_idx < len(pts):
                    target_pt = pts[npc.segment_idx]

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

            if must_stop:
                # Decelerate to stop at red light
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
                    # Allow max turn rate (e.g., 4.5 rad/s ~ 260 deg/s) so turns are gradual
                    max_turn = 4.5 * dt
                    if abs(heading_diff) <= max_turn:
                        npc.heading = target_heading
                    else:
                        npc.heading += math.copysign(max_turn, heading_diff)

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
                                    npc.way, npc.segment_idx, npc.direction = turn_route
                                    npc.layer = getattr(npc.way, "layer", 0)
                                    npc.target_speed = calculate_npc_target_speed(npc.way, npc.speed_factor)
                                    npc.target_lane_offset = compute_desired_lane_offset(npc.way, npc.overtaking)
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
                                npc.way, npc.segment_idx, npc.direction = next_route
                                npc.layer = getattr(npc.way, "layer", 0)
                                npc.target_speed = calculate_npc_target_speed(npc.way, npc.speed_factor)
                                npc.target_lane_offset = compute_desired_lane_offset(npc.way, npc.overtaking)
                                pts = npc.way.points_m
                            else:
                                # Reverse on two-way or loop (dead end)
                                if getattr(npc.way, "oneway", 0) == 0:
                                    npc.direction = -1
                                    npc.segment_idx = len(pts) - 2
                                    npc.target_speed = calculate_npc_target_speed(npc.way, npc.speed_factor)
                                    npc.target_lane_offset = compute_desired_lane_offset(npc.way, npc.overtaking)
                                else:
                                    dist_step = 0.0
                                    break
                    else:
                        turned = False
                        if npc.segment_idx > 0:
                            if random.random() < 0.35:
                                turn_route = self._find_next_way_and_segment(
                                    npc.way, target_pt, exclude_reverse=True, incoming_heading=npc.heading
                                )
                                if turn_route and turn_route[0] is not npc.way:
                                    npc.way, npc.segment_idx, npc.direction = turn_route
                                    npc.layer = getattr(npc.way, "layer", 0)
                                    npc.target_speed = calculate_npc_target_speed(npc.way, npc.speed_factor)
                                    npc.target_lane_offset = compute_desired_lane_offset(npc.way, npc.overtaking)
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
                                npc.way, npc.segment_idx, npc.direction = next_route
                                npc.layer = getattr(npc.way, "layer", 0)
                                npc.target_speed = calculate_npc_target_speed(npc.way, npc.speed_factor)
                                npc.target_lane_offset = compute_desired_lane_offset(npc.way, npc.overtaking)
                                pts = npc.way.points_m
                            else:
                                if getattr(npc.way, "oneway", 0) == 0:
                                    npc.direction = 1
                                    npc.segment_idx = 0
                                    npc.target_speed = calculate_npc_target_speed(npc.way, npc.speed_factor)
                                    npc.target_lane_offset = compute_desired_lane_offset(npc.way, npc.overtaking)
                                else:
                                    dist_step = 0.0
                                    break
