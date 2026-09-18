# Audit and Improve Existing Night Lighting — Road Rage Taxi 0.12.0alpha

Work on the current `release/0.12.0alpha` branch.

## Goal

Improve the existing evening/night rendering of Road Rage Taxi, especially street lights and vehicle headlights, **without creating a second lighting system and without degrading FPS**.

The first task is an audit of the existing implementation. Do not start by designing new architecture.

## Phase 1 — Inspect the existing implementation

Before changing any code, carefully inspect at least:

* `src/theroadragetrip/render/common.py`
* `src/theroadragetrip/render/roads.py`
* `src/theroadragetrip/render/vehicles.py`
* `src/theroadragetrip/render/__init__.py`
* `src/theroadragetrip/main/__init__.py`
* Existing tests related to:

  * street lights
  * headlights
  * crossings
  * solar/day-night calculations
  * spatial culling/performance

Understand how the current implementation already handles:

* solar position and dusk/dawn
* global day/night brightness
* building-based ambient lighting
* OSM street-light/lamp data
* `lit=*`
* street-light geometry caching
* street-light frame/world-position caching
* headlight rendering
* vehicle visibility culling
* existing brightness-overlap handling
* render ordering

Do not duplicate functionality that already exists.

## Phase 2 — Compare the implementation against this specification

Determine which requirements are already satisfied and which are missing or incorrect.

### Street lights

1. Explicit OSM physical street-light/lamp-pole data is the primary source whenever it is available.
2. If explicit street-light data is unavailable for a road segment, use the road's `lit=*` information as the fallback.
3. Do not treat `lit=*` as a replacement for explicit lamp positions when actual lamp data exists.
4. Street lighting should illuminate the road/environment naturally rather than producing obvious isolated bright spots where possible.
5. Preserve the existing street-light caching and geometry-cache architecture.

### Vehicle headlights

1. Headlights must turn on automatically when dusk begins, using the existing solar/day-night system.
2. Headlight rendering must remain lightweight and compatible with the existing vehicle visibility culling.
3. High beams should be used when appropriate on roads/areas without street lighting.
4. Do not introduce expensive per-pixel CPU lighting or full-population lighting calculations every frame.

### Light overlap

When a vehicle headlight beam overlaps an area already illuminated by street lighting:

* brightness must not suddenly increase because the two effects are simply added together
* avoid visible brightness spikes when headlights pass through street-light pools
* preserve and extend the existing overlap protection/tests rather than replacing them

The result should look like combined illumination, not additive glowing circles.

### Environmental darkness

Keep the existing building-based ambient-light model.

For example:

* urban areas with nearby buildings should retain their existing ambient brightness
* a rural road far from buildings and street lights can become almost completely dark at night
* do not introduce a global minimum ambient brightness that makes rural night scenes artificially bright

## Phase 3 — Implement only the missing pieces

After the audit:

1. Make the smallest appropriate changes required to satisfy the specification.
2. Reuse existing caches, culling, data structures and rendering functions wherever possible.
3. Do not rewrite the lighting system.
4. Do not replace the existing day/night implementation.
5. Do not add a new lighting engine or rendering architecture unless the audit proves that an existing limitation cannot be fixed within the current architecture.
6. Preserve existing gameplay and rendering behavior that is already working correctly.

## Performance requirements

Performance is a hard requirement.

The game should maintain a stable 60 FPS target.

Avoid:

* generating large gradients every frame
* rebuilding static street-light geometry unnecessarily
* processing all NPC vehicles for lighting every frame
* expensive per-pixel Python calculations
* unnecessary allocations inside the render loop
* recalculating lighting for off-screen objects
* invalidating existing caches without a clear reason

Prefer the existing:

* geometry caches
* frame/world-position caches
* visibility culling
* throttled day/night calculations
* reusable surfaces/geometry

If a new calculation is necessary, make it cacheable or restrict it to visible/nearby objects.

## Tests

Before modifying tests, understand the existing tests.

Add or modify tests only for behavior that is actually missing or incorrect.

In particular, verify:

* explicit OSM street lights take precedence over `lit=*`
* `lit=*` works as fallback
* headlights activate at dusk
* headlights/high beams behave correctly on unlit roads
* street-light/headlight overlap does not create brightness amplification
* rural areas can remain very dark
* existing lighting behavior does not regress

Run the relevant test suite after the changes.

## Important

Do not blindly implement every item as a new feature.

The correct workflow is:

**inspect → identify existing functionality → identify gaps → implement only the gaps → test → measure/consider performance**

At the end, provide a concise report containing:

1. What the existing implementation already did correctly.
2. Which requirements were missing or incorrect.
3. What you changed.
4. Which tests were added/updated.
5. Any measurable or likely performance impact.
6. Any remaining limitations that should be addressed later.
