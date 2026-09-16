"""Automatic activity plugin discovery.

Adding a new activity later requires only: create a module here ending in
`PLUGIN = SomeActivityPlugin()`, nothing else - no central list to edit
(residents-live.md section 4). A plugin module that fails to import is
logged and skipped; it must never prevent the game from starting.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil

from ..registry import ActivityRegistry

logger = logging.getLogger(__name__)


def discover(registry: ActivityRegistry) -> None:
    for module_info in pkgutil.iter_modules(__path__, prefix=f"{__name__}."):
        try:
            module = importlib.import_module(module_info.name)
            registry.register(module.PLUGIN)
        except Exception:
            logger.exception("Failed to load activity plugin module %s", module_info.name)
