"""Vehicle plugin registry - discovery and lookup, no selection logic."""
from __future__ import annotations

from typing import Dict, List, Optional

from .base import VehiclePlugin


class VehicleRegistry:
    """Holds registered plugins by id. Registration itself never fails
    silently: a duplicate id is a programming error and raises, but
    *discovery* (see plugins/__init__.py's discover()) catches that per
    module so one broken plugin can't block every other one."""

    def __init__(self) -> None:
        self._plugins: Dict[str, VehiclePlugin] = {}

    def register(self, plugin: VehiclePlugin) -> None:
        plugin_id = plugin.definition.id
        if plugin_id in self._plugins:
            raise ValueError(f"Duplicate vehicle plugin id: {plugin_id!r}")
        self._plugins[plugin_id] = plugin

    def get(self, plugin_id: str) -> Optional[VehiclePlugin]:
        return self._plugins.get(plugin_id)

    def all_plugins(self) -> List[VehiclePlugin]:
        return list(self._plugins.values())


_default_registry: Optional[VehicleRegistry] = None


def default_registry() -> VehicleRegistry:
    """The shared, memoized registry populated by plugin discovery once.

    Safe to share across every NPCVehicleManager (including many in
    tests) because it's never mutated again after discover() runs.
    """
    global _default_registry
    if _default_registry is None:
        from .plugins import discover

        _default_registry = VehicleRegistry()
        discover(_default_registry)
    return _default_registry
