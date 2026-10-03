"""Player-centred map streaming for clients without their own map data
(the Godot client): the loaded OSM world cut into a square grid of chunks.

A chunk is identified by its grid cell, "ix_iy" with ix = floor(x / size).
It holds every road, railway, water and building with at least one vertex
in the cell, so a long road is in each chunk it passes through, and
clients draw it once per loaded chunk. Python decides which chunks a
client needs (`plan`); the client only adds and removes what it's told.
Built from the same world objects the simulation uses - no second map model.
"""

from __future__ import annotations

import math

from .protocol import PROTOCOL_VERSION, _line

CHUNK_SIZE_M = 500.0
LOAD_RADIUS = 3    # chunks around the player's chunk that must be loaded (7 x 7, >= 1.5 km each way)
UNLOAD_RADIUS = 4  # loaded chunks are dropped beyond this - the gap stops edge flapping


def chunk_id(ix: int, iy: int) -> str:
    return f"{ix}_{iy}"


def cell_of(x: float, y: float, size: float = CHUNK_SIZE_M) -> tuple[int, int]:
    return math.floor(x / size), math.floor(y / size)


def plan(loaded: set, center: tuple[int, int], load_radius: int = LOAD_RADIUS,
         unload_radius: int = UNLOAD_RADIUS) -> tuple[list[str], list[str]]:
    """(chunk ids to send, chunk ids to drop) for a client with `loaded`
    chunks around the player's cell `center`. Nearest chunks first."""
    cx, cy = center
    wanted = sorted(
        ((ix, iy) for ix in range(cx - load_radius, cx + load_radius + 1)
         for iy in range(cy - load_radius, cy + load_radius + 1)),
        key=lambda cell: max(abs(cell[0] - cx), abs(cell[1] - cy)),
    )
    to_load = [chunk_id(*cell) for cell in wanted if chunk_id(*cell) not in loaded]
    to_drop = []
    for cid in sorted(loaded):
        ix, iy = (int(part) for part in cid.split("_"))
        if max(abs(ix - cx), abs(iy - cy)) > unload_radius:
            to_drop.append(cid)
    return to_load, to_drop


class ChunkIndex:
    """The world's static geometry bucketed by chunk, built once (the map
    doesn't change during a session)."""

    def __init__(self, world, size: float = CHUNK_SIZE_M):
        self.size = size
        self._chunks: dict[str, dict] = {}
        for way in world.ways:
            if len(way.points_m) >= 2:
                self._add("roads", way.points_m, {
                    "points": _line(way.points_m), "half_width_m": way.half_width_m, "kind": way.highway or "",
                    "drivable": bool(way.is_drivable), "layer": way.layer,
                })
        for rail in world.railways:
            if len(rail.points_m) >= 2:
                self._add("railways", rail.points_m, _line(rail.points_m))
        for water in world.waters:
            if len(getattr(water, "points_m", ())) >= 3:
                self._add("waters", water.points_m, _line(water.points_m))
        for building in world.buildings:
            if len(building.points_m) >= 3:
                self._add("buildings", building.points_m, _line(building.points_m))

    def _add(self, kind: str, points, feature) -> None:
        for cell in {cell_of(x, y, self.size) for x, y in points}:
            chunk = self._chunks.setdefault(chunk_id(*cell), {"roads": [], "railways": [], "waters": [], "buildings": []})
            chunk[kind].append(feature)

    def message(self, cid: str) -> dict:
        """The "chunk" message for one chunk (an empty one outside the map,
        so the client knows it has it)."""
        ix, iy = (int(part) for part in cid.split("_"))
        content = self._chunks.get(cid, {"roads": [], "railways": [], "waters": [], "buildings": []})
        return {
            "type": "chunk", "version": PROTOCOL_VERSION, "chunk_id": cid,
            "bounds": [ix * self.size, iy * self.size, (ix + 1) * self.size, (iy + 1) * self.size],
            **content,
        }
