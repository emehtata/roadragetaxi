"""Stop and check a phone, no location required (residents-live.md section 6).

The requires_location=False plugin: proves the core (ActivityManager /
PedestrianManager._update_activity) genuinely doesn't need a location to
exist, not just that this particular activity happens to skip walking.
"""
from __future__ import annotations

import random

from ..base import ActivityContext, ActivityDefinition, ActivityInstance, ActivityPlugin


class PhoneUsagePlugin(ActivityPlugin):
    definition = ActivityDefinition(
        id="phone_usage",
        name="Checking phone",
        requires_location=False,
        min_duration_s=5.0,
        max_duration_s=25.0,
        cooldown_s=45.0,
        base_weight=1.5,
    )

    def start(self, context: ActivityContext, instance: ActivityInstance) -> None:
        instance.data["duration_s"] = random.uniform(self.definition.min_duration_s, self.definition.max_duration_s)
        instance.data["elapsed_s"] = 0.0

    def update(self, context: ActivityContext, instance: ActivityInstance, dt: float) -> bool:
        instance.data["elapsed_s"] += dt
        return instance.data["elapsed_s"] >= instance.data["duration_s"]


PLUGIN = PhoneUsagePlugin()
