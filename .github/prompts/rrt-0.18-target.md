# Road Rage Taxi 0.18 — Living City, Realistic Traffic and Finnish Road Safety

## Mission

Develop the next major simulation improvement for Road Rage Taxi: a coherent, believable Finnish city where people follow daily and weekly routines, traffic demand changes naturally over time, public events influence surrounding activity, and NPC vehicles behave predictably and safely according to Finnish traffic rules.

The target is the current release branch `release/0.18.0alpha`. Inspect the actual repository state before making changes. Do not assume that older documentation, previous performance reports, or earlier implementation plans accurately describe the current code.

This is an implementation task, not merely an architecture proposal. Investigate the existing systems, produce a concise implementation plan, implement the changes in manageable stages, run relevant tests, and document the results.

## Non-negotiable constraints

1. **Do not investigate or fix the existing PBF-map gameplay stuttering as part of this task.** It is a separate, explicitly deferred problem. Do not make performance-related changes to PBF parsing, map loading, or map rendering unless an incidental change is strictly required for correctness. If encountered, document the issue without attempting to solve it.
2. Preserve the current online-map gameplay experience and existing supported map-data workflows.
3. Preserve the existing architecture unless repository evidence establishes a compelling reason to change it. The Python server remains authoritative for simulation rules, traffic decisions, collisions, resident behavior, events, and game time. Godot remains responsible for client rendering and presentation.
4. Do not introduce a binary map-data architecture or propose replacing the existing map-data format as part of this task.
5. Preserve or improve gameplay FPS. Avoid expensive per-NPC global searches, unbounded work per simulation tick, unnecessary allocations, and duplicate simulation systems. Reuse existing spatial indexes, caches, managers, and scheduling mechanisms where appropriate.
6. Do not introduce arbitrary caps on the total number of visible or simulated NPCs as a substitute for fixing the underlying behavior. Existing distance-based activation, relevance filtering, and documented limits may remain where justified.
7. Preserve the existing game mechanics, protocol compatibility, save behavior, NPC identities, taxi gameplay, and event integrations unless a change is necessary and properly tested.
8. Do not replace working subsystems wholesale without first documenting why incremental integration is insufficient.
9. Use English for code comments, documentation, tests, and commit messages, consistent with the repository's conventions.
10. Git pushes to the existing remote are permitted. **Do not create or push Git tags.** Do not publish a release unless explicitly requested.

## Phase 0 — Repository audit and baseline

Before editing code, inspect the current implementation and establish which capabilities already exist.

Read at least the relevant parts of:

- `docs/finnish-npc-traffic-law.md`
- `src/theroadragetrip/npc.py`
- `src/theroadragetrip/traffic_rules.py`
- `src/theroadragetrip/pedestrian.py`
- `src/theroadragetrip/arena_crowds.py`
- `src/theroadragetrip/calendar.py`
- Existing resident, activity, trip, road-network, spatial-index, traffic-signal, parking, and event modules
- Existing sports-fixture integrations and event schedules
- Relevant architecture documentation, tests, and performance-analysis reports

Use actual repository paths; if any listed path does not exist, locate the current implementation rather than creating a duplicate module blindly.

Establish a baseline for:

- NPC vehicle collisions and traffic-rule violations
- Vehicle trip start and completion rates
- Vehicles that remain stationary, reverse repeatedly, or enter recovery loops
- Pedestrian and resident lifecycle correctness
- Time-of-day and weekday effects already implemented
- Event attendance, arrivals, departures, and surrounding activity
- Existing test coverage and simulation performance

Historical performance reports must not be treated as measurements of the current version unless verified against the current branch.

Produce a short audit document that distinguishes:
- Existing and working behavior
- Partially implemented behavior
- Missing behavior
- Confirmed bugs
- Risks that need regression tests

Then proceed with implementation. Do not stop after producing the audit.

## Phase 1 — Establish a coherent simulation model

