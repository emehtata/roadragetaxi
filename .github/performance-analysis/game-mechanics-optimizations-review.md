# Smoothness ideas from `game-mechanics-optimizations/`

Date: 2026-10-15. Branch `release/0.17.0alpha` at `9e2866e`.
Status: **review only; no game code changed.**

The folder holds about 180 short write-ups: 117 general engine and game-feel
techniques (`01`–`117`), plus game-design patterns (sections `A`–`J`:
progression, rewards, difficulty and so on). Several are thin templates
(e.g. `38_dynamic_resolution.md`, whose "shipped games" are placeholders), so
each idea below was checked against how this game actually works and what has
already been measured:
- [map-loading-02](map-loading-02.md)
- [weather-traffic-2026-10-14](weather-traffic-2026-10-14.md)
- the `make godot-selftest` report

"Smoother" here means three things: the picture never freezes or jumps,
frames are steady, and the drive feels responsive.

## Worth trying, in order

### 1. Keep moving when a state is late (bounded extrapolation)

Source: `06_fixed_timestep.md` (interpolation and extrapolation),
`75_input_lag_minimization.md`, `14_ring_buffers.md`.

**Now:**
- `godot/state_buffer.gd` only interpolates, 100 ms behind the server.
- When the render time passes the newest state, the picture holds still:
  "no prediction" in its own header.
- Every server stall longer than the buffer becomes a visible freeze. Then the
  render clock slews at up to ±25 %, and that is the "slow motion afterwards".
- Measured: the selftest in this session had 6 underrun episodes, the longest
  441 ms, with the clock rate down to 0.74. map-loading-02 counts 12–15 freezes
  on a cold drive.

**Try:**
- Past the newest state, move each moving entity on along its last velocity and
  turn rate. Cap it at about 0.2–0.25 s, then hold as now.
- When the late state arrives, blend the drawn pose to it over about 0.1–0.2 s
  instead of snapping.
- Only positions and headings. Discrete values (lights, phases, events) stay
  as they are, and the server stays authoritative.

**Watch out for:**
- Overshoot at a sudden stop or a crash. Limit the extrapolation by the speed
  and the time, and never past a stopped vehicle's own position.
- Events must still play when their state is reached. `take_due_events` is not
  touched.

**Measure:** freezes and clock snaps in `tools/bench_map_jitter.py`, and
`underrun_episodes`, `longest_underrun_ms` and `motion` in the selftest. Two
runs per variant, as before.

This hides the server stalls rather than removing them; #5 removes the biggest
remaining one.

### 2. Camera look-ahead and speed zoom

Source: `82_camera_lead.md`.

**Now:**
- `main.gd` puts the camera exactly on the taxi (`camera.position = entities.player_position()`),
  at a fixed zoom that only the player changes.
- At the default 9 px/m a 1280×720 view is about 142 × 80 m. Driving "up" the
  screen shows about 40 m ahead, which is 2 s at 72 km/h. Every sharp camera
  change also comes straight from the taxi's own interpolation.

**Try:**
- Offset the camera ahead of the taxi by its velocity × about 0.6 s, capped at
  about 30 % of the view.
- Ease out a little with speed, for example to 0.8× at 80 km/h.
- Use a critically damped spring, which follows without overshoot, so that
  steering and braking don't swing the view.
- Client-only; the server's camera position (used for NPC culling and debug
  snapshots) stays as it is.

**Watch out for:**
- Zooming out shows more chunks, more buildings and more labels. Measure the
  frame time at the widest zoom it reaches.
- Keep the player's own zoom (+/−, wheel) as the base the speed factor multiplies.

**Measure:** the selftest's `motion.cv_camera_step` and `step_change_px_*`, plus a
look at fast driving.

### 3. Tyre trail in segments

Source: `42_tilemap_chunking.md`, `48_dirty_rectangles.md`, `04_dirty_flags.md`.

**Now:**
- `entity_layer.gd` keeps up to 4,000 trail points on one canvas item. Each new
  point and, while it snows, each 0.25 s of burial redraws the whole trail.
- weather-traffic-2026-10-14 measured about 22 ms per rebuild of a
  4,000-point trail, four times a second during snowfall.
- That report's other two items have since been fixed: snow geometry
  (`b885d0b`) and parking selection (`55861f4`).

**Try:**
- Fixed-size segments, for example 200 points each on its own canvas item.
- A new point redraws only the newest segment, and old segments are dropped
  whole.
- Snow burial fades a segment with its canvas item's modulate instead of
  redrawing its points.

**Measure:** the existing snow track stress case (`client_driver.gd` in
`weather-traffic-2026-10-14-data/`).

### 4. Cheaper 3D buildings, after measuring on a real GPU

Source: `38_dynamic_resolution.md`, `16_lod_systems.md`.

**Now:**
- `buildings_3d.gd` renders the buildings in a SubViewport the size of the screen.
- Their meshes always include every window: 135,930 in the Oulu benchmark.
- Turning the layer off saved about 5 ms/frame, but that was measured on Mesa
  llvmpipe, a software renderer.

