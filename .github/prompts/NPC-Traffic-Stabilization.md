# NPC Traffic Stabilization – Road Rage Taxi 0.15.0alpha

## Working branch

Work exclusively on:

`release/0.15.0alpha`

Repository:

`emehtata/roadragetaxi`

Do not create a new branch unless explicitly requested.

---

# Objective

The current NPC traffic system is already fairly large and contains many working features, but there are three major problems that now need to be fixed at the architectural level:

1. **Large cities have surprisingly little moving NPC traffic**, while small towns can have a lot of traffic.
2. **NPC vehicles drive badly**: steering, turns, lane positioning and route following are unreliable.
3. **NPC vehicles cannot be reliably collided with**, especially when vehicles are moving.

Do not rewrite the NPC system.

First inspect the current implementation and understand how the existing systems interact. Then make targeted architectural improvements while preserving working functionality such as:

- Residents
- households
- vehicle ownership
- destinations
- trip generation
- parking
- traffic lights
- stop signs
- yield signs
- speed limits
- vehicle-ahead braking
- road rage
- crash handling
- driver departure
- NPC lifecycle
- OSM routing

The goal is to fix the underlying causes rather than adding special-case hacks.

---

# Phase 1 – Inspect the existing implementation

Before changing code, inspect at least:

- `npc.py`
- `physics.py`
- `traffic_world.py`
- `traffic_rules.py`
- `residents.py`
- `geo.py`
- NPC population/spawning code
- main game update loop
- spatial grid implementation
- route generation
- route validation
- collision handling
- existing NPC tests

Trace the complete lifecycle:

```text
population controller
        ↓
NPC/vehicle selection
        ↓
driver assignment
        ↓
trip generation
        ↓
route generation
        ↓
route validation
        ↓
lane/way selection
        ↓
steering
        ↓
physics
        ↓
collision
        ↓
crash state
        ↓
driver departure
        ↓
despawn/replacement
```

Do not start rewriting systems before identifying the exact functions responsible for each stage.

---

# Problem 1 – NPC traffic density is wrong

## Existing population-control behavior

The current implementation contains settings along these lines:

```python
NPC_TARGET_MOVING_FRACTION = 0.5
NPC_TRIP_START_TICK_BUDGET_S = 0.15
NPC_TRIP_START_ATTEMPTS_PER_TICK_WHEN_BELOW_MOVING_TARGET = 3
NPC_TRANSIT_SPAWNS_PER_TICK = 2
NPC_TRANSIT_SPAWN_TIME_BUDGET_S = 0.1
```

There is also a target moving population and a population-management loop which attempts to start trips when the moving population is below the target.

This is important.

Do not simply remove these time budgets.

The problem is that route generation and route validation can become substantially more expensive in large/complex OSM road networks.

As a result, the current behavior can effectively become:

```text
small/simple road network
        ↓
route generation succeeds quickly
        ↓
NPC starts trip
        ↓
moving population increases

large/complex road network
        ↓
route generation/validation is expensive
        ↓
few attempts fit inside the tick budget
        ↓
many candidates fail or time out
        ↓
moving population stays low
```

This explains why city size can indirectly produce the wrong traffic density.

## Required behavior

Traffic density should primarily depend on:

- configured NPC population
- configured moving fraction
- available valid vehicles
- available road network

It should NOT depend strongly on the computational complexity of the local OSM graph.

A large city should not systematically have less moving traffic simply because route generation is harder.

Do not fix this with:

```python
if large_city:
    spawn_more_npcs()
```

or:

```python
if population < target:
    spawn_extra_npcs()
```

Those would hide the underlying problem.

---

# Population controller redesign

Maintain two separate concepts:

```text
total NPC population
moving NPC population
```

A parked household vehicle must not count as moving traffic.

When:

```text
moving_population < target_moving_population
```

the controller should incrementally attempt to start trips.

Conceptually:

```text
population tick
    ↓
select candidate vehicle
    ↓
attempt trip generation
    ↓
route succeeds
    → start moving
    ↓
route fails
    → temporarily reject candidate
    ↓
next tick
    → continue with other candidates
```

