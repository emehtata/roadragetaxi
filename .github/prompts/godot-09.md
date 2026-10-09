# Godot Hotfix: Investigate and Fix Background/Camera Jitter

## Objective

The vehicle is now visually stable after the previous jitter/throttle hotfix.

A new issue remains:

> **The vehicle stays stable, but the background/world visibly jitters while driving.**

Investigate and fix **only the background/camera/world rendering jitter**.

The vehicle movement implementation is currently considered stable and must be treated as protected behavior.

Do **not** rewrite, refactor, or "improve" the vehicle movement/interpolation implementation unless you can demonstrate with code-level evidence that it is directly responsible for the background jitter.

---

## Critical Scope Restriction

This is a focused rendering/camera hotfix.

### Do NOT change:

* vehicle input handling
* accelerator/brake handling
* vehicle acceleration/deceleration
* vehicle physics
* vehicle server-authoritative movement
* vehicle interpolation
* network snapshot handling
* network protocol
* server simulation
* route planning
* NPC movement
* rendering parity features unrelated to the jitter
* map loading architecture
* protocol serialization
* binary protocol work
* general performance refactoring

The previous vehicle jitter fix must remain intact.

If the investigation discovers that the vehicle transform is being used incorrectly as a camera reference, fix the camera/reference relationship rather than modifying vehicle movement itself.

---

# 1. Reproduce the Problem First

Run the current Godot build and reproduce the issue.

Use the real Oulu/game environment if that is the existing standard test environment.

Observe specifically:

* vehicle remains visually stable
* roads/background appear to shake, jump, or oscillate
* buildings
* trees
* map objects
* road markings
* pedestrians
* other vehicles
* HUD
* camera movement
* world-origin/camera-relative movement

Determine whether the jitter affects:

1. the entire world uniformly,
2. only map geometry,
3. only certain map objects,
4. objects near tile/chunk boundaries,
5. objects moving independently,
6. the camera itself,
7. or a combination.

Do not immediately change interpolation parameters.

---

# 2. Trace the Camera Pipeline

Trace the complete path:

```text
server vehicle position
        ↓
Godot vehicle state
        ↓
vehicle world transform
        ↓
camera target/reference
        ↓
Camera2D transform
        ↓
viewport/canvas transform
        ↓
world/map rendering
```

Identify exactly:

* what node owns the camera
* what node the camera follows
* where camera position is calculated
* whether camera position is updated in `_process()`
* whether camera position is updated in `_physics_process()`
* whether camera position is updated by a network callback
* whether Camera2D built-in smoothing is enabled
* whether custom smoothing exists
* whether camera position is assigned more than once per frame
* whether camera position is rounded
* whether camera position is converted between coordinate systems

Document the actual update path before modifying it.

---

# 3. Check for Multiple Camera Writers

Search the entire Godot client for every assignment to:

* `camera.position`
* `camera.global_position`
* camera transform
* camera target
* camera offset
* camera zoom
* viewport/canvas transform

Also inspect camera helper methods.

Determine whether the camera is being written from multiple places such as:

```text
_process()
_physics_process()
network update
vehicle update
camera follow function
world/chunk update
resize handler
```

If multiple systems write the camera transform during a frame, identify the conflict and consolidate it if necessary.

The camera should have one authoritative update path.

---

# 4. Check `_process()` vs `_physics_process()`

Determine which update loop controls:

* vehicle rendering transform
* camera transform
* world/map rendering
* chunk visibility
* map object positions

A common failure mode is:

```text
vehicle updates in physics frame
camera updates in render frame
world updates in another callback
```

or:

```text
camera follows a position that changes only on physics ticks
while rendering occurs at a different rate
```

Do not blindly move systems between `_process()` and `_physics_process()`.

Instead determine the existing architecture and identify whether different update frequencies are causing visible frame-to-frame oscillation.

If interpolation is required for the camera, it must be based on a stable render-time target and must not modify vehicle simulation.

---

# 5. Check Camera Smoothing

Inspect all Godot Camera2D settings, including:

* position smoothing
* position smoothing speed
* drag
* drag margins
* limits
* offset
* zoom

Determine whether Godot's built-in camera smoothing is enabled.

Also search for custom smoothing/interpolation.

There must not be an unintended combination such as:

```text
custom camera interpolation
+
Camera2D position smoothing
```

