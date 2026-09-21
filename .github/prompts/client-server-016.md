# NPC Traffic Optimization and Natural Viewpoint Spawn/Despawn

You are working on the current Road Rage Taxi codebase.

Before making any changes, inspect the actual current implementation in the repository. Do not assume that previous architecture or optimization phases were implemented exactly as intended. Identify the relevant NPC, traffic, rendering, camera, spatial-grid, route-planning, and spawn/despawn code first.

The goal of this task is to improve overall game performance while making NPC traffic feel natural: vehicles should enter and leave the playable view naturally, with spawning and despawning happening outside the player's viewpoint rather than visibly appearing or disappearing on screen.

## 1. Preserve the current architecture

The normal single-player game must remain a direct in-process simulation.

Do NOT reintroduce:

* TCP communication
* JSON state serialization
* a SimulationServer thread
* ShadowVehicle/ShadowPedestrian objects
* network interpolation
* client/server synchronization in the normal game loop

Keep the Phase 1/1.5 architecture:

```text
Input
  ↓
PlayerCommand
  ↓
advance_simulation()
  ↓
Current simulation state
  ↓
Renderer
```

Do not solve performance problems by reverting the simulation/rendering separation.

The existing experimental `--connect` / client-server infrastructure may remain isolated, but it must not affect normal single-player performance.

---

# 2. Profile before optimizing

First establish a measurable baseline.

Use the existing profiling/debugging tools in the project if available. If useful, temporarily add lightweight profiling instrumentation.

Measure at least:

* average FPS
* frame-time average
* frame-time p95/p99
* worst frame times
* NPC update time
* NPC collision/avoidance time
* spatial-grid update time
* route-planning time
* NPC spawn/despawn time
* rendering time
* map/tile streaming time
* pedestrian update time

Pay particular attention to periodic frame spikes rather than only average FPS.

Do not optimize based purely on assumptions.

After the changes, compare the same measurements against the baseline.

---

# 3. Remove artificial visible-NPC limits

Search the entire repository for:

```text
MAX_VISIBLE_NPC_COUNT
```

Determine exactly what it currently controls.

If it is merely an arbitrary limit on how many otherwise valid NPC vehicles can be rendered, remove that artificial limit.

Do NOT replace it with another arbitrary hard limit such as:

```text
MAX_RENDERED_CARS = 10
```

The player should be able to see all appropriate nearby traffic.

If culling is necessary for performance, use spatial/distance/viewpoint-based culling instead.

The principle should be:

```text
NPC is near/in the active world area
        ↓
simulate as required

NPC is inside renderable viewpoint
        ↓
render it

NPC is far outside the active area
        ↓
do not simulate/render unnecessarily
```

Rendering should not depend on an arbitrary "first N NPCs" rule.

---

# 4. Implement natural NPC vehicle spawning

NPC vehicles must NOT suddenly appear directly inside the player's visible area.

Create a proper spawn system based on the player's current viewpoint and active world area.

A suitable conceptual model is:

```text
                  ACTIVE WORLD AREA

        +-----------------------------------+
        |                                   |
        |    SPAWN BUFFER                   |
        |   +---------------------------+   |
        |   |                           |   |
        |   |       PLAYER VIEW         |   |
        |   |                           |   |
        |   |           🚕              |   |
        |   |                           |   |
        |   +---------------------------+   |
        |                                   |
        +-----------------------------------+

        NPCs may spawn here ↑

        NPCs should NOT spawn directly
        inside the player's viewpoint.
```

The actual implementation must account for camera position, camera movement, and the player's current direction/speed where appropriate.

### Spawn requirements

When a new background traffic vehicle is required:

1. Find a suitable road segment outside the current visible viewpoint.
2. Ensure the spawn position is sufficiently outside the visible area.
3. Select a valid driving direction/lane.
4. Generate or obtain a valid route.
5. Initialize the vehicle with a valid cruising state.
6. Spawn it outside the player's visible area.
7. Let it naturally drive into the viewpoint.

