"""Relax on a beach towel while the server says it is warm and sunny."""
import math
import random

from ..base import ActivityDefinition
from ..beach import BeachPlugin


class SunbathingPlugin(BeachPlugin):
    definition = ActivityDefinition(id="sunbathing", name="Sunbathing", min_duration_s=60,
                                    max_duration_s=180, cooldown_s=120)

    def start(self, context, instance):
        super().start(context, instance)
        context.pedestrian.heading = random.uniform(0, math.tau)
        context.pedestrian.animation_state = "sunbathing"


PLUGIN = SunbathingPlugin()
