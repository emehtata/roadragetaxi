Analyze and fix the intermittent frame stutter in the `release/0.11.0alpha` branch of the Road Rage Taxi / The Road Rage Trip Pygame project.

## Problem

The game normally runs at approximately 60 FPS, but gameplay has a noticeable hitch roughly once per second while the taxi is moving. The hitch makes driving difficult.

The camera follows the taxi and its position takes the vehicle's movement/speed into account. The project also uses several static rendering caches that depend on camera position.

The current suspicion is:

```text
taxi moves
  -> camera position changes
  -> camera crosses a cache boundary
  -> one or more render caches are invalidated/rebuilt
  -> expensive work happens synchronously on the main thread
  -> one frame becomes much slower
  -> visible hitch/stutter
```

This is especially important because the project already contains explicit static-cache invalidation and throttled rebuild mechanisms, and the frame profiler has previously documented a large frame spike caused by a static-cache rebuild.

## Goal

Eliminate the periodic camera-induced frame spikes without removing the visual quality of the existing rendering system.

The game should maintain smooth camera movement and approximately stable 60 FPS while driving.

## Requirements

### 1. Inspect the actual camera implementation first

Find the code responsible for:

* calculating `camx` / `camy`
* camera following the taxi
* speed-based camera look-ahead
* camera smoothing/interpolation
* camera jumps
* zoom handling
* camera-related static-cache invalidation

Do not assume where the implementation is located. Trace the actual call path in `release/0.11.0alpha`.

Do NOT simply remove camera smoothing or speed-based look-ahead as a shortcut.

The camera behaviour should remain visually similar after the fix.

### 2. Trace all camera-dependent caches

Identify every rendering cache whose key or invalidation depends on:

* `camx`
* `camy`
* camera movement
* zoom
* viewport changes

Pay particular attention to:

* roads
* scenery
* buildings
* water
* labels
* navigation
* pedestrians
* other static rendering layers

Determine which cache rebuilds can execute synchronously during the gameplay frame.

### 3. Prevent synchronous cache rebuilds caused by normal camera movement

Normal camera following must NEVER cause a large blocking cache rebuild in the same frame.

Use the existing static-cache infrastructure where possible instead of creating a second caching system.

Preferred behaviour:

```text
camera moves
    |
    +-- current cache still usable
    |       -> render cached surface with camera offset
    |
    +-- cache boundary crossed
            |
            +-- continue displaying the previous cache immediately
            |
            +-- schedule/rebuild the new cache incrementally
                over subsequent frames
```

The player should never have to wait for the new cache to finish.

If the existing implementation already has stale-cache support, make sure it is actually used for normal camera movement.

### 4. Keep camera movement smooth

Do not replace the existing camera system with:

```python
camx = car.x
camy = car.y
```

unless that is demonstrably necessary.

Preserve:

* camera smoothing
* speed-based look-ahead
* zoom behaviour
* camera centering
* normal camera transitions

The fix should target the expensive work triggered by camera movement, not the camera feature itself.

### 5. Distinguish camera movement from camera jumps

A deliberate camera jump, such as:

* respawn
* changing city
* teleport/debug reposition
* initial map placement

may legitimately invalidate all relevant caches.

Normal continuous taxi movement must NOT be treated as a camera jump.

Verify that `invalidate_static_caches_for_camera_jump()` is only used for genuine discontinuous camera changes.

### 6. Avoid excessive cache churn

Inspect cache keys carefully.

A cache key should not change because of tiny floating-point camera movements.

Where appropriate, use spatial quantization/grid cells for cache keys, for example:

```python
camera_cell_x = round(camx / CACHE_CELL_SIZE)
camera_cell_y = round(camy / CACHE_CELL_SIZE)
```

Do not blindly choose a new cell size. Determine an appropriate value based on the existing rendering resolution, zoom and visual requirements.

The existing 128-pixel-style quantization is a useful clue, but verify the actual implementation before changing it.

### 7. Do not introduce per-frame allocations unnecessarily

While fixing the cache system, avoid creating large:

* `pygame.Surface`
* lists
* dictionaries
* transformed images
* geometry collections

every frame.

Reuse existing surfaces and data structures whenever possible.

### 8. Keep rendering visually correct

The following must remain correct while the stale cache/new cache transition occurs:

* camera-relative positioning
* roads
* buildings
* scenery
* water
* labels
* pedestrian rendering
* navigation
* shadows/effects where applicable

There must be no visible "jump" in the world when a cache is replaced.

### 9. Use the existing profiler

Extend or use the existing `FrameProfiler` if necessary.

Make it possible to distinguish at least:

```text
camera_update
static_cache_rebuild
static_cache_blit
map_sync
tile_integration
```

Do not leave permanent noisy logging enabled every frame.

If a cache rebuild takes longer than a reasonable frame budget, it should be spread across multiple frames or moved away from the critical rendering path.

### 10. Be careful with threading

Do not blindly move Pygame `Surface` creation/manipulation to a worker thread.

Pygame rendering operations should remain on the main thread unless the existing architecture explicitly supports otherwise.

If expensive preparation can safely be done off-thread, separate CPU-side preparation from Pygame surface creation.

Correctness is more important than adding threads.

## Investigation procedure

Before modifying code:

1. Trace the camera update path.
2. Trace every call to:

   * `invalidate_static_caches`
   * `invalidate_static_caches_for_camera_jump`
   * `begin_static_cache_frame`
3. Trace every static cache rebuild.
4. Determine which rebuild can occur during normal taxi movement.
5. Determine whether the rebuild happens in the same frame that the camera crosses a cache boundary.
6. Identify the specific operation responsible for the frame spike.

Then implement the smallest architectural fix that removes the blocking operation.

## Important constraint

Do not solve the problem by:

* reducing the number of pedestrians
* reducing NPC traffic
* reducing map detail
* lowering rendering quality globally
* disabling static caches
* disabling camera smoothing
* disabling speed-based camera look-ahead
* artificially limiting FPS
* inserting sleeps
* hiding the problem with a larger `clock.tick()` value

The objective is to make the existing system efficient.

## Regression testing

Add or update tests for:

1. Small continuous camera movement does not invalidate/rebuild all static caches.
2. Crossing a cache boundary does not block the gameplay frame.
3. A genuine camera jump still invalidates caches correctly.
4. Zoom changes still invalidate/rebuild the appropriate caches.
5. Replacing an old cache with a newly rebuilt cache does not cause visual positioning errors.
6. Cache rebuild state cannot get permanently stuck.
7. Static-cache rebuilds cannot restart indefinitely while the taxi is moving.

## Performance acceptance criteria

After the fix:

* Normal driving should remain around 60 FPS.
* There should be no recurring ~1 second hitch caused by camera movement.
* A cache boundary crossing may cause background/incremental work, but must not produce a noticeable frame spike.
* No single normal camera movement frame should perform a full-world/static-cache rebuild.
* Genuine map/tile loading may still temporarily require work, but camera movement itself must not amplify that work.

## Final response

After implementing the fix:

1. Explain the actual root cause you found.
2. List the files changed.
3. Explain the new cache/camera behaviour.
4. Explain how normal camera movement differs from a camera jump.
5. Explain what tests were added or updated.
6. Report any remaining potential frame-spike sources.

Do not make speculative changes unrelated to the identified camera/cache bottleneck.
