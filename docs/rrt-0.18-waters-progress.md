# 0.18 water geometry: audit, fixes and resume point

2026-10-17, branch `release/0.18.0alpha`, starting commit `fd514d1`.
Task: `.github/prompts/rrt-018-waters.md`.

## Evidence and scope

Screenshot `1792189663091342080` shows apparent flooding around Merikosken
sillat, Oulu; taxi (427808.8260, 7211598.6741), EPSG:3067. This screenshot
alone does not identify the originating water feature. No traffic, PBF
stuttering, rendering-mask or binary-map architecture changes are included.

Read the collection/projection/area/relation paths in `osm/build.py`, both
online/PBF fetch paths, fetched-bound metadata, normalized-world cache handling,
`map_chunks.py` and Godot's water clipping/drawing. Both data sources reach the
same builder. Raw ways keep their direction when projected. Sea uses the existing
inner projected rectangle of the fetched geographic bbox; bounds are not expanded.
Unbounded road geometry must not enlarge the sea region. Without fetched bounds,
the builder still does not synthesize sea.

The client receives closed, hole-free Water rings, clips to chunks and fills
them. Open streams/rivers are lines, not inferred polygons. No client workaround
is needed for the confirmed server geometry bugs below.

## Confirmed defects

1. Coastline collection was inside an exclusive feature-classification chain.
   In the local Oulu cache, coastline ways also carry fence/wall, weir or
   boatyard tags. Those ways were collected as barriers or ordinary water,
   not coastline. This breaks otherwise complete coastline topology; a closed
   coastline tagged boatyard could itself become filled water. Collection is
   now independent of those tags, retaining barriers and excluding coastlines
   from ordinary water fills. Missing node references retain separate fragments
   and emit diagnostics rather than dropping an entire way or joining a gap.
2. `_sea_polygons` split the region and classified each entire face from the
   nearest arbitrary segment to its representative point. Complete cached Oulu
   coastline reproduces a false sea face covering **8,721.7534 m²** of island
   way **118133030**, including (426799.7722, 7210908.3588). Before sea area:
   1,645,971.1555 m²; after: 1,637,249.4022 m². This is a confirmed real
   geometry regression, not proof that every blue pixel in the screenshot has
   the same cause.
3. Water relations stitched only outer ways; inner island rings were ignored.
   They now preserve islands, including an actual inner area of Oulu relation
   **16252045** at (428070.8496, 7211516.0275). Duplicate standalone tagged
   member areas cannot refill the relation's holes. Legacy riverbank relations
   now use the same area path. Open outer chains remain lines, not invented
   closures; incomplete/invalid inner data withholds area filling with warnings.
4. Invalid closed standalone water geometry could reach polygon rendering.
   It now emits a warning and remains linework instead of an invalid fill.

## Geometry algorithm

- Clip directed coastline to the intended region, node the linework with
  `unary_union`, combine it with the region boundary, then `polygonize_full`.
- Check invalid/self-crossing/branching linework and report cuts/dangles/invalid
  rings. Faces touched by unresolved fragments are not filled as sea.
- Orient each face exterior counterclockwise and holes clockwise. Compare its
  actual shared boundary edges with the original directed coastline: a matching
  direction places the face on the coastline's land-left side; opposite places
  it on sea-right. A face needs consistent sea evidence, not a nearest-point
  guess. Conflicting/unclassified faces are withheld with diagnostics.
- A valid complete enclosing coastline ring can classify an entirely offshore
  or inland region without a crossing inside it. Unknown space is never sea by
  default. No buffers, endpoint offsets, gap bridges or fabricated coast closures.
- Preserve island holes by exact polygon subtraction and splitting through holes
  into valid hole-free rings, compatible with existing Water objects and wire
  messages. Split failure is diagnostic and conservative. No one-square-metre
  discard threshold is used for valid tiny water pieces.

The normalized-world cache generation version is bumped **32 → 33** so cached
bad water is rebuilt on next load rather than retained until TTL expiry. Raw OSM
caches remain usable; no PBF reindex/redownload or new fetch extent is needed.

## Fixture and validation

Files in this slice: `src/theroadragetrip/osm/build.py`,
`src/theroadragetrip/world_cache.py`, `tests/test_coastline_geometry.py`,
`tests/fixtures/oulu_waters.json`, this record, the main 0.18 progress record,
and the supplied `.github/prompts/rrt-018-waters.md` task specification.

`tests/fixtures/oulu_waters.json` contains only water/coastline features, relation
members and referenced nodes from the available local Oulu OSM cache. It preserves
IDs/tags and topology, projected once into EPSG:3067, independent of process-wide
fake pyproj modules in older tests. Source/attribution and bounds are embedded.
Data: © OpenStreetMap contributors, [ODbL](https://www.openstreetmap.org/copyright).

Deterministic tests cover straight/joined/bent coastline, bay/peninsula, multiple
islands and narrow channels, exact/near boundary endpoints, gaps/dangles, reversed
overlapping linework, self-crossings, inland/known offshore/unknown regions, all
sea geometry validity/bounds, final builder Water objects, collection with extra
tags, missing nodes, lakes/reservoirs/riverbanks, stitched relation members and
incomplete island rejection. The real fixture checks both mapped dry land and
retained water; it does not merely assert that the sea list is empty.

Focused suites: **175 passed** (2.08 s). Full suite: **1,686 passed, 2 skipped**
(52.21 s). `make compile` and `git diff --check` pass. The repository defines
no separate lint/formatter/type-check target; supported checks are pytest,
compileall and diff-check (`make check`). No dependencies added.

## Limits and exact next step

- The first complete-enough cached coastal case is verified. The selected point
  east of the screenshot bridge was already dry in the available old initial
  cache, while the screenshot shows wider apparent flooding. Therefore **do not
  mark the entire screenshot-wide flooding fixed yet**. Re-run the same location
  after rebuilding version-33 water; if it persists, capture the actual active
  chunk water polygons and identify the covering source feature. Check streamed
  tile overlaps and client clipping against those exact polygons. Do not invent
  a coastline offset or screen mask.
- Completely offshore regions without a complete enclosing ring or usable local
  directed boundary remain unclassified. Missing/invalid geometry may omit real
  sea rather than flood unknown land. A trusted land/sea context dataset would
  be a separate, measured follow-up, not a default sea assumption.
- A water-only replay using the available version-32 initial-world cache and
  rebuilt fixture was rendered with Godot/OpenGL at the snapshot's reported
  camera coordinates. Neither reproduced the broad blue fill in that viewport.
  Diagnostic inputs/script/images remain at `/tmp/rrt-water-replay.{json,gd}`
  and `/tmp/rrt-water-{cached,rebuilt}.png`. Capture the actual active client
  chunks/camera instead of claiming the screenshot fixed from an initial-cache
  comparison. No replay code or rendering mask is shipped.
- Broken relation inner data withholds the relation's area: omitted water is
  preferable to fabricated island flooding. Diagnostics identify incomplete
  member IDs; acquiring missing context is not implemented here.
- This fixture does not certify all Finnish coastlines or every map-source tile.
  Gameplay/FPS was not benchmarked; no PBF performance work was attempted.
- The ordinary `waterway=*` path still accepts non-coastline closed ways such
  as boatyards as water. Audit these tag semantics next; do not confuse a yard,
  dam or weir with an open-water area, or break genuine docks/river areas.
- Keep unrelated untracked `license-audit.md` and `roadragetaxi.code-workspace`
  untouched. Continue the broader 0.18 work from `rrt-0.18-progress.md` separately.
