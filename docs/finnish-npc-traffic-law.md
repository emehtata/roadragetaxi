# Finnish traffic law for NPC implementation agents

## Authority and scope

Primary source: [Tieliikennelaki 729/2018, consolidated Finnish text](https://www.finlex.fi/fi/lainsaadanto/2018/729).
Reviewed **2026-10-14**. The retrieved page identifies its consolidation as
**2026-04-17** in its ELI identifier. Use the current consolidated act, not the
repealed 267/1981 act or the original 2018 PDF. Check amendments and commencement
dates before changing a legal rule. The Finnish source controls this paraphrase.

Read this guide before changing NPC driving, pedestrian interactions, routing,
parking, traffic controls, emergency response or ploughing. It defines desired
behavior, **not certification that the current game already follows the law**.

**Law** means the requirement in the cited sections/annexes. **Game policy** means
an explicit simulation choice. **Implementation guidance** means engineering
advice, not a statutory algorithm, distance or timer. Keep these separate.

Scope is road-user behavior relevant to this game. Administrative processes,
fine amounts, transport permits, detailed load/mass tables and equipment
certification are not reproduced. For such features, read chapter 5 and the
technical annexes; chapters 6–7 govern enforcement and exceptions. Licensing and
criminal drink-driving rules also involve other legislation. Do not invent them.

## Before implementing a rule

1. Read the applicable Finnish section and annex in Finlex, including exceptions.
2. Identify user category, maneuver, approach, lane, map level and controlling
   devices. Inspect the connected server code and tests, not just a screenshot.
3. Implement shared server decisions. Godot draws server state; it must not
   independently decide legal priority.
4. Test approach, braking, waiting, safe passage and resumption with real update
   loops. Preserve collision checks and performance budgets.
5. Report unsupported cases. A passing geometric helper test is not general legal
   compliance, and rendering a sign does not implement its rule.

## Safety and control precedence

Law: §§ 3–5 require care, anticipation, vehicle control and speed/distance adapted
to visibility, weather, surface and load. Stop within the visible road and in
foreseeable situations. Priority never authorizes a collision.

Law: [§ 8](https://www.finlex.fi/fi/lainsaadanto/2018/729#chp_3__sec_8)
puts controller instructions first. A traffic-control device may override a
general rule. A functioning traffic light overrides a device assigning yielding
obligations, **not** speed limits, access restrictions, turning duties or safety.

Implementation guidance:

- Bind a sign/signal to its approach, lane, direction and level. Nearby controls
  for the opposite direction or another layer do not govern this vehicle.
- Honor temporary controls and supplementary plates: direction, scope, time,
  category and priority direction matter. Under § 85, visible temporary yellow
  longitudinal markings override simultaneously visible white ones.
- Unlit signals and flashing yellow do not mean green: apply remaining signs and
  general rules, with particular caution (annex 2).
- Resolve allowed maneuvers and priority, then combine safe-speed constraints.
  A permissive decision cannot remove a pedestrian, rail or blockage constraint.
- Compute braking from actual speed and available grip, including ice and snow.
  Do not substitute the posted/cruise speed for actual speed on yellow.
- A legal wait must not trigger stuck recovery, reversing or illegal passing.

## Junctions and yielding

Law: [§§ 24–25](https://www.finlex.fi/fi/lainsaadanto/2018/729#chp_3__sec_24),
§ 28 and annex 3.2.

| Situation | Required behavior |
| --- | --- |
| Equal priority, without applicable controls/special entry duty | Yield to conflicting vehicles approaching from the right. An unsigned T-junction does not give the geometrically straight road priority. |
| Turning | Yield to pedestrians, cyclists and moped riders crossing the road into which the vehicle turns. |
| Left turn | Also yield to conflicting oncoming traffic. |
| Leaving the carriageway | Yield to pedestrians, cyclists and moped riders using the carriageway or shoulder. |
| Entry from yard, parking area, petrol station, similar area or off-road | Yield to other road users from either direction, even when coming from their right. |
| Entry from a path/comparable minor road; departure from living/pedestrian street | Apply § 24(3)'s special duty, not ordinary right-hand priority. |
| Crossing a sidewalk/cycleway | Yield to its users; then separately yield to carriageway traffic when entering after the crossing. |
| Entering/crossing a living or pedestrian street | Yield to its users. |
| B5 give-way | Yield to relevant crossing vehicles/trams from both sides; retain turning duties. Stop if necessary. |
| B6 STOP | Completely stop at the stop line even with no traffic. Without a line, stop immediately before the junction where visibility is good; then yield as for B5. At a railway crossing, stop at the sign as annex 3.2 specifies. |
| B1 priority road, B2 end, H22 priority direction | Apply the actual signed continuing/ending/turning direction. Road width, name, class and straightness do not establish priority. |
| Roundabout with B5 and D2 | Yield on entry to relevant circulating traffic. On exit, yield to crossing pedestrians, cyclists and moped riders; signal the exit (§§ 24, 48). `is_roundabout` alone is not all legal evidence. |
| Blocked exit | Do not enter in a manner that would obstruct crossing traffic if stopped inside (§ 28). |

§ 25 requires showing the intent to yield early by slowing or stopping. Keep the
entire vehicle outside the conflict area and proceed when the conflict clears,
not when an arbitrary timer expires.

Implementation guidance: use connected approaches and actual conflicting
movements, including turning paths and already-occupied conflict areas. Infinite
heading rays alone are insufficient. Account for vehicle size and swept motion.
Parked cars, adjacent lanes and vertically separated bridges do not claim
crossing priority. Vehicle IDs, spawn order, horns and anger do not assign it.
Gridlock resolution is a game policy, must remain collision-safe, and must not
silently reverse legal priority or let conflicting vehicles enter together.

## Traffic lights

Law: § 74 and [annex 2](https://www.finlex.fi/fi/lainsaadanto/2018/729).

| Signal | Required behavior |
| --- | --- |
| Red or red+yellow | Stay behind the controlling primary signal/stop line. Red+yellow prepares for green; it is not permission to cross. |
| Green | May pass only with safe exit space and remaining duties satisfied: lawful pedestrians still crossing, turning conflicts and left-turn oncoming traffic. |
| Yellow | Stop unless already too close to stop safely without danger or hindrance at the green-to-yellow change. |
| Arrow | Applies to its movement; do not treat it as permission for a different route. |
| Flashing yellow or unlit | Apply other controls/general rules with extra caution. |
| Flashing red | Do not pass the signal/stop line. |
| Lane signal | Respect red-cross closure and the indicated lane direction. |

Do not infer an exclusively protected left turn from any green light. Protection
requires actual phase/movement evidence; otherwise retain statutory turning
duties. A signal for one lane must not control another.

## Pedestrians, cyclists, buses and rail

Law: §§ 11, 13–16, 24, 26–29.

- Approach a pedestrian crossing at a speed permitting a stop before it. Give
  unobstructed passage to pedestrians on it **or preparing to enter it** (§ 27).
- Stop before passing a vehicle stopped at a crossing, unless a refuge island or
  free lane separates the vehicles as § 27 describes. For other visibility
  obstruction, slow and stop when necessary.
- A mounted cyclist does not automatically gain pedestrian priority from a zebra
  crossing alone. Evaluate cycle controls, B5/B6/B7, turning and driveway duties.
  A person walking a bicycle is a pedestrian.
- Give safe space and particular care to children, elderly/disabled people,
  school transport, stopped buses and trams (§ 29).
- Yield to a bus signaling departure from its stop on a road limited to at most
  60 km/h when approaching in the same/adjacent lane; include § 26's adjacent
  cycle-lane case. The threshold is the road limit, not current speed. Preserve
  boarding/alighting passage (§ 24).
- Give trains unobstructed passage. Approach a level crossing cautiously even
  with barriers. Do not enter with an approaching train, active stop signal,
  warning sound or lowered/moving barrier. Stop safely before the tracks and
  cross without delay when permitted (§ 11).
- Do not treat a road under a railway bridge as a level crossing. Tram priority
  has statutory exceptions; consider its controls and applicable rules.
- Pedestrian residents use sidewalks/shoulders and lawful crossings. § 13 generally
  uses the carriageway's left edge if walking there becomes necessary, with
  exceptions. Their presence remains an input to vehicle safety decisions.

## Speed, lanes, passing and recovery

Law: §§ 5, 9, 18–23, 30–35, 43–46, 58–62, 99; annexes 5.1–5.2 for vehicle limits.

- Respect signed limits and vehicle-specific limits. Unsigned general limits
  are 50 km/h in built-up areas and 80 km/h outside (§ 9). Road category/building
  density alone is not proof of the legal built-up-area boundary.
- A limit is a maximum, not an unsafe-condition target. Reduce speed and increase
  following gaps in snow/ice, poor visibility, bends and with load. § 20 requires
  distances that prevent rear-end collisions.
- Use the carriageway and lawful right-hand lane; honor one-way, access,
  permitted-turn and lane restrictions. Position early for turns (§§ 18–22).
- Yield to oncoming traffic when an obstruction lies on our side (§ 30). A wreck
  does not authorize entry into an occupied opposing lane.
- Passing needs sufficient visibility, clear lane, safe clearance and a safe
  return. Apply § 32's crossing/junction/level-crossing prohibitions and stated
  exceptions, plus no-passing signs and solid lines (annexes 3.3 and 4.1).
- Reverse, turn around, depart the road edge or change lanes only safely and
  without unnecessary hindrance (§§ 34–35). Check pedestrians/vehicles behind.
- On a living street, give pedestrians passage, adapt to walking speed, never
  exceed 20 km/h, and use marked ordinary-car parking spaces (§ 43).
- Pedestrian-street motor access is restricted by § 44; do not invent ordinary
  through routes or parking. Permitted driving follows walking speed, at most
  20 km/h. On bicycle streets, give cyclists passage and adapt to cycling (§ 45).
- Motorway/motor-traffic-road entrants yield to traffic already on the road.
  No reversing/U-turns; use lawful ramps and lanes. § 58 excludes vehicles whose
  maximum permitted or design speed is **at most 70 km/h**, subject to its specific
  exceptions. The game's ordinary 60 km/h tractor is not motorway traffic.
- A signed tunnel prohibits reversing/U-turns and allows stopping/parking only
  in an emergency. Headlights are required; shut down for prolonged stops (§ 46).

Implementation guidance: distinguish lawful traffic waits from failed routes.
Recovery cannot bypass queues, sidewalks, barriers, crossings or rail hazards.

**Game policy (2026-10-15):** ordinary NPC travel must stay on the carriageway.
An obstacle does not automatically authorize an off-road bypass: require a
demonstrably necessary, otherwise-unavoidable, safe and lawful maneuver. Until
that maneuver is validated, stop/reroute rather than drive across open ground.
Keep verified parking/driveway access distinct from ordinary travel; an arbitrary
generated yard destination is not proof of access permission. See § 18's limited
exception for other parts of the road; it is not blanket permission to leave the
road or use pedestrian space.

## Parking and passenger stops

Law: [§§ 36–41](https://www.finlex.fi/fi/lainsaadanto/2018/729#chp_3__sec_36),
§§ 43–46; annexes 3.3, 3.5, 3.8 and 4.1–4.3.

Distinguish parking, brief boarding/alighting/loading stops, and compulsory
traffic waits (§ 2). Hazard lights never legalize a chosen stop.

| Constraint | Required behavior |
| --- | --- |
| Roadside placement (§ 36) | Parallel, close to edge, safe and unobstructing. Right side is the general rule; one-way roads and safe/non-obstructing left-side parking in built-up areas have allowances. Game policy may consistently choose right-side parking. |
| Sidewalk, zebra, cycleway/crossing (§ 37) | No ordinary motor-vehicle parking or stops; distinguish the limited legal stopping exception below. |
| Before pedestrian/cycle crossing (§ 37) | Keep the five-metre approach-side exclusion; do not replace the directional rule with a symmetric radius. |
| Intersection (§ 37) | No stop/parking inside it or on the carriageway within five metres of the crossing carriageway's nearest edge/projected edge. An OSM polyline vertex is not that edge. |
| Rail (§§ 37–38) | Never obstruct rail; parking is forbidden within 30 metres of a railway level crossing. Parking and stopping rules differ. |
| Other places (§ 37) | Reject underpasses/tunnels, roundabouts, cycle/bus lanes, hidden signs/signals, dangerous crests/bends and obstructed lane-positioning areas. Honor the solid-line three-metre-clearance condition and its broken-line exception. |
| Access/bays (§ 38) | No blocked driveways, other cars' access/departure, rescue roads or double parking. Entire vehicle inside its designated bay; use designated spaces in parking areas and honor category restrictions. |
| Controls | Honor no-stopping/no-parking signs, zones, supplementary times/categories, payment and time limits. § 40 governs parking-start indication; do not reset it while still parked. |
| Motorway (§ 37) | Ordinary stops/parking only in designated facilities and the specified bus-stop passenger case, not a convenient shoulder/ramp. |

**Legal exception:** § 37 narrowly permits brief sidewalk/cycleway stopping for
boarding/alighting or loading/unloading with compelling reasons, no suitable
nearby alternative, no unreasonable obstruction, and the driver nearby and ready
to move. It is not parking permission. Cycle/moped and authorized parking-permit
cases have separate exceptions.

**Game policy:** ordinary motor-vehicle NPCs and taxis must not select sidewalk or
pedestrian/cycle-path parking **or passenger stops**. Do not implicitly enable that
exception, disabled/home-care permits or servicing roles. Add special roles only
when explicitly requested and their conditions are modeled.

Validate full oriented footprints, actual vehicle dimensions and departure
access, not just centre points. Recheck asynchronous commits and actual arrivals.
§ 41 also requires securing the vehicle and safe doors/boarding/loading.
Missing map evidence is not legal permission. Prefer verified bays/lots; skip or
reroute when a legal safe spot cannot be established. A building-wall offset is
not proof of a driveway. Keep route access and parking permission separate.

## Lights, occupants and special roles

Law: §§ 7, 10–12, 17, 47–51, 55, 57, 90–95, 98, 105, 141, 144–149 and 184.

- Signal early and throughout turns, lane changes, roadside departure, roundabout
  exit and other lateral moves (§ 48). Signaling does not grant priority.
- Use driving/daytime lights when moving; headlights and taillights in darkness,
  dusk or poor visibility (§ 49). Prevent high-beam glare. Stationary-roadside
  lighting has separate duties/exceptions (§ 50); disabling parked headlight
  beams must not erase required visibility.
- Horn warnings are for danger; other horn use is restricted to overtaking
  outside built-up areas (§ 47). **Game policy:** rage/horn pull-aside is gameplay,
  not legal priority; NPC reactions must still be safe and obey controls.
- § 55 normally limits unnecessary combustion-engine idling to two minutes.
  Before departure below −15 °C the allowance is four minutes, with separate
  readiness/work exceptions. Compulsory traffic waits are not unnecessary idling.
- Do not assign an unfit/intoxicated person to drive (§ 17). Passenger condition
  is not driver condition. Respect seats/capacity, unique occupants, seatbelts and
  child restraints (§§ 90–95, 141, 144–149). Game plugin capacity includes the driver.
- Driving NPCs must not use handheld communication devices or other devices in a
  way that distracts from or endangers driving (§ 98). A phone activity belongs
  to a safely stopped driver or passenger, not an actively driving resident.
- Winter tyre duties under § 105 are weather-dependent during November–March;
  safe surface grip matters outside those months too. Month alone is insufficient.
- Give emergency vehicles using the required sound and lights unobstructed
  passage (§ 10). Police appearance or an amber beacon alone does not qualify.
  § 184 exceptions require the authorized task/conditions; controllers and
  trains remain binding.
- Active road-maintenance work has limited § 184 exceptions with special care.
  A plough still obeys yielding/speed controls, red signals and controller stop
  instructions. An idle tractor has no blanket exemption.
- After a crash, § 7 requires remaining and assisting as able; §§ 12 and 57
  require warning of dangerous obstructions in the applicable circumstances.
  **Game policy:** 60-second wreck removal is cleanup, not a legal towing deadline.
  Preserve people/occupants and collision hazards until properly resolved.

## Existing code and known compliance gaps

Inspection baseline: 2026-10-14. This is not an exhaustive audit.

| Area / entry point | Existing behavior and required follow-up |
| --- | --- |
| `traffic_rules.py:decide_traffic_action` | Basic light phases. Yellow uses cruise speed in stopping comparison; verify actual-speed handling. Green lacks full turning-conflict evaluation. |
| `traffic_rules.py:crossing_yield_decision` | Basic right-side/priority/sign checks using heading rays/timing. STOP and give-way are grouped, without an independent full-stop latch. Connected turning/entry cases are incomplete. |
| `npc.py:update_npc` | Light/crossing caps, following, corners and recovery exist. Verify vulnerable users, special entry duties, exit occupancy, control applicability and legal recovery. |
| `traffic_world.py` / NPC route validation | Verify legal access, tractor motorway restrictions, lanes and connected approaches across streamed map merges. |
| `npc.py` parking selection, walkway validation, placement and route validation | Mapped-walkway full-footprint rejection exists. Segment-end clearance is not statutory junction/crossing geometry; generic lot/yard points are not verified legal bays. Check actual large-vehicle arrival dimensions. |
| `osm/models.py`, `osm/build.py`, `world_loader.py`, `server/map_sync.py` | Controls/road metadata exist. Verify provenance, direction/lane scope and preservation on merges. Missing data must differ from confirmed absence. |
| `physics.py`, `weather.py`, `simulation.py` | Snow visuals and plough clearing exist. Verify local road snow actually affects NPC grip, safe speed and stopping distance; visual whiteness alone is insufficient. |
| `pedestrian.py`, `residents.py`, `npc.py`, `taxi.py` | Verify crossing intent, passenger access, capacity and safe departures/doors. |
| `protocol.py`, Godot entity/map layers | Show authoritative decisions. A visible sign/beacon/crossing does not implement its legal duties. |

All Python paths above are under `src/theroadragetrip/`.

## Required acceptance scenarios

For each affected group, exercise real update loops. Rotate/mirror approaches,
vary speed/dimensions, enable spatial indexing and repeat with streamed map data.

| Group | Scenarios |
| --- | --- |
| Equal priority | Right/left approach; unsigned T; wide versus narrow road; parked object; bridges; turning paths; wait then resume without collision. |
| Signs | B5 conflicts both sides; B6 complete stop without traffic; stop-line/no-line; two signed approaches; priority ending/turning; irrelevant opposite-facing sign. |
| Signals | Red/red+yellow stay behind line; green left-turn yields to oncoming and pedestrians; actual-speed yellow boundary; unlit/flashing yellow; lane arrows. |
| Entry/exit | Yard/lot entry yields even from right; sidewalk users before carriageway; blocked exit. |
| Vulnerable users | Zebra-entry intent; obscured crossing/stopped car; cyclist across car's turn; bus at 60 versus above 60 km/h; boarding passage. |
| Rail | Train approaching despite open barrier; active warning/closing barrier; safe stop/clearance; road below rail bridge. |
| Parking | Partial-body sidewalk overlap, diagonal/long vehicle, five-metre approach exclusion, actual junction edge, 30-metre rail parking prohibition, blocked driveway, bay boundaries, competing async claims. |
| Recovery/passing | Opposing traffic beside wreck, solid line, crossing, unsafe return, pedestrian behind reversing car; legal wait beyond stuck timeout. |
| Conditions/roles | Snow/ice braking, plough at red/yield, ordinary 60 km/h tractor excluded from motorway, emergency with/without active warnings, horn never changes priority. |

Use existing tests in `tests/test_crossing_priority.py`,
`tests/test_npc_sidewalk_parking.py`, `tests/test_npc.py`,
`tests/test_npc_population.py`, `tests/test_traffic_lights.py` and
`tests/test_server_headless.py` as starting points. Add behavior tests, not replicas
of a helper's calculations. Keep queries spatially bounded, not city-wide scans
each frame. Surface reason, control, conflicting user, stop position and target
speed in existing console/debug state; do not add a HUD unless requested.

World metres use +x east, +y north. For heading `h`, the driver's right vector is
`(sin(h), -cos(h))`. Godot flips y for drawing; do not determine legal left/right
in rendering coordinates.
