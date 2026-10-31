# Feature: Enter and Explore the Player's Home

## Objective

Implement the ability for the player to enter their selected home building from outside, explore its procedurally generated interior, and move between rooms.

The player must be standing outside their own home, within the home's yard or entrance area, and must not be inside a vehicle. Pressing a dedicated interaction key should transition the player into the interior.

At this stage, the interior is purely for exploration. The player can walk around, pass through doorways, and inspect the layout. Do not implement furniture interactions, sleeping, inventory, object pickup, property management, or any other gameplay activities.

Before making changes, inspect the existing home selection, procedural interior generation, player movement, vehicle enter/exit logic, input handling, and Godot scene architecture. Extend the existing implementation instead of introducing a parallel system.

## 1. Inspect Existing Architecture

Determine how the following are currently implemented:

- The player's selected home and how its building identity is persisted.
- The previously implemented procedural interior and its generated room layout.
- How building footprints and entrance positions are represented.
- How the player moves and how the game determines the player's world position.
- How the player enters and exits vehicles.
- How input actions are registered and handled.
- How the Python simulation/server communicates player state to the Godot client.
- How game-world and interior views are managed.

Identify which components should remain authoritative on the server and which are presentation or movement responsibilities on the client.

Do not assume specific class names, file paths, or APIs before inspecting the repository.

## 2. Entering the Home

Add an interaction that lets the player enter their own home.

Requirements:

- The player must have selected a home.
- The player must be outside a vehicle.
- The player must be in the exterior world, near their own home and its entrance or designated yard area.
- The interaction must not activate when the player is near somebody else's building.
- Pressing a dedicated, configurable interaction key enters the interior.
- Use the existing input-action conventions. If no suitable action exists, add a clearly named action and choose a sensible default key, such as `E`, after checking for conflicts.
- Display a small contextual prompt when entering is possible, for example: `Press E to enter home`.
- Hide the prompt when the player leaves the valid interaction area, enters a vehicle, or otherwise becomes ineligible.
- Prevent repeated key presses from creating multiple interior instances or triggering overlapping transitions.

The home entrance must be associated with the actual selected building, not merely the nearest building.

If the existing building data does not provide a reliable entrance, implement a deterministic fallback based on the building footprint. Avoid selecting an entrance point that is inaccessible or on the wrong side of the building where practical.

## 3. Interior Exploration

Reuse the existing procedural interior generator and its generated floor plan.

Implement a playable top-down interior in which the player can:

- Move around freely within accessible floor areas.
- Walk through doorways between connected rooms.
- Explore every room reachable through the generated layout.
- See walls, floors, doors, and existing furniture or interior details.
- Clearly distinguish walkable areas from walls and other impassable areas.

Use the existing Godot rendering and movement conventions where possible.

### Movement and collision

- Prevent the player from walking through walls.
- Ensure doorways are wide enough for the player's movement and collision footprint.
- Avoid trapping the player in a room due to incorrectly placed doors or disconnected corridors.
- Ensure generated room geometry and movement boundaries agree.
- Do not introduce unnecessary physics complexity or expensive per-frame procedural calculations.
- Generate and cache static interior geometry where appropriate.

If the current interior generator does not guarantee connectivity or valid door placement, address those issues as part of making the interior explorable.

## 4. Entering and Leaving the Interior

Implement a clean transition between the exterior world and the interior.

When entering:

- Preserve the player's selected home identity.
- Record enough exterior state to return the player to a sensible position.
- Place the player at the interior entrance, not at an arbitrary point in the floor plan.
- Ensure exterior movement and vehicle interactions cannot accidentally operate on the interior coordinates.
- Prevent the player from appearing inside a wall or outside the walkable area.

When leaving:

- Provide a dedicated exit interaction at the interior entrance.
- Use the same configurable interaction system where appropriate, with a contextual prompt such as `Press E to leave home`.
- Return the player to the exterior near the actual home entrance.
- Restore the correct exterior world state and position.
- Ensure the player returns on foot, outside the vehicle.
- Ensure the player can immediately move around the yard and enter a vehicle normally.

