"""Server-authoritative tee shots, approaches and putts on an OSM golf hole."""
from __future__ import annotations

import bisect
import math
import random

from ...geo import closest_point_and_dist_to_segment, point_in_polygon
from ...viewport import in_bounds
from ..base import ActivityDefinition, ActivityInstance, ActivityLocation, ActivityPlugin

GOLF_ACTIVITIES = ("golf", "miniature_golf")
SEARCH_RADIUS_M = 120.0
PREPARE_S = 2.0
SWING_S = 0.7
STANCE_M = 0.8


def point_along(points, distances, distance):
    segment = min(bisect.bisect_right(distances, distance), len(points) - 1)
    start, end = points[segment - 1], points[segment]
    length = distances[segment] - distances[segment - 1]
    t = (distance - distances[segment - 1]) / length if length else 1.0
    return start[0] + (end[0] - start[0]) * t, start[1] + (end[1] - start[1]) * t


class GolfPlugin(ActivityPlugin):
    course_kind = "golf_course"
    putting_only = False
    # shortcut: one hole per activity, add ordered rounds when multi-hole play is needed.
    definition = ActivityDefinition(
        id="golf", name="Playing golf", cooldown_s=300.0, base_weight=1.0,
    )

    def can_start(self, context):
        return context.pedestrian_manager.soccer_open

    def find_location(self, context):
        if not self.can_start(context):
            return None
        pedestrian = context.pedestrian
        holes = [
            points
            for course in context.pedestrian_manager.nearby_sceneries(
                pedestrian.x, pedestrian.y, SEARCH_RADIUS_M
            ) if course.kind == self.course_kind
            for points in course.golf_holes
            if len(points) >= 2 and math.dist(points[0], points[-1]) > 1.0
            and math.dist(points[0], (pedestrian.x, pedestrian.y)) <= SEARCH_RADIUS_M
        ]
        if not holes:
            return None
        points = random.choice(holes)
        next_point = next(point for point in points[1:] if point != points[0])
        heading = math.atan2(next_point[1] - points[0][1], next_point[0] - points[0][0])
        return ActivityLocation(points[0][0] - math.cos(heading) * STANCE_M,
                                points[0][1] - math.sin(heading) * STANCE_M,
                                reservation_key=(self.definition.id, tuple(points)), extra=points)

    def populate(self, manager, course, bounds, budget):
        """Seed games on visible holes; ambient walkers alone rarely reach a tee."""
        if not manager.soccer_open or budget <= 0:
            return 0
        occupied = {p.activity.location.reservation_key for p in manager.pedestrians
                    if p.activity is not None and p.activity.plugin_id == self.definition.id and p.activity.location}
        centre = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
        attempts = 0
        for points in course.golf_holes:
            key = (self.definition.id, tuple(points))
            if key in occupied or len(points) < 2 or math.dist(points[0], points[-1]) <= 1.0:
                continue
            closest = None
            distances = [0.0]
            for start, end in zip(points, points[1:]):
                length = math.dist(start, end)
                x, y, fraction, distance = closest_point_and_dist_to_segment(*centre, *start, *end)
                if in_bounds(bounds, x, y) and (closest is None or distance < closest[0]):
                    closest = distance, distances[-1] + fraction * length
                distances.append(distances[-1] + length)
            if closest is None:
                continue
            # Ambient games enter already in progress, including beside a visible green.
            at = 0.0 if self.putting_only else min(closest[1], max(0.0, distances[-1] - 1.5))
            ball = point_along(points, distances, at)
            stance = point_along(points, distances, max(0.0, at - STANCE_M))
            if at == 0.0:
                ahead = point_along(points, distances, STANCE_M)
                heading = math.atan2(ahead[1] - ball[1], ahead[0] - ball[0])
                stance = ball[0] - math.cos(heading) * STANCE_M, ball[1] - math.sin(heading) * STANCE_M
            attempts += 1
            player = manager.spawn_pedestrian_at(*stance)
            if player is not None:
                context = manager._activity_context(player)
                location = ActivityLocation(*stance, reservation_key=key, extra=points)
                if manager.activity_manager.reserve(context, location):
                    if manager.add_pedestrian(player):
                        player.activity = ActivityInstance(self.definition.id, location, manager.sim_time, data={"spawn_progress": at})
                        player.state = "performing_activity"
                        self.start(context, player.activity)
                        occupied.add(key)
                    else:
                        manager.activity_manager.release(location)
            if attempts >= budget:
                break
        return attempts

    def start(self, context, instance):
        points = instance.location.extra
        distances = [0.0]
        for start, end in zip(points, points[1:]):
            distances.append(distances[-1] + math.dist(start, end))
        progress = instance.data.pop("spawn_progress", 0.0)
        instance.data.update(distances=distances, progress=progress, walked=max(0.0, progress - STANCE_M),
                             strokes=math.ceil(progress / 160.0),
                             ball=[*point_along(points, distances, progress), 0.0],
                             pin=points[-1], holed=False, swing=0.0)
        self._prepare(context, instance)

    def _prepare(self, context, instance):
        data = instance.data
        points = instance.location.extra
        total = data["distances"][-1]
        remaining = total - data["progress"]
        ball = data["ball"]
        areas = context.pedestrian_manager.nearby_sceneries(ball[0], ball[1], 20.0)
        greens = [s for s in areas if s.kind == "golf_green"
                  and point_in_polygon(*data["pin"], s.points_m)]
        on_green = any(point_in_polygon(ball[0], ball[1], s.points_m) for s in greens)
        if not greens:
            # shortcut: unmapped greens use the final 12 m, replace when green geometry is available.
            on_green = remaining <= 12.0
        if self.putting_only or (on_green and data["strokes"] > 0):
            club = "putter"
            # Long putts can stop short; a close tap-in always finishes the hole.
            advance = remaining if remaining <= 1.5 or random.random() < 0.3 else max(0.5, remaining - random.uniform(0.4, 1.4))
        else:
            club = "driver" if data["strokes"] == 0 else "wedge" if remaining < 50.0 else "iron"
            reach = random.uniform(180.0, 230.0) if club == "driver" else random.uniform(70.0, 130.0) if club == "iron" else 40.0
            advance = (remaining if remaining <= reach and random.random() < 0.02
                       else min(reach, max(0.5, remaining - random.uniform(3.0, 8.0))))
        if self.putting_only:
            corner = min(bisect.bisect_right(data["distances"], data["progress"]), len(points) - 1)
            advance = min(advance, data["distances"][corner] - data["progress"])
        target_progress = min(total, data["progress"] + advance)
        target = point_along(points, data["distances"], target_progress)
        if club != "putter":
            areas = context.pedestrian_manager.nearby_sceneries(*target, 40.0)
            landing_areas = [s for s in areas if s.kind in {"golf_fairway", "golf_green"}]
            if landing_areas:
                for factor in (1.0, 0.9, 0.8, 0.7, 0.6):
                    candidate_progress = min(total, data["progress"] + advance * factor)
                    candidate = point_along(points, data["distances"], candidate_progress)
                    if any(point_in_polygon(*candidate, s.points_m) for s in landing_areas):
                        target_progress, target = candidate_progress, candidate
                        break
        data.update(phase="prepare", timer=PREPARE_S, club=club, target=target,
                    target_progress=target_progress, swing=0.0)
        context.pedestrian.heading = math.atan2(target[1] - ball[1], target[0] - ball[0])

    def _hit(self, instance):
        data = instance.data
        start, target = data["ball"][:2], data["target"]
        distance = math.dist(start, target)
        putting = data["club"] == "putter"
        apex = 0.0 if putting else max(1.0, distance * (0.2 if data["club"] == "wedge" else 0.12))
        data.update(strokes=data["strokes"] + 1, shot_start=start, elapsed=0.0, apex=apex,
                    phase="roll" if putting else "flight", swing=0.0,
                    duration=max(0.15, math.sqrt(2.0 * distance / 0.8)) if putting else math.sqrt(8.0 * apex / 9.81))
        if not putting:
            data["carry"] = (start[0] + (target[0] - start[0]) * 0.94,
                             start[1] + (target[1] - start[1]) * 0.94)

    def update(self, context, instance, dt):
        if not self.can_start(context):
            return True
        data = instance.data
        pedestrian = context.pedestrian
        pedestrian.speed = 0.0
        pedestrian.animation_state = "idle"
        if data["phase"] in {"prepare", "swing"}:
            data["timer"] = max(0.0, data["timer"] - dt)
            if data["phase"] == "swing":
                data["swing"] = 1.0 - data["timer"] / SWING_S
            if data["timer"] == 0.0:
                if data["phase"] == "prepare":
                    data.update(phase="swing", timer=SWING_S)
                else:
                    self._hit(instance)
        elif data["phase"] in {"flight", "roll"}:
            data["elapsed"] = min(data["duration"], data["elapsed"] + dt)
            t = data["elapsed"] / data["duration"]
            flight = data["phase"] == "flight"
            end = data["carry"] if flight else data["target"]
            fraction = t if flight else t * (2.0 - t)
            start = data["shot_start"]
            data["ball"] = [start[0] + (end[0] - start[0]) * fraction,
                            start[1] + (end[1] - start[1]) * fraction,
                            4.0 * data["apex"] * t * (1.0 - t) if flight else 0.0]
            if t == 1.0:
                if flight:
                    data.update(phase="roll", shot_start=end, elapsed=0.0,
                                duration=max(0.2, math.sqrt(2.0 * math.dist(end, data["target"]) / 1.6)))
                else:
                    data.update(phase="walk", progress=data["target_progress"],
                                holed=data["target_progress"] >= data["distances"][-1])
        elif data["phase"] == "walk":
            # shortcut: walking follows the hole line; use course footpaths when hazard detours are needed.
            stop = data["progress"] if data["holed"] else max(0.0, data["progress"] - STANCE_M)
            data["walked"] = min(stop, data["walked"] + pedestrian.base_speed * dt)
            target = point_along(instance.location.extra, data["distances"], data["walked"])
            dx, dy = target[0] - pedestrian.x, target[1] - pedestrian.y
            distance = math.hypot(dx, dy)
            step = min(distance, pedestrian.base_speed * dt)
            if distance > 0.01:
                pedestrian.heading = math.atan2(dy, dx)
                pedestrian.x += dx / distance * step
                pedestrian.y += dy / distance * step
                pedestrian.speed = pedestrian.base_speed
                pedestrian.animation_state = "walking"
            if data["walked"] == stop and distance <= 0.1:
                if data["holed"]:
                    return True
                self._prepare(context, instance)
        return False


PLUGIN = GolfPlugin()
