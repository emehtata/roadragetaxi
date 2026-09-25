"""Persistent career-mode progress."""

import json
from pathlib import Path
from typing import Optional
CAREER_SCORE_LIMIT = 5000


def career_path(config_path: Path) -> Path:
    return config_path.parent / "career.json"


def gig_odometer_path(config_path: Path) -> Path:
    return config_path.parent / "gig_odometer.json"


def load_career(path: Path, city_count: int) -> dict[str, object]:
    default = {"city_index": 0, "completed": False, "total_score": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return default
    if not isinstance(data, dict):
        return default
    city_index = data.get("city_index", default["city_index"])
    completed = data.get("completed", False)
    total_score = data.get("total_score", default["total_score"])
    if not isinstance(city_index, int) or not 0 <= city_index < city_count:
        city_index = default["city_index"]
    if not isinstance(total_score, int):
        total_score = default["total_score"]
    return {"city_index": city_index, "completed": bool(completed), "total_score": total_score}


def load_career_distance(path: Path) -> float:
    """Load optional persistent career distance without changing the legacy progress shape."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return 0.0
    distance = data.get("total_distance_m", 0.0) if isinstance(data, dict) else 0.0
    return float(distance) if isinstance(distance, (int, float)) and distance >= 0 else 0.0


def load_gig_odometer(path: Path, default: float = 0.0) -> float:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return default
    distance = data.get("odometer_m", default) if isinstance(data, dict) else default
    return float(distance) if isinstance(distance, (int, float)) and distance >= 0 else default


def _load_gig_number(path: Path, key: str) -> Optional[float]:
    """A saved non-negative number from the previous gig session, or None
    (no save yet, or an older file without it) - keep the default."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    value = data.get(key) if isinstance(data, dict) else None
    return float(value) if isinstance(value, (int, float)) and value >= 0 else None


def load_gig_fuel(path: Path) -> Optional[float]:
    """Fuel left in the tank at the end of the previous gig session."""
    return _load_gig_number(path, "fuel_l")


def load_gig_balance(path: Path) -> Optional[int]:
    """Money (cents) left at the end of the previous gig session."""
    balance = _load_gig_number(path, "balance_cents")
    return None if balance is None else int(balance)


def save_gig_odometer(
    path: Path, distance_m: float, fuel_l: Optional[float] = None, balance_cents: Optional[int] = None,
) -> None:
    """Persist the gig car between sessions: odometer, and fuel/money if given."""
    data = {"odometer_m": max(0.0, distance_m)}
    if fuel_l is not None:
        data["fuel_l"] = max(0.0, fuel_l)
    if balance_cents is not None:
        data["balance_cents"] = max(0, int(balance_cents))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary_path.replace(path)


def save_career(
    path: Path,
    city_index: int,
    total_score: int = 0,
    completed: bool = False,
    total_distance_m: float = 0.0,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(
            {
                "city_index": city_index,
                "completed": completed,
                "total_score": total_score,
                "total_distance_m": max(0.0, total_distance_m),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    temporary_path.replace(path)
