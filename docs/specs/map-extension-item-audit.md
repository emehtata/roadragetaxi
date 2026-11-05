# Map items set only at initial load (audit)

## Goal
Every map item that the opening load populates must also appear in tiles merged later
by map extension. This audit lists the items that do not, and gives the smallest fix for each.

## Audit
Extension path: `MapStreamer` merges tiles over every `_WORLD_SECTIONS` list
(`osm/autofetch.py:130`), then `map_sync_steps` (`server/map_sync.py:87-180`) rebuilds
the grids and managers, and `Server._map_grew` (`server/__init__.py:1387`) rebuilds the chunks.

| Item | At load | On extension | Evidence |
|---|---|---|---|
| ways, waters, buildings, sceneries, places | yes | yes, merged | autofetch.py:130 |
| traffic lights, crossings, stop/yield signs, logical intersections | yes | yes, merged, then traffic_mgr.start_map_sync | autofetch.py:131-133, map_sync.py:133 |
| bus stops, taxi stops (fixed earlier), parking spaces/garages, curbs | yes | yes, merged | autofetch.py:131-134 |
| scenery objects (fuel pumps, benches and other furniture), speed bumps, railings | yes | yes, merged | autofetch.py:134 |
| OSM street lamps and their grid | yes | yes, filtered again from scenery_objects | map_sync.py:116-123 |
| placed street lights (`street_light_points`) | yes, server/__init__.py:443 | yes, per dirty area | server/__init__.py:1455-1469 |
| railways, trams, ferries | yes | yes, managers rebuilt | map_sync.py:139-146 |
| level ways/connectors/roads | yes | yes | map_sync.py:175-179 |
| speed cameras | none at load | spawned at runtime and added to chunks | server/__init__.py:1167-1174 |
| **roadworks (and their temporary lights)** | yes, `create_roadworks(ways)` world_loader.py:235 | **no**: nothing creates them for merged ways | world_loader.py:235-236, map_chunks.py:388 |
| **station announcer platforms** | yes, list built from world.ways, server/__init__.py:413 | **no**: never rebuilt | server/__init__.py:412-414 |

## Gaps and fixes
1. **Roadworks.** Three random works are picked once from the opening ways. Extended
   areas never get any, so further from the start there are none.
   Fix: in `map_sync_steps`, after the merge, call
   `create_roadworks(new_ways, count=k)` only for the ways merged in this sync (ways
   not already in a roadwork set). Use a density per km² instead of 3 per map.
   Append the works to `w.roadworks` and their lights to `w.traffic_lights` before
   `traffic_light_grid` is rebuilt and before `CHUNK_INPUTS_READY`.
   Signature: `create_roadworks(ways, count=3) -> (roadworks, lights)` (unchanged).
   Keep the existing roadworks; a way never gets a second work.
   Density rule (`ROADWORKS_PER_KM2 = 1.0`, server/map_sync.py): count =
   `max(1, round(area_km2 * 1.0))`, where `area_km2` is the bounding box of all
   points of the ways newly merged in this sync, in km², and at least 1 whenever
   new ways exist (fewer if there are not enough drivable ways of at least 90 m).
   A sparse or L-shaped batch has a box larger than the land it covers, so the
   count can be overstated; accepted, because works are capped by the candidate
   ways and a batch is at most a few tiles, so the excess stays small.
2. **Announcer platforms.** A station streamed in later is silent.
   Fix: add `StationAnnouncer.set_platforms(platforms: list) -> None` and call it from
   `_apply_map_growth` (when the result is final) with the same platform filter as line 413.
   Move that filter into one helper, `_platform_ways(ways) -> list`.

## Acceptance
1. After a merge and sync that add drivable ways of at least 90 m, `world.roadworks`
   contains at least one work on a merged way, and the chunk holding its midpoint has a
   `roadworks` entry.
2. Lights for the new roadwork are in `world.traffic_lights` and `traffic_light_grid`.
   NPCs stop at them, which the existing roadwork-light tests check.
3. A second sync over the same tiles adds no more roadworks.
4. After a growth adds a `highway=platform` way, `server.announcer` knows that platform,
   and a train stop next to it gives an announcement.

## Tests to add
- `tests/test_server_map_sync.py::test_extension_adds_roadworks_on_merged_ways`:
  merge a tile world with long drivable ways and run `map_sync_steps` to the end.
  Assert a new roadwork, its lights in `traffic_lights`, and a roadworks chunk entry.
  Without the fix, `roadworks` stays as it was at load and the test fails.
- `tests/test_server_map_sync.py::test_second_sync_adds_no_duplicate_roadworks`.
- `tests/test_station_announcer.py::test_platforms_from_map_growth_are_announced`:
  call `set_platforms` with a new platform near a stop, then assert `event(...)` speaks.
  Without the fix the method does not exist and the server never refreshes the list.
- Render (DEFERRED, not met): a `roadworks_after_extension` scenario would need a roadwork
  in view. Generated roadworks land in a different place each run (shared random generator,
  tiles arrive in a different order), so the pose cannot be fixed. The fix is to seed the
  picks from the OSM ids of the new roads, or to feed a fixed roadworks list to the scenario.
  Until then the behaviour is covered by the unit tests above only.

## Out of scope
- Live Digitraffic roadworks (`live_roadworks`): these are fetched for the whole area, not per tile.
- Taxi stops: already merged (`osm/autofetch.py:131`).
- DEM ground (`world.dem`): one file per city, by design.
