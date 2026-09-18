"""Automatic vehicle plugin discovery.

Adding a new vehicle type later requires only: create a module here ending
in `PLUGIN = SomeVehiclePlugin()`, nothing else - no central list to edit
(NPC-003.md section 5/27). A plugin module that fails to import is logged
and skipped; it must never prevent the game from starting.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil

from ..registry import VehicleRegistry

logger = logging.getLogger(__name__)


def discover(registry: VehicleRegistry) -> None:
    for module_info in pkgutil.iter_modules(__path__, prefix=f"{__name__}."):
        try:
            module = importlib.import_module(module_info.name)
            registry.register(module.PLUGIN)
        except Exception:
            logger.exception("Failed to load vehicle plugin module %s", module_info.name)
