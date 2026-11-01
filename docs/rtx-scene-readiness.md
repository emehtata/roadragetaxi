# Outdoor scene prerequisites before enabling RTX

Status: implementation plan based on the source audit of 1 November 2026.
The checks below are completion criteria, not claims that the work is done.

For engine compilation, runtime deployment, capability detection and export
requirements, see [NVIDIA RTX Godot adoption](nvidia-rtx-godot.md). This document
covers the game scene that must exist before outdoor path tracing can provide
useful, consistent lighting and reflections.

## Goal and scope

Build a shared 3D outdoor scene that works correctly under Forward+ raster
rendering first. Then enable path tracing in an isolated developer trial and
compare it with that baseline. A limited trial can begin with one street;
player-facing outdoor RTX needs the broader coverage checks below.

The existing first-person home interior remains a separate, smaller engine
trial. Completing it does not establish outdoor readiness.

Keep Python authoritative for the existing simulation, traffic, weather,
calendar and map data. Convert presentation using the existing protocol where
possible. Preserve map-layer separation and bounded chunk/update work. Any
needed elevation metadata should be an explicit protocol addition; do not
move gameplay decisions into the renderer.

## Current starting point

[buildings_3d.gd](../godot/buildings_3d.gd) now puts ordinary car, van and taxi
bodies into the buildings' 3D world. It pools body/caster instances and caches
meshes. However, those bodies share the buildings' unshaded shader, their face
colors include baked shading, and the common mesh builder omits normals.

[entity_layer.gd](../godot/entity_layer.gd) keeps the vehicle lamps in 2D and
uses 2D body paths for other categories, under-bridge vehicles and fallen
vehicles. Much of the surrounding world is still CanvasItem geometry.

The outdoor presentation combines a transparent building viewport, a separate
multiplied shadow viewport, a 2D ground map and screen-space lighting. Enabling
path tracing on that arrangement alone would leave important surfaces and
light interactions outside the traced scene.

## Step 1: establish the shared outdoor 3D view

- Give ground, roads, buildings, vehicles and local lights one shared World3D
  and a consistent camera. A SubViewport is acceptable; it must render the
  interacting outdoor scene rather than only a transparent building overlay.
- Reuse the current map-relative coordinate convention and subtract the large
  world origin before packing positions into Vector3. Keep the top-down camera
  and existing driving view while changing the rendering underneath it.
- Define ownership of geometry, lights and materials per chunk. Keep static
  mesh construction outside the per-frame update path and release resources
  on chunk unload. Reuse dynamic instances and update their transforms.
- Keep menus, HUD, labels, navigation and interaction markers as overlays.
  Ensure existing 2D world layers are not drawn again over the new 3D scene.
- Preserve camera-derived server view bounds when the camera path changes.

**Done when:** a small test street renders ground, one building and the taxi
in one Forward+ view; resize, zoom, movement and chunk unload work; HUD and
input remain aligned. Capture and inspect the rendered result.

Relevant code: [map_layer.gd](../godot/map_layer.gd),
[buildings_3d.gd](../godot/buildings_3d.gd), [main.gd](../godot/main.gd).

## Step 2: make existing meshes respond to light

- Add outward-facing normals to the generated meshes. Generate tangents where
  the selected material needs tangent-space normal maps.
- Use shaded spatial materials for opaque surfaces. Separate car paint,
  rubber, glass and lamps through material surfaces or explicit material masks.
- Remove baked directional shading and ambient tint from base colors in the
  new material path. Keep base color, roughness, metallic response and emission
  as distinct inputs. Most ground, masonry and rubber should be nonmetallic.
- Port building snow, windows and seasonal appearance from the unshaded shader
  to material properties. Preserve server-driven snow and shop/window states.
- Give windows and taxi signs genuine emission where appropriate. A brighter
  albedo color is not a substitute for emission.
- Start with opaque reflective car windows if necessary. Treat transparent glass
  and refraction as separately verified features of the selected fork build.

**Done when:** moving a light changes shading on the car and building faces,
paint and rubber have visibly different highlights, and the same light is not
applied again through baked colors or canvas tint. Verify normals and winding
on roofs, glass, walls and vehicle undersides visible to secondary rays.