The player should normally first see the vehicle approaching from outside the screen rather than watching it materialize.

Avoid spawning vehicles at arbitrary map coordinates.

---

# 5. Spawn based on roads, not screen coordinates alone

NPC spawning must respect the existing OSM road network.

Do not simply place an NPC at:

```python
random_x
random_y
```

Instead:

```text
spawn location
    ↓
valid OSM road
    ↓
valid driving direction
    ↓
valid lane/road segment
    ↓
route
    ↓
NPC enters simulation
```

Reuse the existing road graph, route planner, lane logic, traffic-light logic, and vehicle movement implementation wherever possible.

Do not create a second independent traffic simulation.

---

# 6. Spawn outside the viewpoint, including camera movement

The system must work correctly when the player is:

* stationary
* driving slowly
* driving quickly
* turning
* moving the camera
* moving toward previously unloaded areas

Do not use a fixed world-space spawn location.

Spawn/despawn zones should follow the player's active simulation area.

Prefer a system conceptually similar to:

```text
VISIBLE AREA
     +
SPAWN/DESPAWN BUFFER
     +
ACTIVE SIMULATION AREA
```

The exact distances should be configurable and determined through profiling and gameplay testing.

For example:

```text
render distance < spawn distance < simulation distance
```

The exact numerical values should NOT be hardcoded without first considering the game's camera scale and vehicle speed.

---

# 7. Natural despawning

NPCs must not disappear immediately when they leave the screen.

Instead, create a sufficiently large despawn buffer outside the viewpoint.

Conceptually:

```text
                  DESPAWN AREA

        +-----------------------------------+
        |                                   |
        |      NPC may continue driving     |
        |                                   |
        |       +---------------------+     |
        |       |                     |     |
        |       |   PLAYER VIEW       |     |
        |       |                     |     |
        |       +---------------------+     |
        |                                   |
        +-----------------------------------+

        NPC may be recycled/despawned
        only sufficiently far outside view.
```

An NPC that drives just beyond the screen edge should continue existing.

This is important because immediate despawning at the viewport boundary would be visually noticeable.

---

# 8. Recycle traffic instead of constantly creating/destroying objects

Where practical, use an NPC vehicle pool.

Instead of:

```text
destroy vehicle
create new vehicle
destroy vehicle
create new vehicle
```

prefer:

```text
vehicle leaves active area
        ↓
reset/recycle vehicle
        ↓
calculate new route
        ↓
spawn outside viewpoint
        ↓
continue driving
```

This should reduce allocation and garbage-collection pressure.

However, do not introduce object pooling blindly. Profile first and ensure pooled objects are fully reset.

A recycled vehicle must not retain:

* old route
* old route index
* old velocity
* old acceleration
* old collision state
* old traffic-light state
* old target
* old passenger state
* old damage state
* old timers
* old debug state

---

# 9. Maintain continuous background traffic

Do not rely on a low-probability random event to occasionally create traffic.

The traffic system should maintain a target population of active cruising vehicles.

Conceptually:

```text
target background traffic
        ↓
active traffic count
        ↓
if below target:
    prepare new route
    spawn vehicle outside viewpoint
```

However, do NOT simply increase route-planning attempts every tick.

Route planning can be expensive.

Instead:

* prepare routes before spawning
* avoid route planning inside the render loop
* avoid repeatedly planning routes for the same vehicle
* reuse valid routes where possible
* stagger expensive route planning
* avoid creating a large CPU spike when several vehicles are needed

If route planning is currently synchronous and expensive, investigate whether it can be queued or amortized without introducing thread-safety problems.

---

# 10. Optimize the NPC update loop

Profile and optimize the existing NPC hot path.

Pay particular attention to:

### Spatial grid

Determine whether the spatial grid is rebuilt unnecessarily every frame.

Avoid expensive full rebuilds when an incremental update or simulation-tick update is possible.

Do not sacrifice collision correctness.

### Neighbor detection

Avoid unnecessary O(N²) NPC-to-NPC comparisons.