Build on existing managers and data structures. Do not create competing systems for residents, pedestrians, NPC traffic, activities, and events.

The simulation should distinguish the following concepts:

- **Resident:** A persistent person with an identity and relevant life/activity state.
- **Activity:** What the person intends to do, such as commuting, shopping, exercising, visiting a venue, or going home.
- **Trip:** A persistent journey with an origin, destination, purpose, travel mode, and lifecycle.
- **Vehicle:** A road user with a physical footprint, movement state, and applicable traffic rules.
- **Venue:** A meaningful destination such as a workplace, shop, school, sports field, railway station, arena, or leisure location.
- **Event:** A scheduled occurrence that changes demand around a venue.
- **Demand model:** A source of plausible population activity based on game time, weekday, season, weather, and events.

Reuse existing equivalents where they already exist. Introduce new abstractions only when they clarify ownership and eliminate duplicated logic.

### Core invariants

- A person's activity and destination must not change randomly while they are executing a valid trip.
- A person must not exist simultaneously in incompatible lifecycle states, such as both walking outside and being aboard a vehicle.
- Every started trip must eventually complete, be cancelled for an explicit reason, or enter a recoverable failure state.
- Every moving NPC vehicle must have a valid movement intention and a valid route or an explicit, bounded recovery procedure.
- An NPC must never intentionally enter a known, immediate collision conflict simply because its route or destination is valid.
- Invalid or missing map information must not silently be interpreted as permission to perform a dangerous maneuver.
- Simulation decisions must remain server-authoritative and reproducible enough for automated tests.

Document ownership of lifecycle transitions and state changes to avoid manager-to-manager race conditions.

## Phase 2 — Implement believable daily and weekly city rhythms

Create or extend a server-side demand model that changes the city's activity naturally over game time.

Do not simply toggle fixed population multipliers at exact clock boundaries. Use continuous or smoothed demand curves where appropriate, with separate profiles for pedestrians, cars, parking activity, public transport connections, and venue attendance.

The initial profiles should cover the following periods. Treat these as starting points to tune against the existing simulation, not as rigid universal laws.

### Typical weekday

- **Night, approximately 00:00–05:00:** Low general activity; some late-night travel, shift workers, taxis, deliveries, and people returning home.
- **Early morning, approximately 05:00–07:00:** Activity gradually increases as workers and early commuters leave home.
- **Morning peak, approximately 07:00–09:00:** Increased commuting traffic, pedestrian movement around transit stops, and activity around workplaces and schools.
- **Daytime, approximately 09:00–15:00:** Shopping, errands, appointments, deliveries, local walking, and varied destination-based travel.
- **Afternoon peak, approximately 15:00–18:00:** Return commuting, school-related activity, shopping, and increasing leisure and hobby trips.
- **Evening, approximately 18:00–21:00:** Sports, exercise, restaurants, visits, leisure, and people returning home.
- **Late evening, approximately 21:00–00:00:** Declining general activity with continued evening journeys and night-time destinations.

### Weekly variation

Model distinct profiles for:

- Monday: the start of the working week and normal commuting.
- Tuesday–Thursday: regular working and school routines.
- Friday: normal daytime activity followed by increased evening leisure and event activity.
- Saturday: reduced conventional commuting and increased shopping, sports, recreation, and social activity.
- Sunday: generally quieter morning activity, later starts for some activities, family/leisure trips, sports, and evening return journeys.

Avoid simplistic rules that make every location or person follow the same schedule.

### Other demand modifiers

Where supported by existing data, incorporate:

- Public holidays and school holidays
- Seasonal daylight and darkness
- Weather conditions, especially rain, snow, and severe weather
- Local sporting fixtures and other scheduled events
- Venue opening hours
- Work shifts and recurring activities
- Public transport arrivals and departures where schedule data is available

Do not invent exact opening hours or schedules when authoritative data is unavailable. Provide sensible configurable defaults and document assumptions.