Relevant code: `_mesh`, `_car_box`, `_make_material`, `set_light` in
[buildings_3d.gd](../godot/buildings_3d.gd), and
[building_snow.gdshader](../godot/building_snow.gdshader).

## Step 3: add ground, roads and wet surface materials

- Build chunked 3D surfaces from existing ground, road, pavement, parking and
  landuse polygons. Add visible curb and island height where it matters.
- Port [surface.gdshader](../godot/surface.gdshader) patterns into shaded
  materials. Keep markings as material masks, textures or shallow surface
  geometry with controlled depth offsets; detailed geometry per stripe is
  unnecessary. Verify the chosen representation works in the fork.
- Replace painted wet-road sheen with material wetness and roughness. Give
  puddles reflective surfaces and ripple normals; drive them from the existing
  weather state. Avoid duplicate coplanar surfaces and chunk seams.
- Supply a defined sky/environment for reflective surfaces to see. The test
  street must have continuous ground beneath cars and around buildings.

**Done when:** Forward+ lights illuminate the road, cars sit on it without
floating or flickering, wet and dry surfaces differ through material response,
and road appearance stays continuous across loaded chunks.

Relevant code: `_draw_roads`, `_draw_wet`, `_draw_puddles` in
[map_chunk.gd](../godot/map_chunk.gd).

## Step 4: replace the lighting and shadow composition

- Provide a 3D sky/environment and sun/moon lights driven by the existing
  server calendar and weather. Tune exposure and tone mapping for the scene.
- Add vehicle headlights as directed 3D lights, plus emissive lamp surfaces.
  Add streetlights and the important nearby shop and floodlight sources.
- Preserve switching behavior: broken lamps, vehicle engine/brake/reverse/turn
  states, taxi availability and scheduled building lights.
- Bound active light counts and shadow costs. Reuse lights; prioritize those
  whose influence reaches the nearby scene. Do not allocate one expensive
  shadowed light for every distant mapped lamp.
- Stop applying the old headlight polygons, painted streetlight pools and
  canvas ambient multiplication to the new scene. Keep an independent path
  for the established renderer if it still needs them.
- Let the real scene cast and receive shadows. Remove the separate multiplied
  ground-shadow composite and redundant caster geometry from the new path
  once the replacement is verified. Test camera/light visibility masks.

**Done when:** a wall blocks a headlight, a streetlight illuminates the taxi
and pavement, and daytime and nighttime remain readable without double
shadows or duplicate brightening. Verify the raster baseline first.

Relevant code: [night_layer.gd](../godot/night_layer.gd),
[main.gd](../godot/main.gd), `_draw_light_pools` in
[map_chunk.gd](../godot/map_chunk.gd), and the shadow viewport in
[buildings_3d.gd](../godot/buildings_3d.gd).

## Step 5: convert vertical separation and major occluders

- Represent bridges, ramps, rail decks, tunnel enclosures, canopy roofs and
  supports at consistent physical elevations. A CanvasItem z-index is drawing
  order, not a physical height; OSM layer numbers are not metre measurements.
- Place vehicles on their actual visual deck or ramp height. Replace the
  explicit 2D under-bridge fallback in the new path. Preserve existing logical
  map levels, collision behavior and transitions.
- Add nearby walls, fences, hedges, trees, shelters and large roadside props as
  simple reusable 3D meshes. Prioritize objects that block headlights, cast
  substantial shadows or should appear in road/car reflections.
- Keep tree/prop populations bounded. Use shared meshes and chunked instancing
  where appropriate; verify the fork's ray tracing instance cost and foliage
  material support before expanding dense forest coverage.

**Done when:** a vehicle below a bridge stays below it, the deck casts a useful
shadow, canopies shelter their ground visually, and major nearby objects do
not disappear from the shared lighting scene. Check both travel directions
and transitions between levels.

Relevant code: [chunk_detail.gd](../godot/chunk_detail.gd),
[map_chunk.gd](../godot/map_chunk.gd), [forest.gdshader](../godot/forest.gdshader),
and `_vehicle_body` in [entity_layer.gd](../godot/entity_layer.gd).

