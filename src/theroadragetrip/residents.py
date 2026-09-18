"""City residents who may walk or control vehicles."""
import gzip
import json
import math
import random
from datetime import date, timedelta
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Set, Tuple


def _load_names(filename: str, key: str) -> list[dict]:
    path = Path(__file__).with_name("assets") / filename
    try:
        with gzip.open(path, "rt", encoding="utf-8") as source:
            return json.load(source).get(key, [])
    except (OSError, json.JSONDecodeError):
        return []


FIRST_NAMES = _load_names("finnish_first_names.json.gz", "first_names")
SURNAMES = _load_names("finnish_surnames.json.gz", "surnames")
CITY_DATA_PATH = Path(__file__).with_name("assets") / "kunnat.json.gz"


def _load_city_data() -> dict[str, dict]:
    try:
        with gzip.open(CITY_DATA_PATH, "rt", encoding="utf-8") as source:
            data = json.load(source)
    except (OSError, json.JSONDecodeError):
        return {}
    return {entry["taajama"].casefold(): entry for entry in data.get("places", []) if entry.get("taajama")}


CITY_DATA = _load_city_data()


# (id(entries), group) -> (candidates, weights), built once per group
# instead of on every call - FIRST_NAMES/SURNAMES are fixed module-level
# lists (loaded once, never mutated), so a name lookup used to rebuild
# the same filtered-and-weighted list from scratch (thousands of names)
# every single resident created, which during a pedestrian-population
# spawn burst (several residents at once) added real, avoidable cost.
_weighted_name_cache: Dict[tuple, tuple] = {}


def _weighted_name(entries: list[dict], group: Optional[str] = None) -> tuple[str, Optional[str]]:
    cache_key = (id(entries), group)
    cached = _weighted_name_cache.get(cache_key)
    if cached is None:
        candidates = [entry for entry in entries if group is None or entry.get("group") == group]
        if not candidates:
            candidates = entries
        if not candidates:
            return "Asukas", None
        cached = (candidates, [max(1, int(entry.get("people", 1))) for entry in candidates])
        _weighted_name_cache[cache_key] = cached
    candidates, weights = cached
    selected = random.choices(candidates, weights=weights, k=1)[0]
    return selected["name"], selected.get("group")


def _birth_date_for_city(
    city_data: Optional[dict],
    min_age: int = 0,
    max_age: int = 100,
) -> date:
    age_distribution = (city_data or {}).get("ikajakauma", {})
    groups = (
        ("alle_15_vuotta", 0, 14),
        ("15_64_vuotta", 15, 64),
        ("65_vuotta_tayttaneet", 65, 100),
    )
    groups = tuple(
        (key, max(start, min_age), min(end, max_age))
        for key, start, end in groups
        if max(start, min_age) <= min(end, max_age)
    )
    available = [(key, start, end, float(age_distribution.get(key, 0.0))) for key, start, end in groups]
    weighted = [entry for entry in available if entry[3] > 0.0] or [(*entry[:3], 1.0) for entry in available]
    _, age_start, age_end, _ = random.choices(weighted, weights=[entry[3] for entry in weighted], k=1)[0]
    age = random.randint(age_start, age_end)
    return date.today() - timedelta(days=age * 365 + random.randrange(365))


@dataclass
class Resident:
    """Persistent city person; movement mode and vehicles are mutable state."""
    resident_id: int
    first_name: str = "Asukas"
    surname: str = ""
    gender: Optional[str] = None
    birth_date: date = field(default_factory=date.today)
    parent_ids: Set[int] = field(default_factory=set)
    child_ids: Set[int] = field(default_factory=set)
    mode: str = "walking"
    vehicle_ids: Set[int] = field(default_factory=set)
    active_vehicle_id: Optional[int] = None
    active_vehicle_role: Optional[str] = None
    # multi-passenger-car.md sections 3, 16: which NPCVehicle trip group (if
    # any) this resident is currently travelling with - None once they
    # leave the group (reboard timeout, or never in one to begin with).
    trip_group_id: Optional[int] = None
    # NPC-003 section 6: which Household (if any) this resident belongs to -
    # most spawned residents have none (not every household owns a car).
    household_id: Optional[int] = None
    lod_level: int = 0
    lod_update_due: bool = True
    lod_time_accumulator: float = 0.0


