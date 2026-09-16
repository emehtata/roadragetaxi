# RENDER-audit.md — final report

Evidence-based; every claim below was checked against the actual parser
(`osm/build.py`), the internal dataclasses (`osm/__init__.py`), the renderer
(`render/*.py`), and real cached OSM data
(`osm_cache/bbox_64p99848_25p43601_65p02552_25p49999.json`, Oulu, 129,569
elements) — not assumed from the spec's own examples.

## 1. Current OSM rendering coverage

Rendered today, each with its own `draw_*` function: roads (all `highway=*`
types, distinct colors per type incl. `cycleway`), curbs (outline + raised/
scrub-fill), railings/fences/hedges/walls, railways (rail/light_rail/tram/
narrow_gauge/funicular), buildings (walls, roof, windows, commercial signage),
water (natural=water/bay/strait, waterway=*, landuse=reservoir), scenery
areas (all `leisure=*`/`landuse=*`/most `natural=*` land-cover values, ~35
distinct kinds, most speckle-textured), scenery point objects (bench,
waste_basket, bicycle_parking, statue, picnic_table, firepit, fountain,
fuel, gate, bollard), parking spaces, parking lots, traffic lights, stop
signs, yield signs (added this session, section 21 below), crossings, speed
bumps, bus stops/platforms (as point markers), taxi stops, trees, street
lights (synthesized, not OSM-tagged), traffic islands (added this session,
section 15).

## 2. Important OSM features currently missing

Grounded in what the parser reads (or explicitly discards) tag-by-tag:

* ~~Stop signs and yield signs have no visual representation~~ — **fixed
  this session, see section 21.** Correction to this report's first pass:
  `StopSign`/`YieldSign` were parsed and even snapped onto their road
  (`_snap_to_nearest_road`), but a closer check of the actual call graph
  (not just the dataclass docstring's claim) found `traffic_world.py`
  never reads either one — `TrafficWorld.sync_map_data` accepts
  `stop_signs` as a keyword and silently drops it into `**_kwargs`. So
  this was parsed-but-invisible *and* parsed-but-logically-unused, not
  "invisible sign, real behavior" as first reported.
* **`sidewalk=left/right/both` on a road is never read.** A pedestrian path
  only exists in-game if it's mapped as its own `highway=footway`/`path`
  way; a road tagged `sidewalk=both` with no separate footway way renders
  with no sidewalk at all, even though OSM says one exists.
* **On-road cycle lanes (`cycleway:right=lane`, `cycleway:left=lane`, etc.)
  are not read.** Only a standalone `highway=cycleway` way is parsed as a
  distinct cycleway; a lane painted on an ordinary road is invisible.
* **`kerb=raised/lowered/flush` and `tactile_paving=yes` are not read.**
  Every curb renders identically regardless of whether it's a dropped-kerb
  pedestrian ramp or a full-height barrier kerb.
* **A `public_transport=platform` mapped as an area way is collapsed to its
  centroid point** (`osm/build.py:991-1000`) — its actual platform shape/
  footprint is discarded, not just left unrendered elsewhere.
* **Parking metadata is parsed nowhere**: `capacity`, `disabled=yes`,
  `parking=underground/multi-storey`, `access=private/customers` on
  `amenity=parking` are all dropped at parse time — every lot renders
  identically regardless of type or access.

## 3. Features parsed but not rendered

* ~~`StopSign` / `YieldSign`~~ — fixed this session (section 21).

## 4. Features not currently parsed

* `sidewalk=*` tag values (road-attached sidewalks)
* `cycleway:left=*` / `cycleway:right=*` / `cycleway:both=*` (on-road cycle
  lanes, as opposed to standalone `highway=cycleway` ways)
* `kerb=*` value and `tactile_paving=*`
* `amenity=parking` sub-attributes: `capacity`, `disabled`, `parking`
  (surface/underground/multi-storey), `access`, `fee`
* `highway=street_lamp` nodes (street lights are synthetically placed by
  heuristic, real lamp-post positions from OSM are never consulted)
* `amenity=drinking_water`, `amenity=vending_machine`, `advertising=*`
  (billboard/totem — smaller street-furniture categories, spot-checked,
  confirmed absent from `_scenery_object_kind`)

## 5. Traffic island representations found in the data

Checked all 4 real `traffic_calming=island` / `area:highway=traffic_island`
ways in the Oulu extract before implementing: none were literally closed
rings (`pts[0] == pts[-1]`) — each traces one curved side of a small island
with a several-meter gap between its first/last node. All 4 were compact in
both dimensions (3–12 m span, ≥2.3 m in the narrower direction). A separate
size-only heuristic (max span ≤ 25 m) over the full curb-way population
matched 451/818 ways — most of them ordinary short curb segments, not
islands — because a real curb segment is also frequently mapped in short
pieces. Adding a minimum-width filter (≥1.5 m in the narrower dimension,
since an ordinary curb line is a near-zero-width sliver perpendicular to
its own direction) cut that to 302, and cross-checking the explicit
`area:highway=traffic_island` tag showed 51 of those 302 carry it directly.

## 6. Traffic island implementation

Implemented in `osm/build.py`'s existing `curb_raw` processing loop: a kerb
shape with no `natural=`/`landuse=`/`leisure=` area tag now additionally
emits a `Scenery(kind="traffic_island")` when it carries the explicit tag
*or* passes the size+width heuristic above. Reuses the existing `Curb` (for
the physical, non-drivable outline — already checked by `route_stays_on_road`
and the NPC footprint validator, so NPCs already can't drive across a
traffic island's curb without any new collision code) and `Scenery`
dataclasses; zero new classes, per section 16's "no special-case renderer
per tag" goal. `render/scenery.py` renders it as a flat fill (color
`(150, 148, 140)`, not added to `_SPECKLE_SCENERY_KINDS` since a small
traffic island reads as bare pavement/gravel, not turf).

## 7. Other high-priority rendering gaps

In order, reasoning below:

1. ~~Stop/yield sign visuals~~ — implemented this session (section 21).
2. **Sidewalks via `sidewalk=*`** — in real OSM data, attaching sidewalk
   tags to the road is at least as common as mapping a separate footway
   way, so this gap silently removes real pedestrian infrastructure that
   the extract actually contains.
3. **On-road cycle lanes** — same shape of gap as sidewalks; a
   `cycleway=lane` road looks identical to one with no cycling provision.
4. **Kerb ramps / tactile paving at crossings** — affects pedestrian-AI
   crossing behavior realism more than pure visuals, but is cheap (one
   more tag read on an already-parsed feature).

## 8. Changes made (this pass)

* `osm/build.py`: `MAX_TRAFFIC_ISLAND_SPAN_M`, `MIN_TRAFFIC_ISLAND_WIDTH_M`
  constants; extended `curb_raw` loop to emit `Scenery(kind="traffic_island")`.
* `render/scenery.py`: `"traffic_island"` color added to `SCENERY_COLORS`.
* `render/common.py`: added `screen_to_world()` (exact inverse of
  `world_to_screen()`).
* `main/debug_tools.py`: added `find_feature_at()` / `_nearest_boundary_distance()`
  — section 19's feature inspector query.
* `render/hud.py`: added `draw_feature_inspector_panel()`.
* `main/__init__.py`: wired F4 to toggle the inspector, mouse click to query
  `find_feature_at` at the clicked world position, per-frame panel draw.
* Tests: `tests/test_scenery_and_buildings.py` (traffic-island fill test),
  `tests/test_curbs.py` (island-vs-ordinary-curb discrimination), 
  `tests/test_debug_tools.py` (`screen_to_world` inverse property,
  `find_feature_at` nearest-match/inside-polygon/no-match cases).
* `osm/models.py`/`osm/build.py`: added `direction_angle`/`road_half_width_m`
  to `StopSign`/`YieldSign`, snapped both onto their nearest road (same
  `_snap_to_nearest_road` pool as crossings/speed bumps) and offset out to
  the roadside on whichever side the raw OSM node itself leans towards.
* `render/roads.py`: `draw_stop_signs()` (red octagon + "STOP"),
  `draw_yield_signs()` (downward triangle), both a plain pole + pygame
  primitives, no new spatial grid (see section 10).
* `main/__init__.py`: `yield_signs` was parsed but dropped before ever
  reaching the `world` object returned by `_load_world` — added
  `yield_signs=yield_signs` to that `SimpleNamespace` and pulled it into
  the render loop's local scope alongside the (already-present)
  `stop_signs`, then wired both new draw calls in next to `draw_taxi_stops`.
* Tests: `tests/test_road_signs.py` (parse+snap, opposite-side placement,
  world-cache round-trip, render pixel checks, viewport culling).

## 9. Files changed

`src/theroadragetrip/osm/build.py`, `src/theroadragetrip/osm/models.py`,
`src/theroadragetrip/render/scenery.py`, `src/theroadragetrip/render/roads.py`,
`src/theroadragetrip/render/common.py`, `src/theroadragetrip/render/hud.py`,
`src/theroadragetrip/render/__init__.py`, `src/theroadragetrip/main/__init__.py`,
`src/theroadragetrip/main/debug_tools.py`, `tests/test_scenery_and_buildings.py`,
`tests/test_curbs.py`, `tests/test_debug_tools.py`, `tests/test_road_signs.py`.

## 10. Performance considerations

Traffic islands ride the existing `Scenery`/`Curb` static-cache and
incremental-rebuild pipeline — no new per-frame cost, no new spatial index.
The size/width heuristic runs once at world-build time, not per frame. The
feature inspector (`find_feature_at`) does a plain linear scan across every
category, but only on a deliberate mouse click while a debug toggle is on —
never in the per-frame render path — so it doesn't need the spatial-grid
treatment that everything in `render/*.py` proper does.

## 11. Recommended next rendering features

In priority order, matching section 14's categories:

**High** (directly affects driving/pedestrian realism): ~~stop/yield sign
visuals~~ (done, section 21), `sidewalk=*`-driven sidewalks, on-road cycle
lanes (`cycleway:*=lane`), platform footprint shape instead of centroid
point. Separately, now that the signs are visible: NPC right-of-way logic
still doesn't read `stop_signs`/`yield_signs` at all (confirmed in section
21) — the sign now visually exists at an intersection an NPC may still
drive straight through without slowing, which is a bigger, separate
behavioral feature, not a rendering one.