or:

```text
vehicle interpolation
+
camera interpolation
+
world interpolation
```

where multiple layers independently smooth the same movement.

Do not simply disable smoothing without understanding why it is present.

If the existing architecture intentionally uses smoothing, preserve the intended visual behavior while eliminating the jitter.

---

# 6. Investigate Pixel Rounding and Coordinate Conversion

Search for all conversions involving:

```text
Vector2
Vector2i
int()
round()
floor()
ceil()
snapped()
```

especially around:

* vehicle position → camera position
* world coordinates → screen coordinates
* metres → pixels
* map coordinates → Godot coordinates
* camera position → tile/chunk position
* object rendering positions

Check for patterns such as:

```gdscript
camera.position = Vector2i(...)
```

or:

```gdscript
position = position.round()
```

or repeated:

```text
world position
→ integer position
→ world position
```

The vehicle can remain visually stable while the camera/world jumps by one pixel every few frames if different parts of the rendering pipeline use different rounding rules.

Do not introduce arbitrary rounding as a workaround.

Use consistent coordinate precision appropriate for Godot 2D rendering.

---

# 7. Investigate Camera-Relative World Movement

Determine whether the game moves the entire map/world to keep the vehicle centered.

For example:

```text
vehicle stays near screen center
world moves underneath it
```

If so, inspect how the world transform is calculated.

Look for:

* repeated subtraction of camera position
* integer conversion
* accumulated floating-point error
* applying camera offset twice
* applying camera movement both to the world and through Camera2D
* world origin changes
* floating-origin logic
* chunk origin changes

The key question is:

> Is the world actually moving correctly in world coordinates, with the camera moving over it, or is the game manually moving the world while also moving the camera?

If both mechanisms are active, identify and fix the double-transform.

---

# 8. Investigate Tile/Chunk Rendering

The game uses dynamically rendered map/world content.

Inspect:

* map chunks
* visible-area calculations
* chunk activation/deactivation
* object culling
* road rendering
* building rendering
* trees
* map decorations
* static objects
* labels

Determine whether camera movement causes visible objects to be:

* destroyed/recreated
* reparented
* repositioned
* reloaded
* reordered
* converted between coordinates
* snapped to integer positions

Check especially for behavior triggered when crossing:

* tile boundaries
* chunk boundaries
* spatial-grid cells
* map-object visibility thresholds

The jitter may be caused by objects repeatedly crossing a visibility boundary.

Do not redesign chunk loading unless it is proven to be the cause.

---

# 9. Compare World Objects Against the Vehicle

Use the stable vehicle as the reference.

Inspect a fixed world object such as:

* building
* road marking
* tree
* sign

while the vehicle drives past it.

Determine:

### Case A

Vehicle stable + every world object moves smoothly.

Then the apparent jitter may be related to camera perception, zoom, or specific rendering layers.

### Case B

Vehicle stable + all world objects jump together.

Likely camera/world transform issue.

### Case C

Vehicle stable + only some objects jump.

Likely object/chunk/culling/update issue.

### Case D

Vehicle stable + background road/buildings move differently from pedestrians/NPCs.

Likely multiple rendering update paths.

Use this classification to guide the fix.

---

# 10. Inspect Camera Zoom

Check the current Godot camera zoom against the intended game scale.

The previous parity work established the default camera scale at approximately:

```text
9 px / metre
```

Do not change the intended gameplay zoom merely to hide jitter.

Check whether zoom contains fractional values that interact badly with pixel rounding.

Determine whether the jitter is:

* independent of zoom
* amplified by zoom
* caused by fractional zoom
* caused by inconsistent world/camera scaling

Only modify zoom if the investigation proves it contributes directly to the bug.

---

# 11. Inspect Render Ordering and Canvas Transforms

Check whether different world layers use:

* different CanvasLayer nodes
* different Node2D parents
* different transforms
* different camera inheritance
* different viewport/canvas transforms

Determine whether some background elements bypass the same camera transform as the vehicle/world.

Pay particular attention to:

```text
Node2D
CanvasLayer
Camera2D
SubViewport
Control
```

Do not change the HUD implementation unless it is incorrectly participating in the world transform.

---

# 12. Instrument the Problem if Necessary

If the cause is not immediately obvious, add temporary diagnostics.

Useful measurements include:

```text
vehicle global position
camera global position
camera target position
camera position delta
vehicle position delta
world/chunk origin
rendered object position
frame number
physics frame number
```

Log only enough data to identify the oscillation.

For example, detect:

```text
camera position A
camera position B
camera position A
camera position B
```

or:

```text
camera target moves smoothly
camera transform jumps
```

or:

```text
world object position jumps while camera remains stable
```

Remove temporary diagnostics after the root cause is identified unless they are useful as a permanent debug feature.

---

# 13. Do Not Fix Symptoms

Do NOT solve the problem by blindly:

* lowering camera smoothing
* increasing interpolation
* adding arbitrary delays
* adding frame sleeps
* reducing FPS
* forcing 60 FPS
* adding random averaging
* snapping everything to integers
* adding arbitrary epsilon values
* disabling rendering features
* reducing world detail

The final fix must address the actual cause.

---

# 14. Preserve the Previous Vehicle Fix

Before changing anything, inspect the git diff/history from the previous vehicle jitter/throttle hotfix.

Identify which files and code paths were responsible for making the vehicle stable.

Treat those sections as protected.

After your changes, explicitly verify:

```text
vehicle position remains stable
accelerator release still works
vehicle does not continue accelerating after key release
vehicle interpolation remains unchanged
network vehicle state remains correct
```

If your camera fix requires consuming a vehicle position, read that state without changing its semantics.

---

# 15. Regression Tests

Add deterministic tests only where they make sense.

Prefer tests for:

* camera target calculation
* camera transform calculation
* coordinate conversion
* rounding behavior
* chunk visibility calculations
* camera/world transform consistency

Avoid screenshot-based tests unless the repository already has an established reliable screenshot test framework.

Do not create fragile timing-dependent tests.

---

# 16. Required Validation

Run:

```bash
make godot-test
make godot-selftest
make audio-check
```

If shared Python/server behavior was changed, also run the relevant Python test suite.

The vehicle movement regression tests must continue to pass.

---

# 17. Manual Verification

Run the actual Godot game and verify all of the following:

### Camera/world

* drive slowly
* drive at normal speed
* drive continuously for several seconds
* turn left
* turn right
* stop
* start again
* cross map/chunk boundaries
* drive past buildings
* drive past trees/signs
* drive past pedestrians
* drive past other vehicles
* observe road markings

The world must move smoothly without visible shaking.

### Vehicle

Confirm that the previous fix remains intact:

* press accelerator
* release accelerator
* vehicle stops accelerating after release
* brake
* turn
* accelerate/decelerate repeatedly
* no vehicle transform jitter

### Network

If applicable:

* verify normal server connection
* verify incoming state updates do not cause camera jumps
* verify stale network updates do not move the camera backwards

---

# 18. Success Criteria

The task is complete only when:

1. The vehicle remains stable.
2. The background/world moves smoothly.
3. Camera movement is smooth.
4. No visible oscillation occurs during normal driving.
5. Crossing map/chunk boundaries does not introduce jitter.
6. Vehicle input/release behavior remains fixed.
7. Existing tests pass.
8. No unrelated parity or architecture work was introduced.

---

# 19. Final Report

At the end, report:

### Root cause

Precisely explain what caused the background/camera jitter.

For example:

```text
Camera was updated in _process() from a physics-frame vehicle position while
Camera2D smoothing was also enabled, causing alternating camera positions.
```

Do not give a speculative explanation. Report the actual cause found in the code.

### Files changed

List every modified file and explain why.

### Fix

Explain the exact technical correction.

### Vehicle safety

Explicitly state that the previous vehicle stability/input fix was preserved.

### Tests

Report:

```text
make godot-test: PASS/FAIL
make godot-selftest: PASS/FAIL
make audio-check: PASS/FAIL
Python tests: PASS/FAIL/SKIPPED
```

### Manual verification

Report what was tested in the running game.

### Git

Create a focused commit for this hotfix.

Push the branch to the remote if the repository workflow permits it.

**Do not create or push a Git tag.**

Do not include unrelated changes in the commit.

---

## Final Rule

This is a **background/camera jitter investigation**, not another general Godot rendering phase.

Keep the change as small and isolated as possible.

**Do not continue with rendering parity work after fixing the jitter.**

Stop after the root cause is identified, the focused fix is implemented, regression-tested, manually verified, committed, and pushed.
