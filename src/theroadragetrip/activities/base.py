"""Generic pedestrian-activity plugin interface (see .github/prompts/residents-live.md).

A plugin describes one contextual activity (sitting on a bench, checking a
phone, ...) via a plain ``ActivityPlugin`` subclass. The core orchestration
(``ActivityManager``, ``PedestrianManager``) only ever calls the six hook
methods below - it never branches on which activity it's driving.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Hashable, Optional, TYPE_CHECKING

from ..residents import ResidentManager

if TYPE_CHECKING:
    from ..pedestrian import Pedestrian, PedestrianManager


@dataclass
class ActivityDefinition:
    """Static description of one activity kind."""

    id: str
    name: str
    requires_location: bool = True
    min_duration_s: float = 10.0
    max_duration_s: float = 30.0
    cooldown_s: float = 60.0  # this activity's own re-trigger cooldown
    base_weight: float = 1.0  # relative pick weight vs other viable candidates


@dataclass
class ActivityLocation:
    """What find_location() hands back - opaque to the core.

    reservation_key is any hashable the plugin chooses to make a location
    exclusive to one pedestrian at a time; None means no exclusivity is
    needed (e.g. a park has room for everyone).
    """

    x: float
    y: float
    reservation_key: Optional[Hashable] = None
    extra: Any = None  # the plugin's own object reference (a SceneryObject/Scenery/...)


@dataclass
class ActivityInstance:
    """The one live-activity object hung off Pedestrian.activity.

    `data` is the plugin's own private scratch space (duration timer,
    etc.) - the core never reads or writes it.
    """

    plugin_id: str
    location: Optional[ActivityLocation]
    started_sim_time: float
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ActivityContext:
    """Everything a plugin hook needs to make its decision."""

    pedestrian: "Pedestrian"
    pedestrian_manager: "PedestrianManager"
    residents: ResidentManager
    sim_time: float


class ActivityPlugin:
    """Base class for one pedestrian activity.

    Plain class with plain methods (not abc.ABC/typing.Protocol) - this
    codebase has no formal-interface pattern anywhere else, just
    @dataclass + duck-typing, so this matches that grain.
    """

    definition: ActivityDefinition

    def can_start(self, context: ActivityContext) -> bool:
        return True

    def find_location(self, context: ActivityContext) -> Optional[ActivityLocation]:
        return None

    def score(self, context: ActivityContext, location: Optional[ActivityLocation]) -> float:
        return 1.0

    def start(self, context: ActivityContext, instance: ActivityInstance) -> None:
        pass

    def update(self, context: ActivityContext, instance: ActivityInstance, dt: float) -> bool:
        """Return True once the activity is finished."""
        return True

    def finish(self, context: ActivityContext, instance: ActivityInstance) -> None:
        pass
