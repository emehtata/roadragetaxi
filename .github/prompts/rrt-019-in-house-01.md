# Feature: Procedurally Generated Home Interior Floor Plans

## Objective

Implement a first version of procedurally generated, top-down 2D interior floor plans for the player's selected home in Road Rage Taxi.

The player must be able to select a building in the existing game world as their home and inspect its procedurally generated interior from a top-down perspective.

This is a visual and exploratory feature. Do not implement walkable 3D interiors, interior physics, or a general-purpose interior simulation system in this iteration.

The implementation must integrate with the existing project architecture rather than introduce a parallel building or map system.

## 1. Audit the Existing Architecture First

Before making changes, inspect the repository and identify:

- How OSM building footprints are imported, stored, and represented in the game.
- How building geometry is rendered by the Godot client.
- How the player interacts with buildings and other world objects.
- How the game represents the player's home, if such functionality already exists.
- How the existing UI, menus, and interaction prompts are implemented.
- How the Python server and Godot client communicate.
- How world coordinates are converted into Godot coordinates.
- Existing save/load mechanisms and persistent player properties.

Reuse existing systems wherever possible.

Do not assume that particular classes, methods, files, or data structures exist. Verify their actual names and responsibilities before modifying them.

Produce a short implementation plan based on the actual codebase, then implement the feature.

## 2. Home Selection

Allow the player to designate an existing building as their home using the game's established interaction or property-selection UI.

Requirements:

- Reuse the building's existing identity and footprint.
- Use existing OSM metadata where available.
- Ensure the selected home can be identified consistently across game sessions.
- Persist the selected home using the existing save/load mechanism.
- If no suitable persistence mechanism exists, implement the smallest compatible extension.
- Validate that the selected building still exists and has usable geometry.
- Provide appropriate feedback if a building cannot be selected.

Do not generate duplicate buildings or create a separate home representation disconnected from the existing world.

If the game already has a home-selection mechanic, extend it rather than creating a competing one.

## 3. Procedural Floor Plan Generation

Generate a deterministic, top-down 2D floor plan based on the selected building's actual footprint.

The first implementation should focus on ordinary detached houses and similarly sized residential buildings.

The generated floor plan should contain, where the footprint permits:

- Exterior walls following the building footprint.
- Interior partition walls.
- An entrance and interior doors.
- A hallway or entrance area.
- A living room.
- A kitchen or combined kitchen/living area.
- One or more bedrooms.
- A bathroom.
- Furniture appropriate to each room.

The generator must adapt to the building's geometry instead of assuming that every building is rectangular.

Handle polygon winding, coordinate orientation, and concave footprints correctly. Use existing geometry utilities if available.

### Generation rules

- All rooms and furniture must remain inside the building footprint, apart from explicitly modelled exterior entrances.
- Walls must connect sensibly without unintended gaps.
- Doors must be placed in walls and provide plausible connections between rooms.
- Rooms must not overlap.
- Furniture must fit within its assigned room and must not obstruct doors.
- Narrow or irregular footprints must produce a simpler layout instead of an invalid one.
- Very small buildings should receive fewer rooms and less furniture.
- If a footprint cannot support a reasonable layout, show a useful fallback rather than crashing.

Use a deterministic random seed derived from the stable building identifier and, if necessary, a generator version.

Generating the same building with the same generator version must produce the same layout.

Avoid purely random placement of unrelated rectangles. The generator must produce a coherent floor plan with connected rooms and plausible circulation.

Keep the geometry-generation code separate from the Godot rendering code so the algorithm can be tested independently.

## 4. Top-Down Interior Viewer

Implement a dedicated interior-viewing screen or mode within the existing Godot client.

Requirements:

- Display the complete generated floor plan from directly above.
- Render exterior walls, partition walls, doors, rooms, and furniture clearly.
- Use a consistent scale and aspect ratio.
- Fit the complete building into the available viewing area.
- Preserve the proportions of the original building footprint.
- Provide readable visual differentiation between rooms and furniture.
- Include a building or home identifier where appropriate.
- Provide a clear way to close the viewer and return to the normal game view.

