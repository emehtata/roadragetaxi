Implement a **plugin-based Ambient Pedestrian Activity System** for Road Rage Taxi.

The goal is to make Residents behave like believable people in the city instead of simply walking from one point to another.

Residents should be able to spontaneously perform contextual activities such as sitting on benches, talking to each other, throwing rubbish into bins, playing games, using their phones, waiting at bus stops, exercising, and interacting with their environment.

The most important architectural requirement is:

> **The activity system must be genuinely extensible. New activities must be addable later as independent plugins without modifying the core pedestrian/activity management code.**

The initial activities should be implemented now, but the architecture must be designed so that many additional activities can be added later.

---

# 1. Inspect the existing architecture first

Before implementing anything, inspect the existing codebase thoroughly.

Identify:

* Resident implementation
* pedestrian implementation
* pedestrian state machine
* pedestrian navigation/pathfinding
* OSM feature representation
* spatial indexes
* buildings
* parks
* benches
* rubbish bins
* bus stops
* playgrounds
* roads and sidewalks
* vehicle passenger lifecycle
* existing Resident destinations
* existing pedestrian animations/states
* existing interaction systems
* time-of-day system
* weather system
* existing debug tools

Reuse existing systems wherever possible.

Do not create duplicate representations of OSM features or duplicate navigation systems.

Do not rewrite unrelated systems.

---

# 2. Create a generic activity framework

Create a generic activity framework around a concept such as:

```text
PedestrianActivity
ActivityContext
ActivityManager
ActivityRegistry
ActivityInstance
ActivityLocation
```

Use names that fit the existing architecture.

The core activity system should be responsible for:

* discovering activities
* registering plugins
* evaluating whether activities are possible
* scoring activities
* finding suitable locations
* starting activities
* managing activity state
* handling participants
* handling interruption
* finishing activities
* releasing locations
* enforcing cooldowns
* integrating with Residents

The core system must NOT contain activity-specific logic.

Avoid structures such as:

```python
if activity_type == "bench":
    ...
elif activity_type == "garbage":
    ...
elif activity_type == "conversation":
    ...
```

Instead, use a generic plugin interface.

Conceptually:

```python
activity.can_start(context)
activity.find_location(context)
activity.score(context)
activity.start(context)
activity.update(context, dt)
activity.finish(context)
```

The exact API should be adapted to the existing codebase.

---

# 3. Plugin architecture

Each activity should be an independent plugin.

For example:

```text
activities/
    base.py
    registry.py
    manager.py
    plugins/
        bench_sitting.py
        garbage_disposal.py
        conversation.py
        group_conversation.py
        ball_game.py
        playground.py
        phone_usage.py
        eating_drinking.py
        shop_window.py
        bus_stop_waiting.py
        photography.py
        exercise.py
        park_leisure.py
```

Follow the project's existing package structure rather than blindly creating this exact structure.

The important principle is separation.

The core system should not need to know which activities exist.

---

# 4. Automatic plugin discovery

Implement an activity registry capable of automatically discovering activity plugins.

Adding a new activity later should ideally require only:

1. Create a new plugin.
2. Implement the activity interface.
3. Put it in the appropriate plugin location.
4. Start the game.

Do not require editing a central list of activity types if automatic discovery is practical.

For example, a future developer should be able to create:

```text
fishing.py
```

and have the activity automatically become available.

If a plugin fails to load:

* log the error
* skip that plugin
* allow the game to continue running

One optional activity must never prevent the entire game from starting.

---

# 5. Activity plugin capabilities

The base activity interface should allow a plugin to describe:

* unique ID
* name
* description
* required OSM/environment features
* minimum participants
* maximum participants
* whether it can be performed alone
* whether it requires a group
* suitable age groups
* suitable Resident types
* preferred time of day
* weather restrictions
* minimum duration
* maximum duration
* cooldown
* base probability/weight
* required physical space
* preferred location types
* whether it can be interrupted
* whether it can occur indoors
* whether it can occur outdoors

Do not hardcode these properties in `ActivityManager`.

Each plugin should describe its own requirements.

---

# 6. Initial individual activities

Implement these as separate plugins.

## Sitting on a bench

Residents can:

* notice a nearby bench
* walk to it
* approach it naturally
* sit down
* remain seated for a random duration
* stand up
* continue their previous behaviour

Use actual OSM-derived benches if available.

Do not teleport the Resident onto the bench.

---

## Throwing rubbish into a bin

Residents carrying an appropriate item can:

* find a nearby rubbish bin
* walk to it
* approach it
* perform a throwing-away animation/action
* dispose of the item
* continue walking

Use actual OSM rubbish bins where available.

---

## Phone usage

Residents may stop or slow down and:

* take out/use their phone
* stand or sit while using it
* use it for a random duration
* put it away
* continue walking

Different Residents should have different probabilities.

---

## Eating/drinking

Where suitable locations exist, Residents may:

* sit in a suitable area
* eat or drink
* remain there for a while
* resume their normal behaviour

The implementation should be generic enough to later support cafés, restaurants, picnic areas, etc.

---

## Watching traffic

A Resident may stop at a suitable location and observe traffic.

For example:

* sidewalk near a busy road
* pedestrian viewpoint
* city centre
* bridge
* intersection

The Resident should actually face the relevant direction rather than simply stopping randomly.

---

## Shop-window watching

Near suitable commercial buildings:

* approach the building frontage
* stop at a reasonable distance
* face the shop/window
* remain there temporarily
* continue walking

Use actual OSM building/commercial data where available.

---

## Waiting at a bus stop

Residents may:

* identify an actual bus stop
* walk to the waiting area
* wait
* look around
* potentially leave after a random duration

Do not make every Resident wait indefinitely.

If the game already has public transport infrastructure, integrate with it rather than creating a parallel system.

---

## Photography

Residents may:

* identify a visually interesting nearby location
* walk there
* face the subject
* stop
* perform a photography action
* continue

Possible subjects can include:

* landmarks
* buildings
* parks
* traffic
* interesting streets
* other contextual objects

Do not implement a complicated camera system unless the game already has one.

---

## Exercise/jogging

Residents may:

* decide to exercise
* use appropriate pedestrian paths/areas
* jog for a while
* stop/rest
* continue their normal behaviour

The activity should use suitable locations where possible.

---

## Park/grass leisure

Residents may:

* find a suitable park/grass area
* walk there
* sit/rest/relax
* remain for a while
* leave

Use actual OSM landuse/leisure data.

---

# 7. Initial group activities

Group activities must use a **generic group participation system**.

Do not implement conversations and games as unrelated special cases.

The activity framework should support:

```text
minimum participants
maximum participants
joining rules
participant compatibility
group formation
group location
group lifecycle
participant departure
```

---

## Two-person conversation

Two Residents may:

1. notice each other
2. decide to talk
3. approach each other
4. face each other
5. remain together
6. talk for a random duration
7. leave independently

Do not teleport either Resident.

---

## Small-group conversation

Support groups of approximately 3–5 Residents.

Residents should:

* gather naturally
* face toward the group
* remain together
* leave at different times

The group system must be generic enough to support future activities.

---

## Children's ball game

Children may:

* find suitable open space
* gather into a small group
* play with a ball
* move around the area
* continue for a random duration
* eventually leave

Do not implement this as a special hardcoded child state in Resident.

Implement it as an activity plugin using the generic activity system.

---

## Playground activity

Children may:

* identify an actual playground
* walk there
* enter the appropriate usable area
* play
* remain for a while
* leave

Use actual OSM playground data where available.

---

# 8. Generic activity lifecycle

Every activity should use a common lifecycle.

For example:

```text
WALKING
   ↓
CONSIDER_ACTIVITY
   ↓
SELECT_ACTIVITY
   ↓
FIND_LOCATION
   ↓
RESERVE_LOCATION
   ↓
WALK_TO_LOCATION
   ↓
APPROACH
   ↓
PERFORM_ACTIVITY
   ↓
FINISH
   ↓
RELEASE_LOCATION
   ↓
RESUME_NORMAL_BEHAVIOUR
```

Do not teleport Residents.

Residents must physically navigate to activity locations using the existing pedestrian navigation system.

Activities should be interruptible when appropriate.

Possible interruptions:

* Resident needs to cross a road
* Resident's destination changes
* Resident becomes a vehicle passenger
* vehicle is waiting for the Resident
* activity location becomes unavailable
* simulation event requires the Resident to leave

The activity must cleanly release any reservations/resources when interrupted.

---

# 9. Activity selection

Residents should not perform activities randomly without context.

Use a generic scoring system.

Conceptually:

```text
activity score =
    base weight
    + location suitability
    + age suitability
    + time suitability
    + weather suitability
    + personality/preference modifiers
    + social availability
    - distance penalty
    - cooldown penalty
    - repetition penalty
```

