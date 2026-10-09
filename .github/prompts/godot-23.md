# Godot 3D Building Layer — Render-Pass Optimization and Final Visual Polish

## Current State

The 3D building layer is now visually excellent and should remain the default renderer.

It provides:

* real 3D building volumes
* smooth facade changes as the camera moves
* no snapping
* exact alignment with the 2D map
* correct building heights
* correct rotated/irregular/L-shaped footprints
* convincing tall-building facades
* a straight-down perspective camera
* no camera tilt or roll
* FOV now set to **30°**

The implementation is committed and pushed.

Current final commit:

```text
34cae77
```

Branch:

```text
release/v0.16.0g-alpha
```

No Git tag.

The old 2D renderer remains available:

```text
--buildings 2d
```

---

# Important Finding From the Previous Optimization

Back-face culling has been implemented correctly.

It works.

However, it provides only a small overall performance improvement:

```text
FOV 40:
27.1 FPS → 27.6 FPS
approximately +2%

FOV 30:
20.5 FPS → 21.7 FPS
approximately +6%
```

The renderer measurements explain why.

The 3D building pass itself costs approximately:

```text
3.5–4.0 ms/frame
```

with or without culling.

The main view costs approximately:

```text
22–27 ms/frame
```

Therefore:

> Triangle count and wall geometry are NOT the primary bottleneck.

The major remaining cost is:

> rendering the full-screen 3D building image and compositing/blending it into the 2D game frame.

Do not spend another optimization pass trying to reduce triangle count unless profiling demonstrates a new geometry bottleneck.

---

# Primary Objective

Investigate and optimize the **render target / compositing cost** of the 3D building layer while preserving its current visual quality.

Then fix the three straightforward remaining visual geometry issues:

1. pitched-roof triangular end caps
2. canopies using the old 2D lift
3. headlight beam clipping against the 2D footprint

Leave the night-time duplicate building pass for a separate investigation unless profiling shows that it is currently a dominant daytime performance concern.

---

# HARD CONSTRAINTS

Do NOT change:

* the 3D building concept
* straight-down perspective projection
* FOV 30°
* coordinate mapping
* building heights
* building footprints
* chunk architecture
* worker-thread mesh generation
* vehicle movement
* vehicle interpolation
* camera follow implementation
* network protocol
* server simulation
* map data architecture
* 2D road rendering

Do NOT revert to:

* 2D facade tricks
* isometric rendering
* tilted camera
* orthographic 3D
* fake building depth
* camera-dependent building sprites

The current visual result is the baseline to preserve.

---

# 1. Establish a Render-Pass Baseline

Use the existing instrumentation that was added in the previous phase.

Measure separately:

```text
main 2D view
3D building pass
compositing cost if measurable
total frame time
```

Use the existing controlled benchmark:

```text
1280x720
software rendering
Oulu seeded spawn
daytime
30 seconds
standing still
fresh server
```

The previous benchmark established approximately:

```text
3D building pass:
3.5–4.0 ms/frame

Main view:
22–27 ms/frame
```

Confirm the current values before optimizing.

Do not optimize based solely on total FPS.

---

# 2. Investigate the Full-Screen Render Target

Trace exactly how the 3D building layer is rendered:

```text
3D building geometry
        ↓
3D camera
        ↓
SubViewport / Viewport
        ↓
render texture
        ↓
transparent image
        ↓
2D scene
        ↓
screen
```

Identify:

* render target resolution
* whether it is always exactly screen resolution
* whether it contains transparency
* whether MSAA is enabled
* whether HDR is enabled
* texture format
* mipmaps
* filtering
* whether the entire texture is redrawn every frame
* whether the entire texture is blended every frame
* whether only part of the viewport actually contains building pixels

Document the actual implementation before changing it.

---

# 3. Investigate Whether the 3D View Can Be Rendered at a Smaller Resolution

This is the most important optimization to investigate.

Because the building layer is primarily large flat-colour geometry with relatively simple facades, determine whether it can safely use a lower internal render resolution and then be composited/upscaled to the final game resolution.

Do NOT implement this blindly.

Test whether, for example:

```text
100%
90%
80%
75%
```

internal resolution produces an acceptable result.

The goal is to determine whether reducing the number of pixels processed by the 3D pass produces a significantly better frame time while remaining visually indistinguishable during normal gameplay.

Pay particular attention to:

* building edges
* windows
* doors
* thin facade details
* roof edges
* rotated buildings
* tall buildings
* camera movement

Do not accept a visibly blurry or aliased building layer merely to gain FPS.

If a lower resolution is visibly worse, revert it.

---

