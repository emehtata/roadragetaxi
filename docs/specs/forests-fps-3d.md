# Implement True 3D Forest Rendering for FPS and First-Person Vehicle Views

We need to replace the current top-down forest texture representation with actual 3D forest rendering so forests are visible naturally from ground level in FPS mode and through vehicle windshields.

## 1. Audit the existing implementation

Before changing anything:

- Inspect the current forest generation and rendering pipeline.
- Identify how forest areas are extracted from map data.
- Identify whether tree species, density, vegetation polygons or individual tree positions are available.
- Inspect how forest textures are generated and assigned to terrain.
- Inspect the existing Godot 3D renderer, terrain implementation, camera system and chunk streaming.
- Determine how forest data is transferred from the Python simulation/server to Godot.
- Identify existing resource and performance constraints.

Do not assume that individual tree positions are already available.

Preserve the existing 2D forest rendering for the top-down game mode.

## 2. Implement actual 3D trees

Introduce a reusable 3D tree rendering system.

Initially support at least:

- Pine
- Spruce
- Birch

Requirements:

- Visible trunks with believable proportions.
- Distinctive species-specific canopy shapes.
- Branches and foliage.
- Appropriate Finnish boreal forest appearance.
- Natural variations in tree height, width and rotation.
- Avoid repetitive identical tree patterns.
- Trees must be recognizable from a first-person camera at ground level.

Use optimized meshes and materials.

Avoid unnecessarily detailed geometry. The goal is convincing natural appearance at normal gameplay distances.

## 3. Forest placement

Use existing forest polygons and available vegetation data to determine where trees should appear.

Implement deterministic procedural tree placement:

- Tree density should vary naturally.
- Tree placement must respect forest polygon boundaries.
- Avoid placing trees on roads, buildings, water or other unsuitable terrain.
- Support mixed forests where data allows.
- Avoid uniform grid patterns.
- Ensure trees remain stable when map chunks are unloaded and loaded again.

If species information is unavailable, use a deterministic species distribution appropriate for Finnish forests.

Do not introduce arbitrary forest coverage or invent tree locations outside actual forest areas.

## 4. Godot rendering architecture

Use MultiMeshInstance3D or another appropriate GPU-instancing solution.

Requirements:

- Batch trees efficiently.
- Separate rendering by species and suitable spatial chunks.
- Integrate with the existing map chunk streaming system.
- Do not create one Node3D per tree.
- Implement distance-based rendering and LOD.
- Use simplified geometry for distant trees.
- Consider impostors or billboard representations only at sufficiently large distances.
- Ensure proper depth testing and occlusion.
- Avoid unnecessary transparency overdraw.

The existing forest texture may remain as a distant background representation, but it must not replace actual 3D trees in the visible gameplay area.

## 5. FPS and vehicle camera compatibility

Test the forest from:

1. Walking at normal human eye height.
2. Standing still inside a forest.
3. Walking along a forest road.
4. Driving through a forest.
5. Looking through the vehicle windshield.
6. Looking sideways through vehicle windows.
7. Looking towards a forest from an open field.

Pay particular attention to tree trunk visibility and correct perspective.

Trees must not disappear when switching between top-down, FPS and vehicle cameras.

## 6. Terrain integration

Ensure that tree roots align with actual terrain elevation.

If terrain height data is available, use it when positioning trees.

Trees must not float above the ground or become buried in the terrain.

Account for slopes and elevation differences.

## 7. Performance requirements

The game targets stable performance above 60 FPS.

Measure:

- Number of visible tree instances.
- Number of draw calls.
- CPU time spent generating forest chunks.
- GPU rendering time.
- Memory consumption.
- FPS in dense forest and mixed urban/forest environments.

Use frustum culling and distance-based LOD.

Do not introduce arbitrary global tree-count limits that cause visibly empty forests.

Tree generation should not block the simulation's 30 Hz server tick.

## 8. Testing requirements

Create reproducible test scenarios using actual map locations.

Do not place the player or vehicle at arbitrary random coordinates.

Select representative locations containing:

- Dense Finnish forest.
- Mixed forest.
- Forest edge next to a road.
- Sparse woodland.
- Open area with distant forest.

Use the same camera positions and test conditions for before/after comparisons.

Verify that the result is visually convincing from ground level.

## 9. Compatibility

- Preserve the existing top-down forest appearance.
- Do not change simulation rules or collision behavior.
- Keep forest rendering entirely client-side.
- Do not introduce client-side gameplay physics.
- Preserve existing map chunk streaming architecture.
- Do not introduce a new map-data format unless strictly necessary.

## 10. Delivery

Implement this in small, independently verifiable steps.

Provide:

- Architecture findings.
- Implementation summary.
- Files changed.
- Performance measurements.
- Screenshots from actual FPS and vehicle viewpoints.
- Known limitations.

Commit each logically complete implementation step separately.

Do not declare the feature complete until actual ground-level forest rendering has been verified in the running game.