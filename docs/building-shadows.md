# Sun direction and building shadows

The 3D buildings cast real shadows from the sun's actual direction, weakened by
low sun and by clouds. Task: `.github/prompts/rrt-018-shadows.md`.

## Coordinate conventions

| Space | Axes | Source |
| --- | --- | --- |
| Server map metres | EPSG:3067 (ETRS-TM35FIN): +x east, +y grid north | `world_loader`, pyproj |
| Godot 2D map layer | +x east, +y **south** (`MapMath.point` flips y) | `map_math.gd` |
| Godot 3D building view | 2D (x, y) → 3D (x, h, y): +x east, +y up, **−z north** | `buildings_3d.gd` `to_3d` |

Grid north is not true north. The meridian convergence is about
(longitude − 27°) × sin(latitude), from −1.8° in Helsinki to +1.7° in Joensuu.
The server applies it: `calendar.grid_azimuth` is checked against pyproj in
`tests/test_sun_position.py`.

## The sun

- **Model:** `calendar.solar_position_on` gives the altitude and azimuth from
  the existing solar model: Cooper's declination, Spencer's equation of time,
  the game clock and Finnish summer time. Sunrise and sunset now share that
  computation.
- **Azimuth:** clockwise from true north, 0–360° (90 east, 180 south). It is
  computed with `atan2` of the horizontal components, so it is finite at every
  altitude, including below the horizon and near the zenith.
- **Accuracy:** about 1.5° in altitude and azimuth against NOAA's solar
  position equations (`tests/test_sun_position.py`: morning, noon, evening,
  summer, winter, the midnight sun, night, all four quadrants, minute-by-minute
  continuity).
- **Sent to the client:** `calendar.sun_azimuth_deg`, clockwise from the map's
  grid north, next to `sun_altitude_deg`. This is a protocol addition: the
  client must not compute the sun itself.
- **Direction in the client:** `Daylight.sun_direction(alt, az)`
  = (sin az · cos e, sin e, −cos az · cos e) in the 3D view's axes, with
  e = max(alt, `SHADOW_MIN_ELEVATION_DEG`).
- **Light orientation:** Godot's DirectionalLight3D shines along its −z axis,
  so `Buildings3D.sun_basis` points −z away from the sun. The Godot tests
  check this, including the sun straight overhead.

## Rendering

The buildings are unshaded and their light is baked into their colours. They
are drawn by a top-down 3D camera into a transparent SubViewport, which is
composited over the 2D map (z 7). The shadows use:

1. **One DirectionalLight3D in that 3D world:** orthogonal, a single shadow map
   with no splits, which suits a top-down view. The project's directional
   shadow map is 2048 (`project.godot`); 1024 and 4096 cost the same (below).
2. **Prism casters:** one shadows-only prism per building, with walls and a flat
   roof, built with the chunk's meshes in the same worker-thread pass. They hold
   about a fifth of the triangles (no windows or doors) and are never drawn.
   Gables are left out, so their shadows are a little shorter.
3. **A shadow view:** a second SubViewport of the same 3D world, so no building
   geometry is duplicated. It renders at half resolution and sees only a ground
   plane, `shadow_ground.gdshader`: white in the sun, `1 − darkness` in shadow.
4. **Compositing:** that view is multiplied over the map at z 6, under the
   buildings and over the ground, roads and street furniture. Cars and
   pedestrians (z 12) are not shadowed.

Facts verified on Godot 4.7.2's Compatibility renderer while building this:

- `shadow_to_opacity` does not work, so the shadows can't be alpha inside the
  building view.
- A camera culls lights and shadow casters that are outside its cull mask. The
  light, the ground and the casters therefore all sit on `LAYER_SHADOW_GROUND`.
- Unshaded ShaderMaterials cast no shadow, so the casters use a standard
  material.
- With the ground on the camera's far plane, the orthogonal shadow fit loses
  every shadow. The shadow camera sees to twice its height.

| Setting | Value | Why |
| --- | --- | --- |
| `SHADOW_DARKNESS` | 0.45 | A shadow multiplies the ground by 0.55 in clear sunlight |
| Shadow bias / normal bias | 0.05 / 0.5 | No acne on the ground; casters touch their shadows (no peter-panning seen) |
| `directional_shadow_max_distance` | √(height² + (half view diagonal × 1.3)²) | Covers exactly the visible ground, at any zoom |
| `SHADOW_VIEW_SCALE` | 2 | Half resolution, linearly filtered |
| `SHADOW_MIN_ELEVATION_DEG` | 8° | A shadow is at most 1/tan 8° ≈ 7× the building's height |

## Low sun, night and clouds

`Daylight.sunlight(alt, cloud)` sets how strongly the sun shines directly,
0 to 1, and the shadows' darkness follows it:

