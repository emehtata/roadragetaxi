"""Which country a point is in, for the "out of Finland" notice.

assets/borders.json.gz (tools/osm/build_borders.py): Finland's outline,
territorial waters included, from OSM (within ~20 m), and its neighbours'
from Natural Earth (within ~200 m: they only name the country once a point
is outside Finland), in EPSG:3067 metres.
"""
from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.prepared import prep

ASSET = Path(__file__).parent / "assets" / "borders.json.gz"
FINLAND = "FIN"
NEIGHBOUR_REACH_M = 10_000.0  # outside Finland, this near a neighbour's coarse coast is in it (its islands, harbours)


def _area(rings_per_polygon):
    return MultiPolygon([Polygon(rings[0], rings[1:]) for rings in rings_per_polygon])


@lru_cache(maxsize=1)
def _countries():
    with gzip.open(ASSET, "rt", encoding="utf-8") as f:
        data = json.load(f)
    areas = [(FINLAND, _area(data["finland"]))] + [(code, _area(rings)) for code, rings in data["neighbours"].items()]
    return [(code, area, prep(area)) for code, area in areas]


def country_at(x: float, y: float) -> Optional[str]:
    """The country (ISO 3166 alpha-3: FIN, SWE, NOR, RUS, EST) at EPSG:3067
    (x, y); None at sea outside every territorial water, or further away."""
    point = Point(x, y)
    countries = _countries()
    inside = next((code for code, _area, prepared in countries if prepared.contains(point)), None)
    if inside is not None:
        return inside
    distance, code = min((area.distance(point), code) for code, area, _prepared in countries[1:])
    return code if distance <= NEIGHBOUR_REACH_M else None


class BorderWatch:
    """The taxi's country (`country`), checked once a second (a point test:
    ~20 us in Finland): update() also returns the country it has just
    crossed into from Finland (or started in), once per crossing; else None."""
    CHECK_S = 1.0

    def __init__(self) -> None:
        self.country: Optional[str] = FINLAND
        self._elapsed = self.CHECK_S

    def update(self, dt: float, x: float, y: float) -> Optional[str]:
        self._elapsed += dt
        if self._elapsed < self.CHECK_S:
            return None
        self._elapsed = 0.0
        previous, self.country = self.country, country_at(x, y)
        return self.country if self.country not in (None, FINLAND) and previous != self.country else None


if __name__ == "__main__":
    from pyproj import Transformer
    to_m = Transformer.from_crs("EPSG:4326", "EPSG:3067", always_xy=True).transform
    for lon, lat, expected in ((24.94, 60.17, "FIN"), (24.18, 65.85, "FIN"), (24.12, 65.83, "SWE"),  # Tornio, Haparanda
                               (19.94, 60.10, "FIN"), (18.07, 59.33, "SWE"), (28.70, 60.70, "RUS"),  # Mariehamn, Vyborg
                               (24.75, 59.44, "EST"), (23.75, 69.97, "NOR"), (20.5, 59.0, None)):  # Tallinn, Alta, open Baltic
        assert country_at(*to_m(lon, lat)) == expected, (lon, lat, country_at(*to_m(lon, lat)))
    print("ok")
