# Fast through-traffic never parks on the motorway

## Goal
A motorway/trunk through-trip (law § 37: no ordinary stop/parking on a
motorway) must never end PARKED on the road; at its final point it is retired
if out of view, otherwise it keeps moving.

## Files to change
- `src/theroadragetrip/npc.py`
  - NPC vehicle/driver state: add a bool `fast_through` (default False), set True
    in `_motorway_spawn_steps` (~6101) after `_motorway_through_steps` returns a
    plan. Trunk spawns that go through the same path get it too.
  - `update_state` at_destination branch (~3399): if `fast_through`, never assign
    `NPCState.PARKED`; use ARRIVING-free state (stay DRIVING) and do not ramp
    target speed to 0 for it (check the ~3350 ramp and ~3326/3449
    `at_destination and footprint_clear` stops, which must skip `fast_through`).
  - New `_retire_finished_through_traffic(self, resident_manager, viewport_bounds)`
    modelled on `_retire_finished_line_buses` (~4671): for vehicles with
    `fast_through` that reached the final waypoint (route exhausted /
    within NPC_ARRIVAL_RADIUS_M), if `viewport_bounds is None` or not
    `_point_in_viewport`, call `retire_vehicle(vehicle, residents)` (~7044).
    Call it from the same per-tick place as the line-bus retire.
    Cost O(vehicles) with a cheap flag filter; no new caps.
- No client/Godot change.

## Behaviour / acceptance criteria
1. A `fast_through` vehicle whose job is finished is never in state PARKED, on
   any tick, in or out of view.
2. Reaching the end out of view: vehicle is removed from `vehicles` via
   `retire_vehicle`; its route job, parking reservation and resident links are
   released (same cleanup as `discard_outside`; `_drop_vehicles` closes jobs).
3. Reaching the end while in view: vehicle is not removed and keeps moving
   (speed stays > 0.05 m/s); it is retired on the first tick it is out of view.
4. A vehicle ending its trip at the end with no further road still does not stop
   on the carriageway (it may only be retired when out of view; none are
   teleported).
5. Non-through vehicles (ordinary local trips, line buses, legal parking at
   destinations) behave exactly as before: still PARKED at destination; line-bus
   retire unchanged.
6. Retire scan is O(vehicles) per tick with no per-vehicle route/graph work; no
   change to spawn caps or counts.
7. Headless repro (scratchpad `repro_motorway.py`, 60 s at 56 m/s, Keep Lane on):
   zero vehicles PARKED on the motorway (van 214 case) and the through cars
   past their end are gone from `vehicles`.
8. Visual: `motorway_through_traffic` scenario (Keep Lane on) passes its
   readiness checks; screenshot shows no stationary cars on the motorway.

## Tests to add
`tests/test_motorway_through_no_park.py`
- `test_through_trip_at_destination_not_parked`: place a `fast_through` vehicle
  at its final node, speed ~0 / near target, step `update_state`; asserts state
  != PARKED. Fails before: branch sets PARKED at speed < 0.05.
- `test_through_trip_retired_out_of_view`: finished `fast_through` vehicle,
  viewport elsewhere; run the retire pass; asserts it is gone and its job closed.
  Fails before: no retire exists.
- `test_through_trip_kept_in_view`: same but viewport contains it; asserts still
  present and not PARKED.
- `test_local_trip_still_parks`: non-flagged vehicle still ends PARKED (guards
  criterion 5).
- `test_spawn_flags_fast_through`: `_motorway_spawn_steps` placed vehicle has
  `fast_through` True; ordinary spawn False.

## Out of scope
Changing trip length (300-600 m), new vehicle caps, ferry through-trips,
parking legality for non-motorway roads, client rendering.
