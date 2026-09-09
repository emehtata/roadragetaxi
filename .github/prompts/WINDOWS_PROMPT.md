IMPORTANT BUILDING RENDERING REQUIREMENTS

There are two specific visual requirements that must be preserved/restored.

## 1. OSM building:levels MUST control the number of floors

Building floor count must come from the OSM building data whenever available.

The relevant OSM tags are primarily:

    building:levels

and, if the project's existing parser already supports it:

    levels

Inspect the existing OSM parsing code and use the value already stored on the Building object.

The value represents the number of floors/levels in the building and must directly control the vertical distribution of facade windows.

For example:

    building:levels = 1
        → one floor of windows

    building:levels = 2
        → two floors of windows

    building:levels = 5
        → five floors of windows

    building:levels = 10
        → ten floors of windows

Do NOT generate an arbitrary number of floors based only on building height.

Do NOT use a hard-coded floor count for buildings that have valid OSM levels data.

The building's visual height and its number of window rows should remain consistent with the OSM data.

## 2. Window placement must be floor-aware

The facade rendering should explicitly iterate over the building's floor count.

Conceptually:

    level_count = building.levels

    for floor_index in range(level_count):
        calculate vertical position of this floor
        generate windows for the visible facade

Each window row must have a distinct vertical position corresponding to its floor.

For example, a 4-floor building should visually resemble:

    ┌─────────────────────┐
    │ □  □  □  □  □       │  floor 4
    │                     │
    │ □  □  □  □  □       │  floor 3
    │                     │
    │ □  □  □  □  □       │  floor 2
    │                     │
    │ ▣  ▣  ▣  ▣  ▣       │  ground floor
    └─────────────────────┘

The exact existing pseudo-3D projection and facade geometry must be preserved.

Do not simply stretch one row of windows over the entire facade.

## 3. Commercial buildings MUST have storefront windows at ground level

Commercial buildings require a visually distinct ground-floor treatment.

If the building represents a commercial/venue property, the ground floor should contain storefront windows rather than ordinary residential-style windows.

This applies to the project's existing commercial building/venue classification, including appropriate:

- shops
- restaurants
- cafes
- bars
- pubs
- retail buildings
- commercial buildings
- other named commercial venues

Inspect the existing `venue_type` / commercial classification instead of creating a second unrelated classification system.

The ground floor should visually resemble a storefront:

- larger windows than upper floors
- clearly positioned at street/ground level
- visually distinct from upper-floor windows
- aligned with the facade
- repeated across the relevant facade edge where appropriate

Conceptually:

    Upper floors:

    │  □  □  □  □  │
    │  □  □  □  □  │
    │  □  □  □  □  │

    Ground floor:

    │ ┌────┐ ┌────┐ │
    │ │    │ │    │ │
    │ │    │ │    │ │
    │ └────┘ └────┘ │

The storefront windows should use the existing facade geometry and perspective.

Do not draw them as flat screen-space rectangles.

## 4. Ground floor + upper floors

For a commercial building with:

    building:levels = 4

the facade should therefore contain:

    floor 4 → normal windows
    floor 3 → normal windows
    floor 2 → normal windows
    floor 1 → storefront windows

Do not interpret `levels=4` as four upper floors plus an additional storefront floor.

The storefront is the ground/first floor and is included in the OSM level count.

For a residential building with:

    building:levels = 4

all four levels can use the normal window treatment.

## 5. Missing levels data

If OSM does not provide a valid levels value, use the project's existing fallback behavior.

Do NOT invent a new arbitrary heuristic unless necessary.

The fallback must still produce a sensible number of floors/windows, but:

    valid OSM building:levels
        MUST take precedence over the fallback.

Also handle malformed values safely.

For example:

    "4"     → 4
    "4.0"   → 4 if compatible with the existing parser
    missing → fallback
    invalid → fallback

Clamp unreasonable values using a sensible existing/project-compatible limit so malformed OSM data cannot generate thousands of window rows.

## 6. Building height consistency

Inspect how the renderer currently calculates the building's visual height.

If both:

    building:levels

and:

    building height

are available, make sure the facade geometry and floor spacing remain visually consistent.

The important relationship is:

    building height
          ↓
    total facade height

    building:levels
          ↓
    number of floor rows
          ↓
    vertical spacing of windows

Do not allow a 20-floor building to have the same vertical window spacing as a 2-floor building.

## 7. Preserve facade signs

Commercial building signs must remain separate from the storefront window logic.

For a named commercial building:

    OSM place
        ↓
    associated_places
        ↓
    facade sign

The sign should remain attached to the facade, while storefront windows occupy the ground floor.

For example:

    ┌──────────────────────────┐
    │ □   □   □   □   □        │
    │                          │
    │ □   □   □   □   □        │
    │                          │
    │       "CAFE"             │  ← facade sign
    │                          │
    │ ┌────┐ ┌────┐ ┌────┐    │
    │ │    │ │    │ │    │    │  ← storefront
    │ └────┘ └────┘ └────┘    │
    └──────────────────────────┘

The sign must NOT replace the storefront windows.

## 8. Important performance constraint

Do not solve this by reintroducing the old global place scan.

The renderer must continue using the optimized building/place association:

    building.associated_places

or the project's equivalent precomputed relationship.

Do NOT do:

    for building in buildings:
        for place in places:
            point_in_polygon(...)

The building-level rendering optimizations must remain intact.

## 9. Visual regression requirement

Compare the current implementation against the last known good building rendering implementation in git history.

The restored result should have:

- OSM-driven floor counts
- one window row per building level
- vertically separated window rows
- larger storefront windows on commercial ground floors
- facade signs for named commercial buildings
- existing pseudo-3D facade projection
- existing roof/facade geometry

Do not simplify the building renderer merely to make these requirements easier.

## Acceptance examples

Example A:

OSM:

    building:levels=3
    building=residential

Expected:

    3 floors
    3 rows of normal windows

Example B:

OSM:

    building:levels=5
    building=commercial
    name=Example Shop

Expected:

    5 floors total
    4 upper rows of normal windows
    1 ground-floor storefront row
    "Example Shop" facade sign

Example C:

OSM:

    building:levels=2
    amenity=restaurant
    name=Example Restaurant

Expected:

    2 floors total
    1 upper-floor normal window row
    1 ground-floor storefront row
    "Example Restaurant" facade sign

Example D:

OSM:

    building:levels=10
    building=residential

Expected:

    10 visually distinct rows of windows

Do not collapse these into a small fixed number of rows for performance.

The static building cache should make this affordable without sacrificing the visual detail.