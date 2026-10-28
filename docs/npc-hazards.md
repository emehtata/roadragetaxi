# NPC hazards: stuck taxi, stopped and crashing NPCs (2026-10-28, in progress)

Report: the player crashed into a rival taxi standing on Haukiputaantie (a
60 km/h secondary road, on a bridge) in Oulu and was stuck inside it. Asked:
remove such stucks and hazardous NPC driving; iterate until none are found.
Iteration was stopped here on request; this is where it stands.

Screenshot: `screenshot_1793218469657999872` (Windows Pictures folder), taxi at
425213, 7217320, 15:04 on a Wednesday.

## Method

`tools/npc_hazard_probe.py` (built on the repro-at skill) loads the real map
around a point and ticks the simulation for 10-20 game minutes with the player
standing there. It reports every NPC crash with what the vehicles within 8 m
were doing just before, every NPC standing still on a car road for 20 s or
more, and vehicles parked beside a road at more than 15 degrees to it.

The snapshot alone could not say why the rival taxi had stopped: any crash
removes the NPC's driver, so `has_driver: false` was a result of the player's
crash, not its cause. The probe found the mechanisms around that spot instead.

## Fixed (with tests)

| Problem found | Cause | Fix |
| --- | --- | --- |
| Taxi stuck inside a wreck it hit | the collision response put the taxi back to its last pose, itself overlapping, every frame | `npc._check_vehicle_collision`: a taxi already in a vehicle may move if not going deeper into it (as at buildings and posts); pressing on is still stopped. Test: `test_the_taxi_backs_out_of_a_wreck_it_is_stuck_in` |
| Rear-end pile-ups behind a stopped car in a bend | the route lookahead saw only wrecks and parked cars; the straight cone missed a queue around the bend until a few metres short | `_stalled_vehicle_on_route` also takes slow vehicles and those going the same way (not oncoming) |
| A parked taxi pulled out in front of a truck at 36 km/h | no check for traffic when setting off | `_traffic_approaching`: a vehicle still setting off (below 1.5 m/s, near its trip origin) waits while anything would reach it within 5 s (§ 25 entry from parking; §§ 3-5). A lawful wait: no stuck recovery |
| Two NPCs touching at walking pace became wrecks blocking the road | every contact was a crash | below `NPC_SCRAPE_MPS` (5 km/h) both stop apart and go on. Test: `test_npcs_touching_at_walking_pace_scrape_and_go_on` |
| Kerb-parked cars at 20-30 degrees, rear in the lane | the pull-in route ended on its diagonal | `_roadside_pull_in` ends with a 3.5 m run along the kerb (`ROADSIDE_KERB_RUN_M`); measured 26 -> 16 degrees at the report's spot |
| A bus stopped behind a parked car never passed it | its stop gap was a car's: no room for a 12 m nose to swing out | the stop gap behind a standing vehicle grows with the vehicle's own length |
| Cyclists rode into parked cars | a 1 m-wide lead cone; a car angled to the road has its centre 2 m off the line | `cycling.vehicle_on_line`: the other vehicle's oriented extent across the line |
| Cyclists stopped behind a kerb-parked car for good | no passing | `_swing_past`: on a carriageway, pass a parked car or wreck on its left (§ 18), near end then far end, held until past, not with oncoming traffic within 30 m; still following anything else on that line. Test: `test_a_cyclist_rides_around_a_car_parked_at_the_kerb` |
| Cyclists head-on on route connectors | connector legs (no way) had no keep-right offset | `offset_route` keeps right on them too |
| Cyclists head-on on narrow paths | 0.25 m keep-right each on a 1.5 m path | `_oncoming_near`: each keeps 0.55 m further right while meeting. Test: `test_cyclists_meeting_on_a_narrow_path_pass_each_other` |
| Right-hand-rule gridlock at unsigned crossings | each car waited for the one on its right, in a circle | game policy (guide, "Junctions and yielding"): after 3 s, the car that has waited longest (then the lower id) disregards a stopped, itself-yielding car on its right; the rest keep yielding to it, so two conflicting cars never enter together (`traffic_rules._waited_longer`) |

Existing tests whose overlapping vehicles stood still now give them a speed
(`_driving_vehicle` drives at 8 m/s), since a standing overlap is a scrape.

## Probe results after the fixes (10-20 game minutes each)

| Place, time | Crashes | Still >= 20 s on a road |
| --- | --- | --- |
| Report's bridge (425213, 7217320), Wed 15:04 | 0 | 0 |
| Same, 17:00 | 0 | 0 |
| Oulu centre (427872, 7211248), Fri 17:00 | 0 | 0 |
| Oulu centre, Sat 23:30 | 0 | 0 |
| 426500, 7212800, Fri 08:00 (cycleways) | 15 before the path fixes, not rerun | 0 |
| Korjaamontie (429000, 7212500), Fri 16:00 | 5 before the gridlock fix, not rerun | 23 before the gridlock fix, not rerun |

## Open (next iteration)

1. **Rerun** the probe at 426500, 7212800 and 429000, 7212500 with all fixes.
2. **Korjaamontie junction:** a truck turning onto Paulaharjuntie at a signal
   hit a car coming along Korjaamontie at 7 m/s; check the green-light
   turning conflict (the guide notes green lacks full turning-conflict
   evaluation, `traffic_rules.decide_traffic_action`).
3. **Held vehicles:** "recovery failed - no validated route" keeps a vehicle on
   the carriageway for up to ~100 s (`NPC_HOLD_RETRY_TICKS` x
   `NPC_HOLD_GIVE_UP_ATTEMPTS`, growing) before it is removed. Consider a
   shorter give-up for a vehicle standing in a lane.
4. **Turning rear-end:** one car turning behind another that waited for a
   cyclist ran into it at 2.7 m/s (seen once at the bridge before the route
   lookahead change; not seen since).
5. **Flaky test, pre-existing:**
   `test_household_vehicle_ownership_persists_through_a_full_trip_cycle` fails
   for some random seeds on the original code too (e.g.
   `--randomly-seed=3294339365`): a car parking at a kerbside spot 10 m after
   a corner (`ROADSIDE_JUNCTION_CLEARANCE_M`) has no room to straighten out
   and drives off the road. Raising the clearance to 16 m fixed that seed but
   broke six tests built on shorter segments, and the seed then failed
   differently: leaving its kerbside spot the car was stopped by
   `_enforce_npc_road_motion` ("road boundary - awaiting validated route").
   Needs: room for the pull-in measured from the actual junction, and a look
   at the departure corridor (`_npc_parking_access`).
6. Review the traffic changes with the `traffic-law-reviewer` agent (not yet
   done).

## Checks run

The full Python suite passes apart from the flaky test above. The Godot suite
was not affected (no client changes). New and changed tests: see the table.
