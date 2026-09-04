# Task: Implement Realistic Finnish Traffic Behavior for TrafficManager and CarAI

The game **The Road Rage Trip** is a top-down taxi/driving game built with Python/Pygame and OpenStreetMap data.

The game already has a traffic architecture containing concepts such as:

* `TrafficManager`
* `CarAI`
* `RoadGraph` / `RoadNetwork`
* roads and lanes
* intersections
* traffic lights
* parking spaces
* `SpatialHash`
* LOD-based NPC simulation

Your task is to improve the NPC vehicle traffic behavior so that it resembles **realistic everyday driving in Finland**, while remaining computationally efficient and fun for an arcade-style game.

Do not redesign the entire traffic architecture unless necessary. Inspect the existing implementation first and integrate these behaviors into the current systems.

---

# 1. Core design goals

NPC vehicles should behave like reasonably competent Finnish drivers.

They should:

* stay on the correct side of the road
* follow lanes
* obey traffic lights
* obey stop signs
* yield when required
* maintain reasonable following distances
* react to slower vehicles
* brake smoothly
* accelerate smoothly
* stop at intersections when necessary
* turn correctly
* use appropriate lanes for turns
* handle roundabouts correctly
* interact correctly with pedestrians and crossings
* use existing parking spaces
* avoid collisions
* avoid blocking intersections
* recover from unusual situations
* detect traffic deadlocks
* actively resolve deadlocks

The simulation does not need to model every detail of Finnish traffic law.

Prioritize the rules that materially affect NPC movement and gameplay.

---

# 2. Finnish driving side

Vehicles drive on the **right-hand side** of the road.

For two-way roads:

```text
opposing traffic
      ↓

  ← ← ←

  → → →

      ↑
```

NPCs must select the correct lane based on the road direction.

Do not allow normal traffic to drive on the wrong side merely because that produces a shorter path.

Temporary exceptions may be necessary for:

* overtaking
* parking maneuvers
* avoiding an obstacle
* special road geometry

but these should be rare and controlled.

---

# 3. Speed limits

Use the speed limit provided by the processed OSM road data when available.

NPC speed should be constrained by:

```text
target_speed =
    min(
        road_speed_limit,
        vehicle_max_speed,
        safe_speed_for_current_conditions,
        safe_speed_for_geometry
    )
```

Do not make every NPC drive exactly at the speed limit.

Introduce driver variation.

For example:

```text
cautious driver
    90–100% of limit

normal driver
    95–105% of limit

aggressive driver
    100–110% of limit
```

Do not allow arbitrary excessive speeding.

The player may be intentionally more aggressive than NPC traffic because this is an arcade game, but NPC traffic should remain believable.

---

# 4. Following distance

NPC vehicles must maintain a safe distance from vehicles ahead.

Use a dynamic following distance based on:

* current speed
* reaction time
* vehicle length
* braking capability
* road speed limit

A simple model can use:

```text
desired_gap =
    minimum_gap +
    speed * reaction_time +
    braking_margin
```

The vehicle should:

* accelerate when the gap is comfortably large
* maintain speed when the gap is appropriate
* decelerate smoothly when approaching a slower vehicle
* brake harder only when necessary

Avoid constant acceleration/braking oscillation.

---

# 5. Car-following behavior

Implement a simple but stable car-following model.

Each vehicle should continuously consider:

```text
vehicle ahead
distance to vehicle ahead
relative speed
desired speed
required braking distance
```

If the vehicle ahead is slower:

```text
reduce speed
```

If the vehicle ahead accelerates:

```text
gradually accelerate
```

Avoid unrealistic "accordion traffic" where every vehicle instantly changes speed.

Use acceleration and braking limits.

---

# 6. Traffic lights

Traffic lights are authoritative when a valid traffic-light system exists.

NPCs must recognize:

```text
GREEN
YELLOW
RED
```

Behavior:

### Green

Proceed if:

* the intersection is safe
* the exit lane is available
* there is no conflicting traffic

### Yellow

Do not automatically stop regardless of distance.

If the vehicle is sufficiently far away:

```text
prepare to stop
```

If the vehicle is already too close to the stop line to safely stop:

```text
continue through
```

Avoid emergency braking caused by a yellow light.

### Red

Stop before the stop line.

Do not stop in the middle of the intersection.

---

# 7. Stop lines

Use the intersection/road geometry to determine the correct stopping position.