Do not repeatedly hammer the same failed candidate.

Failed candidates should have a short retry/backoff mechanism so that one impossible route does not consume the entire population budget every tick.

The controller should eventually converge toward the target when enough valid vehicles and roads exist.

---

# Diagnostics

Add lightweight diagnostics for:

```text
target moving NPC count
current moving NPC count
trip-start attempts
successful trip starts
route-generation failures
route-validation failures
vehicles waiting for trips
population update duration
```

These diagnostics must not themselves create significant frame-time overhead.

If there are already debug statistics, integrate with them rather than creating a completely separate diagnostics system.

---

# Problem 2 – NPC driving behavior

The current NPC steering implementation is based heavily on directly chasing the current waypoint.

The current logic is approximately:

```python
desired_heading = math.atan2(
    target.y - vehicle.car.y,
    target.x - vehicle.car.x,
)

heading_error = (
    desired_heading
    - vehicle.car.heading
    + math.pi
) % (2.0 * math.pi) - math.pi

steer_magnitude = clamp(
    abs(heading_error) / math.radians(STEER_FULL_ANGLE_DEG),
    0.0,
    1.0,
)
```

This is a major area to investigate.

Directly pointing the vehicle at a single route point is inherently problematic when:

- route points are sparse;
- route points are very close together;
- the vehicle approaches a sharp corner;
- roads curve;
- intersections contain multiple connected ways;
- the vehicle is moving quickly.

It can produce:

```text
zig-zagging
late steering
corner cutting
overshooting
oscillation
unstable heading changes
```

Do not simply tune `STEER_FULL_ANGLE_DEG` until the symptoms look better.

The controller should be changed from:

```text
"point directly at the next waypoint"
```

toward:

```text
"follow the route as a continuous path"
```

---

# Existing waypoint advancement

The current implementation contains logic equivalent to:

```python
while (
    driver.path_index < len(path) - 1
    and math.hypot(
        path[driver.path_index].x - vehicle.car.x,
        path[driver.path_index].y - vehicle.car.y,
    ) < WAYPOINT_REACH_RADIUS_M
):
    driver.path_index += 1
```

The current waypoint reach radius is approximately:

```python
WAYPOINT_REACH_RADIUS_M = 4.0
```

This must be investigated carefully.

A 4 m radius may be acceptable for bookkeeping, but it should not automatically mean:

```text
vehicle is within 4 m
        ↓
switch steering target
```

That can cause premature target switching, especially at intersections and curves.

If possible, separate:

```text
route progress
```

from:

```text
steering target
```

The vehicle should continuously follow the route rather than repeatedly aiming at individual points.

---

# Required path-following improvement

Implement a lookahead-based path follower.

A pure-pursuit-like approach is acceptable.

The basic concept should be:

```text
vehicle position
       ↓
find position on route
       ↓
look ahead along route
       ↓
select lookahead point
       ↓
calculate steering
       ↓
smooth steering
```

The lookahead distance must depend on vehicle speed.

Conceptually:

```python
lookahead_distance = clamp(
    BASE_LOOKAHEAD_M + speed_mps * LOOKAHEAD_TIME_S,
    MIN_LOOKAHEAD_M,
    MAX_LOOKAHEAD_M,
)
```

Do not copy these exact values blindly. Determine sensible values from the existing game's world scale and vehicle physics.

The important property is:

```text
low speed  → shorter lookahead
high speed → longer lookahead
```

This should make fast vehicles anticipate curves rather than reacting only when they reach the next waypoint.

---

# Steering requirements

The new controller must:

- smoothly follow straight roads;
- smoothly follow curves;
- anticipate turns;
- avoid oscillation;
- avoid sudden steering changes;
- avoid corner cutting;
- remain compatible with the existing vehicle physics;
- work with different vehicle speeds.

Do not replace the physics model.

The path follower should produce steering input.

The physics system should remain responsible for actual movement.

---

# Existing corner-speed system

