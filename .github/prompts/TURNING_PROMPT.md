Fix the NPC vehicle turning behavior in Road Rage Trip.

The current NPC cars do not make realistic, smooth turns at intersections. They tend to make the turn as an abrupt change of direction instead of following a continuous curved trajectory.

## The problem

When an NPC approaches an intersection and needs to turn right, the desired behavior is:

1. The car approaches the intersection in its current lane.
2. It enters the intersection following a smooth curved trajectory.
3. It gradually changes heading while turning.
4. The trajectory forms a natural arc through the intersection.
5. The car exits the intersection aligned with the correct lane on the new road.
6. After the turn, it continues straight along the new road.

For a right turn, the car should specifically finish the turn on the RIGHT-HAND LANE of the destination road.

The same principle should apply to left turns:

* follow a smooth arc through the intersection
* finish in the correct lane of the destination road
* smoothly transition back to straight-line driving

There must not be a sudden "rotate 90 degrees and continue" behavior.

## Important

Do NOT solve this by simply interpolating the car's heading while allowing its position to continue on the old straight-line trajectory.

The POSITION and HEADING must both follow the same continuous turning trajectory.

The car should physically drive along a curved path.

Think of the desired movement as:

```
incoming lane
      \
       \
        )   <- smooth turning arc
       /
      /
outgoing lane
```

rather than:

```
incoming lane
      |
      |
      |
      +-------->
           ^
      instantaneous direction change
```

## Inspect the existing architecture first

Before changing code, trace how the traffic system currently:

* determines the next road/way
* determines whether the NPC turns left/right/straight
* calculates lane offsets
* calculates steering angle
* calculates wheelbase
* calculates turning radius
* moves the NPC along `points_m`
* changes `segment_idx`
* handles intersections
* handles intersection reservations
* transitions from one Way to another

The code already contains concepts such as:

* `turning_radius_m`
* `steering_angle`
* `wheelbase_m`
* `max_steering_angle`
* `turn_signal`
* `compute_desired_lane_offset()`
* `compute_turn_lane_offset()`
* `calculate_npc_turning_geometry()`

Determine whether these are actually being used to produce the physical trajectory or whether the NPC still effectively snaps from one road geometry to another.

## Desired implementation

Implement an explicit intersection turn trajectory.

When an NPC commits to a turn, construct a temporary path/trajectory from:

```
incoming lane center
    ->
intersection turning arc
    ->
outgoing lane center
```

The trajectory should contain enough intermediate points that movement is smooth.

A cubic Bézier curve, clothoid-like approximation, circular arc, or another mathematically sound method is acceptable.

For example, a Bézier curve can be used conceptually:

```
P0 = incoming lane point
P1 = incoming tangent control point
P2 = outgoing tangent control point
P3 = outgoing lane point
```

The important requirement is that the curve is tangent to the incoming and outgoing roads so the vehicle does not visibly kink at either end.

Do not hard-code a single turn radius for every intersection.

The turn geometry should adapt to:

* road width
* incoming lane offset
* outgoing lane offset
* intersection geometry
* vehicle wheelbase
* vehicle dimensions
* left vs right turn
* angle between incoming and outgoing roads

## Lane behavior

This is especially important.

For a RIGHT turn:

```
incoming right-hand lane
         |
         |
         |
          \
           \
            +-------->
                     right-hand lane
```

The car must finish in the correct right-hand lane of the destination road.

It must NOT:

* cut across the destination road
* finish in the center of the road
* finish on the wrong side
* overshoot and then snap into the lane
* turn first and correct its lane afterward

For a LEFT turn, use the appropriate destination lane according to the road's driving direction and lane configuration.

For STRAIGHT movement, do not create an unnecessary turning arc.

## Heading

The NPC's heading must be derived from the tangent of the trajectory.

At the beginning of the turn:

```
heading ≈ incoming road direction
```

During the turn:

```
heading changes continuously
```

At the end:

```
heading ≈ outgoing road direction
```

There should be no sudden heading discontinuity.

Steering angle should also change smoothly rather than instantly jumping from 0 to the maximum steering angle and back to 0.

## Vehicle physics

Respect the existing vehicle geometry.

Use the existing:

* wheelbase
* maximum steering angle
* turning radius

where appropriate.

Do not create physically impossible turns where the required curvature is tighter than the vehicle can reasonably achieve.

If the intersection is too tight for the ideal radius, adapt the trajectory while remaining within the road boundaries.

## Intersection state

Make the turn trajectory a temporary state of the NPC.

Conceptually something like:

```
driving
   |
   v
approaching_turn
   |
   v
turning
   |
   v
driving_on_new_way
```

Do not destroy or bypass the existing intersection reservation/traffic-light logic.

The reservation should cover the actual intersection traversal, including the turn.

## Road geometry

Use the actual geometry of the connected OSM ways wherever possible.

Do not assume all intersections are perfect 90-degree intersections.

The implementation should handle:

* approximately 90° turns
* shallow turns
* wider intersections
* roads meeting at non-90° angles
* different road widths
* one-way roads
* two-way roads

Avoid hard-coded world-coordinate assumptions.

## Avoid teleport/snap corrections

There should be no code path where the NPC:

1. drives into the intersection,
2. suddenly changes `way`,
3. snaps its position to the destination road,
4. snaps its heading to the destination road.

Instead, the temporary turn trajectory should bridge the two roads continuously.

If the existing architecture requires changing `npc.way` during the turn, make sure that changing the logical road does not cause a visible positional or rotational snap.

## Debugging

Add useful debug information if necessary.

It would be useful to be able to inspect:

* current turn type
* incoming way
* outgoing way
* turn trajectory points
* target lane offset
* current trajectory index
* desired heading
* actual heading
* steering angle

Do not leave excessive debug rendering enabled by default.

## Tests

Add tests for at least:

1. Right turn from a two-way road onto another two-way road.
2. Left turn from a two-way road onto another two-way road.
3. Straight-through intersection.
4. Right turn onto a road with a different orientation.
5. A non-90-degree intersection.
6. Verify that the vehicle ends in the correct lane.
7. Verify that heading changes continuously through the turn.
8. Verify that the vehicle does not teleport/snap between roads.
9. Verify that the trajectory stays within reasonable road/intersection boundaries.

For a right turn, specifically assert that the final position is on the expected right-hand lane rather than merely somewhere on the outgoing road.

## Important implementation constraint

Do not rewrite the entire traffic system unless absolutely necessary.

First identify the smallest architectural change that can introduce a proper temporary turn trajectory while preserving the existing:

* routing
* traffic lights
* stop signs
* yield signs
* intersection reservations
* lane selection
* NPC spawning
* parking
* collision handling
* LOD system

## Final verification

After implementing the fix:

* run the relevant tests
* inspect existing traffic tests
* add regression tests for the turning behavior
* search for any remaining code that directly snaps `npc.heading`, `npc.x`, `npc.y`, `way`, or `segment_idx` when entering/exiting an intersection
* verify that such code cannot undo the smooth trajectory

Explain in your final response:

1. What caused the abrupt turning behavior.
2. How the new turn trajectory works.
3. How the correct destination lane is selected.
4. How heading and steering are made continuous.
5. Which files were changed.
6. Which tests were added and their results.
