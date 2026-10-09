# Godot Phase 3 — Static Gameplay Points in Map Chunks

## Objective

Continue the Pygame → Godot parity work after godot-11.

The next parity phase is:

> **Static gameplay points in the map chunks**

Implement the static map data and rendering/state needed for:

1. Taxi stands
2. Fuel stations
3. Traffic-light posts and their nearby phases/state
4. Roadworks

The goal is to reproduce the existing Pygame behaviour in Godot as closely as the current server/chunk architecture allows.

Do **not** start the later collision/world, calendar, remaining-static-world, or navigation phases in this task.

---

## Important current state

godot-11 is complete and pushed.

Current parity status:

| Status              | Count |
| ------------------- | ----: |
| Complete            |    35 |
| Partial             |    17 |
| Missing             |    47 |
| Different by design |     4 |
| Debug-only          |     3 |
| Not applicable      |     3 |

Tests currently pass:

```text
make godot-test:     PASS (128 checks)
make godot-selftest: PASS
make audio-check:    PASS
Python tests:        PASS (1548 passed)
```

`tests/test_packaging.py` remains excluded because this machine uses Python 3.10 while that test requires Python 3.11+.

### Stability constraints

The following issues were recently fixed and MUST remain untouched unless a direct regression is proven:

* vehicle jitter
* background/camera jitter
* camera stability
* accelerator-release behaviour
* `StateBuffer` interpolation
* driving input handling
* current camera update path

Do not refactor these systems as part of this phase.

---

# 1. First inspect the repository

Before modifying anything, inspect the current implementation.

Read:

* `docs/architecture/godot-pygame-rendering-parity.md`
* `docs/architecture/godot-rendering-migration.md`
* the current Godot client implementation
* the server map/chunk protocol
* the Pygame implementations for:

  * taxi stands
  * fuel stations
  * traffic lights
  * roadworks

Search the repository for all relevant existing structures and functions rather than assuming that the Godot implementation is missing everything.

In particular, identify:

* existing map chunk payloads
* existing static-map data structures
* existing OSM-derived objects
* existing taxi stand data
* existing fuel station data
* existing traffic-light data/state
* existing roadwork data/state
* any existing server-side simulation logic for these objects
* existing Pygame rendering functions
* existing tests

Determine for each item whether the missing work is:

* protocol/data
* rendering
* simulation/state
* architecture

Do not duplicate data that the server already has.

---

# 2. Use the existing chunk architecture

These objects are explicitly part of the **static gameplay points in map chunks** phase.

The preferred design is:

```text
server static map data
        ↓
map chunk / relevant state payload
        ↓
Godot client
        ↓
rendered gameplay point
```

Use the existing chunk loading/unloading mechanism.

Objects must appear when their containing map chunk becomes available and disappear when it is unloaded.

Do not introduce a second independent map-loading system.

Do not reintroduce the abandoned Pygame BIN architecture.

Do not create a new global static-map database on the Godot client unless the existing architecture genuinely requires it.

---

# 3. Taxi stands

Implement parity for taxi stands.

Inspect the Pygame implementation first and reproduce its actual behaviour.

Determine:

* how taxi stands are represented in server/static data
* their position
* their visual representation
* whether they have orientation
* whether they have a name/identifier
* whether the taxi stand has queue-related state
* whether any interaction/state is already authoritative on the server

The Godot client should render the taxi stand using the same coordinate system as the rest of the map.

If the server already owns taxi-stand gameplay state, expose only the minimum state required by Godot.

Do not implement new taxi dispatch or passenger queue logic unless that logic already exists on the server and merely lacks protocol/rendering exposure.

The goal here is parity, not a redesign of taxi management.

---

# 4. Fuel stations

Implement parity for fuel stations.

Inspect the existing Pygame rendering and server data.

Determine:

* station position
* station footprint/visual marker
* station identifier/name if applicable
* fuel-related state already present on the server
* whether the Pygame implementation displays pumps, a marker, building, or another representation

