"""Deterministic 500 m world-tile calculations."""

from __future__ import annotations

import math
from typing import NamedTuple

TILE_SIZE_M = 500.0


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
