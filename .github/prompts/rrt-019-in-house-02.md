# Task: Generate 3D House Interiors from Existing Procedural Floorplans

## Objective

Implement the first phase of the transition from the existing 2D top-down house interiors to procedurally generated 3D interiors in Godot.

The game can already generate house floorplans, and the player can walk around inside them in the existing 2D view. Reuse this existing floorplan data and generation logic to create a corresponding 3D interior with floors, walls, and door openings.

**This phase is strictly about generating and validating 3D geometry. Do not implement first-person controls, camera switching, or new gameplay mechanics.**

## 1. Audit the Existing Implementation

Before changing code:

1. Locate the existing house interior generation system.
2. Identify the data structures representing buildings, rooms, walls, doors, windows, and furniture.
3. Determine how rooms connect and how doorways are represented.
4. Identify how the current 2D interior is instantiated, displayed, and removed.
5. Examine the existing Godot scene structure, rendering conventions, coordinate systems, and resource management.
6. Identify the existing tests and determine how procedural floorplans are validated.

Use the actual architecture and naming conventions found in the repository. Do not introduce a parallel floorplan generator or duplicate existing functionality.

Document any important assumptions about the existing floorplan representation before implementing the conversion.

## 2. Generate 3D Geometry from Existing Floorplans

Implement a new 3D representation that consumes the existing floorplan data.

Use the following initial dimensions as configurable defaults, adjusting them if the existing coordinate system requires a different scale:

- Interior wall height: 2.5 metres.
- Interior wall thickness: 0.12 metres.
- Standard interior door height: 2.0 metres.
- Standard interior door width: 0.8 metres.

Keep the conversion between floorplan units and Godot world units explicit and consistent.

### Floors

- Generate a floor surface for every room.
- Preserve room boundaries and connections.
- Avoid visible gaps between adjacent rooms.
- Ensure that floor surfaces do not overlap in ways that cause rendering artefacts.
- Support the room shapes produced by the existing procedural generator rather than assuming every room is rectangular.

### Walls

- Generate vertical 3D wall geometry from the existing floorplan.
- Preserve the existing room layout and dimensions.
- Represent shared walls consistently.
- Avoid generating overlapping duplicate wall sections where adjacent rooms share a wall.
- Do not create solid wall geometry across door openings.
- Ensure that walls meet cleanly at corners.
- Avoid gaps, unintended overlaps, and z-fighting.

Prefer generating wall segments from the actual floorplan boundaries rather than independently creating four complete walls for every room.

If the current data model represents room boundaries independently, implement a reliable way to identify shared boundaries and merge or deduplicate them.

### Door Openings

- Preserve existing door locations and room connections.
- Create genuine openings in wall geometry where doors are defined.
- Ensure that openings have consistent dimensions and align with the adjoining rooms.
- Do not add doors or openings where the source floorplan does not support them.
- Actual animated doors and door interaction are outside the scope of this phase.

The resulting geometry must make it possible to walk between connected rooms once a player controller is implemented in a later phase.

### Windows

If the existing floorplan data includes window locations, generate corresponding openings in exterior walls.

Do not invent window locations based on unsupported assumptions. If windows are not represented in the existing data, keep window generation outside this phase and structure the implementation so that it can be added later.

### Roof and Ceiling

The generated interior must be viewable from inside.

Do not create a roof or ceiling that obstructs the interior view from the intended inspection viewpoint. If the existing exterior building representation includes a roof, determine how to prevent it from obscuring the interior without breaking the exterior rendering.

A complete ceiling system is not required in this phase.

## 3. Geometry and Collision Preparation

Create geometry that can later support first-person exploration.

- Use suitable mesh geometry for floors and walls.
- Where practical, generate simple collision geometry for the floors and walls.
- Ensure collision geometry follows the actual openings rather than blocking doorways.
- Do not add a player controller or camera.
- Avoid overly detailed collision geometry.
- Keep visual geometry and collision geometry logically separated where this fits the existing architecture.

