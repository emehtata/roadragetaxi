"""Generic multi-participant activity helpers (residents-live.md section 7).

Not itself a plugin - shared by any activity plugin that recruits other
nearby pedestrians into a group (two_person_conversation,
small_group_conversation, ball_game). Deliberately lives outside
plugins/, so plugins/discover()'s automatic module scan never mistakes it
for a plugin (it has no PLUGIN attribute).

Group formation happens at start() time, never at find_location()/score()
time: find_location() only runs as part of *candidate evaluation* and its
candidate may not end up chosen (see ActivityManager.select_activity) -
mutating another pedestrian's state there would corrupt them even when
this plugin loses the random weighted pick. start() only ever fires for
the activity that actually won, so that's the only safe place to reach
into another Pedestrian and claim them. Once claimed, a recruited
pedestrian's own ActivityInstance.group is already set, so the core's
ordinary per-pedestrian dispatch (_update_activity) drives their walk/
perform/finish exactly like a self-selected activity - no separate
group-aware code path needed anywhere in pedestrian.py.
"""
from __future__ import annotations

import itertools
import math
import random
from typing import TYPE_CHECKING, List, Optional, Tuple

from .base import ActivityContext, ActivityGroup, ActivityInstance, ActivityLocation

if TYPE_CHECKING:
    from ..pedestrian import Pedestrian

_group_id_counter = itertools.count(1)


def next_group_id() -> int:
    return next(_group_id_counter)


def nearby_free_pedestrians(
    context: ActivityContext, radius_m: float, limit: Optional[int] = None, children_only: bool = False
) -> List["Pedestrian"]:
    """Other pedestrians within radius_m that aren't already busy with
    something else - the "compatible and available" half of a group
    activity's joining rules. children_only additionally requires the
    resident age_of() check ResidentManager.create() itself already uses
    to decide who's a minor (no separate "is_child" concept invented)."""
    pedestrian = context.pedestrian
    candidates = []
    for other in context.pedestrian_manager.pedestrians:
        if (
            other is pedestrian
            or other.activity is not None
            or other.linked_vehicle_id is not None
            or other.reserved_vehicle_id is not None
            or other.current_vehicle_id is not None
            or other.is_cyclist
            or other.is_drunk
            or other.state != "walking"
        ):
            continue
        if math.hypot(other.x - pedestrian.x, other.y - pedestrian.y) > radius_m:
            continue
        if children_only:
            resident = context.residents.get(other.resident_id)
            if resident is None or context.residents.age_of(resident) >= 18:
                continue
        candidates.append(other)
        if limit is not None and len(candidates) >= limit:
            break
    return candidates


def recruit(
    context: ActivityContext,
    plugin_id: str,
    group: ActivityGroup,
    partner: "Pedestrian",
    location: ActivityLocation,
    duration_range: Tuple[float, float],
) -> None:
    """Directly claim `partner` for `group` - only ever called from
    start(), see the module docstring for why."""
    partner_instance = ActivityInstance(
        plugin_id=plugin_id, location=location, started_sim_time=context.sim_time, group=group
    )
    partner_instance.data["duration_s"] = random.uniform(*duration_range)
    partner_instance.data["elapsed_s"] = 0.0
    group.member_resident_ids.append(partner.resident_id)
    partner.activity = partner_instance
    partner.state = "walking_to_activity"
    partner.route = None


def other_group_members(context: ActivityContext, group: ActivityGroup) -> List["Pedestrian"]:
    """Live Pedestrian objects for this group's other current members -
    a departed/culled member simply won't be found here anymore (their
    resident_id may still linger in member_resident_ids; harmless, no
    registry to clean up since nothing but ActivityInstance.group
    references an ActivityGroup at all)."""
    pedestrian = context.pedestrian
    return [
        other
        for other in context.pedestrian_manager.pedestrians
        if other is not pedestrian and other.resident_id in group.member_resident_ids
    ]