The player must not be able to leave the interior by simply walking through exterior walls or walking beyond the floor plan.

Do not add interior entrances or exits to unrelated buildings as a side effect.

## 5. World and Simulation Separation

Preserve the existing architecture:

- Python remains authoritative for the existing simulation and game rules.
- Godot handles the interior presentation and client-side interaction to the extent consistent with the existing architecture.
- Do not move existing simulation logic into Godot.
- Do not introduce a second, independent player-state system.
- Do not let interior coordinates interfere with exterior road navigation, NPC traffic, vehicle positions, or world-space distance calculations.
- If the server must know whether the player is indoors, use the existing protocol and state-management conventions rather than creating a disconnected client-only truth.
- Do not unnecessarily simulate the entire exterior world differently while the player is indoors.

Determine whether interior movement can be handled entirely by the existing client-side architecture or requires a server-side state transition. Follow the actual repository design and document the decision.

## 6. Performance and Persistence

- Generate the interior only when needed.
- Reuse cached interior data when the player exits and re-enters the same home.
- Avoid regenerating procedural geometry every frame.
- Preserve deterministic interior generation for the same home and generator version.
- Do not reload the entire game world merely to enter or exit the home.
- Ensure the exterior world resumes correctly after leaving.
- Do not introduce arbitrary NPC or rendering limits as a workaround.

Persist the selected home using the existing persistence mechanism. Do not introduce persistent furniture state or other household simulation data at this stage.

## 7. Testing

Add appropriate automated tests and/or existing-project test coverage for:

1. A player without a selected home cannot enter a home.
2. A player in a vehicle cannot enter their home.
3. A player outside the valid entrance area cannot enter.
4. A player near another building cannot enter it as their own home.
5. A player at their own entrance can enter by pressing the interaction key.
6. The player spawns in a valid walkable interior position.
7. The player cannot walk through walls.
8. The player can traverse all connected rooms in a generated interior.
9. Doorways remain traversable with the player's collision footprint.
10. The exit interaction returns the player to the correct exterior entrance.
11. Repeated enter/exit cycles do not duplicate nodes, leak resources, or corrupt player state.
12. Exterior movement, vehicle entry, and the existing simulation continue to work after exiting.
13. Interior generation remains deterministic for the same home.
14. The feature does not cause significant, avoidable performance regressions.

Use the project's existing test conventions. Add targeted regression tests for any bugs discovered in the current interior generator or transition logic.

## 8. Explicitly Out of Scope

Do not implement:

- Sleeping or time advancement.
- Furniture or object interactions.
- Picking up, storing, or moving objects.
- Inventory or equipment.
- Cooking, eating, washing, or other household activities.
- NPCs living in the house.
- Purchasing, renting, selling, or upgrading properties.
- Multiple floors or stair traversal unless the existing implementation already supports them and they are necessary for basic exploration.
- A full first-person or third-person camera redesign.
- A new general-purpose interaction framework if the existing one can be extended.

The only new gameplay capability is entering the player's home, exploring its interior, and leaving it.

## 9. Implementation Workflow

1. Audit the relevant existing code and document the intended integration points.
2. Implement the smallest coherent end-to-end version.
3. Reuse existing procedural layouts and player movement where practical.
4. Add or update tests.
5. Run the relevant test suites and available static checks.
6. Verify that exterior gameplay remains unaffected.
7. Review the final diff for unnecessary architectural changes, duplicated state, and performance regressions.
8. Commit completed changes in atomic commits using the repository's existing Git workflow.

Do not create or push Git tags.

## Acceptance Criteria

The feature is complete when the player can park or stop near their selected home, exit their vehicle, walk to the home's entrance, press the interaction key, explore the generated interior by walking between rooms, and return outside through the entrance without breaking the existing game simulation.

Provide a final summary describing the implementation, important architectural decisions, tests executed, and any remaining limitations.