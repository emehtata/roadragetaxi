"""Fixed world places (airports, railway stations, ...) from assets/places.json.

The JSON is generated at build time from the Finland OSM PBF by
tools/osm/extract_places.py (docs/places.md) - the game never reads the
PBF for this. A place belongs to the world; taxis, buses or trains decide
for themselves how to reach it. Coordinates are WGS84 lat/lon: project
with the city's own transformer when a local metre position is needed.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_PLACES_PATH = Path(__file__).with_name("assets") / "places.json"
SUPPORTED_VERSION = 1
_CORE_KEYS = {"id", "type", "name", "lat", "lon", "osm", "names"}


@dataclass(frozen=True)
class WorldPlace:
    id: str
    type: str
    name: str
    lat: float
    lon: float
    osm: Optional[Tuple[str, int]] = None  # (element type, id): traceable back to OSM
    names: Dict[str, str] = field(default_factory=dict)  # language -> name, when it differs
    metadata: Dict[str, object] = field(default_factory=dict)  # category-specific (iata, station_code, ...)

    def name_in(self, language: str) -> str:
        return self.names.get(language, self.name)


class WorldPlaces:
    def __init__(self, places: Iterable[WorldPlace] = ()) -> None:
        self._places: List[WorldPlace] = list(places)
        self._by_id = {place.id: place for place in self._places}

    def __len__(self) -> int:
        return len(self._places)

    def __iter__(self):
        return iter(self._places)

    def get(self, place_id: str) -> Optional[WorldPlace]:
        return self._by_id.get(place_id)

    def by_type(self, place_type: str) -> List[WorldPlace]:
        return [place for place in self._places if place.type == place_type]

    def find(self, name: str, place_type: Optional[str] = None) -> List[WorldPlace]:
        """Case-insensitive match on any of a place's names."""
        wanted = name.casefold()
        return [
            place for place in self._places
            if (place_type is None or place.type == place_type)
            and any(n.casefold() == wanted for n in (place.name, *place.names.values()))
        ]

    def within(self, lat: float, lon: float, radius_m: float, place_type: Optional[str] = None) -> List[WorldPlace]:
        """Places within radius_m of a point, nearest first (e.g. the
        airports/stations serving the current city)."""
        kx = 111_320.0 * math.cos(math.radians(lat))
        hits = []
        for place in self._places:
            if place_type is not None and place.type != place_type:
                continue
            distance = math.hypot((place.lat - lat) * 111_320.0, (place.lon - lon) * kx)
            if distance <= radius_m:
                hits.append((distance, place.id, place))
        return [place for _, _, place in sorted(hits)]


def load_places(path: Optional[Path] = None) -> WorldPlaces:
    """Load places.json; a missing or broken file gives an empty set (the
    game runs without it), logged rather than raised."""
    path = Path(path) if path is not None else DEFAULT_PLACES_PATH
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("version") != SUPPORTED_VERSION:
            raise ValueError(f"unsupported version {document.get('version')!r}")
        places = []
        for record in document["places"]:
            osm = record.get("osm")
            places.append(WorldPlace(
                id=record["id"],
                type=record["type"],
                name=record["name"],
                lat=float(record["lat"]),
                lon=float(record["lon"]),
                osm=(osm["type"], int(osm["id"])) if osm else None,
                names=dict(record.get("names", {})),
                metadata={k: v for k, v in record.items() if k not in _CORE_KEYS},
            ))
    except FileNotFoundError:
        logger.warning("World places file missing: %s", path)
        return WorldPlaces()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.warning("World places file unusable (%s): %s", exc, path)
        return WorldPlaces()
    return WorldPlaces(places)
