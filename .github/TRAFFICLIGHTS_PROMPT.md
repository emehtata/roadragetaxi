# Traffic Light and Intersection Signal System

Extend the existing traffic and intersection system with a robust **Traffic Light Manager** capable of handling incomplete and inconsistent OpenStreetMap traffic signal data.

The game uses OpenStreetMap data, but OSM traffic signal information must **not** be assumed to represent every physical traffic light in an intersection.

OSM data may contain:

* only one `traffic_signals` node for an entire intersection
* traffic signal tags attached to only one road
* incomplete signal information
* multiple signal nodes with inconsistent placement
* no explicit information about which lanes are controlled
* no information about turning arrows or signal phases

Therefore, treat OSM traffic signal data primarily as evidence that an intersection is **signal-controlled**, rather than as a complete physical description of every traffic light.

The game must generate a believable traffic-light layout procedurally.

---

# 1. Core Principle

Do not directly render or simulate only the physical traffic signal nodes found in OSM.

Instead:

```text
OSM Traffic Signal Data
          ↓
Detect Signal-Controlled Intersection
          ↓
Analyse Intersection Geometry
          ↓
Detect Incoming Roads and Approaches
          ↓
Generate Traffic Signal Groups
          ↓
Assign Signals to Approaches and Lanes
          ↓
Run Traffic Light Phases
```

The goal is to create a believable signal-controlled intersection even when OSM contains only one traffic signal marker.

---

# 2. Detecting a Signal-Controlled Intersection

An intersection should be considered potentially signal-controlled when one or more of the following are present:

* `highway=traffic_signals`
* `traffic_signals=*`
* a traffic signal node close to the intersection
* traffic signal tags on connected road segments
* multiple nearby OSM signal markers

Do not require every incoming road to contain a traffic signal node.

If even one reliable traffic signal marker is associated with the intersection, analyse the entire intersection and determine whether traffic lights should be generated for all relevant incoming approaches.

Example:

```text
              Road
                |
                |
        ●       |
                |
================+================
                |
                |
```

Even if OSM contains only:

```text
● traffic_signals
```

the system may determine that the entire four-way intersection is signal-controlled.

---

# 3. Intersection Geometry Analysis

Before generating traffic lights, analyse the geometry of the entire intersection.

The system must identify:

* intersection centre
* incoming roads
* outgoing roads
* road directions
* number of approaches
* road widths
* lane counts where available
* divided roads
* traffic islands
* medians
* pedestrian crossings where available

The result should be represented as an intersection model rather than a collection of unrelated OSM nodes.

For example:

```text
                 NORTH
                   ↓
                   │
                   │
WEST ──────────────┼────────────── EAST
                   │
                   │
                   ↑
                 SOUTH
```

The system should identify four separate **approaches**:

```text
North approach
South approach
East approach
West approach
```

Each approach should then be analysed independently.

---

# 4. Approach Detection

Create an `IntersectionApproach` abstraction.

For example:

```python id="d2n5v1"
class IntersectionApproach:
    road_segments
    incoming_lanes
    outgoing_lanes
    direction_vector
    stop_line
    signal_group
```

An approach represents vehicles entering the intersection from one direction.

For example:

```text
              ↓
        NORTH APPROACH

WEST ←──── INTERSECTION ────→ EAST

        SOUTH APPROACH
              ↑
```

Important:

A physical road may contain multiple lanes, but the road should normally be treated as **one traffic approach** unless geometry clearly indicates separate carriageways.

---

# 5. Generating Traffic Lights for Every Approach

For each detected incoming approach, generate at least one appropriate traffic signal.

The minimum requirement for a normal signal-controlled intersection is:

```text
One signal group per incoming approach
```

Example:

```text
          [N SIGNAL]

              ↓

[W SIGNAL] ←  +  → [E SIGNAL]

              ↑

          [S SIGNAL]
```

Each signal group controls traffic entering the intersection from that direction.

Do not require separate OSM traffic signal markers for every approach.

The procedural system should generate missing signals where necessary.

---

# 6. Multi-Lane Intersections

Multi-lane roads require special handling.

Example:

```text
        ↓   ↓   ↓
      ┌───────────┐
      │ L1 L2 L3  │
      │           │
──────┼───────────┼──────
      │           │
      └───────────┘
```

Do not automatically generate one physical traffic light per lane unless necessary.

Instead, distinguish between:

## Logical signal groups

Used by the traffic simulation.

For example:

```text
Northbound straight/right group
Northbound left-turn group
```

## Physical signal objects

Used for rendering.

A logical signal group may control multiple lanes.

For example:

```text
Lane 1 ─┐
Lane 2 ─┼── Signal Group A
Lane 3 ─┘
```

The system should prioritise correct traffic behaviour over perfectly reproducing every physical traffic light.

---

# 7. Lane-Based Movement Analysis

When lane information is available, analyse:

* `lanes=*`
* `lanes:forward=*`
* `lanes:backward=*`
* turn restrictions
* turn lanes
* `turn:lanes=*`

Use this information to determine which movements are possible from each approach.

Example:

```text
Approach:

Lane 1 → LEFT
Lane 2 → STRAIGHT
Lane 3 → STRAIGHT / RIGHT
```

Represent allowed movements logically:

```python id="dpm6wj"
LEFT
STRAIGHT
RIGHT
```

If lane information is missing, infer a simplified lane model based on:

* road width
* total lane count
* driving direction
* connected roads
* local road geometry

Do not attempt to perfectly reconstruct real-world lane markings when OSM data is incomplete.

Prefer believable gameplay behaviour.

---

# 8. Traffic Islands and Divided Roads

Special care is required for intersections containing:

* central medians
* traffic islands
* pedestrian refuges
* divided carriageways
* raised islands
* separated turning lanes

Example:

```text
          ↓       ↓
        ║           ║
────────║─────●─────║────────
        ║           ║
          ↑       ↑
```

Do not assume that two separated pieces of road always represent two independent intersections.

The system must analyse whether separated carriageways belong to the same logical intersection.

For example:

```text
      Road A
        ║
════════╬════════
        ▓  ISLAND
════════╬════════
        ║
      Road B
```

These may visually consist of multiple road segments but still belong to one intersection.

---

# 9. Logical Intersection Clustering

Create a system that groups nearby road junctions into one **LogicalIntersection**.

This is especially important for:

* divided roads
* central medians
* traffic islands
* closely spaced junction nodes
* large multi-lane intersections

Example:

```text
OSM geometry:

      Junction A       Junction B
          +---------------+
          |               |
```

Instead of creating two separate traffic-light controllers, cluster them into:

```text
        LogicalIntersection
```

Use a configurable clustering distance based on the game's world scale.

However, clustering must also consider connectivity and road geometry.

Do not blindly merge every nearby intersection.

---

# 10. Divided Carriageways

A major road may contain separate carriageways:

```text
→ → → →     MEDIAN     ← ← ← ←
```

These may generate separate road geometries and separate OSM ways.

When they meet another road, the system should determine:

```text
Are these separate intersections?

or

Are they part of the same logical intersection?
```

If they belong to the same intersection, they should normally share a coordinated traffic-light controller.

Example:

```text
      ↓

═══════╬═══════
       █ MEDIAN
═══════╬═══════

      ↑
```

The north/south and east/west phases should remain coordinated even if the physical geometry contains multiple junction nodes.

---

# 11. Stop Line Generation

Each incoming approach should have a logical stop line.

The stop line should normally be placed:

* before entering the conflict area
* before the central intersection
* after any relevant pedestrian crossing where appropriate
* in front of the generated traffic light

Example:

```text
Vehicle →

─────── STOP LINE ───────
           █
           █ TRAFFIC LIGHT

        INTERSECTION
```

If OSM contains an explicit stop line or traffic signal position, use it when reliable.

Otherwise generate one procedurally.

For complex intersections, calculate the stop line using the actual conflict area rather than simply placing it at a fixed distance from the intersection centre.

---

# 12. Signal Placement

Physical traffic light sprites should be generated procedurally from the logical intersection model.

Place them near:

* the relevant stop line
* the side of the incoming carriageway
* traffic islands or medians when present
* opposite sides of very wide roads where necessary