The current NPC implementation already contains corner-speed handling, including logic such as:

```python
_distance_to_next_turn(...)
_corner_safe_speed_mps()
```

and braking before sharp corners.

Preserve this system if it is fundamentally correct.

The desired relationship should be:

```text
route geometry
      ↓
corner analysis
      ↓
safe target speed

route geometry
      ↓
lookahead path follower
      ↓
steering

traffic rules
      ↓
allowed target speed

target speed + steering
      ↓
physics
```

Do not remove corner-speed handling just because the steering controller changes.

Instead, make sure the two systems complement each other.

NPCs should:

- brake before sharp turns;
- turn smoothly;
- avoid entering corners too fast;
- accelerate after the corner;
- avoid cutting across buildings/curbs.

---

# Existing traffic-rule system

The NPC code already uses traffic-rule logic such as:

```python
decide_traffic_action(...)
```

and target-speed calculations based on:

- speed limits
- traffic lights
- stop signs
- yield signs
- vehicles ahead
- destination/parking behavior

Preserve this.

Do not bypass `traffic_rules.py`.

Traffic rules should determine whether and how fast the NPC may move.

Path following should determine where it steers.

Physics should determine how the vehicle actually moves.

The architectural separation should remain:

```text
Route/path
    → where the vehicle should go

Traffic rules
    → how fast it is allowed to go

Path follower
    → how it steers

Physics
    → how it actually moves

Collision system
    → what happens when vehicles interact
```

---

# Existing vehicle-ahead logic

The current NPC system already has vehicle-ahead detection using logic similar to:

```python
nearest_vehicle_ahead(...)
```

The implementation uses a forward cone / heading relationship and braking based on:

- lead vehicle
- distance/gap
- lead vehicle speed

Do not remove this system.

However, verify that the new path-following controller does not break it.

The expected behavior should be:

```text
path follower says:
    "steer toward this point"

traffic system says:
    "maximum safe speed is X"

vehicle-ahead system says:
    "slow down because another vehicle is ahead"

physics says:
    "apply the resulting steering/throttle/brake"
```

---

# Lane positioning

The current implementation contains coarse lane-offset logic for different maneuvers.

The existing behavior is approximately:

```python
# right turn
lane_offset = max_offset

# left turn
lane_offset = min(1.0, max_offset)

# straight
lane_offset = min(
    max(1.2, half_width * 0.45),
    max_offset,
)
```

This is useful as a starting point but is too coarse for complex roads.

Investigate how this offset is calculated and applied.

Improve it without trying to implement the entire OSM `turn:lanes` specification.

At minimum:

- vehicles should stay on their intended side of the road;
- straight driving should be stable;
- left turns should not randomly cross unrelated lanes;
- right turns should not cut across the intersection;
- multi-lane roads should not cause random lateral movement;
- lane position should remain stable between route points.

Do not introduce random lateral offsets as a visual fix.

---

# Route geometry

Inspect how the route is represented.

If the current route consists of discrete OSM points, consider creating a lightweight continuous representation for steering.

Possible approach:

```text
OSM route nodes
      ↓
route polyline
      ↓
vehicle projection onto polyline
      ↓
distance-along-route
      ↓
lookahead point
```

The route representation should be cached/reused.

Do not rebuild the OSM graph every frame.

Do not perform expensive full-route processing every frame if the route is long.

---

# Problem 3 – NPC collisions

There is already collision geometry in `geo.py`.

The existing helper is approximately:

```python
def boxes_intersect(
    cx1, cy1, h1, l1, w1,
    cx2, cy2, h2, l2, w2
) -> bool:
    ...
```

It performs:

1. broad-phase distance/circle testing;
2. oriented bounding box testing;
3. SAT projection against the relevant axes.

Do not throw this away.

The collision geometry itself is not necessarily the primary problem.

The larger problem is likely **when and how collision detection is performed**.

---

# Current collision problem

If collision is checked only against the instantaneous vehicle positions during the NPC update, fast vehicles can tunnel through each other.

Conceptually:

```text
Frame N

NPC A        NPC B
  🚗  --->      🚙

No overlap
```

Then:

```text
Frame N+1

NPC A            NPC B
              🚙
```

The vehicles may have crossed each other between the two samples.

Neither pose necessarily overlaps.

Therefore:

```text
previous pose
      ↓
      movement
      ↓
current pose
```

must be considered.

---

# Centralize vehicle collision detection

Vehicle collision should be treated as a physics/collision responsibility rather than as an incidental NPC-AI operation.

At minimum support:

```text
Player ↔ NPC
NPC ↔ NPC
```

Use the existing:

```python
boxes_intersect(...)
```

where appropriate.

Do not introduce a second incompatible collision-geometry system.

---

# Collision update ordering

Inspect the existing game update loop carefully.

The conceptual ordering should be approximately:

```text
1. AI decisions
2. desired steering / target speed
3. physics movement
4. collision detection
5. collision response
6. crash-state transitions
7. rendering
```

The exact implementation can differ if the current architecture requires it.

The important requirement is:

> Collision detection must see the actual movement that happened during the frame.

Do not detect collision only from stale positions from before physics movement.

---

# Swept collision detection

Add a practical continuous/swept collision check.

It does not need to be mathematically perfect.

A reasonable implementation can use:

```text
previous position
+
current position
+
vehicle dimensions
```

to construct a cheap swept broad-phase volume.

For example conceptually:

```text
previous pose ----------------> current pose
              swept bounds
```

Then:

```text
swept broad phase
       ↓
nearby candidate vehicles
       ↓
more accurate collision test
       ↓
existing OBB/SAT test
```

The exact implementation must fit the existing physics model.

Avoid an expensive continuous SAT calculation for every vehicle every frame.

---

# Spatial broad phase

Do not do:

```python
for npc in all_npcs:
    for other in all_npcs:
        ...
```

Use the existing spatial grid or spatial-index infrastructure.

The intended architecture is:

```text
vehicle movement
      ↓
update spatial grid
      ↓
query nearby/swept candidates
      ↓
OBB/SAT only for candidates
```

This is especially important because the game can contain many Residents and NPC vehicles.

---

# Collision response

When a real collision occurs:

- vehicles must not simply pass through each other;
- the collision must be visible/physical;
- do not teleport vehicles unrealistically;
- do not permanently freeze healthy vehicles;
- preserve existing crash behavior;
- trigger the existing crash state machinery.

Inspect the existing crash implementation before changing it.

---

# Existing crashed-driver behavior

The existing NPC system has state intended to prevent a crashed vehicle from simply receiving a new driver.

There is a `driver_departed` concept/state.

Preserve this behavior.

The following must remain true:

```text
vehicle crashes
      ↓
driver leaves
      ↓
driver_departed = True
      ↓
vehicle cannot unexpectedly receive a replacement driver
```

Do not accidentally break this while moving collision handling into the physics/collision layer.

---

# Important collision question to investigate

Before implementing the fix, determine exactly:

1. Where is `boxes_intersect()` currently called?
2. Is it called before or after `update_car_physics()`?
3. Does it test Player ↔ NPC?
4. Does it test NPC ↔ NPC?
5. Are previous positions stored?
6. Is the spatial grid updated before collision queries?
7. Is collision response separate from collision detection?
8. Can an NPC move several meters in one frame at high speed?
9. Can an NPC collision be skipped because the other NPC was not updated yet?
10. Can collision handling be overwritten by subsequent physics movement?

Fix the actual architectural issue instead of adding another collision check somewhere else.

---

# Preserve existing safety checks

The current NPC system also has footprint/safety checks against things such as:

- curbs
- buildings
- road boundaries

These should remain useful safety nets.

However:

> Do not use the footprint safety check as the primary method of route following.

The NPC should follow the road correctly in the first place.

---

# Parking and collision exceptions

Inspect any special collision behavior related to:

- parking
- final approach
- parked vehicles
- destination arrival

There appears to be logic where certain parked vehicles may be ignored during an NPC's final approach.

Do not remove such behavior blindly.

