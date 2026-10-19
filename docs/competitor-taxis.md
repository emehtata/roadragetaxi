# Competitor taxis

Other taxis compete for the same phone fares the player sees. When a
competitor takes a fare it disappears from the player's phone and the
competitor drives the job: to the pickup, the passenger boards, to the
drop-off, the passenger leaves.

## Current state

Phase 1 (below) is implemented. Competitors are ordinary NPC cars of
`vehicle_kind == "taxi"`, driven by the NPC system with all its traffic
rules, and dispatched by `competitor_taxis.py`.

NPC taxis can be cars or vans and retain the normal NPC paint variation
(white, black, grey, silver and other colours). Van dimensions, appearance,
collision body come from the existing van definition. Taxi vans seat eight
passengers plus the driver (nine occupants total); ordinary vans keep their
existing capacity. Conversion also adds the taxi role and roof sign.
The player's own taxi stays yellow with its existing passenger capacity.

## Earlier implementation (analysed, replaced)

An August 2026 version (commits 58a3afc, 4913567) spawned "rival taxis"
at taxi stands that collected pedestrians waiting there
(`TrafficManager.spawn_taxis_at_nearby_stops`,
`let_taxi_pick_up_waiter`). It had no connection to the phone fares and
its taxis never drove a job; 89250cc stopped spawning them and the
traffic rewrite removed the code. What was left:

- `TrafficWorld.let_taxi_pick_up_waiter`: a no-op stub still called every
  frame by `simulation.py`. Removed.
- `NPCVehicle.is_taxi`, sent to the client (`protocol.py`) and drawn as a
  taxi body with an unlit roof sign (`entity_layer.gd`). Kept: competitors
  use it.

## Design

**Server decides, client draws.** Dispatch, routing and stops are server
decisions; the client only draws a competitor as a taxi, its roof light
lit while a passenger is aboard.

**Reuse the NPC system, never a parallel driver.** A competitor's legs
are NPC trip continuations toward a query point
(`_continue_npc_trip_steps(..., destination_query_point)`, the same
machinery household cars drive home with): budgeted route jobs,
validated routes, and the tiered legal stopping place near the point
(space > lot > yard > roadside, `docs/finnish-npc-traffic-law.md`
"Parking and passenger stops": never a sidewalk, crossing or junction).
The driver stays in the car at stops (no trip-group building visit).

**Job lifecycle** (`competitor_taxis.TaxiJob`):

| State | Meaning | Next |
| --- | --- | --- |
| `await_departure` | needs a route for its current leg | the route job applies: `driving` |
| `driving` | on the way to the leg's stop | parked at the stop: `stopped` |
| `stopped` | at the stop, the passenger boarding/leaving (`STOP_DWELL_S`) | pickup: leg `dropoff`, `await_departure`; drop-off: job done |

A leg whose route cannot be planned is retried a few times, then the job
is dropped.

**Dispatch.** Only an idle competitor parked with its driver can take a
fare: NPC route jobs are only applied to a vehicle that has not moved
since planning began, so a moving car cannot be sent somewhere new with
the current machinery. Each phone offer, about once a second, may be
taken by the nearest idle competitor within `CLAIM_RADIUS_M` of its
pickup, at `CLAIM_RATE_PER_S` - so most offers stay on the phone for a
while and the player can still win them.

**Population.** Normally up to `COMPETITOR_TAXIS` moving-traffic spawns
become taxis. On Friday and Saturday nights, 22:00–06:00 (including
Saturday and Sunday early mornings), populated areas target up to ten
rivals, scaled to local population and the configured vehicle budget.
This adds night-time moving demand without increasing the population cap.
Free rivals pause ten seconds for dispatch, then cruise using the existing
budgeted, traffic-rule-aware routes. Outside those hours they wait for a
fare. A taxi with a pending cruise route cannot simultaneously claim a
fare. Distant ambient taxis remain subject to the normal viewport cleanup.

## Phase 1 (2026-10-15)

Implemented as designed above: taxi population, dispatch from the phone
offers, the job lifecycle, the player's notice when a competitor takes a
fare, the roof light. Tests: `tests/test_competitor_taxis.py`.

Not yet: the passenger as a visible pedestrian walking to and from the
competitor; idle competitors driving to taxi stands; competitors taking
moving-car jobs; the player's own street hails or rail bookings being
contested.
