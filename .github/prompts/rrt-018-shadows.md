# Road Rage Taxi — Solar Direction and Dynamic 3D Building Shadows

## Objective

Implement dynamic, sun-direction-dependent shadows cast by the existing lightweight 3D building layer onto the surrounding environment in the Godot client.

The game already calculates solar elevation for its lighting system, but it does not yet calculate or use the sun's azimuth. Extend the existing implementation instead of introducing a separate, inconsistent solar model.

The game uses a top-down camera with a lightweight 3D building layer. Preserve the established visual style and prioritize stable FPS.

## Mandatory constraints

- Audit the current Godot rendering and solar-lighting implementation before making changes.
- Implement rendering changes in Godot only.
- Reuse the existing game date, game time, geographic coordinates, and solar elevation calculation.
- Calculate solar azimuth using the same geographic and temporal inputs as the existing elevation calculation.
- Keep the Python server authoritative for game simulation and time.
- Do not change gameplay rules or server-client protocol unless a concrete, unavoidable requirement is identified and documented.
- Preserve the current camera orientation, vehicle rendering, stabilized camera movement, and building geometry.
- Preserve smooth day/night lighting transitions.
- Do not modify the PBF loading/stuttering behavior.
- Do not introduce a binary map-data architecture.
- Do not reintroduce or develop the Pygame renderer.
- Do not sacrifice the established FPS target for unnecessarily expensive shadows.
- Do not create or push Git tags. Pushing the working branch is permitted.
- All code, documentation, and commit messages must be in English.

## Phase 1 — Audit the existing implementation

Locate and inspect:
- The existing solar elevation calculation.
- The source of the game date, time, and geographic coordinates.
- The current daylight intensity and color transitions.
- The Godot 3D building generation and rendering pipeline.
- The scene hierarchy and existing directional lights.
- The map surface and other geometry intended to receive shadows.
- The camera projection, orientation, and clipping configuration.
- The current renderer and performance benchmark procedures.

Determine how the existing 3D buildings are represented and whether their geometry can cast and receive shadows without rebuilding or duplicating the entire map.

Document the existing coordinate conventions, including which world axis represents north and how geographic coordinates map into Godot world space.

Do not assume that geographic north aligns with Godot's positive or negative Z axis. Verify it from the actual implementation.

## Phase 2 — Calculate solar azimuth correctly

Extend the existing solar calculations to provide:
- Solar elevation above the horizon.
- Solar azimuth, with a documented convention.
- A normalized 3D sun direction compatible with Godot's world axes.

Use the actual game location and current game date/time. Prefer extending the existing astronomical calculation rather than introducing a second independent approximation.

Verify the azimuth convention carefully. Common astronomical conventions measure azimuth clockwise from true north, while Godot uses a 3D direction vector. Convert between these conventions explicitly.

Account for:
- Latitude and longitude.
- Date, including seasonal variation.
- Time of day.
- The project's existing time-zone and daylight-saving conventions.
- The coordinate system used by the map.

Handle edge cases such as the sun below the horizon and near-zero elevation without numerical instability.

Add deterministic tests for known dates, times, and locations. Verify the direction against an independent astronomical reference or a well-established solar-position algorithm.

## Phase 3 — Drive Godot directional lighting from the sun

Use a DirectionalLight3D or adapt the existing directional light so its direction matches the calculated sun position.

Verify Godot's light-direction convention against the actual engine version in the project. Do not assume that the light node's rotation directly equals the astronomical azimuth and elevation.

The resulting light must:
- Illuminate the scene from the correct compass direction.
- Follow changes in game time and date.
- Update smoothly as the sun moves.
- Remain consistent with the existing daylight brightness and color model.
- Avoid visible jumps at update boundaries.
- Avoid unnecessary per-frame recalculation if the game clock changes at a lower frequency.

Do not introduce a second sunlight system that conflicts with the current day/night implementation.

## Phase 4 — Enable and configure building shadows

Enable shadows on the appropriate directional light and configure the existing 3D building geometry to cast them.

Ensure that shadows fall onto the actual visible environment, not only onto other building surfaces.

