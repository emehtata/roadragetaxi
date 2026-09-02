"""City residents who may walk or control vehicles."""
import gzip
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Set


def _load_names(filename: str, key: str) -> list[dict]:
    path = Path(__file__).with_name("assets") / filename
    try:
        with gzip.open(path, "rt", encoding="utf-8") as source:
            return json.load(source).get(key, [])
    except (OSError, json.JSONDecodeError):
        return []


FIRST_NAMES = _load_names("finnish_first_names.json.gz", "first_names")
SURNAMES = _load_names("finnish_surnames.json.gz", "surnames")


def _weighted_name(entries: list[dict], group: Optional[str] = None) -> tuple[str, Optional[str]]:
    candidates = [entry for entry in entries if group is None or entry.get("group") == group]
    if not candidates:
        candidates = entries
    if not candidates:
        return "Asukas", None
    selected = random.choices(
        candidates,
        weights=[max(1, int(entry.get("people", 1))) for entry in candidates],
        k=1,
    )[0]
    return selected["name"], selected.get("group")


@dataclass
class Resident:
    """Persistent city person; movement mode and vehicles are mutable state."""
    resident_id: int
    first_name: str = "Asukas"
    surname: str = ""
    gender: Optional[str] = None
    mode: str = "walking"
    vehicle_ids: Set[int] = field(default_factory=set)
    active_vehicle_id: Optional[int] = None
    lod_level: int = 0
    lod_update_due: bool = True
    lod_time_accumulator: float = 0.0


class ResidentManager:
    """Registry shared by pedestrian and vehicle managers."""

    def __init__(self) -> None:
        self.residents: Dict[int, Resident] = {}
        self._next_id = 1

    def create(
        self,
        mode: str = "walking",
        vehicle_id: Optional[int] = None,
        group: Optional[str] = None,
    ) -> Resident:
        first_name, gender = _weighted_name(FIRST_NAMES, group)
        surname, _ = _weighted_name(SURNAMES)
        resident = Resident(
            self._next_id,
            first_name=first_name,
            surname=surname,
            gender=gender,
            mode=mode,
        )
        self._next_id += 1
        self.residents[resident.resident_id] = resident
        if vehicle_id is not None:
            resident.vehicle_ids.add(vehicle_id)
            resident.active_vehicle_id = vehicle_id
        return resident

    def get(self, resident_id: Optional[int]) -> Optional[Resident]:
        return self.residents.get(resident_id) if resident_id is not None else None

    def remove_vehicle(self, vehicle_id: int) -> None:
        for resident in self.residents.values():
            resident.vehicle_ids.discard(vehicle_id)
            if resident.active_vehicle_id == vehicle_id:
                resident.active_vehicle_id = None

    def remove(self, resident_id: int) -> None:
        self.residents.pop(resident_id, None)

    def update_lod(self, resident_id: Optional[int], x: float, y: float, player_x: float, player_y: float, dt: float) -> int:
        """Update shared LOD state for a resident represented in the world."""
        resident = self.get(resident_id)
        if resident is None:
            return 0
        distance = ((x - player_x) ** 2 + (y - player_y) ** 2) ** 0.5
        resident.lod_level = 0 if distance < 500.0 else 1 if distance < 1500.0 else 2
        resident.lod_time_accumulator += dt
        interval = (1.0 / 30.0, 1.0 / 12.0, 0.2)[resident.lod_level]
        if resident.lod_update_due or resident.lod_time_accumulator >= interval:
            resident.lod_update_due = True
            resident.lod_time_accumulator = 0.0
        else:
            resident.lod_update_due = False
        return resident.lod_level
