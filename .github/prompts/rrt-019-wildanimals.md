Implement Wildlife v1 in Road Rage Taxi.

Repository:
https://github.com/emehtata/roadragetaxi

Target:
The current release/v0.19.0alpha development line, or the active
working branch containing the latest project code.

IMPORTANT:
Inspect the actual repository and its current architecture before
making implementation decisions. Do not assume that files, classes,
APIs, protocols, or data structures exist without verifying them.

## 1. Feature scope

Implement wildlife as visual world ambience.

The initial release must NOT introduce gameplay consequences
for animals.

Animals must NOT:
- Cause vehicle collisions.
- Cause vehicle damage.
- Change the player's finances.
- Affect traffic simulation or traffic rules.
- Block roads or pedestrian paths.
- Trigger gameplay events or penalties.
- Require authoritative collision detection.

Animals are ambient visual entities. They may move independently
and react visually to nearby vehicles, but those reactions must
never affect vehicle simulation.

Preserve the existing server-authoritative simulation architecture
and Godot rendering architecture.

Do not modify the legacy Pygame renderer.

## 2. Required species

Implement the following species:

- Squirrel
- Generic small birds
- Pigeons
- Hare
- Fox
- Moose
- Roe deer

Use clear species identifiers and a data-driven design where
appropriate.

Avoid duplicating behavior code for species that share the same
movement patterns.

## 3. Habitat distribution

Use the existing map and world data wherever possible.

Urban centres:
- Squirrels
- Small birds
- Pigeons

Suburban areas:
- Squirrels
- Small birds
- Pigeons at lower densities
- Hares
- Foxes

Rural roads and remote areas:
- Small birds
- Hares
- Foxes
- Moose
- Roe deer

Squirrels may also appear in suitable rural habitats.

Habitat suitability should influence spawn probability.

Prefer existing information about vegetation, forests, parks,
buildings, roads, and land use when that information is already
available.

Do not introduce a new expensive map-analysis pipeline solely
for wildlife.

If explicit habitat classification is unavailable, implement a
simple fallback using existing world metadata. Document its
limitations.

Do not infer that an area is a forest merely because it is far
from the city centre.

Moose and roe deer must not normally spawn in dense urban centres.

## 4. Time-of-day behavior

Integrate with the game's existing simulation clock.

Do not introduce a second independent clock.

Suggested activity profiles:

- Daytime: birds, pigeons, and squirrels are active.
- Dawn and dusk: increase activity for appropriate species.
- Night: increase fox activity relative to daytime.
- Moose and roe deer can appear at any time, with increased
  encounter probability around dawn and dusk.

Use smooth probability changes where practical.

Do not introduce arbitrary real-world clock dependencies.
The feature must follow the game's simulated time.

If seasonal information already exists, use it only where useful.
Do not introduce an entire seasonal simulation system for this
feature.

## 5. Animal behavior

Implement simple, inexpensive behavior state machines.

Possible states include:
- IDLE
- WANDER
- FEED
- FLEE
- FLY
- CROSSING

Use only states appropriate to each species.

Squirrels:
- Move short distances.
- Pause frequently.
- Occasionally make quick directional changes.

Small birds and pigeons:
- Walk and peck at the ground.
- Pause periodically.
- Fly short distances and land again.
- Small bird groups may be represented as a flock rather than
  independently simulated full entities.

Hares:
- Wander in suitable green areas.
- Pause and occasionally hop short distances.

Foxes:
- Move independently.
- Prefer suitable quiet areas and forest edges when map data
  supports this.
- Have increased activity during dusk and nighttime.

Moose and roe deer:
- Walk slowly.
- Pause periodically.
- Occasionally cross a suitable road or move between nearby
  suitable locations.
- May visibly react to a nearby vehicle.

All movement must remain visual and non-interactive.

Do not add rigid-body physics or collision shapes for animals.

## 6. Visual reaction to vehicles

Inspect the current Godot vehicle representation and determine
whether nearby vehicle positions can be obtained efficiently.

If feasible, animals may react visually to approaching vehicles:

- Birds may take flight.
- Small animals may briefly flee.
- Larger animals may pause or change direction.

These reactions are optional when implementing them would require
expensive polling or invasive changes.

Do not modify vehicle movement, braking, collision handling,
traffic rules, or server simulation as part of this feature.

Animals must never obstruct a vehicle.

## 7. Rendering and assets

Inspect the existing Godot rendering architecture and asset pipeline.

Reuse existing rendering and resource-management patterns.

