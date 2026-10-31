# GitHub Copilot Agent Prompt: Implement Cyclists as NPC Traffic

Implement cyclists as a first-class type of NPC traffic in Road Rage Taxi. Cyclists must participate in the existing traffic simulation alongside cars, buses, and other road vehicles, while following their own cycling behavior and Finnish traffic rules.

## 1. Inspect the existing implementation first

Before making changes, inspect the current repository and identify:

- The existing NPC traffic manager, vehicle models, driver and occupant lifecycles, route planning, road/lane graph, traffic lights, intersections, collision handling, and spatial indexes.
- How OSM road and path data is imported and how road types, directions, lanes, and cycling infrastructure are represented.
- How NPC vehicles are spawned, activated, updated, and despawned.
- How the Python simulation communicates vehicle state to the Godot renderer.
- The existing tests and conventions for adding new NPC vehicle types.
- The repository document `finnish-npc-traffic-law.md`. Locate and read the actual file before implementing cycling behavior.

Produce a concise implementation plan based on the actual code. Then implement the feature incrementally, testing each major step. Do not stop at a plan unless a genuine blocker prevents implementation.

## 2. Finnish traffic rules are authoritative

Use `finnish-npc-traffic-law.md` as the primary specification for cyclists' legal behavior.

Read the entire relevant section, including any definitions, exceptions, intersection rules, traffic-light requirements, right-of-way rules, and interactions with other road users.

Requirements:

- Translate the documented rules into explicit, testable simulation behavior.
- Reuse existing traffic-rule implementations where appropriate, but do not assume that rules for motor vehicles apply identically to cyclists.
- Identify any missing, ambiguous, or contradictory rules before making assumptions. Consult existing project documentation and code; clearly report unresolved questions.
- Do not invent legal requirements or silently introduce rules that contradict the document.
- Keep traffic-law decisions in the Python simulation rather than the Godot presentation layer.

The traffic-law document is the source of truth for legal behavior. Implementation details must follow the existing project architecture.

## 3. Integrate cyclists into the existing NPC vehicle architecture

Cyclists must be genuine moving NPC traffic, not pedestrians with a bicycle sprite and not a separate simulation system.

- Reuse the existing traffic manager, road graph, routing infrastructure, spatial indexes, update lifecycle, and relevant vehicle abstractions.
- Introduce a cyclist-specific vehicle or agent type only where the existing architecture requires it.
- Give cyclists their own movement parameters and behavior without duplicating the entire vehicle simulation.
- Integrate cyclists with the existing NPC activation, route assignment, spawning, despawning, and simulation-area management.
- Preserve the distinction between a vehicle, its driver, and its occupants wherever the existing architecture requires it. Do not create anonymous traffic entities that bypass established lifecycle rules.
- Ensure cyclists coexist with motor vehicles, buses, pedestrians, traffic lights, intersections, and other cyclists.
- Preserve existing taxi collision behavior and unrelated traffic behavior.

Avoid creating a parallel cyclist manager, duplicate road graph, or independent routing system when the existing infrastructure can be extended.

## 4. Cycling routes and road infrastructure

Inspect the actual road-network data model and use the available OSM information to determine suitable cycling routes.

Where supported by the imported data, account for:

- Dedicated cycleways and cycle tracks.
- Roads with designated bicycle lanes.
- Roads where cyclists share the carriageway with motor vehicles.
- Shared pedestrian and cycling paths.
- Relevant one-way restrictions and direction-specific cycling permissions.
- Intersection connections and transitions between different types of cycling infrastructure.
- Restrictions on which road and path types cyclists may use.

Routing must respect the actual network connectivity and cycling permissions. Do not route cyclists through disconnected ways, prohibited roads, buildings, or arbitrary off-road shortcuts.

Prefer appropriate cycling infrastructure when the available graph and documented routing rules support it. Do not assume that every road has a bicycle lane or that every path is legally accessible to cyclists.

If the current map pipeline discards information needed for cycling, identify the minimum necessary data-model or import changes and implement them consistently with the existing architecture.

## 5. Cyclist movement and traffic behavior

Implement realistic, deterministic-enough movement that fits the existing simulation model and its performance requirements.

Cyclists should have behavior appropriate to bicycles rather than inheriting motor-vehicle assumptions unchanged.

Consider the following, adapting each to the existing architecture and the traffic-law document:

- Cycling speed and acceleration appropriate to the road environment.
- Speed adjustments for junctions, turns, obstacles, and other traffic.
- Following routes through road segments and intersections without spinning, oscillating, or repeatedly changing direction.
- Respecting applicable traffic signals, signs, and right-of-way rules.
- Detecting and responding to nearby vehicles, cyclists, and pedestrians.
- Avoiding collisions while accounting for the narrower physical footprint of a bicycle.
- Handling blocked routes and temporary obstacles without becoming permanently stuck.
- Recovering safely from navigation failures using the existing traffic recovery mechanisms.
- Transitioning correctly between cycleways, shared paths, and roads.

Do not give cyclists unrealistic capabilities such as instantly stopping, turning at impossible angles, or passing through other traffic. Do not apply car-specific lane-following behavior blindly where it would be unsuitable for bicycles.

Avoid unnecessary per-cyclist global scans or all-to-all collision checks. Reuse existing spatial queries and traffic-update scheduling.

## 6. Interaction with other road users

Cyclists must be integrated into the existing traffic simulation rather than merely moving independently along their routes.

Implement and test interactions with:

- Motor vehicles following or overtaking cyclists.
- Vehicles turning across cyclists' paths.
- Cyclists approaching intersections and crossing points.
- Other cyclists travelling in the same or opposite directions where permitted.
- Pedestrians using shared spaces or crossing cyclists' routes.
- Traffic lights and other applicable traffic-control devices.

Use the documented Finnish traffic rules to determine legal priority and permitted maneuvers. Keep collision avoidance and legal right-of-way as distinct concerns: an agent may need to avoid a collision even when it has priority.

Do not rewrite existing vehicle behavior unnecessarily. Extend shared interactions in a backward-compatible manner.

## 7. Godot rendering and simulation boundaries

The Python simulation remains authoritative for traffic decisions, movement, routes, and collision outcomes. Godot is responsible for presenting the resulting state.

- Add cyclist rendering using the existing Godot NPC vehicle-rendering architecture.
- Reuse suitable existing assets and rendering abstractions where possible.
- If a suitable bicycle model or sprite already exists, reuse it; otherwise, implement a simple representation consistent with the current visual style.
- Ensure orientation, position, animation if supported, and interpolation follow the existing conventions.
- Integrate cyclists into existing map streaming and visibility handling.
- Do not add client-side physics or collision shapes to determine traffic behavior.
- Do not modify the established simulation protocol unnecessarily. Extend it compatibly only if cyclist-specific state is genuinely required.
- Preserve existing rendering performance and avoid unnecessary visual or simulation work for distant or inactive agents.

Do not develop the legacy Pygame renderer. All presentation changes belong in Godot.

## 8. Population and spawning

Integrate cyclists into the existing NPC traffic population and spawning mechanisms.

- Spawn cyclists only where the available road network and cycling permissions make their presence plausible.
- Account for available cycling infrastructure and the suitability of the surrounding environment using data the game actually possesses.
- Avoid spawning cyclists in remote locations or on roads where cycling is prohibited.
- Preserve existing road-aware, viewport-safe spawning and route-before-activation behavior.
- Ensure that cyclists are not repeatedly spawned and despawned at the same location because of lifecycle or routing errors.
- Avoid arbitrary global cyclist-count caps. Use the existing population-management architecture and profile the actual workload before introducing new limits.
- If traffic-density controls already exist, integrate cyclist population into them instead of introducing unrelated configuration mechanisms.

Do not invent demographic or regional data that the game does not currently have.

## 9. Testing requirements

Add automated tests using the project's existing test framework and conventions.

At minimum, test:

1. Cyclists can be created, assigned valid routes, updated, and despawned through the existing NPC lifecycle.
2. Routing respects cycling permissions and available road connectivity.
3. Cyclists can follow suitable cycling infrastructure and transition between connected infrastructure types.
4. Cyclist behavior at traffic lights, intersections, and priority situations follows `finnish-npc-traffic-law.md`.
5. Cyclists interact correctly with cars, buses, pedestrians, and other cyclists.
6. Blocked routes and navigation failures do not cause endless spinning or uncontrolled movement.
7. Cyclists do not bypass the simulation's authoritative movement and collision handling.
8. Existing motor-vehicle, bus, pedestrian, and taxi tests continue to pass.
9. Cyclist updates use the existing spatial and traffic infrastructure rather than introducing unbounded global scans.

Where useful, add deterministic scenario tests for specific rules documented in `finnish-npc-traffic-law.md`. Reference the corresponding rule in test names or comments so future changes can be traced back to the specification.

Run the relevant focused tests after each major implementation step, followed by the appropriate broader regression suite. Report any tests that cannot be run and explain why.

## 10. Performance and compatibility

Performance is important, particularly on older computers. The Godot renderer is already performing well, so focus optimization and profiling on the Python simulation.

- Measure or benchmark the relevant simulation workload before and after implementation where practical.
- Avoid unnecessary allocations, repeated route calculations, expensive graph searches on every tick, and redundant proximity checks.
- Reuse existing scheduling, caching, and spatial-query mechanisms where appropriate.
- Do not introduce multiprocessing, a new server architecture, or an unrelated language migration as part of this feature.
- Preserve the current single-player simulation flow and existing protocol compatibility.
- Do not regress the performance or behavior of existing NPC traffic.

## 11. Implementation workflow and deliverables

Work in the current project branch and preserve unrelated uncommitted changes.

1. Inspect the architecture, traffic-law document, and tests.
2. Summarize the existing implementation and provide a concise, file-specific plan.
3. Implement the cyclist model and lifecycle integration.
4. Implement cycling-aware routing and legal movement behavior.
5. Integrate cyclist spawning, interactions, and Godot rendering.
6. Add automated tests and run regression checks.
7. Profile the relevant simulation workload and address any avoidable performance regressions.
8. Review the final changes for duplicated systems, architectural violations, and unintended behavior changes.

Use atomic Git commits for logically complete changes as implementation progresses. Do not create Git tags unless explicitly requested.

At completion, provide:

- A summary of the implementation.
- The files changed and the responsibility of each significant change.
- The traffic-law rules implemented and any unresolved ambiguities.
- The automated tests executed and their results.
- Performance measurements, if available, including the test conditions.
- Any remaining limitations or follow-up work.

**Acceptance criterion:** Cyclists behave as fully integrated NPC traffic in Road Rage Taxi, follow the cycling rules specified by `finnish-npc-traffic-law.md`, use the existing simulation and routing architecture, render correctly in Godot, coexist with other road users, and do not introduce significant performance regressions or break existing traffic behavior.