# 4. Investigate Whether the Render Target Needs Full-Screen Resolution

Determine whether the 3D building layer can be rendered only in the region where buildings are actually needed.

Do not assume this is possible.

The building layer currently behaves as a transparent full-screen image.

Investigate whether:

* a scissored region
* viewport rectangle
* partial render target
* screen-space bounds
* camera-visible building bounds

could reduce the amount of pixel work.

However:

> Do NOT introduce CPU-side per-frame polygon clipping or expensive visibility calculations merely to save pixels.

The optimization must remain cheaper than the rendering cost it removes.

If a partial viewport would complicate the architecture substantially, document that and leave it unchanged.

---

# 5. Investigate Transparency and Compositing Cost

The building layer is rendered into a transparent off-screen view.

Determine whether transparency is the primary reason the full-screen image is expensive to composite.

Profile or measure:

```text
3D rendering with transparency
3D rendering without transparency, if technically testable
compositing cost
```

Do not remove transparency from the final implementation if it is required by the layer ordering.

The purpose is diagnosis.

Potentially useful questions:

* Is the entire screen blended even where there are no buildings?
* Is the render target using an unnecessarily expensive format?
* Is MSAA multiplying the pixel cost?
* Is the final Sprite2D/TextureRect filtering unnecessarily expensive?
* Is the texture being copied more than once?

Only change something if measurements demonstrate a benefit.

---

# 6. Preserve Visual Layering

The final order must remain equivalent to the current game:

```text
roads
    ↓
3D buildings
    ↓
vehicles / world elements
    ↓
night tint
    ↓
HUD
```

Do not move the building layer above vehicles.

Do not move it below roads.

Do not break the night tint.

Do not change HUD compositing.

---

# 7. Fix Pitched-Roof End Caps

Current issue:

> The triangular ends of pitched roofs are open.

Close the existing geometry.

A pitched roof should form a closed volume.

Requirements:

* both triangular end caps present
* correct vertex winding
* correct back-face-culling behaviour
* no holes
* no z-fighting
* correct alignment with the existing roof
* correct behaviour for rotated buildings
* correct behaviour at different zoom levels

Do not redesign pitched roofs.

This is a geometry completeness fix.

Add a deterministic geometry test if practical.

The existing test that verifies outward-facing triangles must continue to pass.

---

# 8. Fix Canopy Height

Current issue:

> Canopies still use the old 2D lift.

Trace the existing canopy data and rendering.

Determine exactly what the old 2D "lift" represents.

Convert the canopy into the appropriate 3D representation using the existing building/world coordinate system.

Requirements:

* canopy remains attached to the correct building
* correct horizontal position
* correct height
* no floating
* no sinking
* correct rotation
* smooth camera movement
* no visible snapping

Do not create a new canopy architecture.

Use existing object/building information wherever possible.

---

# 9. Fix Headlight Beam Clipping

Current issue:

> Headlight beams are clipped using the original 2D building footprint, while the visible 3D building facade can extend beyond that footprint.

Investigate how headlight beam clipping currently works.

Identify whether the clipping is based on:

* 2D polygons
* collision geometry
* masks
* render layers
* viewport clipping
* custom ray tests

The desired behaviour is:

> Headlight beams should visually stop/interact at the visible building geometry rather than visibly passing through the 3D facade.

Do not implement real-time shadows.

Do not introduce expensive per-pixel lighting.

Do not redesign the lighting system.

Use the smallest architecture-compatible correction.

If a technically correct solution would require a major rendering architecture change, stop and report that rather than implementing an expensive workaround.

---

# 10. Night-Time Rendering — Investigate, Do Not Automatically Rewrite

Current behaviour:

* normal 3D building pass
* night tint
* separate lit-window pass
* lit-window pass uses black building copies so nearer buildings occlude farther windows
* lit-window pass does not run during daytime

Current issue:

> At night the building view is rendered a second time.

For this phase, determine whether this is a significant performance cost.

Measure:

```text
daytime 3D building pass
night-time normal pass
night-time window pass
total night building cost
```

Do NOT redesign the night renderer simply because it renders twice.

If it is not currently a significant bottleneck, leave it untouched and report the measurement.

If it is significant, document the possible optimization approaches but do not implement a major architecture change unless a simple safe solution exists.

---

# 11. Do Not Chase the Wrong Bottleneck

Do NOT spend time on:

* further triangle-count micro-optimization
* more aggressive back-face logic
* manual face removal
* CPU visibility calculations
* reducing building geometry quality
* reducing number of windows
* removing doors
* simplifying footprints
* reducing building heights

