# Godot Parity Phase 4 — Navigation Route

## Objective

Implement the next recommended phase from
`docs/architecture/godot-pygame-rendering-parity.md`: the Pygame navigation
route, end to end.

1. The server plans and caches the route to the current taxi target.
2. The protocol sends a compact route polyline.
3. Godot toggles route visibility with N and draws the received line.

The server owns routing. Godot must never calculate a route from map chunks.
Preserve the existing compass, target marker, off-screen arrow, camera,
vehicle movement, and interpolation.

This phase is only navigation. Do not combine it with road rage, weather,
speech, settings, or other parity work.

---

## 1. Read the current implementation first

Before changing code, trace:

* Pygame's N key and route lifecycle in `main/__init__.py`
* Pygame's `draw_navigation_route` in `render/navigation.py`
* `TrafficWorld.plan_route()` and resumable `plan_route_steps()` in
  `traffic_world.py`
* the route-job pattern already used in `npc.py`
* surface and non-surface routing through `world.level_routes`
* `TaxiManager.get_current_target()` and taxi state transitions
* `dist_point_to_segment()` in `geo.py`
* the server tick and state broadcast in `server/__init__.py`
* state construction/interpolation in `protocol.py`
* Godot target selection and draw order in `entity_layer.gd`
* Godot compass/arrow handling in `nav_overlay.gd`
* input and HUD hints in `main.gd` and `hud.gd`
* routing, protocol, server-integration, and Godot tests

Use the current repository as the source of truth. Reuse its route graph,
coordinate conversion, drawing style, and test patterns. Do not invent a
second graph or client-side pathfinder.

---

## 2. Preserve Pygame route behaviour

The active target is the same pickup/drop-off target already used by Godot's
marker, arrow, compass, and mission line.

Match Pygame's route lifecycle:

* no target means no route
* a new pickup or drop-off target starts a new route
* changing map level starts a new route for that level
* a route is recomputed when the taxi is more than 35 m from every segment
* a route-graph revision invalidates a route planned against the old graph
* surface routing honours the current road layer when available
* below/above the surface, use the existing level-route system and expose the
  current level's leg; replan after the level transition
* an unreachable target produces no line and does not crash

Do not change road eligibility, one-way handling, graph construction,
connector costs, taxi targets, or the 35 m deviation threshold.

---

## 3. Add a server-owned route service

Keep the minimum route state on `SimulationServer`, or in one small existing
server-side home if the repository already has a better fit:

* current target key
* map level and route-graph revision used for the route
* cached route points
* one in-progress resumable route job, when needed

Use a stable target key based on the target kind/coordinates or existing
stable game state. Do not use a Python object id as protocol-visible state.

Route search must not block the 30 Hz simulation tick:

* use `plan_route_steps()` for surface routes
* advance the job with a small explicit per-tick time budget
* retain the generator between ticks instead of restarting the same search
* cancel/discard a stale job when its target, level, or graph revision changes
* publish the completed route atomically; never publish a half-planned line
* do not call `plan_route()` every tick

For a non-surface level, reuse `world.level_routes.plan()` as Pygame does. If
measurement shows that call can exceed the tick budget, make the smallest
safe scheduling change needed; do not redesign level routing speculatively.

The route should be computed regardless of the Godot N display toggle. N is
client presentation state and must not add a command or make route ownership
client-dependent.

---

## 4. Send a compact route

Add one optional additive state object:

```text
state.navigation.points = [[x, y], ...]
```

Use an empty list when there is currently no completed route. Missing
`navigation` must remain safe for older clients and fixtures.

Send world-metre coordinates, not camera-relative or screen coordinates.
Preserve the route's exact first and last points.

Compact long routes before putting them on the wire. Use the smallest
deterministic polyline simplification that:

* removes redundant collinear/near-collinear points
* preserves turns and route shape within an explicit small metre tolerance
* preserves both endpoints
* never adds a dependency
* is covered by a direct regression check for shape error and point reduction

Cache the compact result with the route. Do not simplify or rebuild JSON
points every simulation tick.

Keep the protocol version unchanged unless this repository's established
rules require a bump for additive state fields. Do not add a separate request,
endpoint, or route message unless the current transport makes the state field
demonstrably unsuitable.

---

## 5. Add the Godot N toggle

N is a local presentation toggle, off by default as in Pygame.

Requirements:

* toggle only on a non-echo N key press
* retain the selection across ordinary state updates and focus loss
* hide the route immediately when toggled off
* show the newest received route immediately when toggled on
* clear/hide it when the state has no valid route or no taxi target
* show `N navigation ON/OFF` in the existing compact driving hint
* do not alter the C compass toggle
* do not send N through `PlayerCommand`

Missing, null, malformed, non-finite, or shorter-than-two-point route data
must be ignored safely.

---

## 6. Draw the route in world space

Draw the route with the existing Godot world origin and `MapMath.point()`.
Do not transform it through camera coordinates manually.

