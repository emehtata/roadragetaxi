"""Ilokapina: bounded group events, not a second pedestrian population.

The sit-in and rage response are explicit arcade policy. Vehicles still stop
for the obstruction; ordinary movement never pushes people out of the way.
"""
from dataclasses import dataclass
import hashlib
import math
import random

from .geo import dist_point_to_segment, point_in_polygon
from .nightlife import parse_opening_hours


@dataclass
class ProtestSettings:
    enabled: bool = True
    max_groups: int = 2
    group_size: int = 24
    schedule: str = "Mo-Su 10:00-20:00"
    intimidation_radius_m: float = 100.0
    clearing_s: float = 3.0
    return_delay_s: float = 30.0
    lifetime_s: float = 1200.0
    spawn_interval_s: float = 30.0
    spawn_probability: float = 0.4
    seed: int = 19

    @classmethod
    def from_config(cls, config):
        defaults = cls()
        values = {}
        for name in cls.__dataclass_fields__:
            default = getattr(defaults, name)
            getter = config.getboolean if isinstance(default, bool) else config.getint if isinstance(default, int) else config.getfloat if isinstance(default, float) else config.get
            values[name] = getter("protests", name, fallback=default)
        values["max_groups"] = max(0, min(8, values["max_groups"]))
        values["group_size"] = max(8, min(80, values["group_size"]))
        for name in ("clearing_s", "return_delay_s", "lifetime_s", "spawn_interval_s"):
            values[name] = max(1.0, min(86400.0, values[name]))
        values["intimidation_radius_m"] = max(5.0, min(500.0, values["intimidation_radius_m"]))
        values["spawn_probability"] = max(0.0, min(1.0, values["spawn_probability"]))
        return cls(**values)


@dataclass
class ProtestGroup:
    id: int
    way: object
    x: float
    y: float
    heading: float
    size: int
    created: float
    state: str = "SITTING"
    elapsed: float = 0.0
    progress: float = 0.0  # 0 roadway, 1 roadside

    def members(self, progress=None):
        p = self.progress if progress is None else progress
        width = self.way.half_width_m
        columns = max(4, math.ceil(self.size / 3))
        ux, uy = math.cos(self.heading), math.sin(self.heading)
        for i in range(self.size):
            col, row = i % columns, i // columns
            across = -width + 0.6 + col * (2 * width - 1.2) / (columns - 1)
            side = -1 if col < columns / 2 else 1
            edge = side * (width + 2.0 + row * 0.8)
            lateral = across + (edge - across) * p
            along = (row - 1) * 1.5 + math.sin(i * 13.7) * 0.2
            # Spread each half along the shoulder instead of stacking people.
            along += p * (col % math.ceil(columns / 2) - columns / 4) * 1.1
            yield self.x + ux * along - uy * lateral, self.y + uy * along + ux * lateral

    @property
    def blocking(self):
        return self.state != "CLEARED"


