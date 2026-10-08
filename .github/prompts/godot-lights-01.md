# Godot Night Rendering – Continuous Solar-Altitude Lighting

Implement the next rendering phase for Road Rage Taxi on the current `release/v0.16.0g-alpha` branch.

## Objective

Improve the Godot night/dusk/dawn rendering so that environmental brightness is driven continuously by the **actual solar altitude above the horizon** at the game's known location.

The result must look visually polished while remaining very cheap to render.

This is a **Godot-only implementation**.

Do NOT modify, extend, or maintain the Pygame renderer as part of this task. The Pygame renderer is legacy and is no longer part of the active rendering architecture.

Do NOT introduce a new physical 3D lighting system.

The game remains:

* 2D/top-down gameplay
* lightweight 3D building layer
* 2D geometry for vehicles, headlights, street lights and other effects
* server-authoritative game state
* Godot responsible for rendering

## Critical requirement: continuous astronomical brightness

The most important requirement is that environmental brightness must be a **continuous function of solar altitude**.

Do NOT implement:

```text
DAY
DUSK
NIGHT
```

as discrete rendering states.

Do NOT switch suddenly between different palettes or rendering modes at sunrise, sunset, or any arbitrary clock time.

Instead:

```text
game date/time
        ↓
solar position
        ↓
solar altitude above horizon
        ↓
continuous environmental brightness
        ↓
continuous visual transition
```

The existing game already knows the location coordinates and game date/time. Reuse the existing astronomical/time implementation where possible instead of introducing a second competing source of truth.

First inspect the current Godot implementation and identify exactly where the existing game calculates:

* game date/time
* darkness
* solar position / solar altitude, if already available
* day/night state used by rendering

Reuse existing authoritative values whenever possible.

If solar altitude is already calculated by the server and transmitted to Godot, use that value.

If the current Godot client only receives a coarse `darkness` value, determine whether the existing protocol already contains enough information to derive the continuous value locally. Do not add protocol fields unless genuinely necessary.

## Solar altitude model

Use the sun's altitude above the horizon as the physical basis.

Conceptually:

* positive altitude = Sun above the horizon
* altitude near 0° = transition around sunrise/sunset
* moderately negative altitude = twilight
* sufficiently negative altitude = deep night

However, do NOT create hard thresholds such as:

```text
if altitude > 0:
    day
else:
    night
```

The visual brightness must remain continuous throughout the entire range.

Use a smooth interpolation/remapping function.

A suitable approach is a smooth curve based on solar altitude, for example a normalized smoothstep-like function over a configurable altitude range.

The exact curve must be selected based on visual testing rather than blindly copied from this prompt.

The important property is:

```text
small change in solar altitude
        ↓
small corresponding change in environmental brightness
```

There must be no visible step at:

* sunrise
* sunset
* 0° solar altitude
* any twilight boundary

## Desired visual progression

The rendering should naturally progress approximately like this:

### Full daylight

* normal world colours
* roads clearly visible
* buildings clearly visible
* street lights have little or no visual influence
* headlights are visible but do not dominate
* windows are mostly unlit or visually insignificant

### Late afternoon / early evening

As solar altitude decreases:

* ambient illumination gradually decreases
* colours gradually become cooler/darker
* artificial lights gradually become more noticeable
* street lights begin to stand out
* headlights become increasingly visible
* illuminated windows gradually become noticeable

There must be no sudden "lights turned on" visual jump.

### Twilight

As the Sun approaches and passes the horizon:

* ambient environment continues becoming darker
* sky/world remains visibly blue rather than becoming pure black
* warm street lights become increasingly dominant
* headlights become prominent
* building windows become visible
* traffic lights/signs remain readable

### Night

At sufficiently low solar altitude:

* ambient environment is very dark
* roads remain readable
* buildings remain readable through silhouettes, roofs and artificial illumination
* street lights provide warm local illumination
* headlights provide cool/neutral local illumination
* illuminated windows provide small warm points/areas
* emissive objects such as traffic lights remain visible

### Deep night

At very low solar altitude:

* environmental ambient light approaches its minimum
* artificial light becomes the primary visual illumination
* the scene must still remain readable and attractive
* do not simply reduce the entire frame to black

