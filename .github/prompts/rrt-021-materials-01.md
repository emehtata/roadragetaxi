# Road Rage Taxi – PBR Material System and Surface Rendering

You are working on the Road Rage Taxi repository:

https://github.com/emehtata/roadragetaxi/tree/release/v0.21.0beta

The game uses a Python server for authoritative simulation and a Godot client for rendering. The Godot client streams map chunks dynamically. Preserve this architecture.

## Main objective

Implement a reusable, scalable PBR material system for the Godot renderer.

The goal is to make different physical surfaces visually distinct and convincing:

- Asphalt and road surfaces
- Wet asphalt
- Concrete
- Brick
- Plaster and painted walls
- Glass
- Steel and other metals
- Painted metal, including vehicle paint
- Plastic
- Rubber
- Wood
- Road markings and other painted surfaces

Materials must react correctly to lighting and weather. Metal surfaces should have convincing environmental reflections where supported by the active rendering backend.

Do not attempt to implement every visual effect at once. Build the foundation first, verify it, and extend it incrementally.

## Phase 0 – Audit the existing implementation

Before changing code, inspect the current implementation on the active branch.

Inspect at least:

- `godot/project.godot`
- `godot/map_layer.gd`
- `godot/map_chunk.gd`
- `godot/buildings_3d.gd`
- `godot/daylight.gd`
- `godot/night_layer.gd`
- `godot/main.gd`
- All scripts responsible for creating road, terrain, building and vehicle meshes
- Existing materials, shaders and texture resources
- The map chunk loading and unloading lifecycle

The file list is a starting point, not an exhaustive list. Find the actual material creation and assignment paths.

Document:

1. Where meshes are created.
2. How surfaces and material overrides are currently assigned.
3. Whether materials are shared or duplicated per mesh/chunk.
4. How streamed chunks acquire and release their resources.
5. Whether materials are created dynamically during chunk loading.
6. Which parts of the renderer use procedural geometry.
7. Which parts use imported meshes or textures.
8. Which rendering backend is currently configured.
9. Which reflection, ambient occlusion and screen-space effects are supported by that backend.
10. Whether existing shaders or materials conflict with a centralized material system.

Pay particular attention to resource lifetime and memory use during repeated chunk loading and unloading.

Do not assume that the rendering backend or its capabilities are unchanged from previous versions. Verify the current configuration.

Produce a concise audit report before implementation.

## Phase 1 – Centralized material library

Create a centralized material library, preferably in a dedicated script such as:

`godot/material_library.gd`

Adapt the location and structure to the existing project conventions.

The library must provide reusable material resources for the major surface categories.

Use Godot StandardMaterial3D and physically based rendering parameters wherever possible.

Define sensible initial values for:

- Albedo
- Metallic
- Roughness
- Normal maps
- Ambient occlusion, where appropriate
- Emission, where appropriate

Create distinct material definitions for at least:

- Dry asphalt
- Wet asphalt
- Concrete
- Brick
- Plaster
- Glass
- Brushed steel
- Polished metal
- Painted metal
- Plastic
- Rubber
- Wood
- Road markings

These are starting categories. Avoid creating unnecessary material variants.

Requirements:

- Reuse shared material resources.
- Avoid creating duplicate materials for every building or map chunk.
- Do not mutate shared material properties globally when an individual object needs a different appearance.
- Use per-instance shader parameters or another appropriate Godot mechanism when individual instances need variation.
- Avoid creating materials every frame.
- Avoid expensive runtime resource loading in frequently executed rendering paths.
- Keep the material library independent of server-side simulation logic.

Do not introduce an elaborate material framework if a small, maintainable library is sufficient.

## Phase 2 – Assign materials to existing geometry

Integrate the material library with the existing procedural geometry generation.

Assign materials according to the actual surface type.

Examples:

- Roads should use asphalt.
- Pavements should use concrete or appropriate paving materials.
- Building facades should use different materials according to available source data.
- Metal structures should use metal materials.
- Windows should use glass materials.
- Vehicle tires should use rubber.
- Vehicle bodywork should use painted-metal materials where appropriate.

Use existing map metadata where available.

Do not invent detailed material information that the source data does not provide.

When material information is missing, use deterministic and visually reasonable defaults. If building variation is needed, derive it deterministically from a stable building or feature identifier. Do not generate random material choices every time a chunk loads.

Preserve existing geometry, collision behavior, map coordinates, building heights and chunk boundaries.

Do not change the authoritative Python simulation.

## Phase 3 – Surface detail

Introduce surface detail only where it provides a meaningful visual improvement.

Consider:

- Asphalt texture variation
- Concrete texture variation
- Brick patterns
- Normal maps
- Roughness maps
- Subtle surface imperfections
- Triplanar mapping for procedural geometry where conventional UV coordinates are unavailable or unsuitable

Avoid obvious texture repetition.

Do not introduce high-resolution textures indiscriminately. Consider GPU memory usage and the number of simultaneously loaded chunks.

Texture resources should be reused across chunks.

Do not add expensive shader calculations to every material without measuring their impact.

## Phase 4 – Environmental reflections and metallic surfaces

Make metallic surfaces respond convincingly to their environment.

First determine what the current rendering backend supports.

Evaluate:

- Environment and sky reflections
- ReflectionProbe usage
- Screen-space reflections, if supported
- ReflectionProbe update modes and their performance implications

Do not assume that all rendering backends support the same features.

For example, screen-space reflections are not available in the Compatibility renderer. Do not implement a feature that silently does nothing on the configured backend.

Use reflection probes selectively rather than creating one for every building or map chunk.

Prioritize:

1. Vehicle bodywork
2. Chrome and metallic vehicle details
3. Glass and selected building surfaces
4. Wet road surfaces

Metallic materials must still look acceptable when detailed environmental reflections are unavailable.

Do not enable real-time dynamic shadows on every streetlight or create a large number of continuously updating reflection probes.

## Phase 5 – Weather-aware materials

Prepare the material system for dynamic weather effects.

The same surface should be able to change appearance without replacing its entire material resource.

Implement the first weather-aware feature:

**Wet asphalt.**

Requirements:

- Dry asphalt should remain relatively rough and matte.
- Wet asphalt should have lower roughness and stronger reflections.
- The wetness effect should change smoothly.
- Wetness should be controlled by the existing weather system if suitable data is available.
- Do not invent new weather state variables without first inspecting the existing implementation.
- Do not make all surfaces equally wet.
- Pavements, buildings and vehicle materials should not automatically receive the same wetness treatment.

Use a shared parameter or another efficient mechanism to control wetness.

Do not create a separate material instance for every road segment just to change wetness.

If the existing renderer cannot support a particular reflection effect, implement a sensible fallback and document the limitation.

## Phase 6 – Performance and streaming verification

The material system must work with the existing dynamic map streaming.

Verify:

- Loading a new chunk does not create unnecessary duplicate materials.
- Unloading chunks does not leave unwanted references or resources behind.
- Material assignments remain stable when revisiting previously loaded areas.
- There are no visible material changes or flickering at chunk boundaries.
- The system does not cause unnecessary shader recompilation during normal driving.
- Material changes do not introduce significant CPU overhead.
- GPU memory use remains reasonable.

Measure performance before and after implementation.

Pay attention to:

- FPS
- GPU frame time
- CPU frame time
- Number of material resources
- Number of material instances
- Texture memory
- Chunk loading time

Do not optimize based on assumptions. Measure the actual impact.

## Phase 7 – Visual verification

Create or identify a suitable test area with:

- Several different building facade types
- Asphalt and pavement
- Metal objects
- Glass surfaces
- Vehicles with different paint colors
- Streetlights and other local light sources

Verify the appearance under:

1. Bright daylight
2. Overcast daylight
3. Sunset
4. Night
5. Rain and wet road conditions

Check that materials remain visually distinct in all conditions.

Make sure metallic surfaces do not simply become black at night.

Make sure glass does not become opaque or excessively reflective.

Make sure rough surfaces do not look polished.

## Architectural constraints

- Python remains responsible for authoritative game simulation.
- Godot remains responsible for rendering and presentation.
- Do not move simulation logic into Godot.
- Do not change collision detection or gameplay behavior.
- Do not change map streaming architecture unless a demonstrable issue requires it.
- Do not introduce a new rendering engine.
- Preserve the existing renderer as the default unless a separate, measured evaluation justifies a change.
- Keep the implementation maintainable and compatible with the existing project conventions.

## Implementation and delivery rules

Work in small, independently verifiable stages.

After each stage:

1. Run relevant automated tests.
2. Run the available Godot project validation or headless checks.
3. Inspect errors and warnings.
4. Verify that the game can still load and stream map chunks.
5. Summarize the changes and their performance implications.

Use atomic commits for logically separate stages.

Do not create or push Git tags.

Do not silently skip an implementation stage. If a feature is unsupported or cannot be verified, explain why and provide a practical alternative.

## Final report

Provide:

- Audit findings
- New and modified files
- Material categories implemented
- Rendering features supported by the active backend
- Reflection implementation and limitations
- Weather integration details
- Performance measurements before and after
- Tests performed and their results
- Remaining limitations and recommended next steps

The priority is a visually convincing and maintainable material system that works reliably with dynamically streamed geometry, not a collection of expensive graphical effects.