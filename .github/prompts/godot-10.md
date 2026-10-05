# Godot vs Pygame Parity Re-Audit

## Objective

The Godot version is now stable in two important areas:

* vehicle movement is stable
* camera/background/world jitter has been fixed

Return to the Godot-vs-Pygame parity work and perform a **fresh, comprehensive implementation audit**.

The purpose of this task is to determine accurately:

> **What is still missing from the current Godot version compared with the existing Pygame implementation?**

This is an **analysis-only task**.

Do not implement new gameplay or rendering features during this audit.

---

# 1. Strict Scope

This task is a parity audit only.

### DO

* inspect the current Godot implementation
* inspect the current Pygame implementation
* inspect the existing parity audit
* verify whether previously reported gaps still exist
* identify newly completed items
* identify remaining gaps
* classify each gap
* inspect the current network protocol/state
* inspect current simulation capabilities
* inspect rendering capabilities
* inspect current camera/world architecture
* update the parity documentation if necessary to reflect the current reality

### DO NOT

Do not implement:

* new rendering features
* new gameplay features
* new protocol fields
* new server simulation
* navigation/route planning
* traffic-light implementation
* weather implementation
* day/night implementation
* audio work
* performance optimizations
* binary protocol
* map architecture changes
* vehicle movement changes
* camera changes
* interpolation changes

The purpose is to establish **what should be implemented next**, not to implement it.

---

# 2. Start From the Existing Audit

Read:

```text
docs/architecture/godot-pygame-rendering-parity.md
docs/architecture/godot-rendering-migration.md
```

These documents were created during the previous parity audit.

Do not assume their counts are still correct.

The previous audit reported approximately:

```text
30 / 108 complete
18 partial
52 missing
```

Recalculate the current state from the actual source code.

---

# 3. Audit Both Implementations

Systematically compare:

### Pygame

Inspect the actual current Pygame implementation for:

* rendering
* HUD
* world objects
* vehicles
* pedestrians
* trains
* taxi interactions
* weather
* lighting
* map rendering
* camera
* markers
* navigation
* special effects
* gameplay UI

### Godot

Inspect the actual current implementation for:

* scenes
* scripts
* nodes
* rendering
* HUD
* world objects
* entities
* camera
* network state
* simulation state
* effects

Do not rely only on filenames or documentation.

Trace the implementation to determine whether a feature is actually functional.

---

# 4. Rebuild the Parity Matrix

Create/update a complete matrix with one row for each meaningful Pygame behavior.

Use categories such as:

```text
Complete
Partial
Missing
Different by design
Pygame-specific
Godot-specific
Not applicable
```

For every incomplete item record:

```text
Feature
Pygame implementation
Godot implementation
Current status
Why incomplete
Data already available?
Protocol change required?
Simulation change required?
Rendering-only?
Priority
Recommended implementation phase
```

Be precise.

For example, do not simply write:

```text
Traffic lights — missing
```

Instead determine whether:

```text
traffic-light objects exist in server state
traffic-light phase exists
traffic-light geometry exists
Godot receives the data
Godot renders the object
Godot updates the phase
```

This distinction is important.

---

# 5. Recheck Previously Missing Rendering Features

The previous audit identified several important missing or partial rendering features.

Explicitly recheck all of these.

## World/UI

* pickup/drop-off marker
* off-screen destination arrow
* destination/address label
* compass
* navigation route
* road names
* speed limits

## Lighting / Environment

* day/night
* darkness
* date/time-dependent lighting
* street lights
* vehicle lights
* wet roads
* puddles
* rain
* snow
* lightning

## Road/Infrastructure

* traffic lights
* traffic-light posts
* taxi stands
* fuel stations
* roadworks
* railway track appearance
* road colours by type
* bridges
* level-aware structures

## Vehicles

* vehicle appearance by type
* headlights
* tail lights
* brake lights
* turn signals
* crash state
* taxi indicators
* taxi exhaust
* vehicle dimensions
* parked/police/far-away vehicle behavior

## Pedestrians

* facing direction
* walking animation
* fallen state
* cursing
* going indoors
* customer states
* booked passenger indicators
* meet-and-greet presentation

## Trains

* train colours
* locomotive appearance
* restaurant stripe
* train length
* train layering relative to roads/vehicles

## HUD

* fuel gauge
* rage meter
* trip/odometer
* water state
* nausea
* other Pygame HUD elements

Verify every item against the current code.

Do not assume that an item is still missing simply because the old audit says so.

---

# 6. Inspect Protocol/Data Coverage

For every remaining gap, answer:

> Is the required information already available to Godot?

Classify it as:

### A. Already available

Godot receives the required information.

Therefore this is a rendering/client implementation task.

### B. Available in server/simulation but not sent to Godot

The server already knows it, but the protocol does not expose it.

This is a protocol/client integration task.

### C. Not available in simulation

The server/simulation itself must be extended.

This is a simulation task.

### D. Pygame-only behavior

The behavior is intentionally part of the old architecture and should not necessarily be reproduced.

### E. Different by design

Godot should behave differently.

This classification is particularly important.

Do not recommend protocol changes when the data is already available.

Do not recommend rendering work when the simulation does not currently produce the required state.

---

# 7. Recheck the Existing Protocol Audit

The previous audit identified approximately 47 protocol gaps.

Revisit them against the current implementation.

Pay particular attention to:

* static chunk data
* trees
* objects
* signs
* fences
* land use
* labels
* bridge flags
* level flags
* building details
* darkness/date
* traffic-light phases
* roadworks
* meet-and-greet booking state
* road name
* speed limit
* lightning
* rain intensity
* knocked-over objects
* broken lamps

