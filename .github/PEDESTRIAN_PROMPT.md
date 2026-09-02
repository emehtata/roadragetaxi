# City NPC Pedestrian System

Implement a scalable **NPC pedestrian system** for **The Road Rage Trip**.

The game is a top-down Python/Pygame game using OpenStreetMap data for the city environment.

NPC pedestrians should populate the city and move around it in a believable way. They should use suitable pedestrian routes derived from the OSM map data, obey pedestrian traffic lights, and dynamically spawn and despawn without noticeable popping.

The system must be designed so that more advanced NPC behaviour can be added later without rewriting the core architecture.

---

# 1. Inspect the Existing Project First

Before making any changes:

1. Inspect the existing project structure.
2. Determine:

   * how the game loop works
   * how the camera works
   * how world coordinates are represented
   * how OSM data is loaded
   * how buildings are represented
   * how roads, sidewalks and crossings are represented
   * how sprites and animations are currently handled
   * how entities are spawned and removed
3. Look for any existing:

   * NPC systems
   * entity managers
   * pathfinding
   * collision systems
   * spatial partitioning
   * map/OSM abstractions

Reuse existing systems wherever practical.

Do not create a completely separate world/entity architecture if suitable infrastructure already exists.

---

# 2. Pedestrian System Architecture

Create a central:

```python
PedestrianManager
```

responsible for:

* spawning pedestrians
* despawning pedestrians
* maintaining active pedestrians
* selecting pedestrian routes
* selecting spawn points
* selecting destinations
* managing pedestrian density
* managing pedestrian LOD
* updating pedestrians at appropriate frequencies

A possible architecture is:

```text
OSM Data
   │
   ├── Buildings
   ├── Roads
   ├── Sidewalks
   ├── Crossings
   └── Traffic Signals
          │
          ▼
    Pedestrian Network
          │
          ▼
   PedestrianManager
          │
          ▼
      Pedestrian
          │
          ├── Route
          ├── State
          ├── Animation
          └── Destination
```

Adapt this to the existing codebase.

---

# 3. Pedestrian Entity

Create a lightweight `Pedestrian` entity.

At minimum it should contain:

```text
position
velocity
direction
speed
route
current_route_segment
destination
state
animation_state
```

Use a state machine so additional behaviour can be added later.

Initial states should include something similar to:

```text
WALKING
WAITING_AT_LIGHT
WAITING
ENTERING_BUILDING
EXITING_BUILDING
TURNING
DESPAWNING
```

A `CRASHED` or `PANIC` state may be added later, but do not implement unnecessary advanced behaviour yet.

---

# 4. Pedestrian Spawn System

Pedestrians must be able to spawn in two fundamentally different ways.

## A. Building Door Spawn

Pedestrians can appear by walking out of building entrances.

The preferred sequence is:

```text
Building
   │
   ▼
Door
   │
   ▼
Pedestrian spawns
   │
   ▼
Walks onto pedestrian network
```

The pedestrian should not simply pop into existence in the middle of a sidewalk.

Instead:

1. Select a valid building entrance.
2. Create the pedestrian slightly inside or directly at the doorway.
3. Play an exit/walking transition if the animation system supports it.
4. Move the pedestrian from the doorway onto the pedestrian route.
5. Continue walking toward the destination.

If OSM contains building entrance information, use it.

---

# 5. Off-Screen Spawning

Pedestrians may also spawn outside the current camera view.

This is necessary to maintain a continuous population without visible spawning.

Preferred spawn locations:

* sidewalks outside the camera
* pedestrian paths outside the camera
* crossings outside the camera
* building entrances outside the camera
* valid pedestrian network nodes outside the camera

Avoid spawning pedestrians:

* directly in front of the player
* inside buildings unless intentionally entering/exiting
* in roads
* inside obstacles
* inside the visible camera area

Whenever possible, spawn pedestrians outside the camera's current view and let them naturally enter the visible area.

---

# 6. Building Door Despawn

Pedestrians should also be able to disappear naturally by entering buildings.

Example:

```text
Pedestrian
    ↓
Sidewalk
    ↓
Building entrance
    ↓
Door
    ↓
DESPAWN
```