Example:

```text
              ↓

        🚦     🚦
───────────────
        STOP
───────────────
```

For a normal road, one or two rendered lights per approach may be sufficient.

For wide or multi-lane roads:

```text
🚦     LANE LANE LANE     🚦
```

Place additional physical signal sprites where visually appropriate.

However, all physical lights may reference the same logical `SignalGroup`.

---

# 13. Signal Groups

Separate **physical lights** from **logical signal groups**.

Example:

```text
Physical Light A ─┐
Physical Light B ─┼── SignalGroup NORTH
Physical Light C ─┘
```

The logical signal group determines:

```text
RED
YELLOW
GREEN
```

The physical traffic light objects simply render that state.

Example structure:

```python id="w2d2cn"
class SignalGroup:
    approach_id
    allowed_movements
    state
    phase_id
```

Physical objects:

```python id="q3z1o6"
class TrafficLight:
    position
    rotation
    signal_group
```

This separation is essential for complex and multi-lane intersections.

---

# 14. Basic Traffic Light Phases

Implement a configurable phase system.

For a standard four-way intersection:

```text
PHASE 1

North/South:
GREEN

East/West:
RED
```

Then:

```text
PHASE 2

North/South:
YELLOW

East/West:
RED
```

Then an all-red safety phase:

```text
PHASE 3

ALL:
RED
```

Then:

```text
PHASE 4

North/South:
RED

East/West:
GREEN
```

Continue cycling.

Use configurable durations.

Example:

```text
GREEN      20 seconds
YELLOW      3 seconds
ALL RED     1 second
```

These values should be configurable and easy to tune for gameplay.

---

# 15. Turning Movements

Initially, implement a simplified turning system.

Default behaviour:

```text
STRAIGHT
RIGHT TURN
```

may share the normal green phase.

Left turns may:

* yield to conflicting traffic
* be blocked when required
* later receive dedicated arrow phases

Do not over-engineer protected turning arrows in the first implementation.

However, design the `SignalGroup` and phase system so that dedicated turning phases can be added later.

For example:

```text
North Straight Group
North Left-Turn Group
```

could later receive separate phases.

---

# 16. Traffic AI and Signal Interaction

NPC vehicles must interact with traffic lights through logical signal groups rather than physical sprite collision.

When an NPC approaches an intersection:

1. Determine its `IntersectionApproach`.
2. Determine its intended movement:

   * left
   * straight
   * right
3. Determine the controlling `SignalGroup`.
4. Query the signal state.

Example:

```python id="8dzjs8"
signal_state = intersection.get_signal_state(
    approach,
    intended_movement
)
```

NPC behaviour:

```text
GREEN:
Proceed

YELLOW:
Proceed only if already too close to stop safely

RED:
Stop before stop line
```

NPCs must stop behind the logical stop line rather than colliding with the rendered traffic light object.

---

# 17. Yellow Light Behaviour

Do not make NPC vehicles immediately brake unrealistically whenever a signal changes to yellow.

When the light changes:

Calculate:

* distance to stop line
* current speed
* braking distance

If the vehicle can safely stop:

```text
YELLOW → BRAKE → STOP
```

If it is too close:

```text
YELLOW → CONTINUE THROUGH INTERSECTION
```

This prevents unrealistic behaviour such as:

```text
Car moving at full speed
      ↓
Light changes yellow
      ↓
Instant emergency stop
```

---

# 18. Red Light Queueing

Vehicles waiting at red lights should form queues.

Example:

```text
CAR 1
CAR 2
CAR 3
──────── STOP LINE
        RED
```

Use the existing vehicle-following system together with the stop line.

The first vehicle stops before the stop line.

Other vehicles follow using normal safe-distance logic.

Do not make every vehicle independently target exactly the same stop point.

---

# 19. Player Interaction

The player should also be able to interact with traffic lights.

However, the game is an arcade-style aggressive driving game, so the player must not be physically prevented from driving through a red light.

Instead, traffic lights should:

* influence NPC behaviour
* provide visual realism
* potentially affect gameplay systems later

The player may ignore red lights and drive through intersections.