The exact implementation should fit the existing Resident architecture.

Each plugin should be able to influence its own suitability.

The ActivityManager should remain generic.

Do not implement activity selection as a large collection of hardcoded conditions.

---

# 10. Resident variation

Residents should behave differently.

If the existing Resident system supports personality/preferences, integrate with it.

If it does not, create lightweight extension points rather than building an unnecessarily complex personality system.

Potential future properties:

```text
socialness
exercise_preference
outdoor_preference
phone_usage
child_play_preference
activity_frequency
```

The same activity should therefore not have exactly the same probability for every Resident.

Avoid making every Resident perform activities at the same intervals.

---

# 11. Time of day

Activities should be affected by the simulation clock.

Examples:

* children playing outdoors more during daytime
* jogging more likely in suitable daylight/evening periods
* shop-window watching during shop-opening hours
* bus-stop waiting based on transport schedules if available
* park activities primarily during suitable daytime periods
* different social activity frequencies during evening

These rules belong to the plugins.

Do not put activity-specific time rules into the core ActivityManager.

---

# 12. Weather integration

Integrate with the existing weather system.

Examples:

* benches less attractive during rain
* outdoor conversations less likely during heavy rain
* children's outdoor activities reduced during bad weather
* jogging probability affected by weather
* indoor activities potentially becoming more attractive

Do not hardcode weather logic in the manager.

Each plugin should decide how weather affects its suitability.

---

# 13. Cooldowns and anti-repetition

Prevent unrealistic behaviour.

For example:

```text
sit on bench
walk 5 metres
sit on another bench
walk 5 metres
sit again
```

Support generic:

* per-activity cooldown
* global activity cooldown
* repetition penalty
* minimum walking distance between activities
* minimum time between activities

The exact implementation should fit the existing Resident state system.

---

# 14. Location system

Activities should declare their location requirements.

Examples:

```text
BenchSitting
    requires bench

GarbageDisposal
    requires waste_bin

Playground
    requires playground

BallGame
    requires open space

BusStopWaiting
    requires bus_stop

ShopWindowWatching
    requires commercial frontage

ParkLeisure
    requires suitable park/grass area
```

Use existing OSM data and spatial indexes.

Do not create duplicate location databases.

If a suitable OSM feature is not currently represented by the game, first inspect whether the feature can be added cleanly to the existing OSM pipeline.

Do not invent fake map objects merely to make an activity work.

---

# 15. Physical validity

Activities must respect the physical world.

Residents must:

* stay on walkable surfaces
* avoid buildings
* avoid roads unless crossing
* avoid curbs where appropriate
* use actual pedestrian navigation
* avoid walking through vehicles
* approach activity locations from valid directions
* maintain reasonable distances from other entities

Group activities must also avoid participants overlapping unrealistically.

For example, a conversation group should form a plausible small circle rather than stacking multiple Residents on the same coordinates.

---

# 16. Integration with NPC vehicle passengers

Integrate the activity system with the existing Resident vehicle lifecycle.

For example:

```text
NPC vehicle arrives
        ↓
Passengers exit
        ↓
Residents become pedestrians
        ↓
Residents perform errands/activities
        ↓
Residents eventually return
        ↓
Residents board the same vehicle
        ↓
Vehicle continues
```

Residents must retain:

* vehicle association
* destination
* household/group information
* return-to-vehicle requirement
* current simulation state

The activity system must not accidentally make a Resident permanently abandon a vehicle.

If a Resident has a pending vehicle return requirement, activity selection should take this into account.

A Resident close to their vehicle return deadline should prefer short activities or return directly.

---

# 17. Future plugin examples

The architecture should make future activities possible without modifying the core.

Examples:

```text
Fishing
Street musician
Feeding birds
Reading newspaper
Skateboarding
Waiting for a taxi
Shopping
Carrying groceries
Walking a baby
Walking a dog
Playing basketball
Playing football
Playing frisbee
Outdoor café
Street performance
Watching a street performer
Queuing
Meeting friends
Taking children to playground
Cycling
Pushing a bicycle
Resting at a bus stop
```

These do NOT all need to be implemented now.

The architecture simply needs to support them.

For example, a future developer should be able to add:

```text
fishing.py
```

with something conceptually like:

```python
class FishingActivity(PedestrianActivity):
    id = "fishing"

    def can_start(self, context):
        ...

    def find_location(self, context):
        ...

    def score(self, context):
        ...

    def start(self, context):
        ...

    def update(self, context, dt):
        ...

    def finish(self, context):
        ...
```