Inspect the map surface and material configuration. If the current map surface cannot receive shadows, make the smallest compatible change necessary. Do not replace the map renderer or redesign the map geometry.

Requirements:
- Buildings cast shadows in the direction opposite the incoming sunlight.
- Shadow length increases as the sun approaches the horizon.
- Shadows shorten as the sun rises higher.
- Shadow direction changes continuously with solar azimuth.
- Adjacent buildings produce plausible shadow interactions.
- Shadows do not appear detached from their casters.
- Avoid excessive shadow acne, peter-panning, flickering, and self-shadow artifacts.
- Avoid rendering shadows from invisible or irrelevant geometry.
- Keep shadow behavior stable as map chunks and buildings are added or removed.

Do not use a screen-space directional gradient or a fake fixed-direction shadow as a substitute for the actual 3D building shadows.

## Phase 5 — Handle low sun and nighttime

Use solar elevation and the existing day/night lighting state to control shadow visibility.

When the sun is below the horizon, do not display normal direct-sunlight shadows as if the sun were above the ground.

At very low positive solar elevation, prevent excessively long or unstable shadows from dominating the scene. Use a smooth, documented transition rather than abrupt thresholds.

Preserve the existing continuous day/night brightness transition. Do not add a hard morning/day or day/night switch.

Nighttime lighting from streetlights and vehicle headlights must continue to work as before. Do not confuse their illumination with direct sunlight.

## Phase 6 — Optimize for the top-down camera

Performance is a primary requirement.

Start with the simplest shadow configuration that produces acceptable results. Benchmark alternatives before increasing quality settings.

Evaluate:
- Directional shadow mode and shadow-map resolution.
- Maximum shadow distance.
- Shadow split count, if using a split-shadow mode.
- Shadow bias and normal bias.
- Shadow updates when the sun moves.
- The number of building meshes included in shadow rendering.
- The cost of dynamic map chunks and moving vehicles.

Because the camera is top-down, prioritize crisp and stable shadows in the visible gameplay area over unnecessary shadow detail far outside the view.

Avoid enabling expensive multi-split shadows by default without demonstrating that the visual benefit justifies their cost.

Avoid excessive real-time shadow filtering or contact-hardening effects unless benchmarks prove they are affordable.

If necessary, expose a graphics setting for shadow quality or an off option, but do not add unnecessary configuration complexity before the baseline implementation has been measured.

## Phase 7 — Automated tests and visual verification

Add tests for solar azimuth and direction conversion, including:
- Morning, noon, and evening.
- Summer and winter dates.
- Different azimuth quadrants.
- Low solar elevation.
- The sun below the horizon.
- Continuity across consecutive time updates.

Add Godot validation and rendering checks where supported.

Provide a repeatable visual test procedure using a fixed location, date, time, camera position, and representative buildings.

Verify at least:
1. Morning: shadows point away from the morning sun.
2. Midday: shadows are shorter when the sun is higher.
3. Evening: shadows rotate as the sun moves.
4. Winter: the low sun produces longer shadows than at a comparable summer midday.
5. Night: direct sunlight shadows are absent.
6. Map movement: shadows remain correctly oriented while the camera and loaded chunks move.

Use scripted screenshots or automated image comparisons if the existing test infrastructure supports them. Do not rely solely on a screenshot to prove astronomical correctness.

## Phase 8 — Performance regression testing

Measure performance before and after enabling shadows using the project's existing benchmark methodology.

Use the same:
- Hardware and rendering backend.
- Resolution and camera configuration.
- Map area and building dataset.
- Game time and weather.
- Test duration and workload.

Record average FPS and frame-time behavior, including noticeable spikes. Compare results against the existing baseline and established performance target.

If shadow rendering causes a material regression, reduce its cost before considering the task complete. Do not claim that performance is preserved without measurements.

## Deliverables

Provide:
- Solar azimuth calculation integrated with the existing elevation model.
- Correct Godot directional-light orientation.
- Dynamic 3D building shadows on the surrounding environment.
- Appropriate nighttime and low-sun behavior.
- Automated solar calculation tests.
- A reproducible visual verification procedure.
- Before/after performance measurements.
- Documentation of coordinate conventions and shadow settings.
- A list of changed files and test results.

