# Road Rage Taxi – Godot 3D Lighting Audit and Streetlight Stability

Repository: `emehtata/roadragetaxi`

Target branch: `release/v0.21.0beta`

## Objective

Perform a thorough audit of the current Godot 3D lighting implementation and identify the exact causes of streetlight flickering, popping, or switching off while the player drives through the city.

Do not redesign the entire rendering system yet.

## 1. Audit the current implementation

Inspect at least:

- `godot/buildings_3d.gd`
- `godot/map_layer.gd`
- `godot/map_chunk.gd`
- `godot/daylight.gd`
- `godot/main.gd`
- `godot/project.godot`
- Relevant lighting shaders and tests.

Document:

- How streetlight positions are obtained.
- How broken streetlights are excluded.
- How the 3D streetlight pool is populated.
- How lights are selected and sorted.
- When the light pool is refreshed.
- What happens when a light leaves the camera area.
- Whether lights are abruptly reassigned to new positions.
- Whether renderer-specific light limits are exceeded.
- Whether mesh visibility AABBs cause lights to disappear.
- Whether camera movement, chunk loading or unloading causes flickering.
- Whether lighting updates are unnecessarily synchronized with simulation state updates.

## 2. Fix streetlight stability

Preserve the existing pooled-light architecture unless profiling demonstrates that it is fundamentally unsuitable.

Requirements:

- Streetlight visibility must never depend on arbitrary camera movement.
- Preserve stable light assignments whenever possible.
- Introduce hysteresis when selecting replacement lights.
- Fade out a light before reassigning its pool slot.
- Avoid sudden changes in illumination when crossing chunk boundaries.
- Ensure broken streetlights remain dark.
- Keep streetlight intensity continuous through dusk and dawn.
- Do not increase the pool size without benchmark evidence.
- Never introduce per-frame creation or destruction of light nodes.

The physical lamp head and its emissive appearance must be independent of the temporary allocation of a real 3D light source.

## 3. Lighting architecture review

Evaluate the existing implementation against these principles:

- One directional sun.
- Continuous ambient daylight and nighttime lighting.
- Local streetlight illumination.
- Emissive building windows.
- Vehicle headlights.
- Wet-road reflections.
- Weather-dependent visibility and lighting.

Do not introduce expensive dynamic shadows for every streetlight.

Evaluate Forward+ against the current Compatibility renderer, but do not change the default renderer without a separate compatibility and performance assessment.

## 4. Testing

Create reproducible tests for:

- Driving continuously through dense streetlight areas.
- Crossing multiple map chunks.
- Driving at different speeds.
- Driving at dusk, night and dawn.
- Broken streetlights.
- Streetlights entering and leaving the camera view.
- Dense urban areas with more than 48 nearby streetlights.

Measure:

- Active 3D light count.
- Light assignment changes.
- Sudden light visibility changes.
- GPU rendering time.
- Frame time during continuous driving.

A successful implementation must not exhibit visible light popping or flickering during continuous driving.

## 5. Delivery

Provide:

1. Root-cause analysis.
2. Identified implementation defects.
3. Minimal corrective implementation.
4. Automated tests.
5. Before/after performance measurements.

Use atomic commits. Do not create Git tags.

Do not modify the Python simulation or its authoritative game rules. All changes belong to the Godot presentation layer.