Use the existing spatial partitioning system where appropriate.

### Collision/avoidance

Keep the current NPC collision and avoidance behavior intact.

Optimize:

* unnecessary repeated lookups
* repeated calculations
* redundant distance calculations
* unnecessary neighbor checks
* repeated road/lane lookups

Do not remove safety checks simply to gain FPS.

### Traffic lights

Keep traffic-light correctness.

Do not optimize by allowing NPCs to ignore red lights or by checking traffic lights only visually.

### Route following

Avoid repeatedly recalculating routes during normal driving.

A vehicle with a valid route should normally follow that route until:

* destination reached
* route invalidated
* road/network changes
* exceptional recovery is required

---

# 11. Separate traffic categories

Keep these concepts logically separate:

### Resident vehicles

Vehicles belonging to simulated Residents and their daily routines.

### Background traffic

Vehicles whose purpose is to provide continuous believable traffic around the player.

Background traffic should not require a full Resident simulation.

This allows the game to have:

```text
Residents
    ↓
meaningful daily routines

Background traffic
    ↓
continuous believable road traffic
```

Do not force every visible vehicle to become a fully simulated Resident.

This separation will also make the future Resident daily-routine system easier to implement.

---

# 12. Active simulation area

Introduce or refine an active traffic area around the player.

Use at least three conceptual zones:

```text
             OUTSIDE ACTIVE AREA
                    ↓
             no simulation

        +-----------------------+
        |   ACTIVE AREA         |
        |                       |
        |   +---------------+   |
        |   | VIEWPOINT     |   |
        |   +---------------+   |
        |                       |
        +-----------------------+

                    ↑
             spawn/despawn
                 buffers
```

The exact implementation can differ, but the important rule is:

**The viewport is not the simulation boundary.**

NPCs need to exist outside the visible screen so they can naturally enter it.

---

# 13. Avoid visible pop-in

Test specifically for these cases:

* driving toward a road with traffic
* turning onto a new road
* rapidly moving through the map
* camera following the player at high speed
* approaching intersections
* NPC entering from the edge of the screen
* NPC leaving behind the player
* crossing map/tile boundaries

The player should not see:

```text
empty road → instant car appears
```

or:

```text
car reaches screen edge → instantly disappears
```

Instead:

```text
car approaches from outside view
        ↓
enters player's view
        ↓
passes naturally
        ↓
continues outside view
        ↓
eventually despawns/recycles
```

---

# 14. Do not over-simulate distant NPCs

NPCs far outside the player's active area should not consume the same CPU budget as visible NPCs.

Use appropriate simulation levels if useful:

```text
Near player:
    full simulation

Moderately distant:
    reduced simulation frequency where safe

Far outside:
    inactive/recycled
```

Do not implement a complicated LOD system unless profiling demonstrates that it is useful.

Keep the implementation simple and deterministic.

---

# 15. Preserve gameplay behavior

Do not regress existing functionality.

The optimization must preserve:

* NPC-004 traffic behavior
* NPC driving
* curved turns
* cruising speed
* route following
* traffic lights
* collision avoidance
* pedestrian systems
* Resident systems
* player physics
* missions
* passengers
* rage/anger system
* weather
* time of day
* camera behavior
* map rendering
* lighting
* audio
* UI

Do not remove gameplay systems merely because they are expensive.

If a subsystem is expensive, profile and optimize it.

---

# 16. Frame pacing is more important than peak FPS

The goal is not merely:

```text
average FPS = high
```

The goal is:

```text
stable frame times
```

For a 60 FPS target:

```text
16.67 ms/frame
```

Avoid periodic spikes such as:

```text
12 ms
14 ms
13 ms
48 ms  ← bad
13 ms
14 ms
```

A stable:

```text
15–16 ms
```

is preferable to a higher average FPS with large periodic stalls.

Investigate spikes caused by:

* route planning
* NPC spawning
* NPC despawning
* spatial-grid rebuilds
* object allocation
* garbage collection
* OSM tile integration
* map streaming
* rendering
* pedestrian updates

