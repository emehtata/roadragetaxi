# Godot/Pygame Parity Audit 2

## Objective

Perform a complete second parity audit of the current Godot implementation against the existing Pygame implementation of Road Rage Trip / Road Rage Taxi.

The previous parity audit is now outdated because substantial Godot functionality has been implemented since then.

This task is **AUDIT ONLY**.

Do not implement, refactor, optimize, or redesign any gameplay or rendering functionality.

The purpose of this audit is to establish a new authoritative baseline answering:

> What functionality still exists in the Pygame version that is missing, incomplete, or materially different in the current Godot version?

The result will be used to plan the next implementation phases.

---

# 1. Current architecture constraints

Respect these decisions throughout the audit:

* Godot 1.x is a 2D/top-down game with a lightweight 3D building rendering layer.
* The current 3D building layer is intentional and must not be classified as an incomplete migration merely because Pygame used a different building renderer.
* Do not recommend reverting the building renderer to Pygame-style rendering.
* Do not propose a full-3D architecture.
* Do not introduce anything intended for the future Godot 2.0/full-3D direction.
* Do not reintroduce the obsolete BIN map architecture.
* Pygame is the reference implementation for feature parity.
* Python/server simulation remains authoritative for game state.
* Godot is responsible for presentation/client-side interaction.
* The current vehicle movement and camera behaviour are stable. Do not modify them.
* Do not change the current rendering architecture during this audit.

---

# 2. Inspect the actual current repository

Do not rely on:

* the previous parity report,
* old task descriptions,
* historical commit messages,
* assumptions about what has or has not been implemented.

Inspect the current code.

Determine:

* current branch
* current commit
* current Godot implementation
* current Python/server implementation
* current protocol
* current rendering systems
* current UI/HUD
* current entities
* current world/environment systems
* current audio systems
* current tests

The audit must describe the repository as it exists now.

---

# 3. Pygame feature inventory

Systematically inspect the Pygame implementation and create an inventory of all player-visible and gameplay-relevant functionality.

At minimum inspect:

## World rendering

* roads
* road surfaces
* road markings
* intersections
* traffic lights
* bridges
* buildings
* building shapes
* building heights
* pitched roofs
* building windows
* night windows
* road names
* speed limits
* signs
* water
* puddles
* rain
* snow
* weather effects
* roadworks
* construction objects
* fuel stations
* taxi stands
* other environmental objects

## Player vehicle

* vehicle rendering
* vehicle dimensions
* vehicle colours
* headlights
* tail lights
* brake lights
* turn signals
* crash effects
* smoke
* exhaust
* orientation
* turning appearance
* special vehicle states
* fuel
* rage/anger
* water/in-water state
* nausea
* trip distance
* odometer
* all related HUD information

## NPC vehicles

* vehicle rendering
* vehicle types
* colours
* lights
* brake lights
* turn signals
* crashes
* smoke/effects
* police vehicles
* distant vehicles
* vehicles whose drivers have exited
* other visible traffic states

## Pedestrians

* rendering
* direction
* walking animation
* fallen state
* indoor state
* angry/cursing state
* passenger state
* pickup/drop-off behaviour
* other visible pedestrian states

## Taxi gameplay

Inspect the complete taxi gameplay implementation:

* normal customer pickup
* destination
* drop-off
* customer name
* customer address
* destination marker
* destination arrow
* customer arrow
* distance
* booked passengers
* pre-booking
* meet-and-greet
* meet-and-greet surcharge
* customer walking to taxi stand
* taxi stand queue
* passenger entering taxi
* passenger exiting taxi
* fare
* starting fare
* service text
* customer state transitions
* taxi stand behaviour

Do not only check whether the Python classes exist.

Verify whether the player can actually see/use the corresponding functionality in Godot.

## Trains

Inspect:

* train rendering
* locomotives
* carriages
* carriage colours
* restaurant stripe
* train composition
* train length
* train direction
* train positioning
* draw ordering
* station/platform behaviour
* timetable behaviour
* passenger behaviour
* train-related UI

