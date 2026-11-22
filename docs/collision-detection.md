# Global Collision Detection and Resolution System

## Objective

Implement a unified, world-wide collision detection and resolution architecture for Road Rage Taxi.

The fundamental requirement is that collidable objects must not be able to pass through one another.

Collision detection must work consistently across the entire streamed game world, regardless of whether objects are currently visible on screen.

This must be a centralized system rather than a collection of unrelated collision implementations.

## 1. Architecture audit

Before implementation, audit the existing collision architecture.

Identify all existing collision and overlap implementations, including:

- Player taxi and NPC vehicles.
- Pedestrians.
- Animals.
- Buildings.
- Trees and vegetation.
- Roadside objects.
- Traffic lights and poles.
- Roadworks and construction equipment.
- Parking structures and other obstacles.
- Other moving and stationary world objects.

Document:
- Which objects currently have collision detection.
- Which objects can pass through other objects.
- Which collision calculations are duplicated.
- Which spatial indexes and geometric representations already exist.
- Which collision calculations are performed by the Python simulation.
- Which collision-related information is transmitted to Godot.

Do not replace working systems without understanding their dependencies.

## 2. Central collision architecture

Create a shared collision management architecture on the Python server.

All authoritative collision detection and resolution must happen on the server.

Godot must remain a rendering and presentation client. Do not introduce client-side physics, collision shapes or independent collision resolution.

The collision system must support:

- Dynamic vs. dynamic collisions.
- Dynamic vs. static collisions.
- Static obstacle detection.
- Moving object collision detection.
- Object overlap prevention.
- Collision response appropriate to each object category.

Use the existing simulation architecture wherever possible.

Do not introduce a second, parallel vehicle or NPC collision system.

## 3. Collision geometry

Use efficient geometric representations appropriate to each object.

Examples:

- Vehicles: oriented bounding boxes or suitable vehicle footprint geometry.
- Pedestrians: circles or capsules.
- Animals: circles or suitable simplified body geometry.
- Buildings: existing building footprints.
- Trees and poles: circles or simplified cylinders.
- Other static objects: appropriate simplified collision geometry.

Collision geometry must correspond reasonably well to the visible object.

A vehicle must not collide based on an excessively large invisible bounding box.

Rotated objects must be handled correctly.

Visual geometry and collision geometry must be independently configurable.

## 4. Broad-phase collision detection

Performance is critical.

Do not perform global all-to-all collision checks.

Reuse existing spatial indexes, grids and nearby-object queries.

Requirements:

- Identify nearby collision candidates efficiently.
- Support streamed map chunks.
- Update dynamic object positions efficiently.
- Avoid scanning the entire world every simulation tick.
- Avoid rebuilding spatial indexes unnecessarily.
- Support objects crossing chunk boundaries.
- Ensure that chunk loading or unloading does not temporarily disable collision detection.
- Handle high-speed objects without tunneling through obstacles, using swept collision tests or appropriate substeps where necessary.

The broad phase must work independently of camera visibility and rendering distance.

## 5. Collision layers and interaction rules

Introduce a clearly documented collision category and filtering system.

Define which object categories can collide with one another.

Examples:

| Object | Collision behavior |
|---|---|
| Player taxi | Buildings, vehicles, pedestrians, animals, obstacles |
| NPC vehicles | Buildings, vehicles, pedestrians, animals, obstacles |
| Pedestrians | Vehicles, buildings, applicable obstacles |
| Animals | Vehicles, buildings, applicable obstacles |
| Buildings | Solid static obstacles |
| Trees and poles | Solid static obstacles |
| Traffic lights | Solid static obstacles |
| Roadworks | Solid obstacles where appropriate |
| Visual effects | No physical collision |

Not every object needs to collide with every other object.

Triggers, pickup markers, navigation markers and other non-solid interactions must remain separate from physical collision.

## 6. Collision resolution

Detecting collisions is not sufficient. The system must also resolve them.

Implement suitable behavior for different collision categories:

- Vehicles must not pass through buildings, trees or other solid obstacles.
- Vehicles must interact physically with other vehicles.
- Pedestrians must not pass through solid buildings or obstacles.
- Vehicles must not pass through pedestrians or animals.
- Static objects must remain stationary.
- Collision responses must not produce uncontrolled acceleration or oscillation.
- Objects must not become permanently stuck inside one another.
- Moving objects must recover gracefully from overlapping or invalid positions.

Preserve existing gameplay behavior where appropriate, particularly existing taxi collision and traffic simulation rules.

Do not simply freeze an object whenever a collision is detected.

## 7. High-speed collision handling