Expose only data actually required by the Godot client.

Do not implement a new fuel economy system.

Do not redesign refuelling.

Do not change existing fuel simulation.

If fuel interaction already exists server-side but Godot cannot access the relevant static point, add the smallest protocol/data addition necessary.

---

# 5. Traffic-light posts and phases

Implement the static traffic-light representation and the existing authoritative traffic-light state.

Separate these concepts:

1. Static traffic-light post/location data
2. Dynamic traffic-light phase/state

Do not confuse static map data with simulation state.

Inspect how Pygame determines:

* traffic-light locations
* orientation
* which road/intersection they belong to
* current phase
* light colour/state
* phase timing, if rendered

If the server already calculates traffic-light phases, Godot must consume that authoritative state.

Godot must NOT independently simulate traffic-light phases.

If the existing server sends a phase/timer/state already, reuse it.

If the server has the phase but does not expose it to Godot, add the smallest protocol addition required.

If the static post geometry is already present in chunk data, reuse it rather than creating another source.

---

# 6. Roadworks

Implement the existing Pygame roadwork representation.

Inspect the source implementation carefully.

Determine:

* roadwork location
* geometry/shape
* orientation
* associated road if applicable
* whether roadwork state changes during simulation
* whether it affects routing, collision, or vehicle movement
* whether it is purely visual in the current Pygame implementation

For this phase, implement only the **static gameplay-point representation**.

If roadworks already affect simulation or routing on the server, do not redesign those systems.

If collision effects are not already part of the existing Godot/server architecture, leave them for the later collision-relevant static-world phase.

---

# 7. Protocol design

Before changing the protocol, determine exactly what already exists.

Do not add protocol fields simply because they seem useful.

For every new field, document:

```text
field:
source:
consumer:
why required:
static or dynamic:
```

Prefer one coherent static-map/chunk representation over multiple independent messages.

Dynamic traffic-light state may be separate from static chunk data if that is how the existing server architecture works.

All protocol additions should remain backwards-compatible with older clients where practical.

Avoid changing unrelated existing protocol structures.

Do NOT introduce a binary protocol.

Do NOT redesign JSON serialization.

---

# 8. Rendering

Match the existing Pygame representation as closely as practical.

Do not blindly copy Pygame's rendering architecture.

Use Godot-native rendering appropriate to the current top-down Godot design.

Important:

* Godot remains top-down.
* Do not restore Pygame's old isometric building rendering.
* Do not introduce 3D.
* Do not change camera behaviour.
* Do not change zoom defaults.
* Do not change entity interpolation.

Static objects should participate correctly in existing camera culling/chunk visibility.

Avoid creating per-frame allocations for static objects.

Prefer persistent/static Godot nodes or equivalent structures tied to chunk lifetime.

---

# 9. Coordinate correctness

Verify coordinates against the authoritative server/map data.

Do not use arbitrary fixed coordinates.

For every object type, test:

* object appears at the correct location
* object disappears when its chunk unloads
* object reappears at the same location after reload
* no duplicate object is created when a chunk is revisited
* no visible coordinate drift occurs
* orientation is preserved where applicable

Pay particular attention to coordinate conversion because recent camera/background jitter work is considered stable.

Do not modify the camera to compensate for incorrect static-object coordinates.

Fix the coordinate conversion at the data/object layer instead.

---

# 10. Tests

Add deterministic tests for every implemented object type.

At minimum cover:

### Taxi stands

* protocol/static data parsing
* correct coordinates
* chunk insertion
* chunk removal
* no duplicates

### Fuel stations

* protocol/static data parsing
* correct coordinates
* chunk insertion
* chunk removal
* no duplicates

### Traffic lights

* static post parsing
* correct coordinates/orientation
* authoritative phase/state parsing
* state changes render correctly
* no client-side phase simulation

### Roadworks

* protocol/static data parsing
* correct coordinates/orientation
* chunk insertion/removal
* no duplicates

