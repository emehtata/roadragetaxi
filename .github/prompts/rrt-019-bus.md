# Fix Local Bus Route Following and Stop Oscillation

Work on the `release/v0.19.0alpha` codebase of Road Rage Taxi.

## Problem

Local buses based on OpenStreetMap bus routes behave incorrectly. Some buses rotate, circle, oscillate, or repeatedly manoeuvre around bus stops instead of progressing along their routes.

The goal is to make local buses drive continuously and plausibly along their actual OSM routes, stopping briefly at stops along the way. **Timetables, scheduled departure times, and real-world service frequency are explicitly out of scope.**

## Architecture constraints

- The Python simulation server remains authoritative for vehicle movement, routing, traffic rules, collisions, and bus state.
- Godot remains responsible for rendering.
- Reuse the existing NPC vehicle, route-planning, vehicle physics, and traffic-rule systems. Do not introduce a separate bus-driving simulator.
- Preserve existing car and taxi behaviour.
- Preserve performance and avoid unnecessary per-frame route searches or whole-map scans.
- Do not introduce new binary map-data formats or replace the existing map-data architecture.
- Do not create or push Git tags.
- Do not stop after writing an analysis: implement the verified fixes and run the relevant tests.

## Phase 1: Inspect and identify the actual root cause

Read the current implementations and related tests, including:

- `src/theroadragetrip/bus_lines.py`
- `src/theroadragetrip/npc.py`
- `src/theroadragetrip/traffic_world.py`
- `src/theroadragetrip/static_world.py`
- OSM route-relation and bus-stop extraction in `src/theroadragetrip/osm/`
- `tests/test_bus_lines.py`
- Relevant NPC routing, steering, stuck recovery, and traffic-rule tests
- `docs/bus-lines.md`

Trace the complete lifecycle of a line bus:

1. Bus spawn and line selection.
2. Initial route and next-stop selection.
3. Route planning and validation.
4. Waypoint progression and steering.
5. Arrival detection and deceleration.
6. Bus-bay entry and exit.
7. Stop dwell and advancement to the next stop.
8. Route failure and recovery.
9. Terminus handling, route reversal or continuation, and despawning.

Determine exactly why a bus can rotate or oscillate at a stop. Inspect the actual state transitions and movement vectors rather than assuming the stop-distance threshold is the cause.

In particular, verify:

- Whether the active route contains duplicate, reversed, or badly ordered waypoints.
- Whether a route endpoint is behind the bus or requires an abrupt turn.
- Whether the bus repeatedly receives a new route before completing its current route.
- Whether the current waypoint index can move backwards or fail to advance.
- Whether stop-arrival detection oscillates between driving, stopped, and awaiting departure.
- Whether bus-bay entry and exit paths are geometrically continuous with the road route.
- Whether a route failure or stuck-recovery event resets the bus to a previous target.
- Whether a bus is attempting to serve a stop from the wrong direction or wrong side of the road.
- Whether the NPC steering controller can follow the generated bus path without oscillation.
- Whether the route relation contains only a partial set of stops or an invalid stop sequence.

Add targeted diagnostics to the existing debugging facilities if necessary. Diagnostics should identify the bus, route relation, current stop, target stop, state, route waypoint index, route failure count, heading error, and recovery reason. Avoid noisy logging every frame.

## Phase 2: Implement robust route progression

Implement the smallest coherent fix supported by the findings.

### Route and stop progression

- Treat the ordered stops of an OSM bus route as an ordered sequence of destinations.
- Maintain an explicit current leg and target stop.
- Advance the target stop only after the bus has actually completed the current stop visit.
- Each stop must be served at most once per route traversal.
- Reaching a stop must be a stable state transition, not a condition that can repeatedly toggle due to small position changes.
- Use appropriate arrival detection and braking so the bus does not overshoot and then circle back.
- After departure, ensure the bus follows the next route leg rather than continuing to target the previous stop.
- Do not repeatedly replan a route that is already valid and being followed.
- Preserve valid route progress during temporary traffic waits.
- Recovery must not reset a bus to an already-served stop or cause it to repeat a completed leg.

### Bus-stop manoeuvres

- Keep bus-bay entry and exit paths geometrically continuous with the road route.
- Ensure the bus approaches the stop from the correct travel direction and on the correct side of the road.
- Avoid abrupt heading changes, U-turns, and loops at the stop.
- Account for the bus's actual length and width when generating manoeuvres.
- If a bay or stop approach cannot be used safely, fail that stop leg explicitly and recover or skip the stop according to a bounded policy.
- Do not let a bus oscillate indefinitely between the road and the bay.

### Route failures

- Bound route retries and recovery attempts.
- Track repeated failures per stop leg.
- Skip an unreachable stop after a bounded number of attempts and continue with the next usable stop where possible.
- If a whole route is unusable, retire or replace the bus safely rather than leaving it circling in the road.
- Never teleport a visible bus to another route point to hide a routing problem.

## Phase 3: Continuous operation without timetables

Buses should be active background traffic, not one-shot demonstrations that disappear after reaching the end of a route.

- Do not implement timetable or departure-time logic.
- Use existing OSM route relations and their ordered stops.
- If the opposite direction is represented by another valid OSM relation, allow the bus to transition to that relation at the terminus when the connection and direction can be established safely.
- Do not assume that two routes with the same line number are necessarily compatible.
- If a safe return route cannot be found, end the current trip gracefully and let the existing population system spawn a replacement when appropriate.
- Avoid U-turns on ordinary streets unless the manoeuvre is explicitly supported and geometrically valid.
- Preserve route direction and prevent immediate reversal to the previous stop.

## Phase 4: Regression tests

Add deterministic tests that reproduce the observed failure modes.

At minimum, cover:

1. A bus drives through at least five ordered stops without revisiting a served stop.
2. A bus reaches a stop, dwells once, and departs without re-entering the same stop state.
3. Small positional fluctuations around a stop do not cause repeated state transitions.
4. A bus cannot route to a stop from the wrong side of the road.
5. A bus enters and exits a stop bay without crossing into the oncoming lane or triggering road-boundary recovery.
6. A bus does not rotate indefinitely when the next waypoint is close or behind its heading.
7. A route failure does not cause repeated replanning of the same failed leg forever.
8. A temporary traffic wait does not reset route progress.
9. An unusable stop is skipped without corrupting the remaining stop sequence.
10. Terminus handling does not cause a U-turn, a route reversal loop, or a permanently stuck bus.
11. Existing car, taxi, traffic-rule, and NPC-recovery tests continue to pass.

Where practical, add a deterministic simulation test that runs the bus for several simulated minutes on a small road network with multiple stops, junctions, and a terminus. Assert that the bus makes measurable forward progress, visits stops in the correct order, and does not enter a repeated position/heading cycle.

## Phase 5: Validation and report

Run the targeted bus tests first, followed by the relevant NPC routing, physics, and traffic-rule tests. Run the broader test suite if practical.

Report:

- The verified root cause or causes.
- The exact files changed.
- The behaviour corrected by each change.
- Tests executed and their results.
- Any remaining limitations, particularly incomplete OSM route relations and missing return-direction connections.

Do not claim the issue is fixed solely because unit tests pass. Identify which movement and stop-transition scenarios were actually tested.