The transition between all of these states must remain continuous.

## Important: preserve the existing astronomical behaviour

Do not replace the existing astronomical model with a simplified clock-based approximation.

The game is intended to represent the actual local lighting conditions of its known location.

In particular, the implementation must naturally handle:

* long summer daylight
* short winter daylight
* long twilight periods
* the Sun remaining close to the horizon
* periods where the Sun does not behave like an ordinary daily sunrise/sunset cycle

Do not assume that every day has a simple sunrise → noon → sunset → night sequence.

## Rendering architecture

Keep the current lightweight architecture.

The preferred conceptual composition is:

1. base world
2. continuous ambient/environment darkening
3. warm street-light contribution
4. cool/neutral headlight contribution
5. emissive elements
6. illuminated windows
7. vehicles and gameplay elements
8. HUD

Use the existing architecture wherever practical.

Do NOT introduce:

* one `Light3D` per street lamp
* one `SpotLight3D` per vehicle
* real-time shadow maps for street lights
* per-light shadow casting
* hundreds of dynamic 3D lights
* a full physical lighting system
* a second full-screen lighting viewport merely to obtain softer lights
* CanvasGroup-based full-screen compositing if it causes the previously observed software-renderer performance regression

The existing 2D geometric light pools and occlusion system are a good foundation.

## Street lights

Keep the existing map-based street-light positions and chunk-level preprocessing.

Do not replace them with physical 3D lights.

Improve their visual appearance so that they behave like local light sources.

Target appearance:

* warm yellow/orange light
* small bright central region
* soft falloff
* wider but weaker surrounding glow
* slightly elongated toward the illuminated road area where appropriate
* no hard triangular-looking yellow polygons
* no excessive bloom
* no huge illuminated circles

The street-light contribution should become increasingly visible as solar altitude decreases.

During daylight it should have little or no visible effect.

At night it should provide a strong but localized warm contribution.

The transition must be continuous.

Keep the current chunk-level precomputation and worker-thread generation if possible.

Do not perform expensive per-light geometry clipping every frame.

## Headlights

Keep the current 2D geometric headlight system and its existing occlusion behaviour.

Do not replace it with `SpotLight3D`.

Improve the visual result if necessary:

* neutral white / slightly warm white
* bright central beam
* soft beam edges
* directional
* strongest close to the vehicle
* decreasing intensity with distance
* affected by building occlusion
* clearly visible at night
* progressively less dominant as ambient daylight increases

The headlights must move exactly with their vehicles.

Do not modify the vehicle movement, interpolation, camera, or input systems.

The recent vehicle/background jitter fixes are considered stable and must not regress.

## Building illumination

Preserve the existing lightweight 3D building architecture.

Do not add physical lighting to the building meshes.

The existing illuminated-window approach can remain.

Windows should:

* be small
* have warm colours
* have variation in brightness
* not make entire buildings glow
* remain correctly occluded by buildings
* become progressively more noticeable as environmental brightness decreases

If the existing second 3D building pass is a measurable performance bottleneck, investigate whether it can be made cheaper.

Do not remove building occlusion merely for performance.

Do not introduce another full-screen 3D pass to solve lighting.

## Wet roads

If the existing wet-road rendering already provides darkening/puddles, preserve it.

At night, wet roads should visually respond to artificial light where the current architecture permits it.

A subtle reflective appearance is desirable.

Do not implement expensive real-time reflections.

A cheap 2D approximation is preferred.

Do not let wet-road effects become brighter than the actual light sources.

## Traffic lights and emissive objects

Traffic lights should remain readable at night.

Their illuminated state should look emissive rather than merely becoming brighter because the entire scene is dark.

Likewise preserve readability of:

* signs
* fuel station elements
* other important gameplay indicators

Do not make them independent full-screen light sources.

## Colour direction

Use a visually coherent contrast:

### Ambient environment

Cold blue / blue-gray.

Avoid pure black.

### Street lights

Warm yellow / warm amber.

### Headlights

Neutral white to slightly warm white.

### Windows

Warm white / warm yellow with modest variation.

### Traffic lights

