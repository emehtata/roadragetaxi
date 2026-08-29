"""Persistent career-mode progress."""

import json
from pathlib import Path
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


def save_gig_odometer(path: Path, distance_m: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps({"odometer_m": max(0.0, distance_m)}, indent=2), encoding="utf-8")
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
