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
signs' *behavior* (not their sign), crossings, speed bumps, bus stops/
platforms (as point markers), taxi stops, trees, street lights (synthesized,
not OSM-tagged), traffic islands (added this session, section 15).

## 2. Important OSM features currently missing

Grounded in what the parser reads (or explicitly discards) tag-by-tag:

* **Stop signs and yield signs have no visual representation at all.**
  `StopSign`/`YieldSign` are parsed (`osm/build.py:1029-1047`) and drive
  right-of-way *logic* (`traffic_world.py`), but no `render/*.py` module
  ever draws one — confirmed by grep, zero hits for `StopSign`/`YieldSign`
  outside `osm/` and traffic logic. This is a genuine parsed-but-invisible
  gap, not a priority judgment call.
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

* `StopSign` / `YieldSign` (see above) — the one unambiguous case: the data
  exists in the internal model, nothing draws it.

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

1. **Stop/yield sign visuals** — the simulation already enforces the
   right-of-way rule; a driver has no visual cue *why* they must stop,
   which reads as a bug ("random braking") rather than correct behavior.
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

## 9. Files changed

`src/theroadragetrip/osm/build.py`, `src/theroadragetrip/render/scenery.py`,
`src/theroadragetrip/render/common.py`, `src/theroadragetrip/render/hud.py`,
`src/theroadragetrip/render/__init__.py`, `src/theroadragetrip/main/__init__.py`,
`src/theroadragetrip/main/debug_tools.py`, `tests/test_scenery_and_buildings.py`,
`tests/test_curbs.py`, `tests/test_debug_tools.py`.

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

**High** (directly affects driving/pedestrian realism): stop/yield sign
visuals, `sidewalk=*`-driven sidewalks, on-road cycle lanes
(`cycleway:*=lane`), platform footprint shape instead of centroid point.

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
having no renderer at all — isn't a hierarchy problem, it's a missing
`draw_*` function; the flat model doesn't stand in the way of fixing it.