When a pedestrian's destination is a building:

1. Walk to the entrance.
2. Align with the entrance.
3. Enter the building.
4. Transition into `DESPAWNING`.
5. Remove the pedestrian from the active world.

The pedestrian should not simply disappear several meters away from the building.

The disappearance should occur at the doorway.

---

# 7. Off-Screen Despawn

Pedestrians may also despawn outside the camera view.

This should work similarly to NPC vehicle despawning.

Example:

```text
                 DESPAWN
                    ↓

       ┌─────────────────────┐
       │                     │
       │      CAMERA         │
       │                     │
       │        PLAYER       │
       │                     │
       └─────────────────────┘

                    ↑
                 SPAWN
```

Do not despawn pedestrians immediately when they leave the visible screen.

Use a configurable outer radius/boundary.

For example:

```text
VISIBLE AREA
      +
ACTIVE AREA
      +
DESPAWN AREA
```

This prevents pedestrians from popping in and out near the camera edge.

---

# 8. Pedestrian Network

Pedestrians must not simply use the road network used by cars.

Create or derive a separate:

```text
PedestrianNetwork
```

from suitable OSM features.

Prefer:

* sidewalks
* footways
* pedestrian paths
* crossings
* pedestrian areas
* plazas
* suitable paths around buildings

Use OSM tags where available.

Potentially useful OSM features include:

```text
highway=footway
highway=path
highway=pedestrian
highway=steps
footway=sidewalk
highway=crossing
```

Adapt this to the actual OSM data already used by the project.

---

# 9. Route Selection

Each pedestrian should have a destination and route.

For example:

```text
Building A
    ↓
Sidewalk
    ↓
Crossing
    ↓
Sidewalk
    ↓
Building B
```

The pedestrian route should be calculated when needed rather than every frame.

Possible triggers:

* spawn
* destination change
* route completion
* blocked/invalid route

Do not perform expensive pathfinding continuously.

---

# 10. Suitable OSM Routes

The pedestrian system should prefer routes that are logically suitable for walking.

Prioritise:

```text
sidewalk
footway
pedestrian path
crosswalk
pedestrian area
```

Avoid:

```text
motorway
trunk
primary road
car-only road
```

unless the OSM geometry explicitly indicates that pedestrians are permitted there.

When OSM pedestrian data is incomplete, use reasonable fallback rules based on the road network.

The goal is believable gameplay behaviour rather than perfect real-world pedestrian routing.

---

# 11. Crossing Roads

When a pedestrian route crosses a road, the pedestrian should use an appropriate crossing where available.

Prefer:

```text
OSM marked crossing
        ↓
Pedestrian crosses road
```

If there is no mapped crossing, the system may later support procedural crossing generation.

For the initial implementation, prefer mapped crossings and safe fallback behaviour.

Do not allow pedestrians to randomly walk through the middle of major roads when a mapped crossing exists nearby.

---

# 12. Pedestrian Traffic Lights

Pedestrians must obey pedestrian traffic lights where available.

The pedestrian system should reuse the logical traffic-light infrastructure created for vehicle traffic where possible.

Do not make pedestrian AI inspect rendered traffic-light sprites.

Instead, query the logical intersection/signal system.

For example:

```python
can_cross = pedestrian_signal_manager.can_cross(
    crossing,
    pedestrian
)
```

Pedestrian behaviour:

```text
GREEN:
Cross

RED:
Wait before crossing
```

---

# 13. Vehicle Traffic Interaction

Pedestrians should not blindly walk into moving traffic.

Initially, implement simple safety behaviour.

Before crossing:

```text
Check:
- pedestrian signal
- crossing state
- nearby vehicles
- vehicle speed
```

If the crossing is unsafe:

```text
WAIT
```

If safe:

```text
CROSS
```

The player may still hit pedestrians because this is an arcade driving game, but pedestrians should behave sensibly during normal simulation.

Do not build an overly complex pedestrian avoidance system yet.

Design the code so more advanced avoidance can be added later.

---

# 14. Pedestrian States at Crossings

A pedestrian approaching a red pedestrian signal should transition to:

```text
WALKING
   ↓
APPROACHING_CROSSING
   ↓
WAITING_AT_LIGHT
   ↓
CROSSING
   ↓
WALKING
```

Do not stop the pedestrian randomly in the middle of the sidewalk.

The waiting position should be generated near the crossing's logical waiting/stop line.

---

# 15. Pedestrian Movement

Pedestrians should move smoothly along their route.

Avoid movement that looks like:

```text
Node A
 ↓
instant rotation
 ↓
Node B
 ↓
instant rotation
```

Instead:

* calculate movement direction from the route
* smoothly rotate/change direction
* interpolate between route points where necessary
* maintain a relatively consistent walking speed

Pedestrians should look like they are actually walking along sidewalks rather than teleporting between graph nodes.

---

# 16. Pedestrian Animation

The pedestrian sprite is viewed **strictly from above**.

This is important.

The character should NOT be rendered as a side-view or isometric character.

The intended visual representation is:

```text
       HEAD
        ●
      /   \
     / BODY\
    /       \
   ARM     ARM
     \     /
      \   /
       LEGS
```

More precisely, from directly above:

* the **head is centered**
* the head is slightly forward in the direction of travel
* the torso is underneath/behind the head
* arms extend from the sides of the torso
* arms swing while walking
* legs are visible slightly underneath the body
* the legs move/swing during the walking animation

The camera/view direction must remain top-down.

The character should not show a normal front-facing human body.

---

# 17. Walking Animation

Implement the pedestrian animation as a small number of states/frames.

At minimum:

```text
IDLE
WALKING
```

The walking animation should communicate movement from the top-down view.

During walking:

* arms alternate their swing
* legs alternate
* body may have a very subtle movement
* head remains approximately centered over the body
* the forward offset of the head follows the walking direction

Example concept:

```text
Frame 1:

      HEAD
        ●
       BODY
      /   \
     ARM ARM
       ||
      LEG LEG


Frame 2:

      HEAD
        ●
       BODY
     \     /
      ARM ARM
        \ /
       LEGS
```

Do not exaggerate the animation.

It should remain readable at the game's normal zoom level.

---

# 18. Directional Animation

Because the character is viewed from above, support directional movement where practical.

At minimum support:

```text
NORTH
SOUTH
EAST
WEST
```

Diagonal movement can either:

* use the closest cardinal direction
* or interpolate between directional animations

Do not create unnecessary animation complexity if the current sprite system does not require it.

The animation system should be designed so additional directional frames can be added later.

---

# 19. Sprite Architecture

Keep pedestrian rendering separate from pedestrian AI.

For example:

```text
Pedestrian
    │
    ├── AI / movement
    │
    └── PedestrianRenderer
             │
             └── Animation
```

Do not put all animation logic directly into the pathfinding or traffic code.

The sprite system should make it possible to later add:

* different genders
* different clothing
* different hair
* different body types
* different walking animations
* random pedestrian appearances
* special NPC types

without changing the movement system.

---

# 20. Pedestrian Variety

Initially implement a basic generic pedestrian.

However, design the data structure so that later we can have:

```text
PedestrianAppearance
    ├── body
    ├── head
    ├── hair
    ├── clothing
    ├── arms
    └── legs
```

This is intentional because pedestrian sprites may later be constructed from interchangeable components/sprite atlas elements.

Do not hard-code appearance data into the AI class.

---

# 21. Pedestrian Density

`PedestrianManager` should support configurable population density.

For example:

```python
pedestrian_density = 0.5
```

This should influence:

* spawn frequency
* maximum active pedestrians
* building spawn frequency
* off-screen spawn frequency

The maximum number of active pedestrians should be configurable.

---

# 22. LOD / Performance

Use the same general philosophy as NPC traffic.

Pedestrians close to the player receive full simulation.

Pedestrians farther away receive simplified simulation.

Example:

```text
LOD 0:
Full movement
Full animation
Collision checks

LOD 1:
Simplified movement
Reduced animation updates

LOD 2:
Very cheap route simulation
No detailed collision
```

Update frequencies should be time-based rather than frame-based.

Do not update hundreds of distant pedestrians at full 60 FPS if there is no gameplay reason to do so.

