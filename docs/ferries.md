# Road ferries

Car ferries run on their real routes, so islands with no bridge can be
reached: drive onto the deck, stop, and the ferry carries the taxi across.

## Current state

Phases 1-2 (below) are implemented: `ferries.py` (`FerryManager`), run by
the simulation each tick and drawn by the client like a train of one car
(look `ferry`). Not yet: navigation over ferries, timetables, NPC cars on
ferries.

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
No timetable: it leaves after 40 s, or 4 s after the taxi has stopped
on its deck. It never leaves with a car half on the ramp. A taxi it
brought across does not hurry it back: only a car that drove on there
does.

**Carrying.** A car with all four corners on the deck moves and turns
with it (the parked taxi too, the driver on foot). Deck points are dry
for the water brake and for sinking, so the taxi drives on and off at a
landing, and the water brake still stops it at the deck's open end.
Driving off mid-crossing sinks it as any water does.

**Looks.** A yellow hull, a grey car deck level with the landing,
side rails and a white wheelhouse on one side. 2D: drawn under the
vehicles (`entity_layer.gd`, `_ferries`). Visual scenarios
`ferry_vartsala_3d` and `ferry_vartsala_2d`.

## Phases 1-2 (2026-11-03)

As designed above. Measured at Vartsala (Kustavi, 925 m): the taxi
posed on the deck was out on the strait, still aboard, 60 s later, with
no sinking. Timetables (Digitransit) were left out by choice;
Digitraffic Marine has none (AIS, port calls and winter navigation only).
