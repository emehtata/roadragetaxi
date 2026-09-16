"""Generic pedestrian-activity plugin interface (see .github/prompts/residents-live.md).

A plugin describes one contextual activity (sitting on a bench, checking a
phone, ...) via a plain ``ActivityPlugin`` subclass. The core orchestration
(``ActivityManager``, ``PedestrianManager``) only ever calls the six hook
methods below - it never branches on which activity it's driving.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Hashable, List, Optional, TYPE_CHECKING

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
    # Group activities (residents-live.md section 7) - unused by a solo
    # plugin, which just leaves these at the 1/1 default. The core never
    # reads these; they exist for a group plugin's own recruiting logic
    # (see grouping.py) to check against.
    min_participants: int = 1
    max_participants: int = 1


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
class ActivityGroup:
    """Shared state for a multi-participant activity (residents-live.md
    section 7) - one instance referenced by every participant's own
    ActivityInstance.group, the same "one shared object, several owners"
    shape as npc.py's TripGroup. Not created or read by the core at all;
    entirely owned and mutated by group-recruiting plugins (see
    grouping.py's nearby_free_pedestrians()/recruit())."""

    group_id: int
    plugin_id: str
    member_resident_ids: List[int]
    formed_sim_time: float
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ActivityInstance:
    """The one live-activity object hung off Pedestrian.activity.

    `data` is the plugin's own private scratch space (duration timer,
    etc.) - the core never reads or writes it. `group` is None for an
    ordinary solo activity; a group plugin sets it to the ActivityGroup
    shared with its other participants (the core never reads this
    either - see grouping.py for the only code that touches it).
    """

    plugin_id: str
    location: Optional[ActivityLocation]
    started_sim_time: float
    data: Dict[str, Any] = field(default_factory=dict)
    group: Optional[ActivityGroup] = None


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
