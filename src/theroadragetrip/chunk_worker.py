"""Map chunk rebuilds in a worker process.

After a tile merge the server rebuilds the chunks (and street lights) of the
changed area: seconds of pure Python that, on the map-growth thread, took a
quarter of the GIL from the ticks and made the client's state late at speed.
Here the area's slice of the world goes to a spawned worker in small pickles
(each a short GIL hold, unlike one big one), the worker places the lamps,
builds the chunks and encodes them, and the server takes back plain bytes.

The worker rebuilds the same grids from the slice, so its lamps and chunks
are the ones ChunkIndex.updated() gives in process (tests/test_chunk_worker).
"""
from __future__ import annotations

import pickle
from types import SimpleNamespace

from .map_chunks import _REGION_LISTS, REGION_MARGIN_M, ChunkIndex, _item_rect, cell_of, chunk_id

# Around the chunks an area rebuilds (they reach past it to whole chunks):
# everything their lamps and contents look at (junctions, buildings by a
# road, a yard's street, shores) lies within this.
SNAPSHOT_MARGIN_M = 300.0
# Objects per pickle: a few ms of GIL each on the map-growth thread.
PIECE_SIZE = 500
# An explicit street lamp is matched to a road anywhere along the road's bbox.
LAMP_REACH_M = 60.0
_HIDDEN_LIGHT = SimpleNamespace(renderable=False)  # keeps the other lights' ids (their list index)


def _overlaps(r, rect) -> bool:
    return r is None or (r[0] <= rect[2] and r[2] >= rect[0] and r[1] <= rect[3] and r[3] >= rect[1])


def area_cells(area, size: float) -> set:
    first, last = cell_of(area[0], area[1], size), cell_of(area[2], area[3], size)
    return {(ix, iy) for ix in range(first[0], last[0] + 1) for iy in range(first[1], last[1] + 1)}


def snapshot(world, area, lights, size: float) -> list[bytes]:
    """`world`'s objects that the rebuild of `area` reads, as pickles of at
    most PIECE_SIZE objects: [(name, items)] pieces, then the scalars."""
    cells = area_cells(area, size)
    (x0, y0), (x1, y1) = min(cells), max(cells)
    m = SNAPSHOT_MARGIN_M
    rect = (min(area[0], x0 * size) - m, min(area[1], y0 * size) - m,
            max(area[2], (x1 + 1) * size) + m, max(area[3], (y1 + 1) * size) + m)
    lists = {}
    for name in _REGION_LISTS:
        if name == "street_light_points":
            continue
        lists[name] = [item for item in getattr(world, name, ()) if _overlaps(_item_rect(item), rect)]
    lamp_rect = rect
    for way in lists["ways"]:
        r = _item_rect(way)
        if r is not None:
            lamp_rect = (min(lamp_rect[0], r[0]), min(lamp_rect[1], r[1]), max(lamp_rect[2], r[2]), max(lamp_rect[3], r[3]))
    lamp_rect = (lamp_rect[0] - LAMP_REACH_M, lamp_rect[1] - LAMP_REACH_M, lamp_rect[2] + LAMP_REACH_M, lamp_rect[3] + LAMP_REACH_M)
    lists["street_lamps"] = [lamp for lamp in getattr(world, "street_lamps", None) or ()
                             if _overlaps(_item_rect(lamp), lamp_rect)]
    lists["street_light_points"] = [lamp for lamp in lights if _overlaps(_item_rect(lamp), rect)]
    lists["traffic_lights"] = [light if _overlaps((light.x, light.y, light.x, light.y), rect) else _HIDDEN_LIGHT
                               for light in getattr(getattr(world, "traffic_mgr", None), "traffic_lights", ())]
    pieces = []
    for name, items in lists.items():
        pieces.extend(pickle.dumps((name, items[start:start + PIECE_SIZE]), pickle.HIGHEST_PROTOCOL)
                      for start in range(0, len(items), PIECE_SIZE))
        if not items:
            pieces.append(pickle.dumps((name, []), pickle.HIGHEST_PROTOCOL))
    scalars = {"roadworks": list(getattr(world, "roadworks", ())), "speed_cameras": list(getattr(world, "speed_cameras", ()))}
    pieces.append(pickle.dumps(("", scalars), pickle.HIGHEST_PROTOCOL))
    return pieces


def _world_from(pieces):
    from .map_level import SURFACE_LEVEL
    from .physics import SpatialWayGrid

    world = SimpleNamespace()
    for piece in pieces:
        name, items = pickle.loads(piece)
        if not name:
            for key, value in items.items():
                setattr(world, key, value)
        else:
            getattr(world, name, None) or setattr(world, name, [])
            getattr(world, name).extend(items)
    world.traffic_mgr = SimpleNamespace(traffic_lights=world.traffic_lights)
    world.spatial_grid = SpatialWayGrid(map_level=SURFACE_LEVEL)
    world.spatial_grid.rebuild(world.ways)
    world.building_grid = SpatialWayGrid()
    world.building_grid.rebuild(world.buildings)
    world.street_lamp_grid = SpatialWayGrid()
    world.street_lamp_grid.rebuild(world.street_lamps)
    # As the server's: a water the grid doesn't index (no extent) is no
    # obstacle to a bonfire or flag pole there, so the list is no stand-in.
    world.water_grid = SpatialWayGrid()
    world.water_grid.rebuild(world.waters)
    return world


def build_area(pieces, area, size: float, place_lamps: bool):
    """Worker entry point. (new lamps for `area` - None unless `place_lamps` -,
    [(chunk id, pickled content, wire bytes)]) for every chunk touching it,
    built as ChunkIndex.updated() builds them, with the area's lamps replaced."""
    from .server import place_street_lights

    world = _world_from(pieces)
    lamps = None
    if place_lamps:
        lamps = place_street_lights(world, region=area)
        world.street_light_points = [
            lamp for lamp in world.street_light_points
            if not (area[0] <= lamp[0] <= area[2] and area[1] <= lamp[1] <= area[3])
        ] + lamps
    cells = area_cells(area, size)
    first = min(cells)
    last = max(cells)
    from .map_chunks import _RegionWorld

    index = ChunkIndex(_RegionWorld(world, (first[0] * size - REGION_MARGIN_M, first[1] * size - REGION_MARGIN_M,
                                            (last[0] + 1) * size + REGION_MARGIN_M,
                                            (last[1] + 1) * size + REGION_MARGIN_M)), size, cells)
    chunks = []
    for cell in cells:
        cid = chunk_id(*cell)
        content = index._chunks.get(cid)
        chunks.append((cid, None if content is None else pickle.dumps(content, pickle.HIGHEST_PROTOCOL), index.encoded(cid)))
    return lamps, chunks
