"""Explicit arcade exception: move NPC vehicles off the taxi's forward road."""
import math

from .geo import closest_point_and_dist_to_segment
from .map_level import on_map_level
from .physics import is_car_road

RAGE_SECONDS = 10.0


def corridor(car, current_way, ways, grid):
    """Follow the road's bends and straightest connected continuation, bounded.
    Each segment carries its own bridge layer; crossing roads are not connected
    merely because they cross in the middle of a segment.
    """
    distance = max(60.0, abs(car.speed) * RAGE_SECONDS) + car.length_m + 10.0
    forward = math.cos(car.heading), math.sin(car.heading)
    if current_way is None or len(current_way.points_m) < 2:
        return [(car.x, car.y, car.x + forward[0] * distance, car.y + forward[1] * distance,
                 max(3.0, car.width_m), car.layer)]
    way = current_way
    points = way.points_m
    index = min(range(len(points) - 1), key=lambda i: closest_point_and_dist_to_segment(
        car.x, car.y, *points[i], *points[i + 1])[3])
    x, y, _, _ = closest_point_and_dist_to_segment(car.x, car.y, *points[index], *points[index + 1])
    direction = 1 if ((points[index + 1][0] - points[index][0]) * forward[0]
                      + (points[index + 1][1] - points[index][1]) * forward[1]) >= 0 else -1
    target = index + 1 if direction == 1 else index
    segments, visited = [], set()
    for _ in range(4096):
        end = way.points_m[target]
        dx, dy = end[0] - x, end[1] - y
        length = math.hypot(dx, dy)
        if length > 1e-6:
            forward = dx / length, dy / length
            step = min(distance, length)
            nx, ny = x + forward[0] * step, y + forward[1] * step
            segments.append((x, y, nx, ny, max(way.half_width_m, 3.0), way.layer))
            distance -= step
            x, y = nx, ny
            if distance <= 0:
                break
        target += direction
        if 0 <= target < len(way.points_m):
            continue
        visited.add(id(way))
        candidates = grid.ways_in_rect(x - 3, y - 3, x + 3, y + 3) if grid is not None else ways
        choices = []
        for other in candidates:
            if id(other) in visited or not is_car_road(other) or not on_map_level(other, car.map_level):
                continue
            for sign, at, next_at in ((1, 0, 1), (-1, len(other.points_m) - 1, len(other.points_m) - 2)):
                if len(other.points_m) < 2 or math.dist((x, y), other.points_m[at]) > 3.0:
                    continue
                a, b = other.points_m[at], other.points_m[next_at]
                size = math.dist(a, b)
                if size > 1e-6:
                    alignment = ((b[0] - a[0]) * forward[0] + (b[1] - a[1]) * forward[1]) / size
                    if alignment > 0.0:
                        choices.append((alignment, other, sign, next_at))
        if not choices:
            break
        _, way, direction, target = max(choices, key=lambda item: item[0])
    return segments


def _hit(x, y, radius, layer, segments):
    for segment in segments:
        ax, ay, bx, by, width, road_layer = segment
        if road_layer != layer:
            continue
        cx, cy, t, gap = closest_point_and_dist_to_segment(x, y, ax, ay, bx, by)
        if gap <= width + radius and (t > 0 or (x - ax) * (bx - ax) + (y - ay) * (by - ay) >= 0):
            return segment, cx, cy
    return None


class RoadRageClearance:
    def __init__(self):
        self.until = float("-inf")
        self.held = {}  # vehicle id -> (vehicle, original x/y, state)

    def activate(self, now):
        self.until = max(self.until, now + RAGE_SECONDS)

    def update(self, manager, car, now, ways, grid, current_way):
        active = now < self.until
        if not active and not self.held:
            return
        manager.rebuild_spatial_grid()  # include vehicles appended by late route-job completions
        segments = corridor(car, current_way, ways, grid)
        max_radius = max((math.hypot(v.length_m, v.width_m) * 0.5 for v in manager.vehicles), default=0)
        live = {v.vehicle_id for v in manager.vehicles}
        for vid, (vehicle, x, y, state) in list(self.held.items()):
            if vid not in live:
                del self.held[vid]
                continue
            radius = math.hypot(vehicle.length_m, vehicle.width_m) * 0.5
            if active or math.hypot(x - car.x, y - car.y) < max(40.0, abs(car.speed) * 2.0):
                continue
            if _hit(x, y, radius, vehicle.layer, segments):
                continue
            if any(v is not vehicle and v.layer == vehicle.layer and v.car.map_level == vehicle.car.map_level
                   and math.hypot(v.x - x, v.y - y) < radius + math.hypot(v.length_m, v.width_m) * 0.5 + 2
                   for v in manager.nearby_vehicles_at(x, y, radius + max_radius + 2)):
                continue
            vehicle.car.x, vehicle.car.y, vehicle.state = x, y, state
            vehicle.debug_waiting_for = ""
            del self.held[vid]
            manager.rebuild_spatial_grid()
        if not active:
            return
        # The existing NPC population is bounded. No buildings/residents scan,
        # pathfinding job, steering controller or traffic-rule decision here.
        for vehicle in manager.vehicles:
            if vehicle.vehicle_id in self.held or vehicle.car.map_level != car.map_level:
                continue
            radius = math.hypot(vehicle.length_m, vehicle.width_m) * 0.5
            hit = _hit(vehicle.x, vehicle.y, radius, vehicle.layer, segments)
            if hit is None:
                continue
            segment, cx, cy = hit
            ax, ay, bx, by, width, _ = segment
            length = math.hypot(bx - ax, by - ay)
            rx, ry = (by - ay) / length, -(bx - ax) / length
            side = 1 if (vehicle.x - cx) * rx + (vehicle.y - cy) * ry >= 0 else -1
            offset = width + radius + car.width_m + 3.0
            for _ in range(len(manager.vehicles) + 2):
                x, y = cx + rx * side * offset, cy + ry * side * offset
                if _hit(x, y, radius + 2, vehicle.layer, segments):
                    offset = max(abs((px - cx) * rx + (py - cy) * ry) + w
                                 for a, b, c, d, w, _ in segments for px, py in ((a, b), (c, d))) + radius + 4
                    continue
                if any(v is not vehicle and v.layer == vehicle.layer and v.car.map_level == vehicle.car.map_level
                       and math.hypot(v.x - x, v.y - y) < radius + math.hypot(v.length_m, v.width_m) * 0.5 + 2
                       for v in manager.nearby_vehicles_at(x, y, radius + max_radius + 2)):
                    offset += 2 * (radius + max_radius) + 2
                    continue
                self.held[vehicle.vehicle_id] = vehicle, vehicle.x, vehicle.y, vehicle.state
                vehicle.car.x, vehicle.car.y, vehicle.car.speed = x, y, 0.0
                vehicle.debug_waiting_for = "road rage: arcade clearance"
                manager.rebuild_spatial_grid()
                break