---

# 17. Add useful traffic diagnostics

If the project has a debug overlay, add lightweight counters such as:

```text
NPC:
  active total
  visible
  background traffic
  resident vehicles
  parked vehicles
  currently cruising

Spawn:
  spawn candidates
  successful spawns
  failed spawns
  recycled vehicles

Despawn:
  recycled
  removed
  outside active area

Performance:
  NPC update ms
  route planning ms
  spatial grid ms
```

Do not update expensive diagnostic information every frame unless necessary.

The debug system itself must not become a performance problem.

---

# 18. Testing

Add or update tests for:

### Spawn

* NPC never intentionally spawns inside the visible viewpoint
* NPC spawn position is on a valid road
* NPC has a valid route before becoming active
* NPC enters the simulation at a valid cruising state

### Despawn

* NPC does not despawn merely because it leaves the screen
* NPC can leave the viewpoint and continue driving
* NPC eventually becomes recyclable outside the active area

### Recycling

* recycled NPC state is completely reset
* old routes do not leak into the new trip
* old collision/physics state does not leak

### Traffic

* target traffic population is maintained
* traffic lights remain correct
* NPC collision/avoidance remains correct

### Performance

* normal single-player does not start the server
* normal single-player does not use TCP/JSON
* no unnecessary ShadowVehicle/ShadowPedestrian state path is active
* route planning is not performed from the render loop

---

# 19. Important constraints

Do NOT:

* reintroduce client/server architecture into single-player
* add multiprocessing just to hide the problem
* add arbitrary hard limits on visible NPCs
* remove NPC behavior to gain FPS
* disable collision checks
* disable traffic-light logic
* move expensive work into the render loop
* perform full route planning every frame
* spawn vehicles directly inside the player's view
* despawn vehicles immediately at the screen boundary
* perform massive synchronous traffic initialization during a frame
* introduce unnecessary threads without profiling and synchronization design

Do not optimize blindly.

**Measure → identify bottleneck → optimize → measure again.**

---

# 20. Acceptance criteria

The implementation is successful when:

1. Normal single-player remains direct in-process.
2. No TCP/JSON/server-thread overhead is present in normal gameplay.
3. `MAX_VISIBLE_NPC_COUNT` is removed if confirmed to be an artificial rendering/gameplay cap.
4. There is no arbitrary "render only N NPCs" limitation.
5. NPCs spawn outside the player's visible viewpoint.
6. NPCs naturally drive into the player's view.
7. NPCs continue driving after leaving the viewpoint.
8. NPCs are recycled/despawned only sufficiently far outside the active area.
9. Background traffic remains continuously populated.
10. Route planning does not create visible frame spikes.
11. NPC updates do not rebuild expensive structures unnecessarily.
12. Traffic-light and collision behavior remain correct.
13. Frame pacing is measurably improved or at minimum not degraded.
14. No new visible pop-in/pop-out is introduced.
15. Existing gameplay remains functional.
16. Tests pass.

If performance cannot support the desired traffic density, do not hide the problem by reducing visible NPCs. Report the actual measured bottleneck and optimize that subsystem instead.

---

# 21. Final report

When finished, report:

* baseline FPS/frame-time measurements
* final FPS/frame-time measurements
* p95/p99 frame time if available
* biggest performance bottleneck discovered
* changes made to NPC update performance
* changes made to spatial-grid handling
* changes made to route planning
* how spawn positioning works
* how despawn/recycling works
* how far outside the viewpoint NPCs are allowed to exist
* background traffic population behavior
* what happened to `MAX_VISIBLE_NPC_COUNT`
* number of active/visible/cruising NPCs during testing
* whether any frame spikes remain
* tests added/updated
* any remaining performance concerns

Do not claim an optimization is successful merely because the average FPS increased. Include frame-time behavior and explain any remaining spikes.

The priority order is:

1. Correctness
2. Stable frame pacing
3. Natural NPC behavior
4. Traffic density
5. Maximum FPS
