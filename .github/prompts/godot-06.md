# Task: Pygame → Godot rendering and feature parity audit

Work on the current branch:

`release/v0.16.0g-alpha`

This is an **audit task first**.

Do not implement a large number of missing features yet.

The purpose is to determine exactly which gameplay-relevant visual elements currently rendered by the Pygame client are still missing from the Godot client.

The final result must be a concrete migration plan that can be used for the next Godot development phases.

---

# 1. Compare the two clients systematically

Inspect the complete rendering paths of:

* the Pygame client
* the Godot client

Do not limit the audit to obvious UI files.

Trace the actual rendering/update pipeline.

For Pygame, inspect:

* world rendering
* roads
* buildings
* terrain/background
* vehicles
* NPCs
* taxi
* pedestrians
* trains
* railway infrastructure
* stations
* taxi stands
* passengers
* destinations
* weather
* effects
* lighting
* shadows
* map labels
* markers
* HUD
* notifications
* interaction indicators
* debugging overlays that may actually represent gameplay information

For Godot, identify the corresponding implementation for each.

---

# 2. Create a parity matrix

Create:

```text
docs/architecture/godot-pygame-rendering-parity.md
```

with a table similar to:

| Element     | Pygame | Godot   | Status         | Gameplay importance | Migration |
| ----------- | ------ | ------- | -------------- | ------------------- | --------- |
| roads       | yes    | yes     | parity         | high                | done      |
| buildings   | yes    | yes     | parity/partial | high                | ...       |
| taxi        | yes    | yes     | ...            | high                | ...       |
| NPC cars    | yes    | yes     | ...            | high                | ...       |
| pedestrians | yes    | partial | missing        | medium              | ...       |
| train       | yes    | yes     | ...            | high                | ...       |

Use the actual implementation rather than assumptions.

Possible status values:

* `complete`
* `partial`
* `missing`
* `different by design`
* `debug-only`
* `not applicable`

Do not use subjective quality rankings.

---

# 3. Identify every Pygame-rendered gameplay element

Trace the Pygame drawing code and build a complete inventory.

For each rendered element determine:

### World

* map background
* roads
* road markings
* buildings
* building details
* water
* parks/green areas
* bridges
* railways
* railway tracks
* stations
* taxi stands
* other map POIs

### Vehicles

* player's taxi
* NPC vehicles
* parked vehicles
* vehicle direction/orientation
* headlights
* brake lights
* indicators
* vehicle shadows
* vehicle state visualisation

### Pedestrians

* pedestrian body/sprite
* walking direction
* animation
* waiting passengers
* booked passengers
* passenger destination indicator
* passenger state indicators

### Trains

* train body
* individual carriages
* carriage colours
* restaurant carriage
* train direction
* train movement
* station/platform relationship
* train markers
* passenger-related train indicators

### Taxi/passenger interaction

* pickup indicators
* destination indicators
* booking indicators
* meet-and-greet indicators
* name card
* arrow/marker pointing at passenger
* taxi stop indicators
* fare/service indicators

### Weather and environment

* rain
* puddles
* snow if currently implemented
* weather transitions
* ambience-related visual effects
* day/night appearance
* lighting
* visibility/fog effects if present

### Gameplay feedback

* collision effects
* speed effects
* damage/state indicators
* anger meter
* customer state
* route/destination markers
* notifications
* warnings
* mission/job state

### HUD/UI

* speed
* current time
* money/fare
* taxi state
* passenger information
* current job
* navigation
* phone
* offers
* notifications
* interaction prompts

Do not assume that every item exists. Verify it in the code.

---

# 4. Distinguish rendering from simulation

An important part of this audit is identifying cases where Pygame currently renders something directly from simulation state that Godot does not yet receive from the server.

For every missing Godot element ask:

> Is the visual element missing only because Godot does not render it, or because the Godot protocol does not provide the necessary state?

Classify the cause as:

* `Godot rendering only`
* `missing protocol data`
* `missing shared simulation state`
* `Pygame-specific implementation`
* `unclear`

This distinction is critical.

Do not solve a missing visual element by duplicating simulation logic in Godot.

---

# 5. Check visual representations, not just existence

A feature can exist in both clients while still being substantially different.

For each element compare:

* position
* scale
* orientation
* visibility rules
* animation
* state transitions
* colour/state indicators
* layering/z-order
* camera behaviour
* distance/culling behaviour
* interaction feedback

Mark such cases as `partial` rather than `complete`.

Do not attempt to subjectively decide which client looks better.

Describe concrete implementation differences.

---

# 6. Camera and coordinate systems

