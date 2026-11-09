# Road Rage Taxi – Deterministic Visual Testing Infrastructure

Implement a reusable deterministic visual testing infrastructure for Road Rage Taxi.

Repository:
https://github.com/emehtata/roadragetaxi/tree/release/v0.21.0beta

## Problem

Visual feature development currently suffers from unreliable test setup.

The development agent may position vehicles at arbitrary coordinates, select unsuitable map locations, use inappropriate weather or lighting conditions, or capture screenshots before the environment has finished loading.

This makes visual verification unreliable.

For example:
- Testing metallic vehicle paint in a dark or unsuitable environment.
- Testing wet asphalt in a dry environment.
- Testing building materials in an area without suitable buildings.
- Testing streetlights during daylight.
- Testing reflections in a location without meaningful reflective surroundings.

We need a reusable system that creates controlled, repeatable and meaningful test conditions.

## Phase 1 – Audit existing test and debug infrastructure

Inspect the existing repository and identify:

- Current debug launch options.
- Existing developer tools.
- How the player vehicle is spawned and positioned.
- How map chunks are loaded.
- How simulation time and calendar date are controlled.
- How weather is controlled.
- How camera position and orientation are controlled.
- How screenshots can be captured.
- How Godot rendering initialization and resource loading can be detected.
- Existing automated tests and test conventions.

Do not assume that these capabilities do not already exist.

Reuse existing mechanisms where appropriate.

Do not modify normal gameplay behavior.

## Phase 2 – Create a visual test scenario registry

Create a centralized collection of named visual test scenarios.

A scenario must be declarative and reproducible.

Each scenario should support:

- Unique scenario ID.
- Human-readable description.
- Exact world coordinates.
- Vehicle spawn position, if a vehicle is needed.
- Vehicle orientation.
- Optional vehicle type and paint configuration.
- Camera position and orientation.
- Camera mode and distance.
- Simulation date and time.
- Weather conditions.
- Cloud coverage.
- Rain intensity.
- Ground wetness, if supported.
- Required map chunks.
- Required world objects or features.
- Expected rendering conditions.
- Screenshot output identifier.
- Validation requirements.

Use stable coordinates from the actual game map.

Do not use arbitrary coordinates simply because they are easy to reach.

## Phase 3 – Scenario selection must be based on feature requirements

Create scenarios that represent meaningful test environments.

Examples:

### metallic_vehicle_paint_day
- A vehicle with metallic paint.
- Daylight.
- Buildings and surrounding objects visible in the reflections.
- Camera angle suitable for inspecting bodywork reflections.

### metallic_vehicle_paint_night
- A vehicle with metallic paint.
- Nighttime.
- Nearby streetlights and illuminated buildings.
- Camera angle suitable for inspecting highlights and reflections.

### wet_asphalt_night
- An actual paved road.
- Nighttime.
- Wet surface conditions.
- Streetlights and nearby illuminated objects.
- Camera positioned to show the road surface and reflections.

### building_materials_day
- A location with several different building facade types.
- Daylight.
- Camera positioned to show material differences clearly.

### glass_and_metal_facades
- A location with glass and metal building surfaces.
- Buildings and surroundings visible in the reflection environment.
- Suitable camera distance and angle.

### streetlight_transition
- A suitable street with multiple streetlights.
- Controlled time progression through dusk, night and dawn.
- Camera position suitable for detecting flicker and lighting transitions.

### dense_city_performance
- A representative dense urban environment.
- Fixed camera and player position.
- Controlled time and weather.
- Suitable for repeatable rendering performance measurements.

These are examples. Inspect actual map data and choose real locations that satisfy the requirements.

Do not invent geographic coordinates.

## Phase 4 – Validate test environment before execution

A scenario must not be considered ready merely because the vehicle has been spawned.

Before capturing results, verify:

1. The requested world location exists.
2. Required map chunks have finished loading.
3. Required geometry is present.
4. Required materials and objects are initialized.
5. The simulation date and time match the scenario.
6. Weather conditions match the scenario.
7. The vehicle is at the requested position and orientation.
8. The camera has reached its requested position and orientation.
9. Required lighting and rendering resources are initialized.
10. The scene has rendered enough frames to reach a stable state.

If a prerequisite is missing, fail the scenario with a clear diagnostic message.

Never silently capture a screenshot under incorrect conditions.

## Phase 5 – Deterministic execution

Implement a developer-only mechanism for launching a named scenario.

For example:

`--visual-test metallic_vehicle_paint_day`

Adapt the command-line interface to existing project conventions.

Execution must:

1. Load the requested scenario.
2. Configure world state.
3. Load required chunks.
4. Position the vehicle if necessary.
5. Configure the camera.
6. Wait for readiness checks.
7. Capture screenshots.
8. Collect relevant performance metrics.
9. Produce a machine-readable result report.

The same scenario must produce the same initial conditions every time.

Do not introduce arbitrary sleeps as the only synchronization mechanism. Use explicit readiness checks and a bounded timeout.

## Phase 6 – Screenshot and result management

Create a predictable output structure for visual test results.

Each result should include:

- Scenario ID.
- Timestamp.
- Git commit identifier if available.
- Rendering backend.
- Screen resolution.
- Simulation time.
- Weather conditions.
- Vehicle and camera configuration.
- Screenshot paths.
- FPS and frame-time measurements.
- Validation status.
- Any errors or warnings.

Avoid committing generated screenshots or large test artifacts unless explicitly appropriate for the repository.

Provide a convenient way to compare screenshots from different implementations.

## Phase 7 – Developer workflow documentation

Create documentation explaining:

- How to list available visual scenarios.
- How to execute an individual scenario.
- How to add a new scenario.
- How to choose an appropriate map location.
- How to define valid environmental conditions.
- How to capture and compare screenshots.
- How to interpret failed readiness checks.

## Mandatory development-agent behavior

From now on, when implementing any feature that requires visual verification:

1. Identify the physical and environmental conditions required to test the feature.
2. Search the existing scenario registry for a suitable scenario.
3. If no suitable scenario exists, create one using actual map data.
4. Explain why the selected location and conditions are appropriate.
5. Execute the scenario.
6. Verify that all prerequisites were satisfied.
7. Capture and inspect the result.
8. Report what was actually verified and what remains unverified.

Never:
- Place a vehicle at arbitrary coordinates without checking the surroundings.
- Assume a map chunk has loaded because a spawn command succeeded.
- Assume weather or lighting conditions are correct without checking them.
- Use a screenshot as evidence if the scene was not ready.
- Claim visual verification based solely on successful compilation.
- Change normal game behavior to make a test pass.

## Architectural constraints

- Python remains responsible for authoritative simulation.
- Godot remains responsible for rendering.
- Test infrastructure must not become part of normal gameplay logic.
- Preserve existing map streaming.
- Keep test-only functionality isolated and developer-accessible.
- Do not create or push Git tags.
- Use atomic commits.

## Final report

Explain:
- What test infrastructure already existed.
- What was added.
- Which scenarios were implemented.
- How their locations were selected.
- How deterministic state setup works.
- How readiness is verified.
- How screenshots and metrics are collected.
- How future visual feature development should use this infrastructure.

The result should be a reusable testing foundation, not a collection of one-off screenshots or hardcoded vehicle teleport commands.