NPCs should stop:

```text
before stop line
```

rather than:

```text
at intersection center
```

This is particularly important for:

* traffic lights
* stop signs
* pedestrian crossings
* railway crossings if present

Stopping positions should have a small safety margin.

---

# 8. Right-of-way

Implement the important Finnish right-of-way rules.

Important cases include:

### Uncontrolled intersections

At an ordinary uncontrolled intersection, vehicles generally yield to traffic approaching from the **right**.

NPCs must be able to determine:

```text
vehicle approaching from right
```

and yield when appropriate.

### Yield sign

A vehicle facing a yield sign must give way to traffic on the priority road.

### Stop sign

A vehicle facing a stop sign must:

1. stop
2. check for traffic
3. proceed only when safe

Do not treat STOP as merely a low-priority yield.

---

# 9. Priority roads

Where the OSM data provides priority-road information, use it.

If a road has priority over an intersecting road:

```text
priority traffic continues
minor-road traffic yields
```

Do not make vehicles on the priority road unnecessarily stop.

If OSM information is incomplete, use the existing intersection analysis rather than inventing arbitrary priorities.

---

# 10. Turning behavior

Vehicles must select an appropriate lane before turning.

For right turns:

```text
approach appropriate right-side lane
slow down
signal/turn state
check crossing/conflicts
turn
accelerate after completing turn
```

For left turns:

```text
approach appropriate lane
slow down
yield to conflicting traffic
complete turn
enter correct lane
```

Avoid cutting across unrelated lanes.

---

# 11. Turn signals

NPC vehicles should have a logical turn-signal state even if the current renderer does not display indicators.

States:

```text
NONE
LEFT
RIGHT
HAZARD
```

Turn signals should be activated before the maneuver rather than at the exact moment of turning.

The timing should depend on:

* distance to intersection
* vehicle speed
* road geometry

If visual indicators already exist, connect the AI state to them.

---

# 12. Roundabouts

Roundabouts are particularly important.

Vehicles entering a roundabout must:

* approach at an appropriate speed
* yield to traffic already in the roundabout
* enter only when safe
* remain in the correct lane
* follow the roundabout direction
* exit at the correct branch
* avoid stopping unnecessarily inside the roundabout

For Finnish-style right-hand traffic:

```text
traffic circulates counter-clockwise
```

Do not treat a roundabout as a normal four-way intersection.

Detect roundabouts from the existing road graph/OSM processing.

---

# 13. Pedestrian crossings

NPCs must yield to pedestrians where required.

If a pedestrian is:

* already crossing
* clearly entering a crossing
* waiting immediately at a crossing in a situation where the vehicle should yield

the vehicle should slow or stop.

Do not stop hundreds of meters before a crossing.

Use a reasonable stopping distance.

Pedestrian crossings must also interact correctly with traffic lights.

If a pedestrian crossing has a red pedestrian light, do not make vehicles stop merely because a pedestrian is nearby unless another rule requires it.

---

# 14. Lane changing

NPCs should change lanes only when necessary or useful.

Reasons include:

* preparing for a turn
* following route
* avoiding a blocked lane
* overtaking
* lane ending
* road topology requiring it

Before changing lanes, check:

```text
front gap
rear gap
relative speed
target lane
intersection proximity
```

Never change lanes blindly.

Avoid rapid left-right-left oscillation.

Add a cooldown or commitment period after a lane change.

---

# 15. Overtaking

Overtaking should be conservative.

Only overtake when:

* the road geometry allows it
* there is sufficient visibility
* the target lane is appropriate
* the maneuver does not conflict with an upcoming intersection
* the vehicle can safely return to its lane

Do not implement arcade-style constant overtaking.

On narrow Finnish roads, it should be uncommon.

---

# 16. Narrow roads and rural roads

Finnish roads often contain:

* narrow two-way roads
* roads without sidewalks
* roads with ditches/forest beside them
* low traffic volumes
* long straight sections
* sharp curves
* variable speed limits

NPCs should adapt speed to geometry.

For example:

```text
sharp curve
    ↓
lower target speed
    ↓
curve
    ↓
accelerate
```

Do not require a huge speed reduction for gentle curves.

---

# 17. Winter/poor-condition extensibility

Do not implement a complete weather simulation unless the game already supports it.

However, design the speed calculation so that future conditions can influence it.

For example:

```python
safe_speed_factor = weather_speed_factor * road_geometry_factor
```

Possible future factors:

```text
dry
rain
snow
ice
```

The current implementation can simply use:

```text
weather_speed_factor = 1.0
```

---

# 18. Intersection reservation

Use the existing `IntersectionManager` if available.

Vehicles should not enter an intersection if they cannot reasonably clear it.

This is especially important when traffic is heavy.

Bad:

```text
green light
↓
vehicle enters intersection
↓
traffic ahead is stopped
↓
vehicle blocks cross traffic
```

Good:

```text
green light
↓
check downstream space
↓
space available
↓
enter intersection
```

If the exit is blocked, wait before entering.

---

# 19. Box junction / blocking prevention

Treat intersections as resources.

A vehicle should only reserve/enter an intersection when it has a reasonable path through it.

Do not allow vehicles to occupy the center merely because their light is green.

This is one of the most important rules for preventing traffic deadlocks.

---

# 20. Traffic queues

Queues should propagate naturally.

Example:

```text
RED LIGHT
    ↓
car 1 stops
    ↓
car 2 stops behind car 1
    ↓
car 3 stops behind car 2
    ↓
...
```

Vehicles should not stop at arbitrary positions.

Each vehicle should know approximately:

```text
stop_target
desired_gap
queue_position
```

When the light changes:

```text
front vehicle moves
    ↓
next vehicle accelerates
    ↓
queue propagates
```

Avoid all vehicles accelerating simultaneously.

---

# 21. Deadlock detection

Deadlocks are a critical requirement.

The TrafficManager must detect situations where traffic has become mutually blocked.

Possible indicators:

* vehicles remain almost stationary for too long
* vehicles are repeatedly braking/accelerating without progress
* vehicles are occupying conflicting intersection reservations
* vehicles are blocking each other's paths
* a queue has not advanced for a significant time
* vehicles form a spatial cycle
* an intersection remains occupied without meaningful progress

Do not use a single condition.

Combine multiple signals.

For example:

```text
vehicle.speed < threshold
AND
vehicle.has_route
AND
vehicle.blocked_time > DEADLOCK_TIME
```

At the TrafficManager level, also detect:

```text
multiple blocked vehicles
+
same intersection/road segment
+
no meaningful progress
```

---

# 22. Deadlock severity levels

Implement at least three levels:

```text
NORMAL
    ↓
SUSPICIOUS
    ↓
DEADLOCK
```

Example:

```text
NORMAL
vehicle progressing normally

SUSPICIOUS
vehicle has not moved for 3–5 seconds

DEADLOCK
vehicle has not meaningfully progressed for 8–15 seconds
AND
other traffic is also blocked
```

Tune the exact values through gameplay testing.

Do not classify a vehicle as deadlocked simply because it is waiting at a red light.

---

# 23. Deadlock detection must understand legitimate waiting

This is critical.

The following are NOT automatically deadlocks:

* waiting at a red traffic light
* waiting for pedestrians
* waiting for a vehicle with right-of-way
* waiting to enter a busy roundabout
* waiting for an intersection reservation
* waiting for a parked vehicle to move
* temporary congestion

A deadlock requires evidence that progress is impossible or abnormally stalled.

---

# 24. Deadlock recovery

When a deadlock is detected, do not simply teleport vehicles.

First attempt a realistic recovery.

Possible recovery actions:

### 1. Re-evaluate intersection reservations

Release stale reservations belonging to vehicles that are no longer actually inside the intersection.

### 2. Recalculate path

If a vehicle's route is blocked for too long:

```text
current route
    ↓
reroute
```

Use the existing RoadGraph.

### 3. Back off

If a vehicle is physically blocking an intersection:

```text
reverse a short distance
```

only when safe.

Use this sparingly.

### 4. Yield priority adjustment

If several vehicles are waiting at an uncontrolled intersection, choose a deterministic vehicle to proceed first.

Avoid infinite mutual yielding.

### 5. Emergency escape

As a last resort, allow a vehicle to perform a controlled recovery maneuver:

* slowly reverse
* move to a nearby valid lane
* clear the intersection
* recalculate route

Do not teleport unless the situation is irrecoverable.

---

# 25. Deadlock breaker

Create a dedicated system such as:

```text
DeadlockDetector
DeadlockResolver
```

or integrate them into `TrafficManager` if that fits the existing architecture better.

The system should track:

```text
vehicle_id
blocked_since
last_progress_position
last_progress_time
blocking_vehicle
blocking_intersection
blocking_lane
```

This makes debugging possible.

---

# 26. Deadlock recovery must be deterministic

Do not have every vehicle independently decide to escape.

The TrafficManager should coordinate recovery.

For example:

```text
TrafficManager
      ↓
detect deadlock
      ↓
identify blocking vehicles
      ↓
select recovery vehicle
      ↓
assign recovery action
      ↓
monitor progress
      ↓
resume normal AI
```

This prevents chaotic behavior.

---

# 27. Stuck vehicle recovery

Also handle non-deadlock situations.

A single vehicle may become stuck because of:

* bad geometry
* pathfinding error
* unexpected collision
* blocked lane
* failed lane change
* invalid intersection state

If a vehicle remains stuck too long:

```text
recalculate local route
```

If still stuck:

```text
reposition/recover using safe controlled movement
```

Only use hard repositioning as a last-resort failsafe.

Log every such event in debug mode.

---

# 28. NPC behavior variation

Not every NPC should drive identically.

Create driver behavior parameters such as:

```text
aggression
patience
reaction_time
desired_speed_factor
following_distance_factor
lane_change_probability
overtaking_probability
intersection_patience
```

For example:

```text
cautious driver
    slower
    larger gaps
    less overtaking

normal driver
    default behavior

aggressive driver
    smaller gaps
    faster acceleration
    more overtaking
    less patience
```

Keep the variation within believable limits.

---

# 29. Player interaction

The player taxi is a special vehicle.

NPCs should react to the player's behavior.

If the player:

* cuts into traffic
* blocks an intersection
* stops unexpectedly
* drives aggressively
* collides with an NPC

NPCs should respond naturally.

Possible responses:

```text
brake
swerve
wait
change lane
continue
```

Do not allow NPCs to ignore the player vehicle's physical presence.

---

# 30. Collision avoidance

The traffic AI should be predictive rather than purely reactive.

Do not wait until:

```text
distance == 0
```

before braking.

Use predicted time-to-collision:

```text
TTC = distance / closing_speed
```

when appropriate.

If TTC becomes too small:

```text
brake
```

If collision is imminent:

```text
emergency braking
```

Normal traffic should rely on smooth predictive braking.

---

# 31. TrafficManager responsibilities

Keep global responsibilities in `TrafficManager`.

`TrafficManager` should handle:

* vehicle spawning
* despawning
* traffic density
* LOD
* spatial queries
* intersection-level coordination
* deadlock detection
* deadlock resolution
* global traffic statistics
* route assignment

`CarAI` should handle individual vehicle behavior:

* lane following
* acceleration
* braking
* following
* turning
* lane changes
* traffic-light response
* yielding
* local collision avoidance
* parking behavior

Avoid duplicating these responsibilities.

---

# 32. LOD compatibility

All of these systems must remain compatible with the existing LOD architecture.

Example:

```text
NEAR
    full traffic AI
    collision avoidance
    lane changes
    detailed intersection behavior

MEDIUM
    simplified lane following
    simplified traffic rules

FAR
    cheap movement model
    route progression
    minimal collision simulation
```

Deadlock detection should focus primarily on nearby/active traffic.

Do not spend expensive CPU time analyzing distant vehicles.

---

# 33. Performance

This is a real-time game.

Do not run expensive global calculations every frame.

Use the existing spatial partitioning system.

Examples:

```text
60 FPS:
    player

30 FPS:
    nearby traffic

10–15 FPS:
    medium traffic

2–5 FPS:
    distant traffic
```

Deadlock detection can run at a lower frequency, for example:

```text
2–5 times per second
```

rather than every frame.

Use spatial queries to find potentially interacting vehicles.

---

# 34. Debug visualization

Add a traffic debug mode.

Display:

* current lane
* target lane
* target speed
* actual speed
* desired following distance
* current AI state
* traffic-light state
* intersection reservation
* route
* vehicle ahead
* braking target
* deadlock state
* blocked-by vehicle ID

For deadlocks, visually highlight:

```text
blocked vehicle
blocking vehicle
blocking intersection
```

This is extremely important for tuning the system.

---

# 35. Debug logging

Provide useful logs such as:

