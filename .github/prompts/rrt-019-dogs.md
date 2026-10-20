Implement dog walking as a pedestrian activity in Road Rage Taxi.

Repository:
https://github.com/emehtata/roadragetaxi

Target:
The current release/v0.19.0alpha development line, or the active
working branch containing the latest project code.

IMPORTANT:
Inspect the actual repository before making changes.
Verify the existing pedestrian simulation, world streaming,
Godot rendering, simulation clock, and entity lifecycle systems.

Do not assume that specific files, classes, APIs, or data structures
exist without inspecting the code.

## 1. Objective

Add dog walking as a new ambient pedestrian activity.

A dog walker consists of:
- One existing pedestrian entity.
- One associated dog entity or visual representation.
- A visual leash connecting the pedestrian and the dog.

Integrate this activity into the existing pedestrian system.

Do not create a separate pedestrian simulation or an independent
world population system.

This feature is ambient world activity only.

Dogs must not affect traffic rules, vehicle physics, collision
handling, player finances, or gameplay outcomes.

## 2. Activity distribution

Dog walking may occur in:

- Urban centres.
- Residential neighbourhoods.
- Suburban areas.
- Parks and green spaces.
- Suitable rural paths and roads.

Never spawn dog walkers on motorways or other unsuitable
pedestrian areas.

Use existing map, pedestrian navigation, road classification,
and land-use information wherever available.

Prefer parks, pedestrian paths, sidewalks, and residential areas.

If the current project does not expose suitable land-use data,
use existing pedestrian navigation and world metadata as a fallback.
Document any limitations rather than inventing a new map-analysis
pipeline.

## 3. Time-of-day activity

Use the game's existing simulation clock.

Do not create a separate clock.

Dog walking should be more common during:
- Morning.
- Late afternoon.
- Evening.

It may occur throughout the day.

Nighttime activity should be reduced but must not necessarily
drop to zero.

Use smooth or probabilistic activity variation where compatible
with the existing pedestrian population system.

Do not make activity dependent on the real-world system clock.

## 4. Pedestrian behavior

Reuse existing pedestrian movement and navigation.

Dog walking must be an activity type or equivalent extension
of the existing pedestrian activity system.

The pedestrian:
- Follows existing pedestrian routes.
- Uses appropriate sidewalks, paths, and park routes.
- Walks at a normal pedestrian speed.
- May briefly pause while the dog investigates its surroundings.
- Resumes walking after the pause.

Do not replace or regress existing pedestrian behavior.

Avoid creating a second independent pathfinding system.

## 5. Dog behavior

Each dog must remain associated with its owner.

The dog:
- Follows the pedestrian.
- Remains within a plausible leash distance.
- Has small natural variations in movement speed and position.
- May briefly stop to sniff the ground.
- May move a short distance sideways.
- Returns towards its owner before continuing normally.
- Does not walk through the owner's body.
- Does not visibly stretch the leash to an implausible length.

Use a lightweight behavior model.

Do not implement full independent dog pathfinding unless the
existing architecture makes it necessary.

The dog must not obstruct or affect vehicles or other simulated
entities.

## 6. Leash rendering

Render a leash between the pedestrian and the dog.

Inspect the existing Godot rendering architecture and determine
the most suitable implementation.

The leash should:
- Connect the appropriate attachment points.
- Follow both entities smoothly.
- Avoid obvious clipping where practical.
- Be rendered only when the associated pair is visible and
  rendering the leash is worthwhile.

Do not create excessive scene nodes or rendering objects.

If a full 3D leash is incompatible with the existing renderer,
use a lightweight approach consistent with the project's
coordinate system and camera.

## 7. Dog appearance

Support at least three visual size categories:
- Small.
- Medium.
- Large.

Reuse existing assets if available.

Do not assume that dog models or animations already exist.

If suitable assets are missing, inspect the existing asset pipeline
and implement a replaceable solution compatible with it.