**First:** measure the same scene on real hardware (Windows build).
If it still costs several milliseconds there, try:
- **Render scale:** draw the SubViewport at 0.75 and let the sprite scale it
  up. Buildings are soft shapes, and the 2D map and labels stay sharp.
- **Window detail by zoom:** split the window and lit-window geometry into its
  own mesh per chunk and hide it below a zoom where a window is under about
  2 px.

If the hardware cost is small, skip this item.

### 5. Build cold tiles outside the server process

Source: `12_job_system_multithreading.md`, `08_async_compute.md`.

This is already the first remaining item in map-loading-02. The tile loader
holds the Python GIL for up to about 0.2 s, and young GCs reach 70–83 ms while
a new area loads. Building tiles in a worker process removes the stall that
#1 would only hide. It is listed here because the folder's job-system note
agrees with that plan, not as a new idea.

### 6. Small, only if a profile shows it

- **Audio one-shot pool** (`01_object_pooling.md`): `audio_manager.gd` creates a
  new `AudioStreamPlayer2D` per sound and frees it when done. Fireworks can
  play about 5 sounds a second, plus footsteps and train events. Pool a dozen
  players if node creation shows up in a frame profile.
- **Game feel, not frame time:**
  - `97_camera_trauma.md`: a short decaying shake on crashes.
  - `113_doppler_effect.md`: pitch passing trains, trams and tractors by their
    relative speed.

  Both are easy polish once the above is done.

## Already done, or not applicable

| Technique | Why it's not on the list |
| --- | --- |
| 06 fixed timestep | The server already runs fixed 1/30 s ticks and the client interpolates; #1 adds the missing extrapolation half. |
| 02, 07 spatial partitioning / hashing | `SpatialWayGrid` is used throughout (ways, buildings, NPCs, street lights). |
| 17, 18, 41, 42 culling, batching, chunking | The map is chunked, each chunk has one draw list per style, and chunks are culled by the view. |
| 04 dirty flags (snow) | Done in `b885d0b`; the remaining case is the tyre trail (#3). |
| 34 shader compilation cache | Godot's disk shader cache is in use (`user://shader_cache`); no first-use hitches were reported in the measurements. |
| 09 sleeping bodies | Parked NPCs without a driver return early in `update_npc`. |
| GC tuning (64, 66) | Done in map-loading-02 (`performance.tune_interpreter()`). |
| 03, 05, 11, 13, 25 ECS, arenas, fast inverse sqrt, SoA, SIMD | Python/GDScript, and none of the measured stalls are this kind of cost. |
| 10, 19–33, 35–37, 39, 40, 53–63 3D/texture pipeline | A top-down 2D map with one simple 3D building pass; no textures, skinning or shadows to optimise. |
| 69, 70 continuous collision, sub-stepping | Correctness, not smoothness. At 210 km/h a tick moves about 1.9 m, so very thin obstacles could be tunnelled. Check separately if it's ever seen. |
| 71–81, 83–94, 100–117 platformer and combat feel | No jumping, aiming or combat in a driving game. |
| Sections A–J (design patterns) | Progression and reward design; out of scope for smoothness. |

## Suggested order of work

1. Bounded extrapolation (#1): the biggest visible improvement for the least
   code, client only.
2. Camera look-ahead (#2): client only; measure the zoomed-out frame time.
3. Trail segments (#3).
4. The real-GPU measurement, then #4 only if needed.
5. The tile worker process (#5), the larger server change.

Measure each change separately against the current numbers, with two runs per
variant. Keep street lights, snow, legal yielding and sidewalk checks as they
are; don't raise the interpolation delay as the fix (the earlier reports' rule).

## Results (2026-10-15, same day)

| Item | Outcome |
| --- | --- |
| 1 Extrapolation | Done (`877a3dd`). `bench_map_jitter.py`, 180 s at 72 km/h. Warm route east: the server was late 28 times (3.9 s), only 3 freezes (0.3 s) remain past the 0.2 s cap. Cold route south: late 20 times (1.4 s), 0 freezes. Before, every late frame was a freeze. |
| 2 Camera look-ahead | Done (`266e3d7`), look-ahead only. The speed zoom was tried and dropped: a zoom change every frame redraws the pixel-sized map layers (selftest 13 fps instead of 138, camera steps up to 31 px). With look-ahead only: 138 fps, largest step 1.1 px. |
| 3 Trail segments | Done (`f5e4aaa`). A new point rebuilds at most 200 points instead of up to 4,000. Snowfall fades segments by modulate, with no redraw. |
| 4 3D buildings | Skipped. On the RTX 5060 (WSL, `GALLIUM_DRIVER=d3d12`, night, 20 s, two runs each) hiding the 3D buildings changed nothing: about 37–43 ms per frame either way. That frame time is mostly render submission on the CPU (`render_cpu` about 19.5 ms for about 1,850 draw calls; the 3D pass about 6 ms). The draw-call count is the real lever, and it needs measuring on a native Windows build, because WSL's d3d12 translation adds its own per-call CPU cost. |
| 5 Tile worker process | Already in place (`3361e36`: cold local-PBF extraction, conversion and build in a worker process). It matches the cold route above showing no freezes. |