NPC traffic must still react appropriately.

---

# 20. Handling Missing or Bad OSM Data

The implementation must be resilient to incomplete OSM data.

Examples:

### Case A: One traffic signal node

```text
       ●
───────+───────
       │
```

Interpretation:

```text
Likely signal-controlled intersection.
Analyse all approaches.
Generate missing signal groups.
```

### Case B: Signal tags only on one road

Do not assume only that road is controlled.

Analyse the entire intersection.

### Case C: No lane information

Generate a simplified lane model.

### Case D: Divided carriageways

Determine whether they belong to one logical intersection.

### Case E: Multiple nearby junction nodes

Cluster them when appropriate.

The system must favour:

```text
BELIEVABLE SIMULATION
```

over:

```text
PERFECT OSM RECONSTRUCTION
```

---

# 21. Debug Visualisation

Add optional debug rendering for:

* logical intersection boundaries
* clustered junction nodes
* approaches
* incoming direction vectors
* generated stop lines
* lane groups
* signal groups
* current traffic-light phases
* physical generated traffic lights

Example:

```text
LogicalIntersection #42

Approaches: 4

NORTH → GREEN
SOUTH → GREEN

EAST → RED
WEST → RED
```

For complex intersections, visualise:

```text
Approach IDs
Lane directions
Signal group assignments
Conflict areas
```

This is essential for debugging incorrectly interpreted OSM geometry.

---

# 22. Recommended Architecture

Use a hierarchy similar to:

```text
OSM Road Data
      │
      ▼
Road Network
      │
      ▼
Raw Junction Detection
      │
      ▼
Logical Intersection Clustering
      │
      ▼
LogicalIntersection
      │
      ├── IntersectionApproach
      │
      ├── StopLine
      │
      ├── SignalGroup
      │
      └── TrafficLight (render objects)
```

Traffic control:

```text
TrafficLightManager
        │
        ▼
LogicalIntersection
        │
        ▼
Signal Phases
        │
        ▼
NPC Traffic AI
```

---

# 23. Performance Requirements

Traffic-light geometry analysis may be relatively expensive, but it should not run continuously.

Perform intersection analysis:

* when map/OSM data is loaded
* when a new map area is generated
* cache the resulting logical intersections

Do NOT repeatedly rebuild intersection geometry every frame.

At runtime, traffic lights should only need lightweight updates:

```text
Timer
↓
Phase Change
↓
Update SignalGroups
```

NPC vehicles should query already-generated logical intersection data.

---

# 24. Implementation Priority

Implement the system in this order:

### Phase 1

Detect signal-controlled intersections from OSM data.

### Phase 2

Cluster nearby junction geometry into logical intersections.

### Phase 3

Detect incoming approaches.

### Phase 4

Generate logical stop lines.

### Phase 5

Generate signal groups for each approach.

### Phase 6

Implement basic North/South vs East/West phases.

### Phase 7

Integrate traffic lights with NPC AI.

### Phase 8

Generate physical traffic-light render objects.

### Phase 9

Add support for multi-lane intersections.

### Phase 10

Improve divided-road and traffic-island handling.

### Phase 11

Add debug visualisation and test against multiple real-world OSM intersections.

---

# Final Requirement

The final system must not depend on OpenStreetMap containing a complete physical representation of every traffic light.

The core rule is:

> **OSM traffic signal data indicates that traffic control may exist. The game's procedural intersection system is responsible for constructing a complete, believable traffic-light system for the entire logical intersection.**

The implementation should correctly handle:

* incomplete OSM traffic-light data
* one signal marker representing an entire intersection
* normal four-way intersections
* T-junctions
* multi-lane roads
* wide intersections
* divided roads
* central medians
* traffic islands
* pedestrian refuges
* multiple nearby OSM junction nodes

Prioritise:

1. Correct NPC traffic behaviour.
2. Believable traffic-light logic.
3. Robust handling of imperfect OSM data.
4. Good visual results.
5. Performance.

Do not attempt to perfectly reproduce every real-world traffic light installation. The goal is a procedurally generated, believable traffic control system suitable for a top-down arcade driving game.