## Step 6: complete nearby scene coverage

Before offering outdoor RTX as a general gameplay option, cover the entities
and surfaces that can enter the player's surrounding scene:

| Category | Required presentation work |
| --- | --- |
| Vehicles | Add buses, trucks, tractors/ploughs, campers/trailers, motorcycles, bicycles, trains and trams; cover fallen/damaged states. |
| People and animals | Add simple shaded 3D bodies with the existing interpolated motion and animation state. Include riders and nearby larger animals. |
| Roadside fixtures | Add lamps, signals, signs, barriers, pumps and other prominent nearby props; retain readable overlays where useful. |
| Water and ice | Add 3D surfaces with roughness and wave/ripple normals. Verify reflection, transparency and ice appearance on the selected fork. |
| World effects | Give smoke, dust and splashes depth where needed. Verify particle/transparency support; screen-space precipitation may remain an intentional overlay initially. |

Detailed models are not a prerequisite. Simple geometry with correct shape,
material and height provides the required interactions. HUD, map labels and
navigation arrows can stay 2D. Ground markings need to belong to the road
surface but do not require thick 3D models.

**Done when:** an ordinary drive does not switch essential nearby objects
between the shared 3D scene and unrelated 2D body drawings. Record any
remaining effect exclusions explicitly.

## Step 7: prove readiness and enable a controlled RTX trial

Steps 1–4 on a bounded street are enough for the first developer trial.
Steps 5–6 are required for consistent outdoor gameplay coverage. Validate
Forward+ raster before enabling the path tracer so scene conversion problems
can be distinguished from fork-specific behavior.

1. Confirm the selected pinned engine, Vulkan Forward+, RT device support and
   required Streamline capabilities using the adoption document's checks.
2. Assign the path tracing Environment and DLSS settings to the viewport that
   actually renders the outdoor World3D. Keep fork-only APIs behind runtime
   discovery so upstream Godot can still parse shared scripts.
3. Retain a bounded off-screen geometry margin for reflections and shadows.
   Measure its memory and update costs; camera-visible geometry alone may be
   insufficient. Preserve stable instance identity for moving objects where
   possible, and inspect temporal trails when instance pools are reused.
4. Start with a dry daytime street and one moving car. Then check a wet night
   street with headlights, a building/window, a bridge, foliage and pedestrians.
   Look for missing reflections, light leaks, ghosting, alpha errors, duplicate
   shadows and layer mistakes. Do not assume every raster effect is supported.
5. Compare the standard renderer, Forward+ raster, path tracing at native scale
   and path tracing with DLSS. Disable Frame Generation for these comparisons.
   Record hardware, driver, engine/runtime versions, resolution, frame times,
   VRAM and cold/warm shader behavior. Agree on a target budget before rollout.
6. Render, capture and visually inspect every affected view as required by
   AGENTS.md. Check resize, zoom, repeated chunk load/unload, interior entry/exit
   and returning to the standard renderer. Run the relevant existing client and
   server checks; headless success does not establish RT visual correctness.

**Ready to expose experimentally when:** scene coverage is consistent, the
feature reports what is actually active, representative scenes meet the
agreed budget, and unavailable hardware/runtime features produce a useful
explanation. Follow the separate adoption document's export and runtime
packaging requirements before distributing it.

## Suggested atomic implementation sequence

1. Shared outdoor viewport and a small 3D street surface.
2. Mesh normals and shaded vehicle/building materials.
3. Spatial road materials, markings and wetness.
4. Sky, celestial light, headlights and streetlights; retire duplicate lighting
   and shadow composition in the new path.
5. First controlled RTX street trial with recorded results.
6. Bridges, vertical placement and major roadside occluders.
7. Remaining vehicles, people, vegetation and water coverage.
8. Final capability handling, broader visual/performance checks and optional
   experimental packaging.

Each rendering change should have a raster result that can be inspected before
adding another conversion. Update this plan as implementation establishes
which fork features and performance limits are actually usable.