Fast-moving vehicles must not tunnel through small objects between simulation ticks.

Investigate:
- Swept bounding volumes.
- Continuous collision detection where justified.
- Adaptive collision substeps.
- Time-of-impact calculations.

Choose an implementation that fits the existing 30 Hz simulation architecture without unnecessarily increasing server load.

## 8. Map levels and streaming

Respect the existing map-level architecture.

- Collision queries must filter objects by map level.
- Objects on different floors must not collide merely because their 2D coordinates overlap.
- Level-less scenery must remain surface-level only.
- Use existing level-aware spatial indexes.
- Objects crossing chunk boundaries must remain collision-aware.
- Hidden or unloaded visual chunks must not cause authoritative collision gaps.

Do not create a separate spatial indexing architecture if existing indexes can be extended.

## 9. Performance requirements

The simulation currently operates on a 30 Hz tick budget.

Collision detection must not become a new performance bottleneck.

Measure:
- Broad-phase execution time.
- Narrow-phase execution time.
- Number of candidate pairs.
- Number of actual collisions.
- Collision resolution time.
- Spatial index update time.

Test in dense urban environments with many vehicles, pedestrians and static objects.

Avoid:
- O(n²) global collision checks.
- Per-frame full-world scans.
- Unnecessary geometry reconstruction.
- Excessive allocation of temporary objects.
- Duplicate collision calculations in different simulation subsystems.

## 10. Testing

Create deterministic test scenarios with explicitly positioned objects.

Test at minimum:

1. Two vehicles approaching each other.
2. Two vehicles colliding at an intersection.
3. A vehicle hitting a building.
4. A vehicle hitting a tree or pole.
5. A vehicle approaching a pedestrian.
6. A vehicle approaching an animal.
7. Two pedestrians crossing paths.
8. A pedestrian walking against a building.
9. Objects approaching each other from different map chunks.
10. High-speed vehicles approaching small obstacles.
11. Objects on different parking garage levels.
12. Objects entering and leaving streamed chunks.
13. Multiple simultaneous collisions.
14. Objects initially overlapping.
15. Dense traffic with many simultaneous collision candidates.

Verify both collision detection and collision resolution.

## 11. Acceptance criteria

- Collidable objects cannot pass through one another under normal simulation conditions.
- Collision behavior is consistent across the streamed world.
- Collision detection does not depend on camera visibility.
- Collision handling is authoritative on the Python server.
- Godot only presents the resulting simulation state.
- Existing gameplay systems continue to work.
- No unnecessary duplicate collision systems are introduced.
- The 30 Hz simulation budget remains achievable under representative load.

Scenario coverage (section 10; tests in tests/test_collision_scenarios.py unless named):

1. test_vehicles_head_on_resolve, test_vehicles_other_level_pass
2. test_scenario2_junction_crash_slide_stops_at_static, test_counters_increment_on_placed_scenarios
3. test_taxi_hits_building_stops
4. test_taxi_hits_pole_stops_or_knocks, test_taxi_fells_tree_keeps_speed, test_tree_fast_no_tunnel
5. test_scenario5_taxi_approaches_pedestrian, test_scenario5_other_level_no_dodge
6. not covered: animals are Godot decoration (wildlife.gd), out of scope in the spec
7. test_scenario7_pedestrians_cross_without_overlap
8. test_scenario8_pedestrian_dodge_stops_at_wall
9. test_static_index_cross_chunk_approach
10. test_scenario10_taxi_stall_step_hits_bollard, test_scenario10_taxi_sideways_hits_bollard, test_scenario10_far_npc_stops_at_bollard
11. test_scenario11_garage_levels_no_cross_level_hits (tests/test_collision_counters.py), tests/test_level_collision.py
12. test_static_index_unload_and_reload, test_unloaded_chunk_trees_stand_and_stay_up
13. test_scenario13_simultaneous_post_vehicle_building
14. test_initial_overlap_building_drive_out, test_initial_overlap_pole_drive_out, test_npc_drives_out_of_initial_overlap
15. test_scenario15_dense_traffic_no_static_overlap, test_counters_deterministic_same_seed (tools/bench_dense_city.py)

## 12. Implementation workflow

Work in the following order:

1. Complete the architecture audit.
2. Produce a collision category matrix.
3. Identify reusable existing geometry and spatial indexes.
4. Propose the centralized architecture.
5. Identify migration risks and performance implications.
6. Implement incrementally.
7. Add deterministic collision tests.
8. Run performance benchmarks.
9. Verify existing gameplay behavior.
10. Document the architecture and commit changes atomically.

Do not sacrifice simulation correctness for visual shortcuts.

Do not create or push Git tags.