Also add regression coverage for any bug discovered during implementation.

Tests must be deterministic.

Do not rely exclusively on screenshots.

---

# 11. Manual verification

After implementation, run the real server and Godot client.

Verify at least one real example of each:

* taxi stand
* fuel station
* traffic light
* roadwork

For traffic lights, verify that the displayed state changes according to server state rather than local client timing.

For chunked objects, move far enough to force chunk loading/unloading and verify that objects appear/disappear correctly.

If a rare roadwork or traffic-light condition cannot naturally be reached, create a deterministic/scripted state for verification rather than waiting indefinitely.

---

# 12. Performance requirements

This phase must not regress current performance.

Do not:

* add per-frame searches through all static objects
* repeatedly instantiate/free objects every frame
* scan the entire map every frame
* perform expensive OSM processing in Godot
* add unnecessary JSON parsing work each frame
* alter the vehicle update loop
* alter camera update frequency
* alter interpolation

Static objects should be processed when chunks are loaded/updated, not rediscovered every frame.

Run the existing Godot self-test and inspect for:

* render backsteps
* frame-time spikes
* duplicate objects
* excessive node counts
* repeated chunk rebuilds

---

# 13. Explicitly out of scope

Do NOT implement any of the following in this phase:

* collision-relevant static-world redesign
* new collision system
* road blocking changes
* pathfinding/navigation
* route planning
* server-owned navigation routes
* route protocol
* calendar system
* day/night cycle
* seasonal lighting
* weather redesign
* snow
* rain rendering
* buildings
* trees
* fences
* generic scenery
* street lights unless they are inseparable from the already-required traffic-light representation
* railway rendering changes
* airport implementation
* train changes
* binary protocol
* WebSocket redesign
* camera changes
* interpolation changes
* vehicle physics changes
* input changes
* performance architecture rewrite

Do not opportunistically fix unrelated parity rows.

Record unrelated findings for a later phase instead.

---

# 14. Documentation and parity accounting

After implementation, update:

`docs/architecture/godot-pygame-rendering-parity.md`

Recalculate the complete parity table.

Do not simply decrement "missing" based on assumptions.

For each changed row, verify the actual implementation.

Record:

* complete
* partial
* missing
* different by design
* debug-only
* not applicable

Also distinguish where useful:

* rendering-only
* protocol/data
* simulation
* architecture

Document any intentionally deferred portion.

---

# 15. Validation commands

Run:

```bash
make godot-test
make godot-selftest
make audio-check
```

Run the relevant Python test suite as well.

The existing packaging-test Python 3.10 limitation may remain:

```text
tests/test_packaging.py requires Python 3.11+
```

Do not modify the packaging test merely to make the current environment pass.

---

# 16. Git workflow

Keep commits focused.

Recommended structure:

1. static map/chunk protocol and server data
2. Godot rendering/client implementation
3. tests and parity documentation

You may push the branch to the remote.

Do NOT create or push Git tags.

Do not rewrite unrelated commits.

---

# Definition of done

This phase is complete only when:

* taxi stands are represented correctly in Godot
* fuel stations are represented correctly in Godot
* traffic-light posts are represented correctly
* traffic-light state comes from authoritative server state
* roadworks are represented correctly
* chunk loading/unloading works correctly
* no duplicate static objects are created
* deterministic tests cover the new functionality
* real-server manual verification has been performed
* current vehicle/camera/background stability remains intact
* performance has not materially regressed
* `make godot-test` passes
* `make godot-selftest` passes
* `make audio-check` passes
* relevant Python tests pass
* parity documentation is updated
* changes are committed and pushed
* no Git tag is created

At the end, report:

1. exact files changed
2. protocol changes
3. server-side changes
4. Godot-side changes
5. tests added
6. manual verification performed
7. new parity counts
8. remaining static-world gaps
9. any deferred issues
10. commit hashes

Do not claim completion for an item that is only partially implemented.