class ResidentManager:
    """Registry shared by pedestrian and vehicle managers."""

    def __init__(self, city_name: Optional[str] = None) -> None:
        self.residents: Dict[int, Resident] = {}
        self._next_id = 1
        self.city_name = city_name
        self.city_data = CITY_DATA.get(city_name.casefold()) if city_name else None
        self.city_center_m: Optional[tuple[float, float]] = None

    def set_city_center_m(self, x: float, y: float) -> None:
        self.city_center_m = (x, y)

    def set_city_center_latlon(self, latitude: float, longitude: float) -> None:
        try:
            from pyproj import Transformer
            transformer = Transformer.from_crs("EPSG:4326", "EPSG:3067", always_xy=True)
            self.city_center_m = transformer.transform(longitude, latitude)
        except (ImportError, RuntimeError, ValueError):
            self.city_center_m = None

    def density_spawn_probability(self, x: float, y: float) -> float:
        if not self.city_data or self.city_center_m is None:
            return 1.0
        density = max(0.0, float(self.city_data.get("väestöntiheys_henkiloa_km2", 0.0)))
        area_km2 = max(1.0, float(self.city_data.get("pinta_ala_km2", 1.0)))
        radius_m = math.sqrt(area_km2 * 1_000_000.0 / math.pi)
        distance = math.hypot(x - self.city_center_m[0], y - self.city_center_m[1])
        center_factor = 0.25 + 0.75 * math.exp(-distance / radius_m)
        density_factor = 0.15 + 0.85 * min(1.0, density / 100.0)
        return max(0.05, min(1.0, center_factor * density_factor))

    def create(
        self,
        mode: str = "walking",
        vehicle_id: Optional[int] = None,
        group: Optional[str] = None,
        age: Optional[int] = None,
    ) -> Resident:
        if age is not None and not 0 <= age <= 100:
            raise ValueError("age must be between 0 and 100")
        birth_date = _birth_date_for_city(
            self.city_data,
            min_age=age if age is not None else 0,
            max_age=age if age is not None else 100,
        )
        first_name, gender = _weighted_name(FIRST_NAMES, group)
        surname, _ = _weighted_name(SURNAMES)
        resident = Resident(
            self._next_id,
            first_name=first_name,
            surname=surname,
            gender=gender,
            birth_date=birth_date,
            mode=mode,
        )
        self._next_id += 1
        self.residents[resident.resident_id] = resident
        if vehicle_id is not None:
            resident.vehicle_ids.add(vehicle_id)
            resident.active_vehicle_id = vehicle_id
        if self.age_of(resident) < 18:
            child_age = self.age_of(resident)
            min_parent_age = child_age + 18
            max_parent_age = child_age + 44
            parents = [
                candidate
                for candidate in self.residents.values()
                if candidate.resident_id != resident.resident_id
                and min_parent_age <= self.age_of(candidate) <= max_parent_age
            ]
            parent = (
                random.choice(parents)
                if parents
                else self.create(
                    mode="household",
                    age=random.randint(min_parent_age, max_parent_age),
                )
            )
            resident.surname = parent.surname
            resident.parent_ids.add(parent.resident_id)
            parent.child_ids.add(resident.resident_id)
        return resident

    @staticmethod
    def age_of(resident: Resident) -> int:
        today = date.today()
        return max(0, today.year - resident.birth_date.year - (
            (today.month, today.day) < (resident.birth_date.month, resident.birth_date.day)
        ))

    def get(self, resident_id: Optional[int]) -> Optional[Resident]:
        return self.residents.get(resident_id) if resident_id is not None else None

    def remove(self, resident_id: int) -> None:
        self.residents.pop(resident_id, None)

    def board_vehicle(self, resident_id: int, vehicle_id: int, role: str) -> Resident:
        resident = self.residents[resident_id]
        if role not in {"driver", "passenger"}:
            raise ValueError("role must be driver or passenger")
        if resident.active_vehicle_id is not None and resident.active_vehicle_id != vehicle_id:
            raise ValueError("resident already occupies another vehicle")
        if resident.active_vehicle_role is not None and resident.active_vehicle_role != role:
            raise ValueError("resident already occupies this vehicle in another role")
        resident.vehicle_ids.add(vehicle_id)
        resident.active_vehicle_id = vehicle_id
        resident.active_vehicle_role = role
        resident.mode = "driving" if role == "driver" else "riding"
        return resident

    def leave_vehicle(
        self,
        resident_id: int,
        vehicle_id: Optional[int] = None,
        mode: str = "walking",
    ) -> Optional[Resident]:
        resident = self.get(resident_id)
        if resident is None:
            return None
        if vehicle_id is not None and resident.active_vehicle_id not in (None, vehicle_id):
            raise ValueError("resident is not in that vehicle")
        resident.active_vehicle_id = None
        resident.active_vehicle_role = None
        resident.mode = mode
        return resident

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


@dataclass
class Household:
    """NPC-003 section 6: the minimal ownership entity linking a home
    position to whichever Residents live there and whichever NPCVehicles
    (0, 1, or more) they own. Deliberately simple - "the exact ownership
    model can initially be simple" (NPC-003 section 6) - just enough that
    a future Resident-trip system can ask "does my household own a car,
    and where does it live" without a special case per caller.

    Not every household owns a vehicle (vehicle_ids empty is normal), and
    not every NPC vehicle belongs to a household at all (a generic
    TRAFFIC_VEHICLE, see npc.NPCVehicle.vehicle_kind, has no household_id
    and is never referenced by one)."""

    household_id: int
    home_position: Tuple[float, float]
    member_resident_ids: Set[int] = field(default_factory=set)
    vehicle_ids: Set[int] = field(default_factory=set)


class HouseholdManager:
    """Registry of Households - same shape as ResidentManager (dict
    registry, incrementing id, get())."""

    def __init__(self) -> None:
        self.households: Dict[int, Household] = {}
        self._next_id = 1

    def create(self, home_position: Tuple[float, float]) -> Household:
        household = Household(household_id=self._next_id, home_position=home_position)
        self.households[household.household_id] = household
        self._next_id += 1
        return household

    def get(self, household_id: Optional[int]) -> Optional[Household]:
        return self.households.get(household_id) if household_id is not None else None