Match Pygame's presentation:

* dark outline under a yellow/gold centre line
* visible above roads and ordinary pedestrians
* below the pickup/drop-off marker, taxi, NPC vehicles, canopies, rail
  bridges, and trains
* thickness remains readable across the existing zoom range
* only visible segments need drawing; avoid work far outside the view

The simplest correct home is the existing entity/world drawing path where
the required ordering can be expressed without a new rendering subsystem.
Do not draw the route as screen-space UI in `nav_overlay.gd`; that file may
own the N input state if useful, but the polyline itself must remain aligned
with the world.

Do not smooth or interpolate route coordinates between state snapshots. A
route is discrete cached state and changes atomically when the server replans.

---

## 7. Performance requirements

This phase has MEDIUM server-side risk. Leave one measurable check behind.

Verify that:

* no route search runs without a target
* no completed route is recomputed every tick
* route jobs obey their per-tick budget
* stale jobs cannot overwrite a newer target's route
* off-route distance checks run only against the cached route and remain
  negligible at the compact route size
* protocol point count is materially lower for long straight/near-straight
  routes while corners remain accurate
* Godot does not allocate/rebuild unchanged route geometry unnecessarily
* normal frame and tick timing remain within the project's existing checks

Prefer a small constant budget and cached data over threads, locks, workers,
or a new job framework. Reuse the resumable generator already in the repo.

---

## 8. Tests

Add the smallest deterministic checks at the owning layer.

### Server and routing

Cover at least:

1. no target produces no route and starts no job
2. a pickup target produces a valid route with exact start/end
3. changing to the drop-off cancels/replaces the old job and route
4. unchanged target/level/graph does not replan each tick
5. more than 35 m deviation triggers replanning; 35 m or less does not
6. changing map level triggers the appropriate route leg
7. a route-graph revision invalidates stale work
8. an unreachable route becomes empty without crashing
9. a deliberately multi-step job spans ticks and respects the time budget
10. a stale job cannot publish after a newer target is active
11. simplification preserves endpoints, stays within its documented error,
    and reduces a representative long polyline

Reuse `TrafficWorld` and production server state rather than creating a mock
pathfinder.

### Protocol

Cover at least:

1. route coordinates encode/decode unchanged
2. empty and missing navigation state are safe
3. interpolation treats navigation as discrete state, not blended points
4. a reconnect/new state snapshot can receive the current cached route

### Godot

Cover at least:

1. N defaults off and toggles on/off on non-echo presses
2. C compass behaviour remains independent
3. valid points convert through the world origin correctly
4. invalid, non-finite, missing, empty, and one-point routes do not draw or
   crash
5. turning N off removes the line immediately
6. a changed route replaces the previous line
7. losing the target hides the route
8. route ordering places it below target/vehicles and above roads/pedestrians
9. the driving hint reports N navigation ON/OFF

Prefer extending existing routing, server-integration, and
`godot/tests/run_tests.gd` checks over adding new harnesses.

Run at minimum:

```bash
pytest -q tests/test_traffic_world.py tests/test_protocol.py tests/test_server_headless.py
make godot-test
make godot-selftest
```

Run any other directly affected server integration tests. Distinguish
unrelated pre-existing failures from regressions.

Manually verify with the real Oulu server:

1. accept a fare and press N
2. confirm the route follows roads to pickup
3. pick up the passenger and confirm it changes to the drop-off route
4. drive along the route and confirm it stays stable
5. deviate by more than 35 m and confirm it replans
6. toggle N off/on and confirm only visibility changes
7. confirm target arrow and C compass still work
8. confirm route/world alignment while driving and zooming
9. confirm no hitch when a long route is planned
10. complete/cancel the fare and confirm the route clears

---

## 9. Documentation

Update only the relevant rows and phase history in
`docs/architecture/godot-pygame-rendering-parity.md`:

* navigation route
* server ownership and replan triggers
* protocol shape and simplification rule
* Godot N toggle and draw layer
* `godot-final-04` implementation, tests, and measured cost

Update protocol documentation if it enumerates state fields. Do not rewrite
or re-audit the whole parity document.

---

## 10. Git workflow

Work on the current branch:

```text
release/v0.16.0g-alpha
```

Create clear commits and push them when implementation and validation are
complete. Do not create or push a Git tag.

---

## Final report

Report:

### Implementation

* server route ownership, lifecycle, and replan triggers
* protocol field and simplification rule
* Godot N toggle, drawing, and layering
* any existing contract that differed from this prompt

### Tests

* exact commands and results
* manual Oulu scenarios checked
* any unrelated failures

### Performance

* route-job tick budget and measured worst slice
* raw versus compact point counts for a representative long route
* observed server tick and Godot frame impact

### Git

* commit hash(es)
* confirmation that the branch was pushed
* explicit confirmation that no Git tag was created

Do not start the next parity phase automatically.
