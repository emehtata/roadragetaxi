# Remove three duplicates (no behaviour change)

## Goal
Delete dead/duplicated code: `WorldCache.tile_id`, `trains._segment_distance`,
and the doubled `OVERPASS_FORCE_REFRESH` env parsing.

## Files to change
- `src/theroadragetrip/world_cache.py` (~509): delete staticmethod `tile_id(tile) -> str`.
  Grep (`\btile_id\b` over src, tests, tools, godot) found only the definition: zero callers.
  Re-run the grep before deleting; if a caller appears, stop and report.
- `src/theroadragetrip/trains.py` (~288): delete `_segment_distance(point, a, b)`.
  Its one caller (~683) becomes
  `geo.dist_point_to_segment(mine[0], mine[1], a[0], a[1], b[0], b[1])`
  (import from `.geo` per file's existing import style; `mine`, `a`, `b` are (x, y) tuples).
  Drop `math` import only if now unused.
- `src/theroadragetrip/osm/overpass.py` (~217): add helper
  `def force_refresh_requested(force_refresh: bool = False) -> bool` returning
  `force_refresh or os.getenv("OVERPASS_FORCE_REFRESH", "0").lower() in ("1", "true", "yes")`;
  use it at the existing line.
- `src/theroadragetrip/osm/pbf_source.py` (~116): import the helper from `.overpass`, replace the inline expression; remove `os` import if unused.

## Acceptance criteria
1. `grep -rnw tile_id src tests tools godot` returns nothing.
2. `grep -rn _segment_distance src tests tools` returns nothing.
3. `grep -rn OVERPASS_FORCE_REFRESH src` matches only the helper in overpass.py.
4. Argument order verified: geo takes (px, py, ax, ay, bx, by); trains' version took (point, a, b). Both clamp t to [0,1] and return hypot to the closest point; zero-length segment returns distance to a in both. Results identical (same float ops).
5. Helper: unset/"0"/"" -> False; "1", "true", "YES" -> True; `force_refresh=True` arg -> True regardless of env. Same as before in both call sites.
6. No other files changed.

## Tests to add
- `tests/test_cache.py` (covers overpass cache loading):
  `test_force_refresh_requested_env_values` - monkeypatch env over the values above. Fails without the fix (helper doesn't exist).
- `tests/test_trains.py`: `test_platform_clearance_matches_geo_segment_distance` - assert
  `geo.dist_point_to_segment` on a point projecting inside, past each end, and onto a zero-length segment gives expected distances (3-4-5 cases), and that the platform-clearance check in trains (~683) still flags/ignores a pair on each side of PLATFORM_CLEARANCE_M. Existing train tests cover the rest.
- No test for `tile_id` removal (grep criterion covers it).

## Commands for the tester
```
cd /home/ubuntu/work/theroadragetrip
grep -rnw tile_id src tests tools godot
grep -rn _segment_distance src tests tools
grep -rn OVERPASS_FORCE_REFRESH src
python -m pytest -n auto tests/test_world_cache.py tests/test_pbf_source.py tests/test_pbf_index.py \
  tests/test_trains.py tests/test_train_routing.py tests/test_train_timetable.py \
  tests/test_train_compositions.py tests/test_train_passengers.py tests/test_cache.py
```

## Out of scope
`TaxiManager.notify_rail_booking` (taxi.py), the activities plugin layer, any other cleanup.