### Implementation requirements

- Use the existing game clock and local simulation calendar.
- Handle time acceleration correctly. Demand must be based on in-game time, not wall-clock time.
- Smooth demand transitions so traffic does not suddenly double or disappear at a single clock tick.
- Avoid independently randomizing the entire population on each update.
- Use deterministic seeds or stable per-resident random choices where appropriate.
- Distribute population updates over existing ticks or bounded batches.
- Keep existing online-map and PBF-map workflows compatible.

## Phase 3 — Make residents and pedestrian behavior destination-driven

Improve the existing resident and pedestrian systems so people appear to have plausible reasons for being where they are.

### Activity selection

Use the demand model to influence the probability and timing of activities such as:

- Going to work or school
- Returning home
- Shopping and running errands
- Walking for recreation
- Exercising outdoors
- Visiting sports facilities
- Attending arena or other public events
- Visiting leisure destinations
- Connecting to public transport
- Entering or leaving parked vehicles

Use the actual destinations available in the loaded world. Prefer suitable nearby destinations rather than selecting arbitrary coordinates.

If the map lacks a suitable destination or route, fail gracefully and select another valid activity.

### Persistent activity lifecycle

Implement or verify explicit transitions such as:

`AT_HOME → PREPARING → TRAVELLING → AT_DESTINATION → RETURNING → AT_HOME`

Use equivalent existing state names if the code already has a lifecycle model.

Not every activity needs every state, but transitions must be valid, observable, and testable.

Ensure that:

- Trips have explicit start, progress, completion, cancellation, and failure states.
- A person cannot be materialized outside while still marked as aboard a vehicle.
- Boarding and alighting are atomic from the perspective of other managers.
- Completed or cancelled trips do not leave stale reservations, passengers, or vehicle references.
- Failed trips can be retried without causing endless spawning or repeated identical failures.
- Activity selection does not repeatedly send people to the same unreachable destination.
- Pedestrian movement respects available pedestrian paths and the relevant traffic-safety rules.
- Pedestrian activity remains consistent with the time of day and weekday.

Keep activity selection separate from movement execution and rendering.

## Phase 4 — Integrate sports and public events into one event model

The existing Liiga arena crowd functionality is a foundation, not a separate special case to replicate for every new event.

Create or extend a shared event representation with, as applicable:

- Stable event identifier
- Event category
- Venue and entrance locations
- Scheduled start and end times
- Expected attendance
- Arrival and departure distributions
- Expected travel-mode distribution
- Accessibility and route constraints where supported
- Optional event-specific demand profiles

Integrate the existing arena crowd and fixture systems with this model without breaking current behavior.

### Required event behavior

For a scheduled hockey match or other major event:

1. Attendance grows as the event approaches.
2. People travel toward the venue before the event.
3. Pedestrians use appropriate entrances and nearby walking routes.
4. Road traffic increases plausibly in the surrounding area.
5. Parking demand increases where parking locations are available.
6. Taxi demand reflects arrivals and departures.
7. During the event, the surrounding area reflects the venue's activity.
8. After the event, attendees leave over a configurable time distribution rather than all at once.
9. The crowd eventually dissipates, and the area returns toward its ordinary demand profile.

Avoid teleporting entire crowds into existence at the venue or keeping event crowds active indefinitely.

### Extend beyond hockey

Where data and suitable map features exist, support:

- Scheduled sports training at outdoor fields and sports facilities
- Recurring amateur sports activities
- Other scheduled venue events
- Public transport connections associated with event arrival and departure times

Do not pretend that all sports fields have known real-world schedules. Generate plausible configurable recurring activities when real schedules are unavailable, and distinguish generated schedules from verified external fixtures.

Respect the current map's actual venue locations and available routes. Do not create fictional buildings or change the underlying map to force event behavior.

## Phase 5 — Make NPC road traffic safe and rule-compliant

