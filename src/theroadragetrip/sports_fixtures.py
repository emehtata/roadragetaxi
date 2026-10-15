"""Finnish major-league match times for stadium crowd simulation.

Each match has UTC ``start``, ``crowd_start`` and ``crowd_end`` timestamps,
teams, phase, venue name, nullable result and attendance. Liiga venues also
carry coordinates supplied by Liiga.
"""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path


DEFAULT_FIXTURES_PATH = Path(__file__).with_name("assets") / "sports_fixtures.json.gz"


@lru_cache(maxsize=1)
def load_sports_fixtures(path: Path = DEFAULT_FIXTURES_PATH) -> tuple[dict, ...]:
    with gzip.open(path, "rt", encoding="utf-8") as source:
        data = json.load(source)
    if data.get("schema_version") != 1:
        raise ValueError("unsupported sports fixture data version")
    return tuple(data["matches"])


def active_match_crowds(when: datetime, fixtures: tuple[dict, ...] | None = None) -> list[dict]:
    """Matches whose arrival/game/departure crowd window contains ``when``."""
    if when.tzinfo is None:
        raise ValueError("sports fixture lookup requires a timezone-aware datetime")
    instant = when.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    matches = load_sports_fixtures() if fixtures is None else fixtures
    return [match for match in matches
            if match["crowd_start"] <= instant <= match["crowd_end"]]
