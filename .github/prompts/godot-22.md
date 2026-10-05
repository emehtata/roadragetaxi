# Godot 3D Building Layer — Performance and Visual Tuning

## Context

The 3D building layer is now working correctly and has solved the original building-rendering problem.

The buildings are rendered as real 3D volumes. Their visible facades change smoothly as the camera moves, with no snapping, and the building footprints remain exactly aligned with the 2D map.

The implementation is committed and pushed.

Current last commit:

```text
003ce33
```

No Git tag was created.

The old 2D renderer is still available for comparison:

```text
--buildings 2d
```

The 3D renderer is now the default.

---

# Current Architecture

The game remains a **2D/top-down game with a lightweight 3D building layer**.

Do not turn this into a full 3D game.

The current 3D building camera:

* points straight down
* has no tilt
* has no roll
* currently uses a 40° vertical FOV
* matches the 2D camera's centre and zoom
* is positioned so the ground coverage matches the 2D view

Coordinate mapping:

```text
2D (x, y)
    ↓
3D (x, 0, y)

building height
    ↓
3D Y
```

The building geometry is generated per map chunk on a worker thread.

Current geometry:

* walls from ground to server-provided height
* roof at building height
* pitched roofs consist of two sloped halves meeting at a ridge
* windows and doors are flat quads immediately in front of walls
* flat colours
* no dynamic lighting
* no shadows

The 3D building view is rendered into a transparent off-screen view and composited at the existing building layer.

Current layering:

```text
roads
  ↓
3D buildings
  ↓
vehicles / other world elements
  ↓
night tint
  ↓
HUD
```

Lit windows are currently rendered separately above the night tint.

---

# Current Benchmark

The existing benchmark was:

```text
Location: Oulu spawn
Duration: 30 seconds
Time: daytime
Resolution: 1280x720
Renderer: software rendering
Player standing still
```

Results:

| Metric      |             2D |                3D |
| ----------- | -------------: | ----------------: |
| Average FPS |           43.4 |              33.9 |
| 1% low FPS  |           35.7 |              27.5 |
| Worst frame |        31.1 ms |           38.9 ms |
| Memory      |      104.5 MiB |         107.9 MiB |
| Walls       | 10,631 visible |  21,121 submitted |
| Windows     | 60,112 visible | 119,838 submitted |
| 3D objects  |              — |              ~150 |

The current 3D renderer is approximately 22% slower in this test.

The likely cause is that the 3D renderer currently submits all wall/window faces rather than allowing the GPU to reject faces pointing away from the camera.

---

# IMPORTANT SCOPE

This phase has two primary goals:

## Phase A — Performance

Implement and benchmark proper back-face culling.

## Phase B — Visual tuning

Tune the building camera FOV so the facade depth looks appropriate.

Do these two things first.

Do NOT simultaneously redesign:

* canopy rendering
* headlights
* night window rendering
* building geometry architecture
* map rendering
* camera architecture
* networking
* protocol
* vehicle movement
* world simulation

The remaining issues are documented below but should only be investigated after the primary performance/FOV work is complete.

---

# 1. Establish a Baseline

Before changing rendering behaviour, run the existing 3D benchmark as consistently as possible.

Record:

```text
Average FPS
1% low FPS
Worst frame
Memory
```

Do not compare a new benchmark against an unrelated run with different conditions.

Keep the benchmark methodology identical:

```text
1280x720
software rendering
Oulu spawn
daytime
30 seconds
standing still
```

---

# 2. Implement Back-Face Culling

This is the highest-priority optimization.

The current geometry sends both sides of wall/window geometry to the renderer.

The benchmark shows approximately twice as many submitted wall/window surfaces as the old 2D renderer's visible counts.

Implement proper GPU back-face culling using Godot's normal material/mesh mechanisms.

## Requirements

* Use Godot's standard culling mechanism.
* Correct triangle winding where necessary.
* Do not manually remove geometry simply to simulate culling.
* Do not introduce CPU-side per-face visibility calculations.
* Do not change building dimensions.
* Do not change building coordinates.
* Do not change the camera orientation.
* Do not change the building height interpretation.

The goal is for the GPU to reject faces that point away from the camera.

---

# 3. Verify Geometry After Culling

Back-face culling must not introduce visual regressions.

Test at minimum:

* low buildings
* tall buildings
* L-shaped buildings
* irregular buildings
* commercial buildings
* rotated buildings
* pitched roofs

Check:

* front-facing walls remain visible
* roofs remain visible
* windows remain visible
* doors remain visible
* no walls disappear incorrectly
* no pitched-roof surfaces disappear incorrectly
* no building becomes hollow from the wrong side

If geometry winding is inconsistent, fix the winding.

Do not disable culling as a workaround.

---

# 4. Benchmark Again

After culling, repeat the exact baseline benchmark.

Report:

```text
Before:
Average FPS:
1% low:
Worst frame:
Memory:

After:
Average FPS:
1% low:
Worst frame:
Memory:
```

Calculate the relative improvement.

Do not claim that the optimization is successful simply because one FPS number increased.

If the improvement is smaller than expected, investigate why before adding more optimizations.

---

# 5. Tune the FOV

The current FOV is:

```text
40°
```

The visual issue is:

> Tall buildings can have excessively deep-looking facades. A 60 m building near the edge of the screen can visually cover too much of the street.

The FOV in:

```text
buildings_3d.gd
```

is the intended tuning parameter.

Do not change camera tilt.

Do not introduce camera roll.

Do not change the coordinate system.

Do not move buildings to compensate for FOV.

Test a small range of lower FOV values, for example:

```text
40°
35°
30°
25°
```

You may test intermediate values if necessary.

The exact final value should be chosen visually.

---

# 6. FOV Evaluation Criteria

Evaluate the FOV using both the existing building test scene and real Oulu.

The test scene contains:

* low building
* tall building
* L-shaped building
* irregular building
* pitched-roof building
* commercial building
* rotated building

Also inspect the real Oulu scene, including the existing Rantakatu area.

For each candidate FOV check:

### Building footprint

The footprint must remain exactly aligned with the 2D map.

### Facade depth

Tall buildings should show convincing facades without swallowing unreasonable amounts of street space.

### Low buildings

Low buildings must still have clearly visible facades.

### Camera movement

Facade transitions must remain smooth.

There must be no snapping.

### Zoom

Test at multiple existing zoom levels.

The chosen FOV must not only look good at one zoom level.

---

# 7. Preserve the Successful Camera Model

The current straight-down perspective camera is intentional.

Do NOT replace it with:

* orthographic projection
* tilted perspective
* isometric projection
* a camera with roll
* a camera with gameplay tilt

Previous experiments established that:

* straight-down orthographic does not show the required walls
* tilted cameras distort the ground and break footprint alignment
* straight-down perspective provides the required GTA1/GTA2-like visual effect while preserving the map

Preserve this design.

---

# 8. Do NOT Optimize by Changing the Visual Model

Do not attempt to regain FPS by:

* removing buildings
* reducing building height
* reducing window count
* disabling facades
* disabling pitched roofs
* disabling rotated buildings
* reducing map coverage
* lowering resolution
* changing the camera to orthographic
* reducing world detail globally
* reducing FPS
* adding frame delays

The first optimization target is GPU back-face culling.

---

# 9. Remaining Problems — DO NOT SOLVE YET

The current implementation has these known issues:

### Canopies

Canopies still use the old 2D lift.

### Headlights

Headlight beams are clipped against the original 2D building footprint rather than the visible 3D building.

### Pitched roofs

The triangular ends of pitched roofs are currently open.

### Night windows

The lit-window pass renders the building view a second time at night.

These are real issues, but **do not solve them in this phase unless one of them is directly necessary to implement or validate back-face culling/FOV.**

They should be handled in focused follow-up changes.

---

# 10. Tests

Run:

```bash
make godot-test
make godot-selftest
make audio-check
```

The current Godot baseline is:

```text
347 checks
all passing
79 new checks
```

All existing tests must continue to pass.

Also verify the existing geometry/camera tests that confirm that ground points map to the same positions as the 2D map.

---

# 11. Python Tests

The current Python baseline is:

```text
1,562 passed
3 failed
```

The three failures are in:

```text
test_main_city_bin_integration.py
```

They load old Pygame city map files.

This 3D building phase does not modify that Python implementation.

Do not modify those tests or the old Pygame/BIN implementation as part of this task.

If the Python suite is run, report those three known failures separately.

Do not attempt unrelated cleanup.

---

# 12. Manual Verification

After the implementation:

### Performance

Run the 30-second benchmark again.

### Visual

Check:

* Oulu
* test building scene
* low buildings
* tall buildings
* L-shaped buildings
* irregular buildings
* pitched roofs
* rotated buildings
* commercial buildings

### Camera

Check:

* normal driving
* slow movement
* turning
* multiple zoom levels
* camera movement across building boundaries

The existing camera/background jitter fix must remain intact.

---

# 13. Protect Existing Fixes

The previous work fixed a serious vehicle/camera jitter issue.

The vehicle is now stable.

Do not modify the vehicle movement or camera update architecture unless absolutely required and proven necessary.

After this phase verify:

* vehicle remains stable
* background remains stable
* camera remains smooth
* accelerator release still works
* no vehicle jitter returns
* no background jitter returns

If a change causes either jitter problem to return, revert that change and investigate rather than masking the symptom.

---

# 14. Git

Keep this work focused.

Use separate commits where useful, for example:

```text
Optimize 3D building rendering with back-face culling
Tune 3D building camera FOV
```

Push the completed changes to the current branch according to the existing workflow.

**Do not create or push a Git tag.**

Do not include unrelated modifications.

---

# 15. Final Report

Report:

## Performance

Before/after benchmark:

```text
Average FPS
1% low FPS
Worst frame
Memory
```

Include the percentage improvement.

## FOV

Report:

* tested values
* selected final value
* why it was selected

## Visual verification

Report which building types and scenes were checked.

## Tests

Report:

```text
make godot-test: PASS/FAIL
make godot-selftest: PASS/FAIL
make audio-check: PASS/FAIL
Python tests: PASS/FAIL
```

If the three known `test_main_city_bin_integration.py` failures remain, explicitly identify them as pre-existing/unrelated.

## Remaining known issues

Confirm that these remain intentionally deferred unless they were unavoidably touched:

* canopies
* headlight clipping
* pitched-roof triangular caps
* night-time duplicate building pass

## Git

Report:

* commits created
* branch
* push status
* final commit hash

Do not create a Git tag.

---

# Definition of Done

This phase is complete when:

1. Back-face culling is correctly implemented.
2. Building geometry remains visually correct.
3. Performance is measured before and after.
4. FOV has been tuned to a visually convincing value.
5. Building footprints remain exactly aligned with the 2D map.
6. Camera movement remains smooth.
7. Vehicle stability remains unchanged.
8. Accelerator-release behaviour remains unchanged.
9. Existing Godot tests pass.
10. No unrelated architecture or parity work has been introduced.

Stop after this phase.

Do not proceed automatically to the canopy, headlight, or night-window redesign.