Do not introduce a large external asset dependency.

Dog models must use the same world coordinate system and rendering
conventions as existing pedestrians and vehicles.

Ensure correct orientation, plausible scale, and smooth movement.

Avoid floating, sliding, abrupt teleportation, and visible
position discontinuities.

## 8. Integration with wildlife

If the wildlife feature is already implemented, integrate dog
walking with it without coupling unrelated systems unnecessarily.

For this initial version:
- Dogs are owned ambient entities, not wild animals.
- Dogs must not be independently spawned by the wildlife system.
- Dog walkers should not duplicate the same dog across systems.
- Existing wildlife behavior must remain unchanged.

Do not implement animal attacks, animal collisions, or any other
gameplay consequences.

## 9. Entity lifecycle and streaming

Inspect the existing entity lifecycle and map chunk streaming.

Requirements:
- A pedestrian and its dog share a consistent lifecycle.
- Removing or despawning the pedestrian also removes or despawns
  its associated dog and leash.
- Streaming boundaries must not create duplicate dogs.
- Re-entering an area must not leave stale dog entities behind.
- Entity counts must remain bounded.
- The implementation must not create new objects every frame.
- Reuse existing entity management or pooling mechanisms when
  appropriate.

Ensure that dog walkers do not accumulate indefinitely when
the player moves around the map.

## 10. Performance

Preserve the current game's frame rate and simulation performance.

Avoid:
- Independent full pathfinding for dogs.
- Per-frame allocations.
- Unnecessary scene-node creation and destruction.
- Expensive global searches for pedestrian owners.
- Unbounded entity accumulation.
- Unnecessary network traffic.

Use existing nearby-entity queries and spatial indexing when
available.

Measure the impact with existing profiling or benchmark tools
where practical.

Do not claim that performance is unchanged without measurements.

## 11. Configuration

Follow the project's existing configuration conventions.

Where appropriate, make the following configurable:
- Dog-walking activity weight.
- Maximum number of active dog walkers.
- Dog-walking activity variation by simulated time.
- Visual dog variants.

Use conservative defaults.

Do not invent environment variables or configuration APIs.

Avoid unnecessary configuration complexity.

## 12. Testing

Add tests following the repository's existing conventions.

Cover:
1. Dog walking is a valid pedestrian activity.
2. The activity uses the existing simulation clock.
3. Dog walkers use valid pedestrian navigation.
4. Every dog has exactly one valid owner.
5. Dogs follow owners within the configured leash distance.
6. Dog movement remains stable across different frame rates.
7. Removing a pedestrian also removes its associated dog.
8. Chunk transitions do not create duplicate dogs.
9. Population limits are respected.
10. Dogs do not affect vehicle state, traffic rules, or finances.
11. Existing pedestrian behavior remains intact.
12. Existing regression tests continue to pass.

Use deterministic random seeds where appropriate.

If some visual behaviors cannot be tested automatically,
document the manual verification steps.

## 13. Implementation workflow

First inspect:
- Pedestrian activity selection.
- Pedestrian movement and navigation.
- Godot entity rendering.
- World and chunk streaming.
- Simulation clock.
- Entity lifecycle management.
- Existing asset conventions.
- Existing tests and performance benchmarks.

Then provide a short implementation plan based on the actual code.

Implement the feature using the smallest appropriate changes.

Do not refactor unrelated systems.

Do not modify the legacy Pygame renderer.

Do not change the network protocol unless inspection proves
that a protocol change is necessary.

Do not introduce a new programming language or external runtime.

Finally:
- Run relevant automated tests.
- Run regression tests where practical.
- Check entity cleanup and duplicate spawning.
- Verify leash rendering and dog movement in Godot.
- Measure performance where practical.
- Summarize changed files, implementation decisions, tests,
  benchmark results, and known limitations.

Do not create or push Git tags.
Do not publish a release.
