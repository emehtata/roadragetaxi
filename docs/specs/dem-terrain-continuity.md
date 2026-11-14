# DEM terrain on every streamed chunk

## Goal
Chunks built after the map grows get DEM `ground_heights` too. Today only the startup
chunks have them, so the ground goes flat again after a few km of driving.

## Cause (found by reading the code; no long drive was run)
- `server/__init__.py:301` sets `world.dem` once at startup. `ChunkIndex.__init__`
  (`map_chunks.py:270`) reads it with `getattr(world, "dem", None)`, and
  `message()` (`map_chunks.py:677`) leaves out `ground_heights` when `_dem is None`.
- When the map grows, the chunks are rebuilt in the chunk worker process (`server/__init__.py:475-479`).
  `chunk_worker.snapshot()` (`chunk_worker.py:55-89`) pickles only `_REGION_LISTS`
  plus `roadworks`/`speed_cameras` (`chunk_worker.py:88`). It never sends `dem`.
  `_world_from()` (`chunk_worker.py:99`) builds a `SimpleNamespace` that has no `dem`, so
  `build_area()` (`chunk_worker.py:145`) builds `ChunkIndex(...)` with `_dem=None`. The wire bytes it
  returns have no `ground_heights`, and `ChunkIndex.replaced()` (`map_chunks.py:469`)
  sends those bytes to clients as they are. Result: every chunk the worker builds is flat.
- The in-process path is fine: `ChunkIndex.updated()` and `_RegionWorld.__getattr__` pass on
  `world.dem`. That explains why only the start area has terrain.
- `Dem80` cannot be pickled as it is, because `_tile` is an `lru_cache` around a bound method. So the
  fix sends the folders, not the object.

## Fix (smallest)
- `chunk_worker.snapshot()`: add `"dem_dirs"` to `scalars`. Its value is
  `[str(d) for d in world.dem.dirs]` when `world.dem` is a `Dem80`, otherwise `None`.
- `chunk_worker._world_from()`: after the scalars are set, set `world.dem = Dem80(*dirs)` when
  `dem_dirs` is set, otherwise `None`. Each worker keeps its own LRU of 8 tiles. That is fine.
- Legacy `<city>.dem.json` ground (`load_dem`): if its object pickles, send it as
  `scalars["dem"]`. If it does not, leave it out of scope (startup city only).

## Files
- `src/theroadragetrip/chunk_worker.py`: `snapshot`, `_world_from`.
- `tests/test_chunk_worker.py`: new test.

## Acceptance criteria
1. With `world.dem = Dem80(PACKAGED_DEM80)`, `build_area(snapshot(world, area, ...), area, ...)`
   for an area more than 3 km from the start point returns wire bytes for each chunk. Decoded,
   they hold `ground_heights` with non-zero `heights` that are not all equal.
2. Those `ground_heights` equal what `ChunkIndex(world).message(cid)` gives for the same chunk.
3. With `world.dem = None`, the worker chunks have no `ground_heights`, as before.
4. Long drive: after driving about 3 km from a city-centre start, with terrain on and chunk workers on
   (bench or `godot-shot --screenshot-drive`), the debug snapshot shows that the far chunks
   have non-flat `ground_heights`, and the screenshot shows sloped ground.

## Tests to add
- `tests/test_chunk_worker.py::test_worker_chunks_keep_dem_ground_far_from_start`.
  Fails today: the worker world has no `dem`, so `ground_heights` is missing.
- `tests/test_chunk_worker.py::test_worker_chunks_flat_without_dem`. Regression guard for criterion 3.
- No Godot test: the client already renders every `ground_heights` it receives.

## Commands
- `make check`
- `XDG_DATA_HOME=$(mktemp -d) make godot-test`
- The long-drive check from criterion 4, with screenshot and JSON inspected.

## Out of scope
- Tile LRU size, chunk prune, client fallback paths. None of these drop the grid.
- Map-growth thread rebuilds after `server/__init__.py:823`. They go through `updated()` and keep the DEM.

## Status
- Code: `462bfe8d` makes the chunk worker rebuild Dem80 from its folders, so streamed chunks keep `ground_heights`.
- Tester verdict: PASS. Headless bench long drive (180 s, 5262 m east, 13 tiles loaded): all 111 far chunks (over 2 km) have non-constant `ground_heights` from the packaged DEM. This is chunk-data evidence, not a rendered screenshot.
- Open: criterion 4 screenshot NEEDS SCREENSHOT. The `godot-shot --screenshot-drive` attempts were inconclusive (shot.sh timeout), so sloped far ground is not yet seen in the Godot client.
