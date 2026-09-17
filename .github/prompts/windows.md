# Audit and Improve Building Windows — Road Rage Taxi 0.12.0alpha

Work on the current `release/0.12.0alpha` branch.

## Goal

Improve the visual rendering of building windows so that the city looks believable both during daytime and at night.

The desired result is:

* commercial buildings have large ground-floor storefront/display windows
* apartment buildings and office buildings have regularly spaced windows across their floors
* detached houses have smaller, normal residential windows
* at night, some windows are randomly illuminated
* window lighting must integrate naturally with the existing day/night and building lighting system
* the implementation must have negligible impact on the game's 60 FPS target

## IMPORTANT: Audit the existing implementation first

Do NOT immediately implement a new window system.

First inspect the existing building rendering implementation, especially:

* `src/theroadragetrip/render/buildings.py`
* `src/theroadragetrip/osm/models.py`
* OSM building parsing/import code
* existing building-related tests
* existing day/night and ambient-light code in `render/common.py`
* any existing window, facade, sign, entrance, or night-light rendering code

Understand what is already implemented.

In particular, determine whether the current implementation already has:

* window rendering
* floor/level handling
* building height handling
* commercial building detection
* associated OSM places/venues
* facade-edge detection
* building visual plans
* static building caching
* night-time building/window illumination
* deterministic per-building randomness

Do not duplicate any of these systems.

## Desired window behaviour

After the audit, compare the existing implementation against the following requirements.

### 1. Commercial buildings

Buildings containing commercial uses should have a clearly different ground floor.

Use existing OSM information whenever possible.

Commercial classification should consider the existing building/venue data, including associated OSM places.

Examples include:

* shops
* supermarkets
* restaurants
* cafés
* bars
* pharmacies
* banks
* hotels
* other retail/commercial premises

Ground-floor commercial facades should use:

* large windows
* wide storefront/display-window sections
* fewer but larger window areas than upper floors
* visually appropriate ground-floor positioning

The storefront windows should make it immediately apparent that the building contains a commercial space.

Do not make every building with an arbitrary `building=*` tag look commercial.

### 2. Apartment and office buildings

For multi-storey residential and office buildings:

* render windows on multiple floors
* use reasonably regular horizontal floor rows
* space windows at believable intervals
* avoid covering the entire facade with windows
* maintain visible wall sections between windows
* adapt the number of rows to the existing OSM `levels`/height information
* respect the existing pseudo-3D facade geometry and visible facade edges

The window layout should be generated from the building geometry rather than simply placing windows at arbitrary screen coordinates.

### 3. Detached houses

Detached/small residential buildings should have:

* fewer windows
* smaller window dimensions
* less dense window spacing
* a clearly different appearance from apartment/office buildings

Use existing OSM building information where available to distinguish building scale/type.

Do not force apartment-style rows onto small detached houses.

### 4. Window placement

Windows must follow the actual visible building facades.

Do not render windows:

* floating beside the building
* across the roof
* outside the visible facade
* across entrances/doors where that would look incorrect
* on facade edges that are hidden by the pseudo-3D roof geometry

Reuse existing facade-edge and visual-plan calculations where possible.

### 5. Night-time illuminated windows

At night, some windows should appear illuminated.

The result should be subtle and believable:

* not every window is lit
* different buildings should have different illumination patterns
* different floors/windows should have different states
* commercial ground-floor windows can have a higher probability of being illuminated
* residential windows should have a lower/random probability
* office windows should generally have fewer illuminated windows late at night than commercial storefronts

The illumination state should be deterministic for a given building/window rather than changing randomly every frame.

For example, derive a stable pseudo-random seed from the building identity and window position/index.

This prevents windows from flickering as the camera moves or the building cache is rebuilt.

### 6. Day/night integration

Window illumination should integrate with the existing day/night system.

Use the existing solar/day-night state rather than creating another independent clock or lighting system.

The transition should be gradual around dusk/dawn.

During daytime:

* windows should look like physical windows rather than bright lights

During night:

* illuminated windows should provide a subtle warm interior glow

Do not make illuminated windows brighter than nearby street lighting in an unrealistic way.

The existing building-based ambient-light model must remain intact.

## OSM data

Use OSM information already available in the project.

Before adding new parsing, determine what building metadata is already available, including:

* `building=*`
* `building:levels`
* height
* building type
* associated `shop=*`
* associated `amenity=*`
* other existing venue/place information

Do not invent new OSM fields or data structures if the required information already exists.

If important information is genuinely unavailable, implement a sensible fallback based on the existing building geometry and dimensions.

## Performance requirements

Performance is critical.

The game targets a stable 60 FPS.

Do NOT:

* generate new window geometry every frame
* perform expensive calculations for every window every frame
* repeatedly create large pygame surfaces inside the main render loop
* use expensive per-pixel lighting
* regenerate random window states every frame
* bypass the existing building cache architecture

Prefer:

* camera-independent building/window visual plans
* deterministic window layouts
* cached window surfaces/geometry
* existing incremental building cache rebuilds
* existing viewport culling
* existing static rendering architecture

Window geometry and layout should ideally be generated once and reused until the building's relevant data changes.

Night-time illumination may change with the day/night state, but it should not require rebuilding the entire window geometry unnecessarily.

## Visual quality

The goal is not architectural precision.

The goal is a convincing top-down city-game appearance.

A player should be able to visually distinguish:

* detached house
* apartment building
* office building
* commercial building with storefronts

At night, illuminated windows should make the city feel inhabited without turning every building into a glowing rectangle.

Avoid excessive visual noise at normal gameplay zoom.

## Tests

First inspect the existing building rendering tests.

Add tests only where they cover actual missing behaviour.

Tests should cover as appropriate:

* commercial building detection
* storefront window generation
* multi-floor window generation
* detached-house window density
* facade-edge constraints
* deterministic window illumination
* different buildings producing different stable illumination patterns
* day/night transition behaviour
* no regression in existing building rendering
* cache compatibility

Run the relevant test suite after implementation.

## Implementation rules

Follow this workflow strictly:

1. Inspect the current implementation.
2. Document internally what already exists.
3. Identify the exact gaps against this specification.
4. Implement only those gaps.
5. Reuse existing building caches and visual-plan infrastructure.
6. Add tests for the implemented behaviour.
7. Run the relevant tests.
8. Check for unnecessary per-frame work.

Do NOT redesign `buildings.py` merely to implement windows.

Do NOT create a separate global window-rendering engine unless the audit demonstrates that the existing architecture cannot support the required behaviour.

At the end, report:

1. What window/facade functionality already existed.
2. What was missing.
3. What you changed.
4. How commercial, residential, office and detached-house windows are differentiated.
5. How deterministic night illumination works.
6. What caching is used.
7. Tests executed and their results.
8. Any remaining visual limitations.