**Medium** (environmental detail): `kerb=*`/`tactile_paving` distinction at
crossings, parking-lot sub-typing (`disabled`, `underground`, `access`) so
not every lot renders identically, real `highway=street_lamp` node
positions instead of purely synthetic placement.

**Low**: `amenity=drinking_water`, `amenity=vending_machine`,
`advertising=*` — small decorative point features, unlikely to be
noticed missing.

Priorities are ranked by how much each gap changes whether the *simulation
itself* reads as correct (a car braking for an invisible stop sign looks
like a bug) over pure visual completeness — not by arbitrary scoring, per
section 14's explicit instruction.

---

# Section 16 — Rendering architecture assessment

**Question**: does the existing flat per-type-dataclass model (`Way`,
`Curb`, `Building`, `Scenery`, `Railing`, `Railway`, `Water`, `ParkingSpace`,
each with its own `draw_*` function) satisfy "reusable feature categories,
no special-case renderer per tag," or does it need the doc's suggested
`MapFeature → AreaFeature/LinearFeature/PointFeature/...` hierarchy?

**Finding**: the flat model already satisfies the *goal*, if not the
doc's literal shape. Evidence: implementing traffic islands (section 15) —
a real, previously-invisible OSM feature — required **zero new classes**.
It reuses `Scenery` (an existing "closed-polygon area feature" category)
and `Curb` (an existing "linear physical boundary" category) exactly as
they already exist, differentiated only by a `kind` string, the same
pattern every one of `Scenery`'s ~35 existing land-cover kinds already
uses. That is precisely what "reusable feature categories" is asking for —
it's just organized as one dataclass per *geometric shape* (area/line/
point) rather than a formal class hierarchy with `AreaFeature` etc. as base
classes.

