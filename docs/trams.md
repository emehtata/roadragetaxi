# Trams

Trams run on their rails in the cities that have them - Helsinki and
Tampere today - stopping at their stops and braking for what is on the
track.

## Current state

Phases 1-2 (below) are implemented: `trams.py` (`TramManager`), driven by
the simulation each tick and drawn by the client like train cars. Trams
serve the real OSM tram lines (phase 2).

## Design

**The track.** OSM `railway=tram` ways, as a rail graph
(`trains.build_rail_graph(..., kind="tram")`; trains keep to
`railway=rail`). Tram stops (`railway=tram_stop`, or a tram
`public_transport=stop_position`) are mostly mapped beside the track, on
the platform side: each joins the nearest tram line within 15 m
(`Railway.stops`, world cache format 30) and the nearest track node.

**Where a tram goes.** OSM's tram route relations are not loaded, so a
tram follows the track: at a junction the straightest way on (75 %), else
another, never round a corner sharper than 70 degrees. It keeps right: on
a double line the other track lies 3.5 m to its left, so it never takes
the wrong-way track if another way exists, and it is spawned facing the
right-hand way. At a dead end of the loaded track it turns back if in
view, else it goes.

**Stops and safety.** It stops at each tram stop on its way for 15 s,
braking into it. It brakes for anything on its track ahead (within
2.2 m of the rail line, its braking distance plus 5 m): the taxi, NPC
cars, pedestrians, other trams. Driving the taxi into a tram is a crash
(stopped, a penalty, once an impact); a taxi a tram moved into is never
pinned and can drive out.

**Population.** Trams are kept near the viewpoint: about one per 2 km of
tram track within 900 m of it, at most 8, spawned out of sight, removed
beyond 1.3 km. One held 20 s out of sight goes (a deadlock's safety net).
Bounded work: about 0.2 ms a tick in central Helsinki.

**Looks.** Articulated sections drawn like train cars (state `trains`,
ids `tram-N`): Helsinki HSL green and white (3 x 9.2 m), Tampere red and
white (3 x 12.4 m), 2.4 m wide.

## Phase 1 (2026-10-15)

As designed above. Measured in central Helsinki: 52 km of tram track,
109 stops; in 3 minutes trams stood at 16-22 different stops.

Not yet:

- NPC cars give way to trams where Finnish law says so (tram priority,
  `docs/finnish-npc-traffic-law.md`); they do not see trams at all yet,
  so a car may stand on the rails and hold a tram.
- Real tram lines (OSM route relations) and timetables; terminal loops.
  (Lines: phase 2. Timetables are not wanted.)
- Passengers boarding and leaving at stops; tram sounds.
- Trams at traffic lights (they brake for the cars queueing there, but do
  not read the signals themselves).

## Phase 2 (2026-10-15): OSM tram lines

Trams serve the real lines instead of wandering the network. Each OSM
`route=tram` relation's `ref` ("7", "1T") is recorded on its member tram
ways (`Railway.lines`, world cache format 31; Overpass now fetches the
relations) and on the rail graph's edges (`RailGraph.lines`). A tram is
spawned on track carrying a line (not a depot siding) and serves one of
its lines; at a junction it takes the way its line goes on - keeping
right, as both directions' tracks carry the line's number - and only off
its line's mapped track falls back to straight on. No timetables.

Measured in central Helsinki: lines 1, 1T, 2, 3, 4, 5, 6, 7, 8, 8T, 9, 10
on 3,095 of 3,590 track edges; trams stay on their own line's track 100 %
of the time, and stop at 13-17 different stops in 3 minutes.

Still not: the line number shown on the tram; terminal loops beyond the
loaded map; NPC cars giving way to trams.