without modifying the ActivityManager.

---

# 18. Debugging tools

Integrate activity debugging with the existing debug system.

Show:

* loaded activity plugins
* activity ID
* current activity
* activity state
* activity location
* participants
* remaining duration
* activity score
* why an activity was rejected
* cooldown status

Provide a way to force an activity for testing.

For example, conceptually:

```text
/activity bench_sitting
/activity conversation
/activity playground
```

Use the project's existing debug command/input conventions.

Add optional world visualization for:

* activity locations
* reserved locations
* group members
* navigation target
* activity radius
* current activity state

---

# 19. Performance

The system must work with potentially large numbers of Residents.

Do not evaluate every possible activity and every possible location every frame.

Use:

* spatial indexes
* nearby-location queries
* cached locations
* decision intervals
* cooldowns
* distance filtering
* event-driven state changes where appropriate

Activity decisions should happen periodically, not every render frame.

Do not perform expensive OSM searches in the render loop.

Avoid allocations and expensive pathfinding when an activity is only being considered.

The activity system must not introduce periodic frame stutters.

This is especially important because Road Rage Taxi already has a large number of dynamic entities.

---

# 20. Testing

Add tests for:

### Plugin system

* plugin discovery
* plugin registration
* duplicate plugin IDs
* broken plugin handling
* plugin isolation
* adding a new plugin without modifying core code

### Activity selection

* scoring
* requirements
* time restrictions
* weather restrictions
* distance
* cooldowns
* repetition prevention

### Lifecycle

* starting
* walking to activity
* performing
* finishing
* interruption
* resource/location release

### Group activities

* group creation
* joining
* leaving
* minimum participants
* maximum participants
* participant compatibility
* independent departure

### Resident integration

* activity while walking
* activity interruption
* vehicle passenger integration
* returning to vehicle

### Performance

Add reasonable tests/benchmarks if the repository has an existing performance-testing approach.

---

# 21. Documentation

Document the activity plugin API.

Include a concise developer guide explaining:

1. How to create a plugin.
2. How to define location requirements.
3. How to score the activity.
4. How to start/end the activity.
5. How to use group activities.
6. How to interact with Resident state.
7. How to access time/weather context.
8. How to test a plugin.
9. How automatic discovery works.

The documentation should include a complete minimal example of a new activity plugin.

---

# 22. Important architectural constraint

Do NOT merely create an abstraction layer around hardcoded activities.

The goal is a genuinely extensible plugin architecture.

The core system should know:

> "There are activities available, and these activities implement the activity interface."

It should NOT need to know:

> "Bench sitting, garbage disposal, conversation, playground, etc. are special cases."

Individual plugins own their own behaviour.

The ActivityManager owns orchestration.

---

# 23. Implementation strategy

Implement incrementally:

### Phase 1

Create the generic activity interfaces, registry and lifecycle.

### Phase 2

Implement individual activity plugins:

* bench sitting
* garbage disposal
* phone usage
* eating/drinking
* traffic watching
* shop-window watching
* bus-stop waiting
* photography
* exercise
* park leisure

### Phase 3

Implement generic group activities.

### Phase 4

Implement:

* two-person conversation
* small-group conversation
* children's ball game
* playground

### Phase 5

Integrate with Resident and vehicle passenger lifecycle.

### Phase 6

Add debugging and visualization.

### Phase 7

Add tests and plugin documentation.

At each phase, preserve existing game behaviour.

---

# 24. Acceptance criteria

The implementation is complete when:

1. Residents naturally perform contextual activities while walking around the city.
2. Activities use real OSM/environment features where appropriate.
3. Residents physically navigate to activity locations.
4. Activities have a consistent lifecycle.
5. Group activities use a generic participant system.
6. Time and weather influence activities.
7. Residents do not repeatedly perform the same activity unrealistically.
8. Activities integrate correctly with vehicle passengers.
9. The system is performant with large numbers of Residents.
10. Activity behaviour is visible through debugging tools.
11. Individual activities are implemented as independent plugins.
12. The core ActivityManager contains no activity-specific branching.
13. A new activity can be added without modifying the core activity system.
14. A broken optional plugin cannot prevent the game from starting.
15. The plugin API is documented with a working example.

The final result should feel like a **living city simulation**, where Residents have small believable reasons to stop, interact, socialize, rest, play and use their environment, while keeping the architecture open for dozens of new activities to be added later.
