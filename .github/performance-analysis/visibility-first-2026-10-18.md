# Visibility-first simulation

Status: first implementation phase; no measured FPS claim yet.

## Implemented

- Godot reports the actual camera rectangle in world metres on commands.
  Reports have finite coordinate/extent limits, are tied to a connection and
  expire after two simulation seconds. Multiple connected views are combined.
- Spawn visibility checks use that rectangle, including zoom/panning. Legacy
  clients and headless runs without a report retain the previous viewport.
- Ambient activity uses the view plus 60 m + three seconds of taxi speed
  (speed contribution capped at 240 m), also including 100 m around the taxi.
  Full vehicle bounds overlapping the active rectangle are retained.
- Outside this area, ambient NPC cars can retire below the population minimum.
  Their linked residents, route jobs, parking reservations and rage references
  are released. A visible linked walker or active fare prevents group retirement.
- Ordinary walkers/activities retire outside the area. Owned station/booked
  pedestrians and active fare identities are protected. Activity teardown uses
  the existing finish/release path. Distant vomit puddles/footprints are discarded.
- Vehicle decisions and post-physics collision sweeps are bounded to active
  vehicles. Visible cars can update beyond the old 400 m radial cutoff.
- Pedestrians in view or within 60 m of the taxi update at full rate; buffered
  off-screen walkers use 12 Hz instead of the previous 500 m full-rate band.
- Parking/transit spawn candidates and completed transit plans are checked
  against the current active area to avoid creating disposable distant work.
  Transit searches cover the buffered view rather than only the old 110–220 m
  ring, so zoomed-out views can still replenish beyond their visible edges.
  Candidate-bucket traversal yields to the existing route-job time budget.

These are game cleanup policies, not changes to Finnish right-of-way rules.
Resident identity records remain; discarded ambient journeys do not catch up.

## Next phases

Validation: full Python suite 1,879 passed / 2 skipped; after final adaptive
spawn changes, affected actor/server/protocol suite 300 passed, plus 19
vehicle-dimension/license checks. Godot suite 1,584 checks / zero failures,
including actual zoom/canvas-to-world command conversion.
The synthetic collision test reduces sweeps from 20 retained cars to one car
overlapping the active area. This demonstrates bounded work, not a measured FPS
gain. Existing Godot test shutdown resource warnings remain.

1. Measure tick wall/thread CPU, actor counts, collision calls, route-job work
   and snapshot size during stationary play, 210 km/h travel, reversing,
   zoom/panning, intersections and snow. Compare to the parent revision with
   identical isolated save/cache directories and deterministic seeds.
2. Filter network presentation separately from mission metadata. Train bodies
   require segment/vehicle bounds, not a locomotive-centre test.
3. Convert distant trains/competitor jobs to event-driven data where compatible
   with bookings, audible arrivals and approaching level-crossing hazards.
   Timetable/booking and train movement are unchanged in phase one.
4. Replace remaining whole-list proximity work (vomit checks, tram obstacles,
   activity candidates) if profiling still identifies it as significant.
5. Review camera-driven map prefetch: static chunks still follow the player;
   distant debug camera panning does not request a new world.

## Acceptance

No disappearance of visible vehicle bodies or linked group members. No orphan
parking reservations, continuing discarded route jobs or lost active fares.
No distant population floor veto. No collision/traffic-rule simplification in
the active area. Reports with malformed, non-finite, oversized or stale bounds
must not crash or constrain the server. Benchmark tests must not touch player
saves or bank balances.