Audit:

* world-to-screen transformation
* camera position
* camera zoom
* camera following
* entity rotation
* sprite orientation
* map scaling
* viewport resizing
* off-screen culling
* interpolation

Determine whether the two clients represent the same simulation coordinates consistently.

Pay particular attention to:

* taxi movement
* NPC vehicles
* pedestrians
* trains
* passenger markers

Do not modify the coordinate system as part of this audit.

---

# 7. Layering and visibility

Determine the rendering order in both clients.

Document important cases such as:

```text
map
→ roads
→ railway
→ buildings
→ vehicles
→ pedestrians
→ effects
→ markers
→ HUD
```

Use the actual implementation.

Identify any Godot cases where an element exists but is rendered behind an inappropriate layer.

---

# 8. Animation and interpolation

Compare how Pygame and Godot handle moving entities.

Inspect:

* taxi interpolation
* NPC interpolation
* train interpolation
* pedestrian movement
* marker movement
* animation frame updates

Identify cases where Pygame has visual animation that Godot currently lacks.

Do not implement them during this audit.

---

# 9. Performance-related rendering differences

Identify Pygame rendering features that would be expensive or inappropriate to copy directly to Godot.

For each candidate note:

* approximate object count
* update frequency
* whether it can be batched
* whether it needs GPU rendering
* whether it can be represented with a Godot node/sprite/particle system
* whether it should remain simulation-only

Do not optimize prematurely.

The purpose is to inform future implementation.

---

# 10. Godot-specific opportunities

Also identify cases where Godot can reproduce the same gameplay-visible result more appropriately than copying the Pygame implementation.

Examples could include:

* GPU particles instead of software effects
* shader-based weather
* sprite animation
* lighting
* camera effects
* batching
* instancing

These are recommendations for later implementation, not changes to make now.

---

# 11. Produce a migration backlog

Create:

```text
docs/architecture/godot-rendering-migration.md
```

Group missing/partial functionality into sensible phases.

For example:

## Phase A – gameplay-critical visuals

Elements required to understand and play the game.

## Phase B – world detail

Elements that make the world visually complete.

## Phase C – effects and polish

Particles, weather effects, lighting etc.

## Phase D – optional/debug

Debug overlays and development-only visualisations.

Do not assign subjective "best" rankings.

Explain why an item belongs in a phase using concrete dependencies or gameplay requirements.

---

# 12. Identify dependencies

For every migration item record dependencies such as:

```text
Passenger marker
  requires:
    passenger position
    passenger state
    booking state
```

or:

```text
Train station display
  requires:
    train identity
    station identity
    platform
    schedule state
```

This should make it clear whether the next task should modify:

* server protocol
* simulation state
* Godot renderer
* Godot UI
* shared code

---

# 13. Check current Godot implementation against the real game

Do not assume the current Godot code is complete because a class exists.

For each feature:

* find the actual render call
* find the state source
* determine whether it is visible during gameplay
* determine whether it is exercised by tests

A class that exists but is never instantiated should be marked as missing/incomplete rather than complete.

---

# 14. Tests

This is primarily an audit, so avoid writing a large test suite.

Add only small regression tests where they help prove an important finding.

At minimum verify that existing tests still pass:

```text
make godot-test
make godot-selftest
make audio-check
```

and the Python suite.

Do not modify tests simply to make them pass.

The existing three known BIN map-format failures remain outside this task.

---

# 15. Do not implement the migration yet

This is important.

Do not start implementing every missing rendering feature discovered by the audit.

The output of this task is:

1. the complete parity matrix
2. the list of missing/partial elements
3. the cause of each gap
4. dependencies
5. proposed implementation phases
6. relevant protocol requirements
7. performance considerations

After the audit, stop and report the findings.

Do not push or tag.

Do not make unrelated code changes.

---

# 16. Final report

Provide a concise summary containing:

### Rendering parity

* number of complete elements
* number of partial elements
* number of missing elements
* number of intentionally different elements

### Biggest gaps

List the concrete gameplay-visible elements currently missing from Godot.

### Protocol gaps

List elements that cannot be implemented correctly without additional server state.

### Rendering-only gaps

List elements that can be implemented entirely in Godot.

### Recommended next implementation phase

Describe the logical next group of work based on dependencies, without implementing it.

### Files changed

Prefer only:

```text
docs/architecture/godot-pygame-rendering-parity.md
docs/architecture/godot-rendering-migration.md
```

plus small test/documentation changes if genuinely necessary.

Do not modify the simulation, networking or rendering implementation during this audit unless a tiny change is required to prove a finding.