---

# 23. Spatial Hash Integration

Reuse the existing `SpatialHash` from the traffic system if appropriate.

Pedestrians should be registered in the spatial partitioning system so that nearby objects can be found efficiently.

This will later allow:

* pedestrian avoidance
* player/pedestrian collision
* vehicle/pedestrian interaction
* NPC awareness
* crowd behaviour

Do not create a second redundant spatial partitioning system if the existing one can support multiple entity types.

---

# 24. Spawn/Despawn Consistency

The system should avoid obvious population changes.

For example:

```text
Player enters city
        ↓
Buildings gradually produce pedestrians
        ↓
Pedestrians appear from doors / outside camera
        ↓
Pedestrians walk around
        ↓
Some enter buildings
        ↓
Others leave the active area
```

The city should feel continuously populated rather than as a collection of NPCs that randomly appear and disappear.

---

# 25. Future Extensibility

Do not implement these features yet, but design the system so they can be added later:

* NPC daily schedules
* home/work destinations
* shops
* restaurants
* parks
* public transport
* random destinations
* groups of pedestrians
* conversations
* waiting at bus stops
* panic/flee behaviour
* reactions to crashes
* reactions to the player's aggressive driving
* pedestrian personality
* different walking speeds
* children/elderly pedestrians
* pets
* weather-dependent behaviour

The current implementation should establish a clean foundation for these future systems.

---

# 26. Debug Tools

Add optional debug visualisation for:

* pedestrian network
* pedestrian route
* current destination
* current route node
* pedestrian state
* crossing state
* pedestrian traffic-light state
* spawn points
* building entrances
* despawn zones

For example:

```text
NPC #42

State: WALKING
Speed: 1.4 m/s

Destination: Building #183
Route node: 17 / 34

Crossing: NONE
```

For pedestrians waiting at a traffic light:

```text
NPC #17

State: WAITING_AT_LIGHT
Crossing: #12
Signal: RED
```

Debug rendering must be easy to disable.

---

# 27. Implementation Order

Implement the system in phases.

### Phase 1

Inspect the existing project and identify reusable systems.

### Phase 2

Create or integrate the `PedestrianNetwork`.

### Phase 3

Detect/use mapped building entrances and pedestrian spawn points.

### Phase 4

Implement the `Pedestrian` entity.

### Phase 5

Implement basic route following.

### Phase 6

Implement `PedestrianManager`.

### Phase 7

Implement spawning at mapped building doors.

### Phase 8

Implement off-screen spawning.

### Phase 9

Implement building-door despawning.

### Phase 10

Implement off-screen despawning.

### Phase 11

Implement pedestrian crossing behaviour.

### Phase 12

Integrate pedestrian traffic-light behaviour.

### Phase 13

Implement the top-down walking animation.

### Phase 14

Implement LOD and performance optimisation.

### Phase 15

Implement debug visualisation.

---

# Final Requirements

The pedestrian system should produce a city that feels populated without overwhelming the CPU.

Pedestrians should be able to:

```text
spawn at building doors
        OR
spawn outside the camera
        ↓
follow suitable OSM pedestrian routes
        ↓
approach crossings
        ↓
obey pedestrian traffic lights
        ↓
cross roads
        ↓
continue toward destination
        ↓
enter a building
        OR
leave the active area
        ↓
despawn
```

The pedestrian character must be rendered from a **true top-down view**.

The visible character consists primarily of:

```text
head
  ↓
torso
  ↓
arms
  ↓
legs
```

with:

* the head centered and slightly forward relative to the walking direction
* a visible torso
* swinging arms
* partially visible legs beneath the body
* a readable walking animation

Do not use a conventional side-view human sprite.

The architecture must separate:

```text
Pedestrian AI
Pedestrian routing
Pedestrian spawning
Pedestrian rendering
Pedestrian animation
Pedestrian traffic-light interaction
```

so that additional NPC behaviour can be added later without rewriting the core system.

Most importantly, **inspect the existing codebase first and integrate this system with the existing OSM, entity, camera, collision, rendering, and traffic infrastructure rather than creating redundant parallel systems.**