Do not introduce a physics simulation for the house itself.

## 4. Visual Appearance

Use simple, neutral materials sufficient to distinguish the main surfaces:

- Floors.
- Interior walls.
- Exterior walls, if represented separately.

Prioritise correct geometry over visual detail.

Do not introduce elaborate textures, furniture models, decorative assets, advanced lighting, or complex materials in this phase.

Use existing project resources and conventions where appropriate. Avoid adding external asset dependencies.

## 5. Integration with the Existing Game

- Preserve the existing 2D interior mode and its behaviour.
- Do not replace the current floorplan data model with a 3D-only representation.
- Make the new 3D representation an additional view of the same generated interior.
- Follow the existing building-entry and interior lifecycle.
- Do not change the server-authoritative simulation or unrelated gameplay systems.
- Avoid unnecessary changes to the exterior building renderer.
- Do not implement FPS controls, mouse-look, camera switching, or new input bindings yet.

If a suitable development or debugging workflow already exists, integrate the 3D interior into it. Otherwise, add the smallest practical way to inspect generated 3D interiors without disrupting the normal game.

## 6. Performance and Resource Management

The game may contain a large number of buildings, but only a small number of interiors need to be instantiated at any given time.

- Generate 3D interior geometry only when needed.
- Do not generate 3D interiors for every building during world initialisation.
- Reuse the existing floorplan where possible rather than generating it again.
- Avoid creating unnecessary nodes and mesh instances for individual small geometry elements.
- Combine compatible static geometry where beneficial, without making door openings or room boundaries incorrect.
- Keep collision geometry simple.
- Follow existing resource cleanup and caching patterns.
- Ensure that leaving an interior does not leave unnecessary nodes, meshes, or collision objects behind.

Do not introduce aggressive caching or complex optimisation infrastructure without evidence that it is needed.

## 7. Validation and Testing

Add or extend tests for the conversion logic using the repository's existing testing conventions.

Cover at least the following cases:

1. A simple rectangular room.
2. Multiple adjacent rooms with a shared wall.
3. Two rooms connected by a doorway.
4. A room with an exterior wall.
5. An irregular room shape, if supported by the existing floorplan generator.
6. A floorplan containing multiple connected rooms.

Verify that:

- Generated geometry has valid dimensions and coordinates.
- Shared walls do not produce unintended duplicate geometry.
- Door openings remain open.
- Connected rooms have continuous floor surfaces.
- The conversion does not mutate or corrupt the original floorplan.
- Existing 2D interior tests continue to pass.

Where automated tests cannot validate visual geometry, provide a practical in-game or development inspection workflow.

## 8. Acceptance Criteria

This phase is complete when:

- An existing procedurally generated floorplan can be rendered as a 3D interior.
- Floors and walls follow the source floorplan.
- Door openings connect the intended rooms.
- Shared walls and corners are handled correctly.
- The interior can be inspected from a suitable viewpoint.
- Existing 2D interior functionality remains available and unchanged.
- The conversion does not generate interiors for all buildings unnecessarily.
- Tests cover the principal geometry-conversion cases.
- The implementation is ready for a subsequent phase adding a first-person player controller.

## 9. Implementation Workflow

1. Audit the existing code and identify the minimum required changes.
2. Explain the proposed implementation briefly, including how shared walls and door openings will be handled.
3. Implement the 3D geometry generation using the existing floorplan data.
4. Integrate it with the existing interior lifecycle and inspection workflow.
5. Add tests and run the relevant existing test suites.
6. Run the applicable Godot validation and headless checks available in the repository.
7. Inspect the changes for regressions, unnecessary duplication, and resource leaks.
8. Fix any issues discovered during validation.
9. Make atomic Git commits for logically independent, completed changes.

Do not expand the scope into first-person movement or decorative interior modelling. If the existing floorplan data cannot reliably represent a required feature, identify the limitation rather than silently fabricating geometry.