Determine whether the exception is:

```text
legitimate parking behavior
```

or:

```text
a workaround hiding collision bugs
```

If it is a legitimate parking rule, preserve it.

If it causes player/NPC collisions to be skipped incorrectly, narrow the exception to the exact parking scenario where it is required.

---

# Performance requirements

This is a real-time game.

Do not solve the problems using expensive global operations.

Avoid:

```python
for npc in all_npcs:
    for other in all_npcs:
        ...
```

Avoid:

```text
full OSM graph search every frame
```

Avoid:

```text
rebuilding every NPC route every frame
```

Avoid:

```text
recalculating every route's entire geometry every frame
```

Use:

- spatial grid
- local candidate queries
- cached route information
- incremental population management
- bounded route-generation work
- cached route/polyline data where appropriate

---

# Testing – population

Add or update tests for:

### Moving population

Verify:

```text
moving count < target
        ↓
population controller starts trips
```

Verify that:

- successful routes increase moving population;
- failed routes do not permanently block recovery;
- failed candidates are not retried continuously without backoff;
- multiple ticks eventually retry candidates;
- parked vehicles are not counted as moving;
- traffic does not depend incorrectly on city size.

---

# Testing – path following

Test at minimum:

```text
straight road
gentle curve
sharp curve
left turn
right turn
closely spaced route points
long route
low speed
medium speed
high speed
```

Verify that NPCs:

- remain on the road;
- do not zig-zag;
- do not oscillate;
- do not cut corners;
- do not overshoot turns;
- maintain reasonable lane position.

---

# Testing – traffic rules

Verify that the new steering system does not break:

- red lights;
- stop signs;
- yield signs;
- speed limits;
- vehicle-ahead braking;
- destination approach;
- parking.

A red light must never become effectively green for conflicting traffic because of the new path-following logic.

---

# Testing – collisions

Test:

```text
Player → NPC from behind
Player → NPC from side
NPC → Player
NPC → NPC
NPC → NPC at high speed
NPC → NPC crossing trajectories
low-speed collision
high-speed collision
collision near intersection
collision while turning
crashed NPC
departed driver
```

Specifically verify that a vehicle cannot routinely tunnel through another vehicle between two physics frames.

---

# Debug information

If the existing debug UI supports NPC inspection, expose or improve:

```text
NPC state
speed
target speed
path index
route length
lookahead distance
steering
lane offset
moving/parked state
traffic-rule action
vehicle-ahead distance
collision candidates
last collision
```

This is extremely useful for debugging the system.

Do not make expensive debug calculations mandatory during normal gameplay.

---

# Do not use symptom hacks

Do NOT solve these problems using special cases such as:

```python
if large_city:
    spawn_more_npcs()
```

or:

```python
if npc_is_near_player:
    force_collision()
```

or:

```python
if vehicle_is_stuck:
    teleport_vehicle()
```

or:

```python
if collision_failed:
    force_crash()
```

or:

```python
if turn_is_bad:
    increase_steering()
```

unless the condition is part of a properly designed physical/traffic rule.

The goal is to fix:

```text
population management
route following
steering
physics integration
collision architecture
```

rather than hide their symptoms.

---

# Recommended architecture

Keep the following responsibilities clearly separated:

```text
Residents
    ↓
trip generation
    ↓
route generation
    ↓
route/polyline
    ↓
path follower
    ↓
desired steering
    ↓
traffic-rule speed constraints
    ↓
vehicle physics
    ↓
collision detection
    ↓
collision response
    ↓
crash state
    ↓
NPC lifecycle
```

More specifically:

```text
Route
    = where the NPC wants to go

Path follower
    = where the NPC should steer

Traffic rules
    = how fast the NPC is allowed to go

Physics
    = how the vehicle actually moves

Collision
    = interaction between physical vehicles

NPC lifecycle
    = driver/vehicle state and trip state
```

Avoid mixing these responsibilities further.

---

# Implementation strategy

Work incrementally.

## Step 1 – Investigation

Inspect the existing implementation and identify the exact functions responsible for:

- population maintenance;
- trip creation;
- route generation;
- route validation;
- waypoint advancement;
- steering;
- lane positioning;
- corner-speed calculation;
- traffic-rule decisions;
- vehicle-ahead detection;
- physics movement;
- spatial-grid updates;
- collision detection;
- collision response;
- crash handling;
- driver departure.

Before modifying code, summarize the actual current flow.

---

## Step 2 – Fix population management

Improve the moving-population controller.

Keep the existing time budgets, but make them work incrementally.

Add candidate retry/backoff and diagnostics.

Run the relevant tests.

---

## Step 3 – Improve route following

Implement the lookahead-based path-following controller.

Keep route generation intact unless investigation proves that route generation itself is producing invalid paths.

Run path-following tests.

---

## Step 4 – Integrate steering with traffic rules

Ensure:

```text
path follower → steering
traffic rules → target speed
corner analysis → safe speed
vehicle-ahead → braking
physics → movement
```

Run traffic-rule tests.

---

## Step 5 – Fix collision architecture

Move vehicle collision handling to the correct update stage.

Implement:

- Player ↔ NPC
- NPC ↔ NPC
- swept broad phase
- spatial-grid candidate filtering
- existing OBB/SAT narrow phase
- proper collision response
- crash-state integration

Run collision tests.

---

## Step 6 – Full regression test

Run the complete test suite.

Fix all regressions.

Then perform a manual gameplay test in:

1. a small town;
2. a medium-sized town;
3. a large city;
4. a complex multi-lane road;
5. a large intersection;
6. an area with traffic lights;
7. an area with stop/yield signs.

---

# Performance review

After implementation, explicitly inspect the changed code for:

- O(n²) NPC loops;
- unnecessary allocations;
- repeated route processing;
- repeated OSM searches;
- repeated geometry calculations;
- excessive spatial-grid updates;
- expensive collision checks;
- excessive logging;
- frame-time spikes.

The NPC system must remain performant with realistic traffic.

Do not trade a correct simulation for an unplayable frame rate.

---

# Acceptance criteria

## Traffic

Large cities should contain a healthy amount of moving NPC traffic.

Small towns should not artificially generate excessive traffic.

The moving population should converge toward its configured target when sufficient valid vehicles and road network are available.

Route-generation failures must not permanently suppress traffic.

Population maintenance must not create visible frame-time spikes.

---

## Driving

NPCs should:

- remain on roads;
- maintain stable lane positioning;
- follow curves smoothly;
- anticipate turns;
- slow before sharp corners;
- accelerate after turns;
- avoid zig-zagging;
- avoid oscillation;
- avoid random reversals;
- avoid repeatedly hitting curbs/buildings;
- obey traffic lights;
- obey stop signs;
- obey yield signs;
- obey speed limits;
- brake for vehicles ahead.

---

## Collision

The player must be able to collide with NPC vehicles.

NPC vehicles must be able to collide with each other.

Fast vehicles must not routinely tunnel through other vehicles.

Collision detection must use efficient broad-phase candidate selection.

Existing OBB/SAT geometry should be reused where appropriate.

Existing crash and driver-departure behavior must continue to work.

---

## Performance

Do not introduce:

```text
O(N²) vehicle collision scans
full-map searches every frame
OSM graph rebuilding every frame
full-route regeneration every frame
large per-frame allocations
```

The game should maintain a stable frame rate with a realistic NPC population.

---

# Final deliverable

After implementation:

1. Run the complete test suite.
2. Fix all regressions.
3. Perform manual testing in small and large cities.
4. Summarize the root causes discovered.
5. Explain why large cities previously had less traffic.
6. Explain what caused the poor NPC driving.
7. Explain why vehicle collisions were being missed.
8. List the files modified.
9. Summarize the architectural changes.
10. Report test results.
11. Report performance observations.
12. Report any remaining known limitations.

Do not merely report that the code compiles.

The goal is a genuinely more reliable NPC traffic simulation while preserving the existing Road Rage Taxi architecture.