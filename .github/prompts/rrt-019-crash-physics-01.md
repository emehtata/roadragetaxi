# Task: Audit and Improve Vehicle Collision Physics

## Context

Road Rage Taxi uses a Python server-side simulation for gameplay rules, NPC behavior, vehicle movement, and collision handling. Godot is responsible for client-side rendering. The server remains authoritative over vehicle positions, velocities, collisions, and gameplay outcomes.

A serious collision physics problem has been observed: when the player hits another vehicle at high speed, the other vehicle often remains stationary. This also happens to bicycles.

The objective is to make collisions produce believable, speed-dependent physical reactions without compromising simulation performance or changing the existing client-server architecture.

## Phase 1: Audit the Existing Implementation

Before modifying code, trace the complete collision handling pipeline.

Identify:

1. Where collisions between the player and NPC vehicles are detected.
2. Where collision responses are calculated and applied.
3. How vehicle speed, velocity, heading, mass, and movement are represented.
4. Whether collision handling modifies the actual authoritative simulation state.
5. Whether NPC pathfinding, steering, acceleration, braking, or movement updates overwrite collision-induced velocity changes.
6. Whether collision resolution resets vehicle positions or velocities in a way that cancels the collision response.
7. How bicycles, motorcycles, scooters, cars, buses, and other vehicle types are represented in the simulation.
8. Whether collision handling differs between the player, NPCs, and stationary vehicles.
9. Whether collision responses are applied consistently across simulation ticks.
10. Which existing tests cover collision detection, vehicle movement, damage, and post-collision recovery.

Inspect the actual implementation and relevant tests. Do not assume that the problem is caused by any particular function or subsystem.

Report the root cause or causes, citing the relevant files and functions.

## Phase 2: Design the Collision Response

Based on the audit, design the smallest robust change that addresses the identified problems.

Requirements:

- Collision responses must affect the authoritative simulation state.
- Moving vehicles must transfer momentum to other vehicles during collisions.
- Collision response must depend on relative velocity, collision direction, and vehicle mass or an equivalent vehicle-specific physical parameter.
- Vehicle mass must be configurable by vehicle class or derived from existing vehicle data.
- Lightweight vehicles, particularly bicycles and scooters, must react noticeably to collisions.
- Heavy vehicles must be harder to displace than lightweight vehicles.
- Stationary vehicles must respond correctly when hit by moving vehicles.
- Collisions must not always stop the player vehicle or the other vehicle instantaneously.
- Head-on, rear-end, and side collisions must produce distinguishable outcomes.
- Collision resolution must prevent vehicles from remaining embedded in each other.
- Collision response must not cause unbounded velocities, numerical instability, or repeated artificial acceleration.
- Existing vehicle damage and difficulty-mode behavior must remain compatible with the improved collision model.
- Preserve the existing server-authoritative architecture.

Use a simplified impulse-based collision response if appropriate for the existing simulation. Do not introduce a full rigid-body physics engine without demonstrating that the existing architecture cannot support the required behavior.

## Phase 3: Integrate Collision Response With NPC Movement

Ensure that collision effects survive subsequent simulation updates.

Specifically:

- NPC steering and pathfinding must not immediately erase collision-induced velocity changes.
- NPC acceleration and braking must respect the vehicle's current post-collision state.
- Collision recovery must allow displaced vehicles to resume normal movement when safe.
- Vehicles must not become permanently stuck because of collision resolution.
- Repeated collision processing must not apply the same impulse multiple times for a single collision event.
- Collision response must remain stable when several vehicles are involved in a short sequence of collisions.
- Do not make all NPCs ignore traffic rules or obstacles merely to make them recover from collisions.

Follow the existing movement and collision architecture. Avoid introducing a second competing movement system.

## Phase 4: Automated Tests

Add or extend tests to cover at least these scenarios:

1. A moving car collides with a stationary car.
2. A moving car rear-ends another moving car.
3. Two cars collide head-on.
4. A car collides with the side of another car.
5. A car hits a stationary bicycle.
6. A car hits a moving bicycle.
7. A car hits a scooter or motorcycle, if supported by the current simulation.
8. A moving car hits a stationary heavy vehicle.
9. A collision does not leave vehicles permanently stuck.
10. NPC movement does not immediately overwrite the collision response.
11. Repeated collision processing does not produce duplicate impulses.
12. Collision resolution does not produce NaN values, infinite values, or unbounded velocities.

Use deterministic initial conditions and fixed simulation steps wherever possible.

Tests must verify actual changes to vehicle state, not merely that a collision event was detected.

Avoid asserting arbitrary exact physical outcomes unless the model explicitly guarantees them. Prefer testing meaningful invariants, directional behavior, relative magnitudes, and stable recovery.

## Phase 5: Performance and Regression Testing

- Measure the cost of the changed collision handling using the project's existing performance-testing conventions.
- Avoid unnecessary allocations and expensive calculations in per-vehicle or per-collision loops.
- Do not introduce global pairwise collision checks if the existing simulation uses a more efficient broad-phase mechanism.
- Preserve current traffic simulation behavior when no collision occurs.
- Preserve existing traffic rules, vehicle AI, player controls, damage handling, and difficulty settings.
- Run relevant existing tests and the new collision tests.
- Investigate and fix regressions caused by the changes.

## Implementation Constraints

- Keep Python as the authoritative simulation language.
- Do not move collision detection or physics to Godot.
- Do not change the networking protocol unless the audit demonstrates that a change is necessary.
- Do not alter unrelated gameplay systems.
- Do not remove existing vehicle types or simplify NPC behavior to work around collision bugs.
- Do not introduce arbitrary vehicle-count limits.
- Follow the repository's existing coding conventions and test structure.

## Deliverables

1. A concise explanation of the original root cause.
2. The implemented collision physics improvements.
3. Automated tests covering the required scenarios.
4. Test results and any relevant performance measurements.
5. A summary of modified files and any remaining limitations.

Implement the fix after completing the audit. Keep changes focused and compatible with the existing simulation architecture.