- **Altitude:** smootherstep from 0 at 1° to 1 at 12°. There are no shadows
  below the horizon, and they fade in at dawn and out at dusk without a step.
  The day/night ambient (`Daylight.ambient`) is unchanged.
- **Clouds:** 1 − smootherstep from 0.3 to 0.9 cloud cover. Up to 30 % cover
  gives full shadows; from 90 % up there are none, with a smooth fade between.
- **Switched off:** when the result is under 0.01 (night, overcast), the light,
  the ground and the shadow view are switched off. Nothing is rendered, so the
  frame costs what it did before this feature.
- **Recomputed only on change:** the sun is reapplied only when the server's
  values change (they are rounded to 0.01°).
- **Weather never moves the sun:** clouds change only the strength, never the
  direction.

Street lights, headlights and lit windows are unchanged; they don't use this
light.

### Cloud cover (weather)

The weather model only knew clear, rain, slush and snow, so it gained
`cloud_cover` (0 clear to 1 overcast), sent as `weather.cloud_cover`:

- **History on (FMI):** the observed `n_man` (cloud amount in eighths, from the
  nearest station that reports it) / 8, or the forecast's `TotalCloudCover` / 100.
  The weather follows it smoothly. The FMI cache tables moved to `_v4` and
  `_v2` with a cloud column, so older chunks are fetched again.
- **Generated:** a new target every 1–4 game hours from a seasonal mix of clear
  (0–0.25), partly cloudy (0.3–0.7) and overcast (0.8–1) skies.
  - The mix weights are **estimates** of Finnish climate: summer 35/40/25 %,
    winter 15/25/60 %.
  - The cover eases toward each target over 15 game minutes.
  - While it rains or snows, the target is at least 0.85. That is not 1,
    because showers have breaks, and precipitation alone doesn't say how cloudy
    it is.
- **Thunderstorms:** no separate rule. A storm precipitates, so the 0.85 floor
  applies, and observed cloud wins when available.

## Visual verification

The test scene uses fixed buildings and a fixed camera, one screenshot per case:

```
GALLIUM_DRIVER=d3d12 godot --path godot --resolution 1280x720 --script res://tests/shadow_scene.gd -- /tmp/shadows
```

`GALLIUM_DRIVER=d3d12` uses the GPU under WSL; Godot's default there is
llvmpipe, software rendering. Results (checked by eye, 2026-10-17):

| Case | Sun | Seen |
| --- | --- | --- |
| morning | 20° up, from 100° (east) | Long shadows pointing west |
| noon | 50° up, from 180° (south) | Shorter shadows, pointing north |
| evening | 15° up, from 280° (west) | Shadows rotated to point east |
| winter | 6° up, south | The longest (capped at 7× height) and faint |
| partly | noon, 60 % cloud | The same shadows, paler |
| overcast | noon, 100 % cloud | None |
| night | −10° | None |

In the game, the same can be forced with `--sun-altitude`, `--sun-azimuth` and
`--cloud-cover`. In central Oulu on 21 June at 10:30 (sun about 45° up in the
south-east), the shadows fall north-west across courtyards and streets. They
stayed aligned with their buildings while the view was rotated with the taxi's
heading, and an overcast frame of the same scene has none.

## Performance

Measured with `tests/shadow_bench.gd`: one process, about 3,000 buildings, 1080p
and a moving view. Shadows are switched on and off in alternating blocks of 60
frames, so drift hits both alike. The values are building-layer frame times
(milliseconds, median of the blocks), on an RTX 5060 through WSL d3d12:

| Shadow map | Off | On | Cost |
| --- | --- | --- | --- |
| 1024 | 5.90 | 6.68 | +0.8 |
| 2048 (chosen) | 5.82 | 6.52 | +0.7 |
| 4096 | 5.80 | 6.62 | +0.8 |

- **Before optimising:** the first version used the full building meshes as
  casters at full resolution, and doubled the game's frame time in `--bench`.
  Prism casters and the half-resolution view made it what it is now.
- **Software rendering (llvmpipe):** the same scene costs +13 ms
  (28.9 → 42.0 ms).
- **No change when off:** at night and under overcast the shadow view isn't
  rendered at all.

Full-game `--bench` runs on this machine weren't usable for a before/after
comparison. The WSL d3d12 path's frame times drifted between 59 and 122 ms on
the unchanged code within an hour, and GPU timer queries read 0. Measure the
Windows build on real hardware before a release.

## Limitations

- **Cars and pedestrians:** they are drawn above the shadows, so they are never
  shadowed and don't cast shadows.
- **Roofs:** they don't receive shadows from taller neighbours (the buildings
  are unshaded).
- **Gables:** the casters are flat-roofed prisms, so gable shadows are slightly
  short.
- **Low sun:** shadows are capped at 7× the building's height.
- **Generated clouds:** they are an estimate, not a forecast. Cloud cover is
  only real when FMI history is on.