This is a critical workstream. Follow `docs/finnish-npc-traffic-law.md`, but also verify that its rules and exceptions are consistent with applicable Finnish traffic law. Do not assume that a heading comment alone establishes legal correctness.

The purpose is not merely to make NPCs appear compliant. Their movement decisions must avoid foreseeable conflicts, and their recovery logic must not create dangerous or physically impossible maneuvers.

### 5.1 Predictive collision avoidance

Audit existing nearest-vehicle, forward-cone, intersection, and collision-checking logic.

Where necessary, improve it using:

- Actual vehicle dimensions and orientation
- Predicted movement over a short time horizon
- Braking distance and reaction margins
- Swept vehicle footprints or another appropriate geometric conflict test
- Relevant vehicles approaching from intersecting directions
- Vehicle speed and acceleration limits
- A safe stopping position before a conflict point

A centre-point or narrow forward-cone check is not sufficient for long vehicles, angled approaches, turning vehicles, or cars that are already stopped.

A vehicle must not proceed merely because the nearest vehicle is outside a centre-point detection cone if the two predicted paths overlap.

Use existing spatial indexes to find nearby candidates. Avoid comparing every vehicle with every other vehicle globally.

### 5.2 Intersections and right of way

Use road-network connectivity and the actual approach and intended movement wherever that information is available.

Handle and test:

- Uncontrolled intersections
- Priority roads and applicable priority signs
- STOP signs
- Give-way signs
- Traffic lights, including red, yellow, and green phases
- Left and right turns
- Opposing traffic during turning
- Roundabouts and their entry/exit conflicts
- Pedestrian crossings
- Long vehicles whose bodies remain in the intersection longer
- Queues and vehicles stopped near junctions

Distinguish the approach lane, conflict point, intended exit, stop line, and applicable sign or signal. Do not rely solely on a heading ray or a generic “next way” property if the current route changes ways during a turn.

If the map lacks sufficient information to establish safe priority, use conservative behavior rather than inventing a right of way.

Prevent vehicles from entering an intersection when there is insufficient space to clear it safely, where applicable to the existing road model.

### 5.3 Speed, following distance, and stopping

Ensure that NPCs:

- Respect the applicable speed limit and road conditions.
- Maintain a safe following distance.
- React to stopped or slowing vehicles early enough to stop safely.
- Do not accelerate into an occupied conflict area.
- Do not oscillate continuously between acceleration and braking.
- Respect appropriate vehicle-specific handling and braking behavior.

Use predictable and smooth speed control rather than abrupt reactions that cause collisions or visual jitter.

### 5.4 Lane discipline and road geometry

Audit route following, lane placement, turns, and road-footprint validation.

Vehicles must not casually cut across conflicting lanes, drive through buildings or curbs, or take shortcuts across the map to reach their destinations.

Preserve the road and lane geometry already represented in the existing OSM-based model.

Use the actual vehicle footprint in safety-critical checks, especially for long vans, buses, and trucks.

When geometry or route data is insufficient, the vehicle must stop or choose a safe alternative rather than continue through an invalid pose.

### 5.5 Pedestrian crossings

Make pedestrian crossing behavior consistent with the Finnish rules documented in the repository.

Ensure vehicles approach crossings at a speed that allows them to respond to pedestrians and do not continue through a known occupied crossing conflict.

Pedestrian pathing and vehicle yielding must share consistent crossing geometry or compatible conflict-point definitions. Avoid two independent systems making contradictory decisions about the same crossing.

### 5.6 Recovery, reversing, and deadlocks

Audit the full lifecycle of stuck-vehicle detection, recovery route searches, reversing, parking, and trip continuation.

Recovery must be a bounded state machine, not an endless loop.

For every recovery attempt:

- Record why the vehicle became stuck.
- Track measurable progress, such as distance to destination or route progress.
- Determine whether a valid forward route exists before choosing to reverse, where applicable.
- Verify reverse clearance using the actual vehicle footprint and relevant surrounding traffic.
- Never reverse into a pedestrian, occupied lane, intersection conflict, or known obstruction.
- Limit repeated attempts at the same failed maneuver.
- Use a safe wait, alternative route, reroute, or explicit trip failure when recovery is not possible.
- Ensure a vehicle cannot remain indefinitely in alternating `STUCK`, `WAITING`, and `REVERSING` states without progress.

Recovery route searches and other expensive operations must have bounded scheduling and must not monopolize a simulation tick.

Do not treat a timed-out route search as proof that no route exists. Represent timeout, unreachable destination, and invalid route as distinguishable outcomes.

If the system cannot determine that a maneuver is safe, the vehicle should remain stopped until a safe action becomes available.

### 5.7 Resident and vehicle lifecycle integrity

Audit interactions among residents, pedestrians, drivers, passengers, parked vehicles, and moving NPC vehicles.

Pay particular attention to cases where one manager removes an entity and another manager subsequently recreates it based on a missing-list entry.

Enforce a single authoritative lifecycle transition for boarding, alighting, despawning, spawning, parking, and trip completion.

Add regression tests that advance all relevant managers through multiple complete update cycles. Unit tests of an individual method are not enough to prove the full lifecycle is correct.

## Phase 6 — Build an automated Finnish traffic acceptance suite

Create a dedicated test suite based on `docs/finnish-npc-traffic-law.md` and the actual supported road-network model.

At minimum, add deterministic tests for:

1. A vehicle stopping at a red traffic light.
2. Correct handling of a yellow light based on the existing documented rule model.
3. A vehicle obeying STOP and give-way controls.
4. Conflicting traffic at an uncontrolled intersection.
5. A left turn yielding to relevant opposing traffic.
6. A roundabout entry and exit conflict.
7. A vehicle yielding correctly at a pedestrian crossing.
8. A vehicle stopping behind an already stopped vehicle without hitting it.
9. A long vehicle avoiding a collision despite its centre point clearing the other vehicle.
10. A vehicle unable to enter a blocked intersection.
11. A safe response when a route is missing or route search times out.
12. A blocked vehicle recovering without endless reversing.
13. Reverse movement stopping when the actual vehicle footprint cannot clear the maneuver.
14. Correct handling of parked, boarding, alighting, and despawned residents.
15. Correct behavior when one resident trip fails but other trips continue.
16. Correct behavior for multiple NPC vehicles approaching the same conflict point.
17. Traffic signals, right of way, and vehicle movement remaining consistent over several consecutive simulation ticks.

Tests must verify trajectories and state transitions, not just return values from individual helper functions.

Where appropriate, test both short and long vehicle dimensions.

Use fixed seeds and minimal reproducible road layouts for deterministic unit and integration tests.

Do not make tests pass by weakening collision assertions or silently skipping problematic scenarios.

## Phase 7 — Validate city rhythms and event behavior

Add deterministic tests for:

- Different traffic and pedestrian demand at night, during the morning peak, daytime, and evening.
- Weekday versus Saturday and Sunday behavior.
- Smooth transitions between adjacent demand periods.
- Correct use of accelerated in-game time.
- Stable resident activity and destinations across consecutive updates.
- Correct trip completion and return-home behavior.
- Venue activity increasing before a scheduled event.
- Event arrivals and departures being distributed over time.
- Event attendance not remaining permanently active after the event.
- Taxi demand responding to event arrivals and departures.
- Missing venue data or unavailable routes being handled safely.
- Seasonal and weather modifiers not producing invalid or extreme demand.

Tests should verify relative trends and valid state transitions, not impose arbitrary universal population numbers.

## Phase 8 — Observability and long-running simulation tests

Introduce or extend low-overhead diagnostic counters for:

- NPC trips started, completed, cancelled, and failed
- Collision events and near-conflict events, where measurable
- Traffic-rule violations detected by the simulation
- Vehicles entering recovery
- Recovery attempts and successful recoveries
- Vehicles with no meaningful progress over a configurable interval
- Residents stuck in inconsistent lifecycle states
- Pedestrian and vehicle activity by time period
- Event attendance, arrivals, departures, and associated taxi demand

Use existing diagnostics facilities where available. Avoid unbounded logging on every simulation tick.

Create a reproducible long-running test scenario that includes multiple intersections, traffic signals, pedestrian crossings, parked vehicles, long vehicles, residential destinations, and at least one scheduled venue event.

Run the simulation long enough to expose repeated recovery loops and lifecycle errors. Record the seed, duration, test scenario, and relevant metrics.

Compare results against the baseline from Phase 0. Clearly distinguish a genuine improvement from an unverified assumption.

Do not claim zero collisions in all possible gameplay scenarios merely because a finite test run completed without one.

## Phase 9 — Performance and compatibility guardrails

The PBF stuttering problem is explicitly out of scope.

However, the new systems must not introduce avoidable performance regressions.

- Reuse existing spatial indexes and cached road-network data.
- Avoid global scans for every NPC on every update.
- Avoid performing route searches synchronously for every resident at once.
- Schedule noncritical activity selection and route planning in bounded batches.
- Keep immediate collision avoidance and safety checks responsive.
- Avoid duplicating existing event, calendar, resident, and traffic managers.
- Ensure demand changes do not trigger a mass respawn of NPCs.
- Ensure the same world can continue to operate with the existing online-map workflow.
- Add measurements for any newly introduced recurring work.

Do not reduce safety checks or make vehicles ignore hazards to improve FPS.

## Phase 10 — Documentation and delivery

Update relevant documentation to describe:

- The final simulation architecture and ownership boundaries
- The demand model and its configuration
- Resident and trip lifecycle states
- The event model and venue requirements
- NPC traffic decision-making and recovery rules
- Known limitations when map geometry or traffic controls are missing
- Test commands and reproducible scenarios
- Before/after measurements and any remaining known defects

Keep documentation aligned with the actual implementation. Remove or revise obsolete claims where justified, but do not delete historical reports simply because newer measurements differ.

When implementation is complete:

1. Run the focused traffic and lifecycle tests.
2. Run the demand, event, and calendar tests.
3. Run the relevant broader regression suite.
4. Run linting, formatting, and type checks supported by the project.
5. Investigate and fix regressions introduced by the changes.
6. Summarize the changes, tests, measurements, and remaining limitations.
7. Commit changes in coherent, reviewable commits.
8. Push the working branch to the existing remote if the repository environment permits.
9. Do not create or push Git tags.

If the full scope is too large for one uninterrupted implementation session, implement complete, tested vertical slices in this order rather than leaving a broad collection of unfinished changes:

1. Traffic safety and lifecycle correctness.
2. Daily and weekly demand model.
3. Persistent resident trips and destination behavior.
4. Shared venue-event integration.
5. Long-running validation and performance review.

Do not claim the entire mission is complete if any of these stages remain unfinished. Clearly state what was implemented, what was tested, and what remains.

## Definition of done

The work is complete only when:

- The city has distinguishable and believable daily and weekly activity patterns.
- Residents have persistent, plausible activities and destinations.
- Event arrivals, attendance, departures, surrounding traffic, and taxi demand are connected.
- NPC vehicles use predictable, physically plausible movement and bounded recovery.
- Safety-critical decisions account for vehicle dimensions and foreseeable path conflicts.
- The documented Finnish traffic-rule scenarios have automated tests.
- Resident, passenger, pedestrian, and vehicle lifecycles survive complete multi-manager update cycles.
- Long-running tests provide measurable evidence of improved stability.
- Existing gameplay and online-map behavior remain functional.
- No attempt has been made to fix the explicitly deferred PBF stuttering problem.
- The final report accurately distinguishes verified improvements from remaining risks.