## Aircraft

Inspect all aircraft functionality currently present in Pygame:

* aircraft rendering
* aircraft movement
* airports
* nearest-airport logic
* weekly schedules
* cached schedules
* airport passenger behaviour
* taxi demand related to aircraft
* visible aircraft state

Clearly distinguish existing server functionality from missing Godot presentation.

## Navigation

Inspect:

* route calculation
* route state
* navigation line
* route rendering
* destination
* destination distance
* turn information
* compass
* off-screen arrows
* navigation markers

If Python already calculates a route but Godot does not display it, classify this as a parity gap.

## HUD/UI

Compare every normal player-facing Pygame UI element with Godot:

* speed
* fuel
* rage
* trip
* odometer
* nausea
* money
* fare
* customer
* address
* destination
* game time
* weather
* navigation
* vehicle state
* interaction prompts
* notifications
* status indicators

Exclude purely developer/debug UI unless it is part of normal gameplay.

## Time and weather

Inspect:

* game clock
* accelerated game time
* day/night
* lighting changes
* rain
* wet roads
* puddles
* drying
* snow
* weather transitions
* other time-dependent effects

## Audio

Compare the actual player-facing audio functionality.

Check:

* engine sounds
* horns
* crashes
* rain
* weather ambience
* trains
* aircraft
* UI sounds
* taxi/customer sounds
* announcements
* music
* environmental sounds
* other gameplay sounds

Distinguish:

1. implemented in Godot with equivalent/new audio,
2. implemented but currently silent,
3. completely missing.

Do not consider replacing old audio assets with newer AI-generated assets a parity problem if the functionality itself exists.

---

# 4. Godot verification

For every Pygame feature, determine whether the current Godot implementation actually provides it.

Do not classify a feature as complete merely because:

* a similarly named class exists,
* a protocol field exists,
* a server-side implementation exists,
* a TODO comment exists,
* code appears to support it.

Verify the actual implementation path:

Pygame feature
→ Python/server state
→ protocol
→ Godot state
→ Godot rendering/UI/audio
→ player-visible result

If any meaningful part is missing, classify the feature appropriately.

---

# 5. Classification

Every feature must receive exactly one status:

### COMPLETE

Equivalent player-visible functionality exists.

### PARTIAL

The feature exists but meaningful functionality is still missing.

### MISSING

The feature exists in Pygame but has no usable Godot equivalent.

### DIFFERENT BY DESIGN

Godot intentionally implements the feature differently and the difference is acceptable.

### SERVER/PROTOCOL GAP

Required simulation or protocol state does not exist.

### GODOT RENDERING GAP

Required state exists but Godot does not render it correctly.

### GODOT UI GAP

Required state exists but Godot does not present it in UI.

### AUDIO GAP

The gameplay feature exists but the corresponding Godot audio functionality is missing.

### PYGAME-ONLY / OBSOLETE

The feature should not be ported because it belongs to obsolete Pygame architecture or has intentionally been superseded.

Do not use "MISSING" as a generic category.

---

# 6. Source tracing

For every PARTIAL or GAP item, identify the relevant implementation locations.

Record:

* Pygame source file/function/class
* Godot source file/function/class, if present
* Python/server source, if relevant
* protocol message/field, if relevant
* current state/data source
* exact missing functionality

Do not invent file names or locations.

Use actual repository paths.

---

# 7. Re-check historical gaps

Explicitly revisit the major gaps from the previous parity audit:

* meet-and-greet
* booked passenger state
* customer arrows
* day/night
* traffic lights
* taxi stands
* fuel stations
* roadworks
* road names
* speed limits
* navigation route
* fuel gauge
* vehicle visual states
* pedestrian states
* train rendering
* aircraft
* audio
* protocol/state gaps

Do not copy their old status.

Verify each one against the current implementation.

---

# 8. Rendering parity

Perform a separate visual rendering audit.

Inspect:

* world rendering layers
* road rendering
* environmental objects
* buildings
* 3D building layer
* windows
* night rendering
* vehicles
* pedestrians
* trains
* aircraft
* markers
* arrows
* navigation
* HUD
* render ordering
* occlusion
* camera
* zoom
* off-screen indicators

The current Godot 3D building layer is intentional.

Do not classify the architectural difference itself as a parity problem.

Only identify actual player-visible differences.

---

# 9. Gameplay parity

Perform a separate gameplay audit.

Look for Pygame behaviour that exists independently of rendering, including:

* taxi lifecycle
* customer lifecycle
* booked trips
* meet-and-greet
* fares
* passenger state transitions
* vehicle state
* fuel
* rage
* weather effects
* train interactions
* aircraft interactions
* navigation
* game-time effects
* environmental interactions

A feature that visually looks correct but behaves differently must be marked PARTIAL or another appropriate gap.

---

# 10. Audio parity

Create a dedicated audio section.

For every Pygame audio feature identify:

* whether Godot has an equivalent,
* whether it is silent,
* whether a replacement asset exists,
* whether playback logic exists,
* whether the missing part is an asset or implementation.

Do not generate or modify audio during this audit.

---

# 11. Performance risk

Do not optimize anything.

However, assign a performance-risk estimate to each significant missing rendering feature:

* LOW
* MEDIUM
* HIGH

Examples:

* traffic lights
* route lines
* particles
* dynamic effects
* large numbers of lights
* animated entities
* environmental effects
* additional render passes

The purpose is planning only.

Do not implement speculative optimizations.

---

# 12. Produce the new audit document

Update:

`docs/architecture/godot-pygame-rendering-parity.md`

The document must contain:

## Executive summary

Totals for every classification.

## Feature matrix

Use:

| Area | Feature | Pygame implementation | Godot implementation | Status | Exact gap | Data source/dependency | Performance risk | Priority |
| ---- | ------- | --------------------- | -------------------- | ------ | --------- | ---------------------- | ---------------- | -------- |

## Server/protocol gaps

Only genuine missing state/data.

## Godot rendering gaps

Only presentation problems.

## Godot UI gaps

Only missing UI.

## Audio gaps

Only missing audio functionality.

## Gameplay gaps

Only behaviour differences.

## Intentional differences

Explain why each is intentional.

## Pygame-only / obsolete

Explicitly list functionality that should NOT be ported.

---

# 13. Prioritization

Assign every incomplete item:

### P0 — Core gameplay parity

Important missing functionality affecting normal gameplay.

### P1 — Major world/presentation parity

Highly visible world or gameplay presentation.

### P2 — Secondary functionality

Useful but not essential.

### P3 — Polish

Visual/audio/detail improvements.

Prioritize according to player impact, not implementation convenience.

---

# 14. Recommended next phases

At the end of the document, propose implementation phases based on the audit.

Each phase should contain:

* phase name
* features included
* why they belong together
* dependencies
* expected player-visible result
* performance risk

Do not implement these phases yet.

---

# 15. No implementation

This is strictly an audit.

Do NOT:

* add features
* modify rendering
* modify gameplay
* modify protocol
* modify server logic
* modify camera behaviour
* modify vehicle movement
* modify tests except if absolutely required for the audit itself
* refactor unrelated code
* optimize rendering

Only update the parity audit documentation.

---

# 16. Validation

Run:

```text
make godot-test
make godot-selftest
make audio-check
```

Also run the Python test suite if practical.

Do not change tests to hide failures.

Report exact results.

---

# 17. Git

If the audit document is updated successfully:

* commit the audit
* push the commit to the current branch

Do NOT create or push a Git tag.

Report:

* current branch
* commit hash
* push result
* test results
* final parity totals
* top 10 remaining gaps

---

# Final report

The final response to the user must be concise but include:

1. total feature counts by status
2. the 10 most important remaining gaps
3. the recommended implementation order
4. test results
5. commit hash
6. push status

Do not claim a feature is complete without tracing its actual implementation.