Use their actual red/yellow/green colours.

The contrast between cool ambient night and warm artificial lighting should create the visual identity of the night scene.

Avoid excessive saturation.

## Dusk and dawn

Dusk and dawn are especially important.

Test both directions:

```text
day → evening → twilight → night
night → twilight → dawn → day
```

They must be visually symmetrical enough that there is no obvious implementation discontinuity.

Do not simply reverse a boolean `night` flag.

The same continuous solar-altitude model should drive both directions.

## Performance requirements

The current Godot renderer is already performance-sensitive.

The 3D building layer has previously been measured as having a relatively small geometry/render-pass cost, while the larger cost comes from pixel/compositing work.

Therefore:

* do not add another expensive full-screen render pass unless absolutely necessary
* do not add hundreds of dynamic lights
* avoid per-frame polygon generation
* keep chunk preprocessing
* keep batching
* keep static light geometry static where possible
* prefer cheap colour/alpha manipulation and precomputed geometry
* avoid unnecessary overdraw

Benchmark the result at:

* 1280×720
* software renderer, using the project's existing benchmark method
* daytime
* dusk
* twilight
* night
* deep night

Record:

* average FPS
* 1% low FPS
* worst frame time
* memory usage if already measured by the benchmark

Do not accept a large performance regression for a purely cosmetic effect.

## Visual acceptance criteria

The implementation is successful only if all of these are true:

1. Solar altitude, not clock thresholds, controls environmental brightness.
2. Brightness changes continuously.
3. There is no visible step at sunrise.
4. There is no visible step at sunset.
5. There is no visible step at 0° solar altitude.
6. Summer and winter lighting naturally differ because the astronomical calculation differs.
7. Street lights become progressively more visible as ambient light decreases.
8. Headlights become progressively more dominant as ambient light decreases.
9. Building windows become progressively more visible.
10. Night remains dark blue rather than black.
11. Warm artificial lights contrast naturally with the cool environment.
12. Existing building occlusion remains correct.
13. Existing vehicle/camera interpolation remains unchanged.
14. No physical 3D light system is introduced.
15. Performance remains within a reasonable margin of the current renderer.

## Investigation before implementation

Before changing code:

1. Inspect the current Godot time/darkness implementation.
2. Identify the authoritative source of solar position/solar altitude.
3. Identify every Godot renderer component currently affected by `darkness`.
4. Trace how street-light visibility is currently controlled.
5. Trace how headlights are currently controlled.
6. Trace how lit windows are currently controlled.
7. Measure the current cost of night rendering before changing it.
8. Document the current behaviour briefly.

Do not guess about existing implementation details.

## Tests

Add deterministic tests for the new continuous brightness model.

At minimum verify:

* brightness at full daylight
* brightness at a representative low-sun position
* brightness near the horizon
* brightness immediately above the horizon
* brightness immediately below the horizon
* deep night
* monotonic behaviour as solar altitude decreases
* no discontinuity around the horizon
* sunrise and sunset produce the same continuous curve in reverse

If the brightness mapping is implemented as a pure function, make that function independently testable.

Also verify that no discrete day/night switch remains in the actual rendering path.

Run the project's normal checks:

```text
make godot-test
make godot-selftest
make audio-check
```

Run the Python test suite only if changes touch shared/server code.

Do not modify unrelated Python/server behaviour.

## Scope protection

Do NOT:

* work on Pygame rendering
* redesign the 3D building renderer
* change the camera
* change vehicle movement
* change interpolation
* change network protocol unless strictly required
* change game rules
* change map data
* introduce BIN-based architecture
* add physical 3D lighting
* fix unrelated parity items
* implement navigation, taximeter, road rage, career, weather particles, etc.

This task is specifically about **continuous astronomical environmental lighting and the visual behaviour of artificial lights in Godot**.

## Git

When implementation and tests are complete:

* commit the changes to the current branch
* push the branch to the remote
* do NOT create or push a Git tag

Report:

* files changed
* implementation approach
* solar-altitude/brightness curve used
* visual validation performed
* benchmark before/after
* test results
* commit hash
* confirmation that the branch was pushed
* confirmation that no tag was created