Do not modify unrelated gameplay or rendering systems.

Commit the completed implementation on the current working branch and push it if the existing workflow permits it. Do not create or push Git tags.

In the final report, clearly state whether shadows were visually verified in the actual Godot renderer, whether the FPS target was maintained, and what limitations remain.

## Additional Phase — Weather-Dependent Sunlight and Shadow Visibility

### Objective

Integrate the existing weather simulation with the solar lighting and dynamic building-shadow system.

Direct sunlight and building-shadow visibility must reflect both solar elevation and current weather conditions. Overcast skies must not produce clearly visible, hard-edged direct-sunlight shadows.

### Requirements

1. Inspect the existing weather model and identify how cloud cover, rain, thunderstorms, snow, and weather transitions are represented. Reuse the existing authoritative weather state. Do not create an independent weather system.

2. Introduce a continuous sunlight-visibility factor based on solar elevation and weather conditions. Use this factor to control the effective direct-sunlight contribution and the visibility and contrast of building shadows.

3. Under clear skies, retain visible directional sunlight and well-defined building shadows when the sun is above the horizon.

4. Under partly cloudy conditions, reduce direct sunlight and shadow contrast according to the existing weather state. Transitions must be smooth.

5. Under fully overcast conditions, suppress direct-sunlight shadows so that they are effectively invisible in normal gameplay. Avoid hard-edged shadows that contradict the visual appearance of an overcast sky.

6. During rain and thunderstorms, use the existing cloud and weather information to determine direct-sunlight visibility. Do not assume that rain always means zero sunlight if the weather model supports different cloud conditions.

7. If the existing model does not represent cloud coverage separately, introduce the smallest compatible extension needed to distinguish clear, partly cloudy, and overcast conditions. Document any approximations. Do not infer precise cloud coverage from precipitation alone.

8. Preserve the existing day/night transition. When the sun is below the horizon, direct-sunlight shadows must remain absent regardless of weather. Nighttime streetlights and vehicle headlights must continue to work.

9. Keep the solar direction physically consistent. Weather should primarily affect direct-light intensity and shadow contrast, not arbitrarily rotate shadows or alter the calculated solar azimuth.

10. Avoid expensive real-time cloud rendering or volumetric atmospheric effects. This task concerns weather-aware lighting and shadow rendering, not a complete atmospheric renderer.

### Rendering implementation

Inspect the capabilities and limitations of the current Godot renderer and version.

Choose an approach that reduces direct-light and shadow contribution smoothly as cloud cover increases. Do not assume that reducing a directional light's energy alone will remove its shadows: verify the actual rendering behavior.

If necessary, combine direct-light energy control with a compatible shadow-visibility or shadow-strength approach. Ensure that the solution works with the existing map surface and 3D building meshes.

Avoid abrupt threshold-based changes, visible flickering, or rapid updates that cause shadow popping. Update lighting only as frequently as necessary.

### Tests and visual verification

Verify the same location, date, time, camera position, and buildings under:
- Clear daytime skies.
- Partly cloudy skies.
- Fully overcast daytime skies.
- Rain with the cloud conditions supported by the weather model.
- Thunderstorms.
- Snowy weather, where supported.
- Sunrise and sunset.
- Nighttime.

Confirm that clear-sky shadows are visible, overcast shadows are effectively absent, and intermediate conditions transition smoothly.

Add automated tests for the weather-to-sunlight factor and its boundary conditions. Add a reproducible Godot visual verification procedure because numeric tests alone cannot establish the final shadow appearance.

### Performance and delivery

Measure performance with shadows enabled under clear and overcast conditions. Avoid unnecessary shadow-map updates or expensive per-frame weather calculations.

Preserve the existing FPS target and all unrelated gameplay behavior. Document the weather mapping, relevant parameters, test results, and any limitations.

Include these changes in the existing solar-shadow task. Do not create or push Git tags.