class ProtestManager:
    def __init__(self, settings=None, city=""):
        self.settings = settings or ProtestSettings()
        self.city = city
        seed = int.from_bytes(hashlib.sha256(city.encode()).digest()[:8], "little") + self.settings.seed
        self.rng = random.Random(seed)
        self.groups = []
        self._next_spawn = 0.0
        self._next_id = 1
        self._cleanup_at = 0.0
        self._schedule = parse_opening_hours(self.settings.schedule) or []

    def scheduled(self, now):
        if now is None:
            return False
        minute = now.weekday() * 1440 + now.hour * 60 + now.minute
        return any(start <= minute + shift < end for start, end in self._schedule for shift in (0, 10080))

    def can_spawn(self, world, way, x, y, heading, car):
        if (not way.is_drivable or way.highway not in {"primary", "secondary", "tertiary", "residential", "unclassified"}
                or getattr(way, "layer", 0) != 0 or getattr(way, "map_level", None) not in (None, 0)
                or getattr(way, "is_bridge", False) or getattr(way, "is_tunnel", False)
                or getattr(way, "is_roundabout", False)
                or way.speed_limit_kmh > 60 or not 2.5 <= way.half_width_m <= 8.0):
            return False
        if not 120 <= math.hypot(x - car.x, y - car.y) <= 650 or any(math.hypot(x-g.x, y-g.y) < 300 for g in self.groups):
            return False
        grid = getattr(world, "spatial_grid", None)
        nearby = grid.ways_in_rect(x-40, y-40, x+40, y+40) if grid else world.ways
        for other in nearby:
            if other is way or not other.is_drivable or getattr(other, "layer", 0) != 0 or getattr(other, "map_level", None) not in (None, 0):
                continue
            if any(dist_point_to_segment(x, y, *a, *b) < 25 for a, b in zip(other.points_m, other.points_m[1:])):
                return False
        if any(work.contains(x, y, margin_m=12) for work in getattr(world, "roadworks", ())):
            return False
        if any(math.hypot(obj.x-x, obj.y-y) < 25 for attr in ("crossings", "traffic_lights", "bus_stops", "taxi_stops")
               for obj in getattr(world, attr, ())):
            return False
        group = ProtestGroup(0, way, x, y, heading, self.settings.group_size, 0)
        # Spawn-time only; use local spatial indexes, never scan buildings per tick.
        checks = [(x, y), *group.members(), *group.members(1.0)]
        for attr, features in (("building_grid", "buildings"), ("water_grid", "waters")):
            index = getattr(world, attr, None)
            candidates = list(index.ways_in_rect(x-20, y-20, x+20, y+20)) if index else getattr(world, features, ())
            if any(point_in_polygon(px, py, obj.points_m) for obj in candidates for px, py in checks):
                return False
        railway_grid = getattr(world, "railway_grid", None)
        rails = railway_grid.ways_in_rect(x-20, y-20, x+20, y+20) if railway_grid else getattr(world, "railways", ())
        for rail in rails:
            if getattr(rail, "layer", 0) == 0 and any(dist_point_to_segment(px, py, *a, *b) < 3 for a, b in zip(rail.points_m, rail.points_m[1:]) for px, py in checks):
                return False
        cars = [car] + [v.car for v in getattr(world.npc_manager, "vehicles", ())]
        if any(math.hypot(v.x-x, v.y-y) < 20 + abs(v.speed)*4 for v in cars):
            return False
        if any(math.hypot(p.x-x, p.y-y) < 20 for p in getattr(world.pedestrian_mgr, "pedestrians", ())):
            return False
        return True

    def spawn(self, world, car, sim_time):
        from .roadworks import _point_at, _way_length
        grid = getattr(world, "spatial_grid", None)
        ways = list(grid.ways_in_rect(car.x-650, car.y-650, car.x+650, car.y+650)) if grid else list(world.ways)
        ways.sort(key=lambda w: (getattr(w, "osm_id", 0) or 0, w.points_m[0]))
        self.rng.shuffle(ways)
        for way in ways[:40]:
            length = _way_length(way)
            if length < 100:
                continue
            a, b = _point_at(way, length/2-10), _point_at(way, length/2+10)
            if math.dist(a, b) < 19.5:  # no sharp bends through the crowd
                continue
            x, y = _point_at(way, length/2)
            heading = math.atan2(b[1]-a[1], b[0]-a[0])
            if self.can_spawn(world, way, x, y, heading, car):
                self.groups.append(ProtestGroup(self._next_id, way, x, y, heading, self.settings.group_size, sim_time))
                self._next_id += 1
                return

    def intimidate(self, car):
        for group in self.groups:
            if (group.state in {"SITTING", "RETURNING"} and getattr(car, "map_level", 0) == 0
                    and getattr(car, "layer", 0) == 0 and math.hypot(car.x-group.x, car.y-group.y) <= self.settings.intimidation_radius_m):
                group.state, group.elapsed = "ALARMED", 0.0

    def update(self, dt, world, car, now, sim_time):
        # Keep a protest when the player leaves; remove only expired/unloaded events.
        self.groups[:] = [g for g in self.groups if sim_time-g.created < self.settings.lifetime_s]
        if self.groups and sim_time >= self._cleanup_at:
            self._cleanup_at = sim_time + 5.0
            grid = getattr(world, "spatial_grid", None)
            self.groups[:] = [g for g in self.groups if any(w is g.way for w in
                (grid.ways_in_rect(g.x-1, g.y-1, g.x+1, g.y+1) if grid else world.ways))]
        for group in self.groups:
            group.elapsed += dt
            if group.state == "ALARMED" and group.elapsed >= 0.8:
                targets = list(group.members(1.0))
                occupied = any(math.hypot(p.x-x, p.y-y) < 1.0 for p in getattr(world.pedestrian_mgr, "pedestrians", ()) for x, y in targets)
                if not occupied:
                    group.state, group.elapsed = "CLEARING", 0.0
            elif group.state == "CLEARING":
                group.progress = min(1.0, group.progress + dt/self.settings.clearing_s)
                if group.progress >= 1.0:
                    group.state, group.elapsed = "CLEARED", 0.0
            elif group.state in {"CLEARED", "RETURNING"}:
                cars = [car] + [v.car for v in world.npc_manager.vehicles]
                unsafe = any(getattr(v, "map_level", 0) == 0 and getattr(v, "layer", 0) == 0
                             and math.hypot(v.x-group.x, v.y-group.y) < 35 + abs(v.speed)*(self.settings.clearing_s+2) for v in cars)
                unsafe |= any(math.hypot(p.x-group.x, p.y-group.y) < 15 for p in getattr(world.pedestrian_mgr, "pedestrians", ()))
                if group.state == "CLEARED" and group.elapsed >= self.settings.return_delay_s and not unsafe:
                    group.state, group.elapsed = "RETURNING", 0.0
                elif group.state == "RETURNING":
                    if unsafe:
                        group.state, group.elapsed = "CLEARING", 0.0
                    else:
                        group.progress = max(0.0, group.progress-dt/self.settings.clearing_s)
                        if group.progress <= 0:
                            group.state, group.elapsed = "SITTING", 0.0
        if self.settings.enabled and self.scheduled(now) and sim_time >= self._next_spawn:
            self._next_spawn = sim_time + self.settings.spawn_interval_s
            probability = self.settings.spawn_probability * (1.25 if now.weekday() >= 5 else 1.0)
            if len(self.groups) < self.settings.max_groups and self.rng.random() < probability:
                self.spawn(world, car, sim_time)

    def blocks_movement(self, car, previous):
        if getattr(car, "map_level", 0) != 0 or getattr(car, "layer", 0) != 0:
            return False
        diameter = getattr(car, "radius_m", 0.45)*2
        radius = math.hypot(getattr(car, "length_m", diameter), getattr(car, "width_m", diameter))/2
        for group in self.groups:
            if not group.blocking:
                continue
            ux, uy = math.cos(group.heading), math.sin(group.heading)
            def local(x, y):
                return (x-group.x)*ux+(y-group.y)*uy, -(x-group.x)*uy+(y-group.y)*ux
            a, b = local(*previous[:2]), local(car.x, car.y)
            limits = (3.0+radius, group.way.half_width_m+radius)
            enter, leave = 0.0, 1.0
            for axis in (0, 1):
                delta = b[axis]-a[axis]
                if abs(delta) < 1e-9:
                    if abs(a[axis]) > limits[axis]:
                        enter, leave = 1.0, 0.0
                        break
                else:
                    low, high = sorted(((-limits[axis]-a[axis])/delta, (limits[axis]-a[axis])/delta))
                    enter, leave = max(enter, low), min(leave, high)
            if enter <= leave:
                return True
        return False

    def speed_cap(self, car):
        cap = None
        if getattr(car, "map_level", 0) != 0 or getattr(car, "layer", 0) != 0:
            return cap
        for group in self.groups:
            if not group.blocking:
                continue
            dx, dy = group.x-car.x, group.y-car.y
            forward = dx*math.cos(car.heading)+dy*math.sin(car.heading)
            lateral = abs(-dx*math.sin(car.heading)+dy*math.cos(car.heading))
            if 0 <= forward <= 150 and lateral < group.way.half_width_m + 2:
                value = math.sqrt(2*1.8*max(0, forward-6-getattr(car, "length_m", 4)/2))
                cap = value if cap is None else min(cap, value)
        return cap

    def snapshot(self, camx, camy):
        return [{"id": g.id, "x": g.x, "y": g.y, "state": g.state,
                 "heading": g.heading, "progress": round(g.progress, 3),
                 "members": [[round(x, 2), round(y, 2)] for x, y in g.members()]}
                for g in self.groups if math.hypot(g.x-camx, g.y-camy) < 800]

    def block_walkers(self, people, previous):
        for person in people:
            start = previous.get(id(person))
            if start is not None and self.blocks_movement(person, start):
                person.x, person.y = start
                person.speed = 0.0