If appropriate assets already exist, reuse them.

Do not assume that wildlife models, sprites, or animations exist.

If new assets are required, implement a documented, replaceable
asset interface and provide the simplest visually coherent
implementation supported by the existing project.

Do not introduce a large external asset dependency.

Animal rendering must be consistent with the game's current
top-down camera and world coordinate system.

Animals must have appropriate orientation and scale.

Avoid floating, sliding, sudden teleportation, and visible
position discontinuities.

If full 3D models are impractical for this release, use an approach
consistent with the existing renderer rather than introducing
an unrelated rendering framework.

## 8. World lifecycle and streaming

Inspect how the game currently streams map chunks and manages
world entities.

Wildlife must integrate with those existing mechanisms.

Requirements:
- Avoid recreating all animals every frame.
- Avoid unbounded accumulation of animal nodes.
- Avoid spawning large numbers of animals in one update.
- Remove, suspend, or reuse entities when their areas become
  irrelevant to the player.
- Avoid duplicate animals at chunk boundaries.
- Prevent visible teleportation during ordinary chunk streaming.
- Use deterministic per-region random seeds if compatible with
  the existing architecture.
- Keep random state independent of frame rate.

Animals should only be actively updated when they are close enough
to matter visually.

Use lower update frequencies for distant or inactive animals
where practical.

Do not introduce a global NPC population cap. Any population limits
must apply specifically to wildlife and be configurable.

## 9. Performance

Performance preservation is a hard requirement.

The game must remain responsive on older hardware.

Avoid:
- Per-animal physics simulation.
- Per-frame pathfinding.
- Excessive scene-node creation and destruction.
- Repeated allocations in hot update loops.
- Unnecessary searches through all world entities.
- Expensive scans of the complete map.
- Independent full simulation of every bird in a flock.

Use spatial partitioning, nearby-entity queries, object pooling,
or existing equivalent mechanisms only when appropriate to the
current architecture.

Do not implement speculative optimizations without evidence.

Measure performance before and after implementation using the
project's existing benchmark or profiling facilities where
available.

Record the test environment and limitations of the measurements.

Do not claim that performance is unchanged without measurements.

## 10. Testing

Add automated tests following the project's existing test
conventions.

Cover at least:

1. Species identifiers and configuration are valid.
2. Habitat distribution produces appropriate species.
3. Moose and roe deer are not normally spawned in dense urban
   habitats.
4. Species activity changes according to simulated time.
5. Animal movement is independent of frame rate.
6. Animal state transitions are valid.
7. Wildlife population limits are enforced.
8. Chunk transitions do not create duplicate entities.
9. Wildlife entities are cleaned up or reused correctly.
10. Wildlife does not modify vehicle state, finances, traffic
    rules, or collision behavior.
11. Repeated world updates do not cause unbounded entity growth.
12. Existing tests continue to pass.

Use deterministic random seeds in tests.

Do not rely solely on visual inspection.

If automated Godot rendering tests are unavailable, document
which visual behaviors require manual verification.

## 11. Configuration

Use the project's existing configuration conventions.

Provide configurable values for:
- Wildlife density.
- Maximum active wildlife population.
- Relevant visibility or activity distance.
- Species-specific spawn weights.
- Whether vehicle-triggered visual reactions are enabled.

Choose conservative defaults.

Do not invent environment variables or configuration APIs.

If a configuration option would add unnecessary complexity,
explain why before introducing it.

## 12. Implementation workflow

First inspect:
- The current Godot renderer.
- World and map chunk streaming.
- Existing entity lifecycle management.
- Simulation time handling.
- Vehicle representation and spatial queries.
- Available land-use and habitat information.
- Existing asset loading conventions.
- Existing automated tests and benchmarks.

Then produce a concise implementation plan based on actual code.

Implement the feature in small, coherent changes.

Preserve existing functionality and avoid unrelated refactoring.

Do not introduce a new programming language or external runtime
for wildlife.

Do not change the network protocol unless the existing architecture
demonstrably requires it.

Prefer client-side ambient wildlife when this fits the existing
architecture. If the project requires server-originated entity
state, explain why and use the smallest appropriate extension.

Finally:
- Run relevant automated tests.
- Run the existing regression test suite where practical.
- Check for resource leaks and unbounded node growth.
- Compare performance against the baseline.
- Document required assets and any manual setup.
- Summarize modified files, architectural decisions, tests,
  performance measurements, and remaining limitations.

Do not create or push Git tags.
Do not publish a release.