```text
[Traffic] Vehicle 182 stopped at red light
[Traffic] Vehicle 182 yielding to vehicle 194
[Traffic] Vehicle 182 changing lane LEFT
[Traffic] Vehicle 182 entering intersection 42
[Traffic] Vehicle 182 waiting for intersection exit
```

Deadlock:

```text
[Deadlock] Suspicious traffic detected at intersection 42
[Deadlock] Vehicles: 182, 194, 201
[Deadlock] Blocking vehicle: 194
[Deadlock] Attempting reservation recovery
[Deadlock] Re-routing vehicle 182
[Deadlock] Deadlock resolved
```

Keep logging configurable so normal gameplay is not flooded with output.

---

# 36. Important Finnish traffic rules to prioritize

The implementation should prioritize the following real-world rules:

1. Drive on the right.
2. Obey traffic lights.
3. Stop at red lights.
4. Handle yellow lights sensibly rather than emergency braking.
5. Stop before stop lines.
6. Yield at yield signs.
7. Stop at STOP signs before proceeding.
8. Yield to traffic from the right at applicable uncontrolled intersections.
9. Follow priority-road rules where available.
10. Yield appropriately when entering roundabouts.
11. Use appropriate lanes when turning.
12. Give way to pedestrians at applicable crossings.
13. Do not enter an intersection if the exit is blocked.
14. Maintain safe following distances.
15. Adapt speed to road geometry.
16. Respect OSM speed-limit information where available.
17. Avoid unnecessary lane changes.
18. Avoid unsafe overtaking.
19. Remain on the correct side of the road.
20. Do not block intersections, crossings or other traffic.

Do not attempt to implement every detail of Finnish traffic legislation. Focus on rules that directly affect vehicle movement.

---

# 37. Important implementation principle

Do not create dozens of independent special cases.

Prefer a hierarchy such as:

```text
Global route
      ↓
Current road/lane
      ↓
Target maneuver
      ↓
Traffic control
      ↓
Obstacle detection
      ↓
Target speed
      ↓
Acceleration/braking
```

For example:

```text
target speed
    ↓
road speed limit
    ↓
curve safety
    ↓
traffic light
    ↓
intersection
    ↓
vehicle ahead
    ↓
pedestrian
    ↓
collision avoidance
```

The final speed should be the safest applicable value.

---

# 38. State machine

Use the existing `CarAI` state machine if one exists.

The state model should support states such as:

```text
DRIVING
FOLLOWING
APPROACHING_INTERSECTION
WAITING_AT_LIGHT
YIELDING
TURNING
CHANGING_LANE
ENTERING_INTERSECTION
IN_INTERSECTION
PARKING
PARKED
LEAVING_PARKING
BLOCKED
RECOVERING
```

Do not create unnecessary state transitions every frame.

States should have clear entry and exit conditions.

---

# 39. Acceptance criteria

The implementation is complete when:

* NPCs drive on the correct side of Finnish roads.
* NPCs follow lanes correctly.
* NPCs obey traffic lights.
* NPCs handle yellow lights sensibly.
* NPCs stop at appropriate stop lines.
* NPCs respect yield and stop signs.
* NPCs handle right-of-way correctly at applicable uncontrolled intersections.
* NPCs handle priority roads.
* NPCs navigate roundabouts correctly.
* NPCs select appropriate lanes for turns.
* NPCs yield appropriately to pedestrians.
* NPCs maintain believable following distances.
* NPCs avoid unnecessary lane changes.
* NPCs use predictive braking.
* NPCs avoid entering blocked intersections.
* Traffic queues behave naturally.
* TrafficManager detects genuine deadlocks.
* Legitimate waiting is not incorrectly classified as a deadlock.
* Deadlocks can be resolved without teleporting vehicles under normal circumstances.
* Stuck vehicles can recover.
* Recovery is coordinated by TrafficManager.
* Behavior remains compatible with LOD.
* Performance remains suitable for real-time Pygame gameplay.
* Debug visualization makes traffic problems diagnosable.
* Existing parking-space functionality is preserved.
* Existing RoadGraph/RoadNetwork and IntersectionManager systems are reused where appropriate.

Most importantly:

**The traffic system must prefer realistic, coordinated behavior over simply making vehicles move.**

A vehicle waiting for right-of-way is correct behavior.

A vehicle stopping at a red light is correct behavior.

A vehicle refusing to enter a blocked intersection is correct behavior.

But a group of vehicles that remains permanently stuck must eventually be detected and resolved.
