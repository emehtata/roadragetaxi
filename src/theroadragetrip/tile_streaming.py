"""Deterministic world-tile calculations."""

from __future__ import annotations

import math
from typing import NamedTuple

TILE_SIZE_M = 1000.0

# The active window is always the 3x3 grid around the player (see
# active_tiles below), so its worst-case single fetch - the full 3x3, hit
# on the initial load and on any diagonal-ish move - is 3x this value on a
# side. Calibrated so that worst case is ~10x10km: measured end-to-end
# (osmium extract + XML parse + build_ways) against the real Finland PBF,
# 10x10km/100km^2 takes ~28s and ~530MB, while 25x25km already balloons to
# ~80s/1GB and 30x30km (literal 10km tiles) would land in between those -
# a real, noticeable stall on every tile transition instead of only the
# initial load. Only used for osm_source=pbf (see main()) - Overpass
# fetches at this size would risk the query timing out or tripping a
# public instance's response-size limits, and don't share the local
# extract's "worth it once you're already scanning the whole file" appeal.
PBF_TILE_SIZE_M = 3300.0


def set_tile_size_m(meters: float) -> None:
    """Override the world-tile grid size (see PBF_TILE_SIZE_M above for
    why osm_source=pbf uses a bigger one). Must be set once, before any
    AutoFetchManager/tile coordinates are computed - tile coordinates
    computed under one size aren't valid under another, so changing this
    mid-session would corrupt an already-running manager's bookkeeping.
    """
    global TILE_SIZE_M
    TILE_SIZE_M = meters


class TileCoord(NamedTuple):
    x: int
    y: int


def world_to_tile(x: float, y: float) -> TileCoord:
    return TileCoord(math.floor(x / TILE_SIZE_M), math.floor(y / TILE_SIZE_M))


def tile_bbox(tile: TileCoord) -> tuple[float, float, float, float]:
    min_x = tile.x * TILE_SIZE_M
    min_y = tile.y * TILE_SIZE_M
    return min_x, min_y, min_x + TILE_SIZE_M, min_y + TILE_SIZE_M


def active_tiles(center: TileCoord) -> frozenset[TileCoord]:
    return frozenset(
        TileCoord(center.x + offset_x, center.y + offset_y)
        for offset_x in (-1, 0, 1)
        for offset_y in (-1, 0, 1)
    )


def tile_changes(previous: set[TileCoord], current: set[TileCoord]) -> tuple[set[TileCoord], set[TileCoord]]:
    return current - previous, previous - current