**Recommendation: do not introduce the `MapFeature` hierarchy.** Section 20
of this same document explicitly warns not to rewrite the renderer without
demonstrated need, and this pass just demonstrated the opposite — a new
tag-driven feature landing as a one-line `kind` addition to an existing
dataclass, no new renderer, no new class. A formal inheritance hierarchy
would move `points_m`/`bbox`/color-lookup logic that's currently
duplicated in a handful of straightforward, independently-readable
dataclasses into a base class, at the cost of every existing renderer
needing to be touched to fit the new hierarchy — a large, risky diff to
buy an abstraction the codebase isn't short on today. The one real
architectural weakness this audit did surface — `StopSign`/`YieldSign`
having no renderer at all — wasn't a hierarchy problem, it was a missing
`draw_*` function (see section 21); the flat model didn't stand in the
way of fixing it, and fixing it needed no new dataclass at all.

---

# Section 21 — Stop/yield sign visuals implemented

Closes the one gap section 7 ranked highest: `StopSign`/`YieldSign` were
parsed and even correctly positioned since day one, but had no renderer,
*and* (corrected from this report's first pass, after actually tracing the
call graph instead of trusting the dataclass docstring) no consumer in
`traffic_world.py` either — right-of-way at a stop/yield-controlled
intersection is decided purely by the existing traffic-light/logical-
intersection rules, never by these signs. This pass fixes the rendering
gap only; wiring the signs into right-of-way *behavior* is a separate,
larger NPC-driving feature and out of scope here.

**What changed:**

* `StopSign`/`YieldSign` gained `direction_angle`/`road_half_width_m`
  fields and are now snapped through the same `_snap_to_nearest_road`
  pool as `Crossing`/`SpeedBump` — but unlike those (road-surface
  markings, correctly drawn on the centerline), a sign is a roadside
  post: the final stored position is pushed out past the road edge, on
  whichever side of the centerline the raw OSM node already leaned
  towards (mappers commonly nudge these nodes slightly off-center towards
  the physical sign).
* `render/roads.py` gained `draw_stop_signs()` (red octagon, white
  border, "STOP" label) and `draw_yield_signs()` (white triangle,
  red border), both upright fixed-size icons on a small pole — same
  simplicity as the existing `draw_taxi_stops()`, not a to-scale 3D
  object, no rotation to face traffic (the icon reads clearly either way).
* `yield_signs` turned out to be parsed but silently dropped before ever
  reaching the `world` object the gameplay loop reads from — the
  `SimpleNamespace` `_load_world()` returns had a `stop_signs=stop_signs`
  entry but no matching one for `yield_signs`. Fixed alongside the
  renderer, or the new `draw_yield_signs()` call would have had nothing
  to draw regardless.

**Verified:** `tests/test_road_signs.py` covers parse+snap-to-road,
opposite raw-node offsets landing on opposite rendered sides, world-cache
round-trip, and render pixel checks (including viewport culling). Confirmed
each test fails against the pre-change code (import error / attribute
error) before the fix and passes after. Full suite and the subprocess-based
`tests/test_main_loop.py` smoke test both pass with the change in.

**Performance:** signs are drawn with a plain per-frame loop, no spatial
grid — consistent with `draw_taxi_stops`/`draw_speed_bumps`, which don't
use one either; stop/yield sign counts in a real extract are far too small
(tens, not thousands) to need one.