The floor plan must remain readable for both compact and irregularly shaped buildings.

Use the existing UI framework and visual conventions. Do not introduce a new UI framework.

The interior viewer must not require the player to enter the building physically. It is a separate top-down inspection view in this iteration.

## 5. Furniture and Interior Details

Create a small reusable set of simple 2D furniture representations, such as:

- Beds.
- Sofas.
- Tables and chairs.
- Kitchen counters.
- Bathroom fixtures.
- Wardrobes.
- Shelves.

Use existing project assets if suitable.

If suitable assets do not exist, create lightweight procedural 2D shapes or reusable scenes. Do not introduce a large external asset dependency merely to furnish the first prototype.

Furniture placement must respect room boundaries and orientation.

Keep furniture density reasonable. The floor plan should remain understandable rather than being filled with decorative objects.

## 6. Opening the Home Interior

Integrate the viewer with the existing game UI.

The player should be able to open their selected home's floor plan through an obvious and discoverable action, such as an existing home menu or building interaction.

Do not invent an unrelated control scheme if the project already has a suitable interaction pattern.

If the home is not selected, explain how the player can select one.

If the building data is unavailable or invalid, show an appropriate error message and allow the player to return safely to the game.

The viewer must not leave the game in a broken input, camera, or UI state after closing.

## 7. Architecture and Performance

Preserve the existing separation of responsibilities:

- Python remains responsible for authoritative game rules and simulation.
- Godot remains responsible for rendering and the client-side presentation.
- Interior generation must not introduce unnecessary server-side simulation work.
- Do not create interiors for every building at startup.
- Generate the selected home's floor plan only when needed.
- Cache the generated layout where practical.
- Invalidate or regenerate cached layouts when the source footprint or generator version changes.
- Avoid loading additional map data solely to generate the interior.
- Do not add per-frame geometry-generation work.
- Keep the normal exterior rendering path unchanged unless a modification is strictly necessary.

Do not move collision detection, simulation, or other gameplay responsibilities between the server and client as part of this feature.

Do not introduce arbitrary limits on the number of buildings visible in the existing world.

## 8. Testing

Add automated tests for the geometry generator and its integration where practical.

At minimum, test:

1. A rectangular building footprint.
2. An irregular convex footprint.
3. A concave footprint.
4. A very small footprint.
5. Invalid or degenerate geometry.
6. Deterministic generation using the same building identifier.
7. Different layouts for different building identifiers where the generator supports variation.
8. Room containment within the building footprint.
9. Room connectivity and door placement.
10. Furniture containment and door clearance.
11. Persistence and restoration of the selected home.
12. Opening and closing the viewer without breaking the normal game state.

Use the project's existing test framework and conventions.

Do not claim that graphical integration tests have passed unless they have actually been executed.

## 9. Implementation Workflow

- Inspect the existing architecture before editing.
- Identify the smallest coherent implementation.
- Implement the feature in logical, atomic commits.
- Run relevant automated tests and existing validation tools.
- Check for regressions in the normal game startup and exterior rendering.
- Report any manual testing that remains necessary.

Keep the implementation focused on the selected home's 2D floor plan.

Do not implement the following in this iteration:

- Walkable 3D interiors.
- Interior collision physics.
- NPC navigation inside buildings.
- Multiple floors or stair navigation.
- General access to every building in the world.
- Interior gameplay activities.
- Complex building-type classification.
- Exterior building rendering changes unrelated to opening the viewer.

## Acceptance Criteria

The feature is complete when:

1. The player can designate an existing world building as their home.
2. The selected home persists across sessions.
3. The player can open its interior floor plan from the game UI.
4. The floor plan follows the actual building footprint.
5. The generated rooms, doors, and furniture form a coherent layout.
6. The same building produces a stable layout across repeated openings.
7. Invalid building geometry does not crash the game.
8. Closing the viewer restores the normal game state.
9. Existing exterior rendering and simulation remain functional.
10. Relevant automated tests pass.

At completion, summarize the implemented functionality, architectural decisions, modified files, test results, and any known limitations.