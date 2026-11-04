# Task: Implement First-Person Movement in Procedurally Generated 3D House Interiors

## Objective

Implement the second phase of the procedural house interior system: allow the player to explore generated 3D house interiors from a first-person perspective.

The previous phase introduced 3D geometry generated from the existing procedural 2D floorplan data. This phase adds the player controller, camera, collision handling, and transitions between the existing exterior gameplay and the 3D interior.

Before implementing anything, inspect the repository and verify the current state of the 3D interior implementation. Adapt the solution to the actual code rather than assuming that previous-phase classes or files have particular names.

## 1. Preserve the Existing Architecture

The game uses a Python server for authoritative simulation and a Godot client for rendering and player interaction.

Follow these constraints:

- Implement the first-person controller entirely on the Godot client.
- Do not move simulation responsibilities from the Python server to the client.
- Do not change unrelated vehicle, NPC, traffic, collision, or economy systems.
- Preserve the existing 2D interior mode.
- Do not replace or duplicate the existing procedural floorplan generator.
- Reuse the 3D geometry and collision data produced by the previous phase.
- Follow the project's existing scene, input, and resource-management conventions.

The first-person controller is for exploring house interiors. It must not replace the existing exterior player movement or vehicle controls.

## 2. First-Person Player Scene

Implement a dedicated first-person player controller using Godot's `CharacterBody3D`, unless the existing architecture provides a clearly better equivalent.

The controller should include:

- A `CharacterBody3D` root.
- A suitable collision shape.
- A head or camera pivot node.
- A `Camera3D` for first-person viewing.

Keep the controller separate from the generated house geometry so that it can be instantiated and removed cleanly.

Use configurable defaults approximately as follows:

| Setting | Default |
|---|---:|
| Player height | 1.75 m |
| Collision capsule radius | 0.30 m |
| Eye height | 1.60 m |
| Walking speed | 3.5 m/s |
| Mouse sensitivity | Configurable |
| Gravity | Use the project's existing conventions where applicable |

Treat these values as initial tuning parameters, not immutable constants.

Ensure the collision capsule fits through standard doorways without clipping through walls.

## 3. Movement Controls

Implement the following controls for the 3D interior:

- **W:** Move forward.
- **S:** Move backward.
- **A:** Strafe left.
- **D:** Strafe right.
- **Mouse:** Look around.
- **Escape:** Release the mouse cursor and provide a way to exit or pause the interior mode, consistent with the existing input conventions.

Use Godot's Input Map and existing project actions where appropriate. Do not create duplicate actions if equivalent actions already exist.

Movement requirements:

- Movement must be relative to the player's horizontal facing direction.
- Looking up or down must not cause the player to move vertically.
- Diagonal movement must not be faster than straight movement.
- Apply gravity and floor detection correctly.
- Prevent the player from walking through walls.
- Prevent the player from falling through floors.
- Allow movement through valid doorways.
- Avoid jitter and unintended sliding against walls.
- Use `CharacterBody3D` movement and collision handling rather than implementing a separate custom physics simulation.

Do not add jumping, sprinting, crouching, combat, or other unrelated mechanics in this phase.

## 4. Mouse Look and Camera

Implement first-person mouse-look:

- Horizontal mouse movement rotates the player around the vertical axis.
- Vertical mouse movement rotates the camera pivot.
- Clamp vertical rotation so the player cannot look completely upside down.
- Do not introduce camera roll.
- Keep mouse sensitivity configurable.
- Ensure mouse motion is not applied twice or accumulated incorrectly.

Capture the mouse when entering active first-person exploration.

Provide a reliable way to release the cursor, especially when the player needs to access an existing menu or exit the interior.

When returning to first-person exploration, restore mouse capture only when appropriate.

Avoid changing the camera configuration used by the existing exterior renderer.

## 5. Entering and Leaving an Interior

Integrate the controller with the existing building-entry and interior lifecycle.

When the player enters a building in 3D mode:

1. Identify the selected building and its generated floorplan.
2. Instantiate or activate the corresponding 3D interior.
3. Spawn the first-person controller at a valid entrance or other appropriate entry point.
4. Place the player at a safe height above the floor.
5. Orient the player toward the interior rather than into a wall.
6. Activate the interior camera.
7. Capture the mouse for first-person exploration.
8. Ensure that the player does not spawn inside a wall or furniture collision shape.

When the player exits:

1. Restore the existing exterior gameplay state.
2. Restore the appropriate exterior camera and player controls.
3. Release the first-person controller and its resources when no longer needed.
4. Restore mouse visibility and cursor interaction.
5. Ensure that exterior movement and vehicle controls continue to work normally.

