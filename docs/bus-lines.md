# Bus lines

NPC buses drive the real bus routes from OpenStreetMap, stop to stop,
without a timetable.

## Current state

Phase 1 (below) is implemented. A line is one OSM `route=bus` (or
`trolleybus`) relation: its stops in order. A few of the NPC
population's moving-traffic spawns are line buses; each drives its line
from the stop nearest where it spawned to the end of the line, pulling
into every stop's bay. Its riders stay aboard. Buses show their line
number on a roof box that turns with the bus.

## Design

**Server decides, client draws.** Lines, legs and stops are server
decisions (`bus_lines.py`, `npc.py`); the client draws an ordinary NPC
bus with its line number (`bus_line` in the NPC state) on a roof box.

**Reuse the NPC system, never a parallel driver.** As competitor taxis
(`docs/competitor-taxis.md`), a line bus is an NPC vehicle of
`vehicle_kind == "bus_line"`; its legs are NPC route jobs, so it obeys
every traffic rule in `docs/finnish-npc-traffic-law.md`. Unlike a taxi
it never parks: a leg ends in the stop's bay, beside the road on the
stop's side (see Phase 2). The bus stands there for `STOP_DWELL_S`.

**Lines from OSM, kept on the stops.** `osm/build.py` reads each route
relation's platform members (PTv2), or its stop members when it has no
platforms, and records `[route key, member index, ref]` on the
`BusStop` each one is (a stop_position node snaps to the nearest stop
within 30 m). Sorting a route's stops by member index gives the line
(`bus_lines.lines`). Keeping this on the stops means the world cache
and tile streaming carry lines without a new section. Overpass returns
the relations without recursing into their members: the stops already
come with the map, the routes' far-away ways are not needed.

**Job lifecycle** (`bus_lines.BusJob`):

| State | Meaning | Next |
| --- | --- | --- |
| `await_departure` | needs a route to its next stop | the route job applies: `driving` |
| `driving` | on the way to the stop | stopped within `AT_STOP_M` of it: `stopped`; stopped elsewhere (a recovery): `await_departure` |
| `stopped` | dwelling at the stop | the next stop: `await_departure`; the last one: the job ends |

A stop that cannot be routed to `MAX_ROUTE_ATTEMPTS` times is skipped.

**The terminus.** Buses never turn round: an 11 m bus cannot U-turn on
a city street, and the route planner does not plan around a block for
a vehicle's heading. At its last stop the job ends; the bus waits there
while in view and is retired once out of sight. Each direction of a
line is its own OSM relation, so new spawns serve both.

**Population.** While lines are loaded, up to `LINE_BUSES` of the
moving-traffic spawns are line buses (vehicle type `bus`), starting
towards their line's stop nearest the spawn point.

**Cost.** Lines are rebuilt only when the world's stops change; a line
bus costs what any NPC vehicle does, plus one route job per stop.

## Phase 1 (2026-10-19)

Implemented as designed above: OSM route relations onto the stops,
line buses in the NPC population driving stop to stop, the terminus
retirement, the line number on the bus. Overpass and world caches were
versioned so existing maps refetch with their routes. Tests:
`tests/test_bus_lines.py` (parsing, the job, and a bus driving its
line through the NPC system).

Not yet: passengers boarding (pedestrians already wait at stops), a
timetable, buses using the bay itself, heading-aware turning at a
terminus.

## Phase 2 (2026-10-19): into the bay, riders aboard

Played, two faults: buses stopped in the lane (or, approaching a stop
just before a junction, drifted into the oncoming lane), and every rider
got off at the first stop.

- **Lane.** The route search ends at the road node nearest the stop,
  often just past it: the path drove on, crossed into the oncoming lane
  and came back. A leg's path is now cut where it first reaches the stop
  (`npc._end_at_stop`).
- **Bay.** The route is validated to the kerb-side lane point beside the
  stop; the pull-in is added after validation (the bay is drawn by the
  game, the map's roads end at the kerb): along the lane, eased to just
  inside the kerb, into the bay and straight along it to its middle
  (`BUS_BAY_PULL_IN_M`, `BUS_BAY_STRAIGHT_M`). It stays within the
  driver's 30 m off-road access stretch before an off-road destination,
  so the body leaves the carriageway only there.
- **Riders.** The pedestrian system unloads a parked NPC's trip group to
  walk to a building; a line bus is skipped, as a taxi is.

Known: pulling out of a bay can briefly trip the road-boundary check;
the recovery re-routes and the bus goes on.
