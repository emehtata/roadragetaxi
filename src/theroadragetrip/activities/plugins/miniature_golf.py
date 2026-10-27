"""Putting-only games at mapped miniature-golf facilities."""
from ..base import ActivityDefinition
from .golf import GolfPlugin


class MiniatureGolfPlugin(GolfPlugin):
    course_kind = "miniature_golf"
    putting_only = True
    definition = ActivityDefinition(
        id="miniature_golf", name="Playing miniature golf", cooldown_s=120.0, base_weight=1.0,
    )


PLUGIN = MiniatureGolfPlugin()