For each one determine whether it is still genuinely required.

Do not automatically add all previous protocol gaps to the next development phase.

---

# 8. Recheck the Navigation Gap

The previous audit identified navigation as special because Pygame performs route planning in its main loop while the current Godot/server architecture does not provide an equivalent simulation-side route.

Verify the current situation.

Determine:

* where Pygame calculates the route
* whether Godot currently calculates one
* whether the server calculates one
* whether a route exists in the current protocol
* whether the route is required for gameplay or only visual parity

Do not implement routing.

Only document the actual architectural gap and possible future direction.

---

# 9. Check the Recent Jitter Fix

Because the latest work fixed:

* vehicle jitter
* stuck accelerator
* background/camera jitter

inspect those changes as part of the audit.

Verify that:

* the vehicle remains stable
* camera follows the intended target
* world rendering is stable
* no parity feature was accidentally disabled
* camera/world coordinate handling still matches the intended Godot architecture

Do not modify the fix.

The stability fix is considered protected.

---

# 10. Separate Gameplay Importance From Visual Parity

Not every missing Pygame feature has equal importance.

Assign each remaining gap a priority:

### P0 — Core gameplay

Missing behavior that materially affects gameplay.

Examples:

* interaction markers
* passenger/customer state
* navigation
* important taxi interaction feedback

### P1 — Major visual/gameplay feature

Clearly visible and important to the game experience.

Examples:

* day/night
* traffic lights
* fuel stations
* roadworks
* trains
* taxi stands

### P2 — Visual parity

Useful but not essential.

Examples:

* exact road colours
* detailed signs
* minor environmental objects
* secondary animations

### P3 — Cosmetic

Small visual differences that can safely wait.

---

# 11. Identify Quick Wins

From the remaining gaps, identify features where:

```text
required data already exists
+
no server change is required
+
no architectural change is required
```

These should be candidates for the next implementation phase.

Also identify the opposite:

```text
requires simulation/protocol architecture work
```

These should be grouped separately so that implementation phases do not become unnecessarily coupled.

---

# 12. Produce an Implementation Roadmap

At the end, group remaining work into logical phases.

For example:

```text
Phase A — Rendering-only parity
Phase B — Existing protocol data exposed in Godot
Phase C — Small protocol additions
Phase D — Static world data
Phase E — Simulation features
Phase F — Navigation architecture
```

Do not assume these exact phases are correct.

Create the phases based on your findings.

The important principle is:

> Prefer small, independently testable phases with minimal cross-layer changes.

---

# 13. Performance Consideration

Do not perform optimization work.

However, flag features that could have significant performance impact.

For example:

```text
Potentially expensive:
- large numbers of traffic lights
- dynamic weather particles
- large static object sets
- navigation visualization
- street-light rendering
```

Simply identify the risk.

Do not optimize it yet.

---

# 14. Tests

Run the existing relevant validation:

```bash
make godot-test
make godot-selftest
make audio-check
```

If practical, also run the relevant Python test suite.

Do not modify tests merely to make the audit pass.

Do not add feature implementation just to satisfy a test.

The purpose is to establish the current baseline.

---

# 15. Documentation

Update:

```text
docs/architecture/godot-pygame-rendering-parity.md
```

so that it accurately represents the **current implementation**.

If `godot-rendering-migration.md` contains obsolete conclusions or counts, update those too.

Do not create a large collection of new documentation files.

Keep the existing parity documentation as the canonical audit.

---

# 16. No Code Implementation

This point is important.

The audit must **not** turn into implementation work.

Allowed:

* documentation updates
* corrected parity counts
* corrected classifications
* corrected recommendations
* audit notes

Not allowed:

* new features
* protocol changes
* rendering code
* server code
* simulation code
* refactoring unrelated code

If you discover an obvious one-line bug while auditing, document it rather than fixing it.

---

# 17. Final Report

Return a concise but technically detailed report containing:

## Current parity

```text
Complete: X
Partial: Y
Missing: Z
Different by design: N
Pygame-specific: N
```

Compare these numbers with the previous audit.

## Biggest remaining gaps

Rank the top 10 by gameplay/visual importance.

## Rendering-only gaps

List features that can be implemented without server/protocol changes.

## Protocol gaps

List features where the required data is missing from the Godot protocol.

## Simulation gaps

List features that require changes to the simulation/server.

## Architecture gaps

List features that require a larger architectural decision.

## Quick wins

List the best next implementation targets.

## Larger work

List items that should be deliberately postponed.

## Recommended next phase

Recommend exactly **one** next implementation phase.

Do not implement it.

## Tests

Report:

```text
make godot-test: PASS/FAIL
make godot-selftest: PASS/FAIL
make audio-check: PASS/FAIL
Python tests: PASS/FAIL/SKIPPED
```

## Git

If documentation was updated:

* create one focused commit
* push the branch if repository workflow permits it
* do not create or push a Git tag

If no documentation changes are necessary, do not create an empty commit.

---

# Final Constraint

The goal is not to maximize the number of parity rows marked "complete".

The goal is to establish a **technically accurate roadmap for bringing the Godot version to functional parity with the Pygame version while preserving the new Godot architecture**.

Do not blindly reproduce Pygame architecture.

If Godot already has a cleaner or more appropriate implementation, classify the difference as:

> **Different by design**

when the gameplay result is equivalent.

Most importantly:

**Do not modify the stable vehicle or camera implementation.**