Use existing entrance or exit representations if they are already available.

If there is no existing exit interaction, implement the smallest practical interaction using the project's current interaction conventions. For example, a contextual prompt near an entrance could allow the player to leave.

Do not invent a new building-entry architecture if one already exists.

## 6. Spawn Position and Collision Validation

Do not assume that the geometric centre of the building is a valid spawn position.

Use the existing floorplan, room connectivity, and doorway data to find a safe starting position.

Validate that the spawn position:

- Is inside the generated interior.
- Is above a valid floor.
- Does not overlap wall geometry.
- Does not block a doorway.
- Has sufficient room for the player capsule.
- Is connected to the interior's walkable areas.

If the preferred spawn position is invalid, select a reasonable alternative or report the failure clearly rather than spawning the player inside geometry.

Ensure that generated collision geometry and visual geometry remain consistent.

## 7. Interior Camera and Exterior Rendering

The first-person camera must show the inside of the selected building rather than being obstructed by the exterior building model.

Inspect how the existing exterior buildings are rendered and determine the least disruptive way to handle the active building.

Possible approaches include hiding the active building's roof or exterior shell while the player is inside, but use the approach that best fits the existing renderer.

Requirements:

- Do not hide all buildings globally.
- Do not break the surrounding exterior scene.
- Restore the building's exterior visibility correctly when the player exits.
- Avoid leaving buildings permanently hidden after an interrupted transition.
- Keep the solution compatible with the existing building rendering approach.

Do not implement a complete room-by-room visibility system in this phase.

## 8. 2D Mode and Compatibility

The existing 2D interior must remain functional.

If the project already has an interior mode selection or configuration mechanism, integrate the new first-person mode into it.

Otherwise, introduce the smallest practical way to select between:

- Existing 2D top-down interior.
- New 3D first-person interior.

Do not make first-person mode mandatory if the generated 3D interior has not been enabled or cannot be instantiated.

Do not alter the existing exterior camera or permanently change its settings.

## 9. Performance and Resource Management

- Instantiate the first-person controller only when needed.
- Do not create player controllers for buildings that are not active.
- Avoid unnecessary per-frame node searches and allocations.
- Reuse the active interior's existing geometry.
- Clean up the controller and temporary resources when leaving.
- Avoid accumulating duplicate cameras, controllers, or input handlers after repeated building entries.
- Ensure repeated enter/exit cycles do not leak nodes or leave the game in an inconsistent input state.

Do not introduce speculative performance optimisations without evidence.

## 10. Testing and Validation

Add tests where practical and use the existing project testing conventions.

Validate at least the following:

1. The controller can be instantiated in a generated 3D interior.
2. The player can move in all four directions.
3. Diagonal movement is normalised.
4. Mouse-look works horizontally and vertically.
5. Vertical camera rotation is clamped.
6. Gravity and floor collision work correctly.
7. Walls block movement.
8. Doorways remain traversable.
9. The player can enter and leave an interior repeatedly.
10. Mouse capture and visibility are restored correctly.
11. The exterior camera and controls work after leaving.
12. The existing 2D interior mode still works.
13. Repeated transitions do not create duplicate controllers or cameras.

Run the available Godot headless validation and relevant automated tests. Where headless tests cannot validate interactive behaviour, provide a reproducible manual test procedure.

## 11. Acceptance Criteria

This phase is complete when:

- The player can explore a generated 3D interior in first person.
- WASD movement and mouse-look work correctly.
- The player collides with walls and remains on the floor.
- The player can move between connected rooms through doorways.
- The player enters at a valid location and can exit reliably.
- The active interior does not become obscured by the exterior building model.
- Existing exterior gameplay and 2D interiors remain functional.
- Resource cleanup and repeated enter/exit transitions are reliable.
- The implementation is ready for a subsequent phase focused on interior appearance, doors, windows, furniture, and lighting.

## 12. Implementation Workflow

1. Inspect the existing 3D interior implementation and report any missing prerequisites.
2. Identify the existing building-entry, interior lifecycle, camera, and input systems.
3. Explain the intended controller and transition architecture briefly.
4. Implement the first-person controller and integrate it with the existing interior lifecycle.
5. Add or extend tests.
6. Run available automated tests and Godot validation.
7. Test transitions, collision behaviour, and compatibility with existing modes.
8. Fix issues discovered during validation.
9. Review the changes for duplicated state, resource leaks, and regressions.
10. Create atomic Git commits for logically independent, completed changes.

Do not implement decorative interior assets or expand into unrelated gameplay features. If a prerequisite from the previous phase is missing or incorrect, address the minimum necessary issue and document it.