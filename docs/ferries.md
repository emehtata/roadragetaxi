# Road ferries

Car ferries run on their real routes, so islands with no bridge can be
reached: drive onto the deck, stop, and the ferry carries the taxi across.

## Current state

Phases 1-3 (below) are implemented: `ferries.py` (`FerryManager`), run by
the simulation each tick and drawn by the client like a train of one car
(look `ferry`). The ferry is at the landing the taxi drives to and waits
for it; navigation (local and intercity) crosses on ferries; NPC cars
arrive aboard and drive off. Timetables are left out by choice. NPC trips
do not plan across a ferry.

## Design

**Routes.** OSM `route=ferry` ways that carry cars: `motor_vehicle` or
`motorcar` `yes`/`designated`, or a road class in `ferry=*` (Vartsala:
`ferry=secondary`) unless cars are shut out (`osm/build.py:_is_car_ferry`).
In Finland's PBF (2026-11): 615 ferry ways, about 100 of them for cars.
A route is kept as a `Railway` of kind `ferry`, so it is cached and
streamed with the rails; the rail consumers (rail graph, rail grid, rail
chunks and bridges) leave it out. Some crossings are mapped as one way
each direction (Prostvik-Lillmälö): a route whose ends both lie within
80 m of another's is that one's other way and gets no ferry of its own.

**The ferry.** 50 x 12 m, one per route within 2.5 km of the viewpoint.
It waits at a landing with its deck end on the route's end point, then
crosses at up to 4.5 m/s (accelerating and braking at 0.25 m/s²).
No timetable (game policy: the ferry serves the taxi). The taxi within
150 m of a landing, not aboard, finds the ferry docked there: brought at
once unless it is already on its way there. It waits as long as the taxi
is near and leaves 4 s after the taxi has stopped on its deck. Away from
the taxi it shuttles, leaving after 40 s. It never leaves with a car
half on the ramp, or with an NPC car on the ramp. A taxi it brought
across does not take it back: only a car that drove on there does.

**Carrying.** A car with all four corners on the deck moves and turns
with it (the parked taxi too, the driver on foot). Deck points are dry
for the water brake and for sinking, so the taxi drives on and off at a
landing, and the water brake still stops it at the deck's open end.
Its side rails stop a car crossing them, either way (`FerryManager.blocks`):
the ends are the only way on and off. Driving off the open end
mid-crossing sinks it as any water does.

**NPC cars aboard.** A ferry brought to the taxi's landing arrives with
0-2 NPC cars (`NPCVehicleManager.ferry_car`: parked, driverless, the
ferry moves them). Docked, they drive off at 3 m/s, nearest the ramp
first, single file in the lane on the right of the way they go
(right-hand traffic). Each waits while the taxi is in its lane within
8 m ahead: a lawful wait (§§ 3-5: no collision, room to pass), not a
stuck car. 8 m past the deck end it is ashore and starts an ordinary
trip; where no parking validates near the landing (an arterial road
has no roadside tier), it drives on as through traffic to a road node
some 250-400 m on, where the visibility cleanup retires it out of view.
Without any valid trip it is retired. A car still aboard when the ferry
leaves with the taxi rides back and reverses off at the other side.
NPC trips never plan across a ferry: the crossings are not in the shared
route graph's edges (`TrafficWorld._route_edges`).

**Navigation.** The player's route search (`NavigationRoute`,
`TrafficWorld.route_graph()`, `plan_route_steps(ferries=True)`) adds
each route as an edge between the road nodes within 40 m of its ends,
costed as 3 x its length + 300 m (boarding), and joins the islands'
components for the search only. Intercity: the backbone keeps car ferry
ways whose `ferry=*` is a backbone class (`ferry=trunk/primary/secondary`)
as segments timed at 4.5 m/s + 60 s boarding (`intercity.VERSION` 2:
prepared graphs rebuild).

**Looks.** A yellow hull with a dark waterline, a grey car deck level
with the landing, yellow side rails and ramp corners, deck lane marks,
and a yellow glazed wheelhouse on one side. The shape follows the yellow
vehicle ferries in [Timo Hirvi's ferry gallery](https://tjh.1g.fi/kuvat/LAIVAT,+VENEET++YM./MAANTIELAUTAT,+SAARISTOLAUTAT,+YHTEYSALUKSET/);
the photos are references only and are not shipped. 2D: drawn under the
vehicles (`entity_layer.gd`, `_ferries`). Visual scenarios
`ferry_car_3d` and `ferry_car_2d`.

## Phases 1-2 (2026-11-03)

As designed above. Measured at Vartsala (Kustavi, 925 m): the taxi
posed on the deck was out on the strait, still aboard, 60 s later, with
no sinking. Timetables (Digitransit) were left out by choice;
Digitraffic Marine has none (AIS, port calls and winter navigation only).

## Phase 3 (2026-11-03)

The ferry serves the taxi, navigation crosses on ferries, NPC cars
arrive aboard, the side rails are solid. Measured at Vartsala's western
landing (real map, headless): the taxi 15 m from the ramp found the
ferry docked there at once (it had been at the eastern one); both NPC
cars it brought drove off past the taxi waiting in its lane and were
cruising inland 10 s later. The player's route across the strait: 1.5 km
with the 925 m crossing. Seen in the 2D view (`--test-seed 1`): a car
driven off, one still on the deck, in the right-hand lane.

First measured, then fixed: the NPC cars waited behind the taxi waiting
beside their lane (a plain distance test); then one waited behind it in
the left-hand lane, until they kept right; then the car ashore found no
trip at this rural landing (only parking tiers) and was retired, until
the through-traffic fallback.

## Phase 4 (2026-11-03): the deck is steel

The deck had counted as the open ground under the water (soft mud): it
left muddy tracks that stayed on the water as the ferry moved on, and
gave the taxi grass grip. Now no tyre mark is laid on a deck (the
server's `_tyre_mark`) and `update_car_physics(hard_at=...)` makes it
hard ground. Driven on the real map (Vartsala, headless, the player's
throttle and brake): on to mid-deck at 13.7 m/s, ground "hard", no
marks; stopped (the game's 28 m/s² brake, as on a road); the ferry left
4 s later and carried the taxi 925 m in 208 s without it moving on the
deck; at the far landing it drove off onto the road. No sinking at any
point.
