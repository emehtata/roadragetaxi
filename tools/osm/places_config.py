"""Place categories for tools/osm/extract_places.py.

One PlaceCategory per exported place type. Adding a category (bus_station,
ferry_terminal, harbour, landmark, ...) means appending one entry here -
the extractor itself never names a category. See docs/places.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Tuple

Tags = Mapping[str, str]

# Lifecycle markers: an element tagged like this is not a working place.
CLOSED_VALUES = {"yes", "true", "1"}


def is_closed(tags: Tags) -> bool:
    return any(tags.get(key, "").lower() in CLOSED_VALUES for key in ("disused", "abandoned", "demolished"))


@dataclass(frozen=True)
class PlaceCategory:
    type: str  # JSON "type", also the id prefix
    # osmium tags-filter expressions selecting candidates (nwr/key=value).
    osmium_filters: Tuple[str, ...]
    # Final say on a candidate's tags; the filter is only a coarse pre-pass.
    matches: Callable[[Tags], bool]
    # JSON key -> OSM tag, copied when present (never required).
    metadata: Mapping[str, str]
    # Tags whose value identifies one physical place: equal values are the
    # same place whatever the distance/name. The first present also forms
    # the stable id ("airport_efou"); otherwise the OSM element does.
    identity_tags: Tuple[str, ...]
    # Same (normalised) name within this distance = the same place.
    dedupe_radius_m: float
    # Which duplicate to keep: earlier element type wins (then more
    # metadata, then lower OSM id). Airports prefer the area (its centroid
    # is the airport), stations the node (the station point itself).
    element_preference: Tuple[str, ...] = ("node", "way", "relation")


def _airport(tags: Tags) -> bool:
    # A passenger/transport destination, not every airfield: the ~60
    # Finnish ICAO-only aerodromes are gliding, private and club fields.
    return (
        tags.get("aeroway") == "aerodrome"
        and not is_closed(tags)
        and (bool(tags.get("iata")) or tags.get("aerodrome") == "international")
    )


# Metro and tram stops are their own networks - a future category, not
# railway stations.
NON_MAINLINE_STATIONS = {"subway", "light_rail", "tram", "monorail", "funicular", "miniature"}


def _railway_station(tags: Tags) -> bool:
    return (
        tags.get("railway") in ("station", "halt")
        and tags.get("station") not in NON_MAINLINE_STATIONS
        and not is_closed(tags)
    )


CATEGORIES: Tuple[PlaceCategory, ...] = (
    PlaceCategory(
        type="airport",
        osmium_filters=("nwr/aeroway=aerodrome",),
        matches=_airport,
        metadata={"iata": "iata", "icao": "icao"},
        identity_tags=("icao", "iata"),
        dedupe_radius_m=5000.0,
        element_preference=("relation", "way", "node"),
    ),
    PlaceCategory(
        type="railway_station",
        osmium_filters=("nwr/railway=station,halt",),
        matches=_railway_station,
        metadata={"station_code": "railway:ref", "uic_ref": "uic_ref", "operator": "operator"},
        identity_tags=("railway:ref", "uic_ref"),
        dedupe_radius_m=1000.0,
    ),
)
