# Godot-07: Complete Rendering-Only Parity

## Objective

Implement the next Godot migration phase based on the completed godot-06 parity audit.

The goal of this phase is to close as many **rendering-only parity gaps** as possible without changing the server protocol or simulation architecture.

The authoritative audit documents are:

* `docs/architecture/godot-pygame-rendering-parity.md`
* `docs/architecture/godot-rendering-migration.md`

Read both documents completely before making any changes.

The existing Pygame implementation is the behavioral/rendering reference where parity is required.

## Important constraints

1. **Do not redesign the game architecture.**
2. **Do not migrate route planning yet.**
3. **Do not add new server protocol fields unless absolutely required to fix an item explicitly classified as rendering-only in the audit.**
4. **Do not modify the simulation merely to make a visual effect easier to implement.**
5. Prefer using data that Godot already receives.
6. Do not reintroduce the old Pygame rendering model into Godot.
7. Godot remains the target architecture.
8. Keep the existing top-down Godot presentation. Do not implement the old Pygame isometric building perspective.
9. Preserve existing gameplay behavior and network behavior.
10. Do not create Git tags.
11. Pushing commits to the remote is allowed.
12. Do not silently remove existing functionality just because it is not yet implemented in Godot.

## Phase scope

Prioritize the rendering-only gaps identified by the godot-06 audit.

Implement these where the required information is already available:

### Destination and navigation presentation

* pickup/drop-off marker
* off-screen arrow pointing toward the destination
* navigation route visualization, but only if the route information is already available to Godot
* compass

If the navigation route is genuinely impossible without moving route planning into the simulation, leave it for the later route-planning phase. Do not invent a client-side replacement during this phase.

### Rail meet-and-greet presentation

Implement the Godot equivalents of:

* meet-and-greet panel
* booked rail passenger indicator/arrow
* associated passenger state already present in the protocol

The UI should follow the existing game's semantics rather than introducing a new workflow.

### Vehicle rendering

Implement parity for:

* vehicle appearance by vehicle type
* turn signals
* crash/damaged state
* taxi headlights/lamps
* other vehicle lighting that is already represented by existing state

Do not introduce a completely new vehicle rendering system if the existing Godot implementation can be extended.

### Player/HUD presentation

Implement the rendering-only HUD elements identified by the audit, including:

* fuel gauge
* relevant existing HUD fields
* nausea bubble

Do not add gameplay mechanics to the fuel gauge or other HUD elements. This phase is visual parity only.

### Pedestrian presentation

Implement rendering-only pedestrian details for which the required state already exists:

* heading/orientation
* walking animation/cycle
* cursing bubbles

Keep the implementation efficient. Do not create an expensive per-frame animation system for off-screen entities.

### Train presentation

Implement:

* train car colours/appearance parity

Preserve the existing train composition and simulation logic.

### Environment rendering

Implement rendering-only parity for:

* wet roads
* puddles
* smoke
* bridges rendered above the roads they cross

Use the existing Godot rendering architecture and avoid expensive full-map redraws.

## Performance requirements

Performance is important.

Before implementing expensive visual effects:

* identify the existing visibility/culling system
* reuse existing chunk/camera visibility mechanisms
* avoid processing off-screen entities unnecessarily
* avoid allocating objects every frame
* avoid per-frame creation of temporary arrays/dictionaries where practical
* avoid introducing new polling loops when existing update mechanisms can be reused

Do not optimize prematurely by removing visual parity.

After implementation, measure the affected areas where practical.

## Pygame reference

For every feature implemented, inspect the corresponding Pygame implementation and determine:

1. What is actually rendered?
2. Under what conditions is it rendered?
3. Which existing Godot state corresponds to those conditions?
4. Whether the coordinate system requires conversion.
5. Whether the feature is affected by camera zoom, viewport size, or entity culling.

Do not blindly copy Pygame code. Reproduce the behavior in idiomatic Godot.

## Audit-driven workflow

Start by reading the two audit documents and constructing a concrete implementation checklist from the rendering-only rows.

For every selected item:

1. Locate the Pygame implementation.
2. Locate the corresponding Godot rendering/state code.
3. Verify that the necessary data already exists.
4. Implement the smallest appropriate Godot change.
5. Add or update tests where meaningful.
6. Run the relevant Godot tests.
7. Run the Godot self-test.
8. Run `make audio-check`.
9. Run the Python test suite if the change touches shared behavior.
10. Update the parity documentation with the new status.

Do not mark an audit row as complete merely because something visually similar exists. Verify the actual behavior against the Pygame reference.

## Important distinction: protocol vs rendering

The audit identified many missing protocol items. Do not implement those in this phase.

In particular, leave these for the later protocol phase unless the audit explicitly confirms that the required data is already available:

* darkness/date
* traffic-light phases
* roadworks state
* road names
* speed limits
* lightning/rain intensity
* knocked-over objects
* broken lamps
* additional static chunk data

Also leave the following architectural work for later:

* moving route planning into the simulation
* major server-side simulation changes
* new map-data generation pipelines

## Tests

The known baseline after godot-06 is:

* `make audio-check`: 0 problems
* `make godot-test`: 74/74
* `make godot-selftest`: OK, 0 underruns
* Python suite: 1535 passed, with only the 3 known BIN map-format failures

The three known BIN map-format failures are expected and should not be treated as regressions.

Preserve the existing timing-test fixes from godot-05. Do not undo the garbage-collection handling added for the timing tests.

If new tests are added, keep them deterministic and avoid introducing timing-sensitive tests unless there is no reasonable alternative.

## Documentation

After implementation, update:

`docs/architecture/godot-pygame-rendering-parity.md`

and, where appropriate:

`docs/architecture/godot-rendering-migration.md`

Clearly distinguish:

* newly completed rendering parity
* remaining rendering gaps
* protocol-dependent gaps
* route-planning/simulation gaps

Do not claim complete parity if any relevant behavior remains missing.

## Git

At the beginning:

* inspect `git status`
* inspect the current branch
* inspect recent commits
* do not reset, rebase, or discard unrelated existing work

During the work:

* make focused commits
* do not create tags
* pushing commits is allowed

At the end, report:

1. files changed
2. features implemented
3. parity rows completed
4. tests run and results
5. remaining parity gaps
6. commits created
7. whether anything was pushed

Do not stop after producing an analysis. Implement the phase completely, subject to the scope above.
