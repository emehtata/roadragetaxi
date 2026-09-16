"""Ambient pedestrian activity plugin system (.github/prompts/residents-live.md).

Public surface for pedestrian.py, the only consumer. Individual plugins
live under .plugins and are never imported directly - they're found via
discover()/default_registry().
"""
from .base import ActivityContext, ActivityDefinition, ActivityGroup, ActivityInstance, ActivityLocation, ActivityPlugin
from .manager import ActivityManager
from .registry import ActivityRegistry, default_registry

__all__ = [
    "ActivityContext",
    "ActivityDefinition",
    "ActivityGroup",
    "ActivityInstance",
    "ActivityLocation",
    "ActivityPlugin",
    "ActivityManager",
    "ActivityRegistry",
    "default_registry",
]