The previous profiling already demonstrated that the building pass's major cost is pixel/render-target work.

---

# 12. Performance Acceptance Criteria

There is no arbitrary FPS target.

The optimization should be judged by:

1. measurable reduction in 3D render/composite time
2. measurable improvement in total frame time
3. no visible degradation during normal gameplay

Report the improvement in milliseconds as well as FPS.

For example:

```text
3D pass:
Before: 3.8 ms
After: 2.6 ms

Total frame:
Before: 35.0 ms
After: 31.5 ms
```

Use actual measured values, not estimates.

---

# 13. Visual Regression Testing

Use the existing test scene:

* low building
* tall building
* L-shaped building
* irregular building
* pitched-roof building
* commercial building
* rotated building

Check at:

* zoom 4
* zoom 7
* zoom 12

Also check:

* camera pan
* normal gameplay movement
* Oulu
* building edges
* roofs
* windows
* doors
* canopies
* headlights

The visual baseline is the current 30° implementation.

Do not compare against the old 40° version as the desired result.

---

# 14. Protect the Existing Vehicle/Camera Fix

The vehicle is currently stable.

The background/camera jitter has already been fixed.

Do not modify:

* vehicle interpolation
* vehicle transform ownership
* camera follow logic
* network state timing

unless a direct dependency makes it unavoidable.

After all changes verify:

* vehicle remains stable
* background remains stable
* camera remains smooth
* accelerator release remains correct

---

# 15. Tests

Run:

```bash
make godot-test
make godot-selftest
make audio-check
```

The current Godot baseline is:

```text
350 checks
all passing
```

All existing tests must remain green.

Add focused deterministic tests for:

* pitched-roof end caps
* canopy 3D positioning, if practical
* render-target configuration, if practical

Do not add fragile screenshot tests unless an existing reliable screenshot framework already exists.

---

# 16. Python Tests

The known Python baseline remains:

```text
1,562 passed
3 failed
```

The three failures are:

```text
test_main_city_bin_integration.py
```

These are known unrelated Pygame/BIN failures.

Do not modify the old Pygame/BIN implementation to make them pass.

If the Python suite is run, report them separately.

---

# 17. Scratchpad

The previous phase left:

```text
godot-22.md
```

untracked.

Review it.

If it contains the appropriate documentation/report for this work, commit it.

Do not blindly commit unrelated scratchpad files.

---

# 18. Git

Keep commits focused.

Suggested structure:

```text
Optimize 3D building render target/compositing
Fix pitched roof end caps
Fix 3D canopy positioning
Fix 3D headlight clipping
```

Combining very small related changes into one commit is also acceptable if the resulting history remains clear.

Push the completed changes to:

```text
release/v0.16.0g-alpha
```

**Do not create or push a Git tag.**

Do not include unrelated work.

---

# 19. Final Report

Report:

## Render performance

Before and after:

```text
3D building pass:
Main view:
Total frame:
Average FPS:
1% low:
Worst frame:
Memory:
```

Explain whether the render-target/compositing optimization materially helped.

## Resolution / viewport

If changed:

* previous resolution
* new resolution
* measured performance improvement
* visual impact

If not changed, explain why.

## Geometry

Report:

* pitched roof end caps
* canopies
* headlight clipping

## Night rendering

Report measured daytime/night costs and whether the second-pass architecture was left unchanged.

## Tests

Report:

```text
make godot-test: PASS/FAIL
make godot-selftest: PASS/FAIL
make audio-check: PASS/FAIL
Python tests: PASS/FAIL
```

Mention the three known Python failures separately.

## Git

Report:

* commits
* final commit
* branch
* push status
* whether `godot-22.md` was committed

No Git tag.

---

# Definition of Done

This phase is complete when:

1. The 3D building layer remains visually equivalent to the current excellent result.
2. The main render-target/compositing bottleneck has been measured.
3. A safe optimization is implemented if a meaningful one exists.
4. No optimization is added merely for the sake of changing code.
5. FOV remains at 30°.
6. Pitched-roof end caps are closed.
7. Canopies are correctly integrated with the 3D building layer.
8. Headlight clipping is corrected if it can be done without major rendering redesign.
9. Night rendering is measured rather than blindly rewritten.
10. Vehicle and camera stability remain intact.
11. All Godot tests pass.
12. Changes are committed and pushed.

If render-target optimization does not produce a meaningful improvement without visible quality loss, **leave the current implementation intact and report that result**. A measured conclusion that the remaining cost is inherent to the current compositing architecture is preferable to a complicated optimization that makes the game worse.

Stop after this phase. Do not proceed into a new rendering architecture.
