# Godot Parity Phase 6 — Weather Presentation

## Objective

Implement the next recommended phase from
`docs/architecture/godot-pygame-rendering-parity.md`:

1. visible rain, slush, and snow
2. puddle ripples while precipitation is falling
3. local taxi splashes when entering a visible puddle at speed
4. normal/heavy rain, wind/strong-wind, and wet-tyre audio

The server remains authoritative for weather type, wetness, thunderstorm
state, wind, vehicle position, and speed. Godot owns only short-lived visual
particles/effects and derives loop volumes from authoritative state, as the
Pygame renderer/audio layer does.

This is one weather-presentation phase. Do not combine it with historical FMI
weather, temperature, forecasts, speech, stations, settings, or unrelated
polish.

---

## 1. Read the current implementation first

Before changing code, trace:

* `WeatherSystem` types, fixed rain-particle pool, thunderstorm state, wind,
  wetness, splash pool, and real-time/game-time update rules in `weather.py`
* `draw_rain`, puddle ripple constants/drawing, `find_puddle_overlap`, and
  `draw_splashes` in `render/weather.py`
* Pygame's puddle-entry edge detection and `audio.update_ambience()` call in
  `main/__init__.py`
* rain/wind/wet-road loop formulas in `audio.py`
* weather state construction in `protocol.py`
* server weather updating and thunder event handling in `server/__init__.py`
* Godot wetness/puddle generation in `map_layer.gd`, `map_chunk.gd`, and
  `render_style.gd`
* current rain loop and lightning presentation in `main.gd`
* audio loop configuration and playback in `audio_manager.gd` and
  `audio/audio_events.json`
* frame/render measurements from godot-18 and the current benchmark path
* existing Python weather/audio and Godot rendering tests

Use the current repository as the source of truth. Reuse the existing weather
types, constants, deterministic puddle geometry, audio assets, performance
counters, and test patterns.

---

## 2. Do not invent precipitation intensity

The current Pygame implementation has no continuous precipitation-intensity
game state. It uses:

* `weather_type`: clear, rain, slush, or snow
* a fixed pool of 220 screen-space particles while precipitation is active
* `is_thunderstorm` to add the heavy-rain audio variation

The audit's “intensity” wording must not create a new weather model. Preserve
the existing fixed-density visuals. Treat thunderstorm state as the existing
heavy-rain fact.

Do not add precipitation rates, density simulation, new random server state,
or weather gameplay rules.

---

## 3. Extend weather state minimally

Add only the missing authoritative facts to the existing `state.weather`:

```text
is_thunderstorm: bool
wind_vector_mps: [east, north]
```

Requirements:

* read both directly from the server's `WeatherSystem`
* send the gust-adjusted vector returned by `weather.wind_vector_mps`
* use finite numeric components
* keep `weather_type`, `wetness`, and `lightning_intensity` unchanged
* keep the extension additive and safe when fields are absent
* keep interpolation discrete for `is_thunderstorm`
* either use the newest wind vector discretely or interpolate its two finite
  components only if that matches the current state-buffer conventions
* do not bump the protocol version unless established repository rules require
  it for additive state fields

Do not send particle positions, ripple phases, splash objects, loop volumes,
or a fabricated precipitation-intensity field.

---

## 4. Add one lightweight Godot weather presenter

Use one focused Godot script/node for dynamic weather presentation. Reuse an
existing suitable layer if it is clearly smaller; otherwise add one weather
canvas item rather than spreading particle state through `main.gd`.

It may own only client presentation state:

* a fixed particle pool initialized once
* real-time animation clock
* active local splash rings, capped at the existing maximum
* the previous “taxi is in a puddle” edge state

It must not own authoritative weather, wetness, taxi physics, or wind.

Avoid one Node per particle or splash. Reuse arrays/buffers and redraw one
canvas item.

---

## 5. Render rain, slush, and snow

Match Pygame's current fixed pool and real-time motion:

* 220 particles, allocated once and recycled
* screen-space positions independent of the camera and loaded map
* animation uses real frame delta, not accelerated game time
* clear weather hides the layer and performs no particle draw work
* rain: short pale-blue streaks
* snow: white flakes, one or two pixels/radius classes as appropriate
* slush: small grey-white flakes with short rain streaks
* snow falls slower and drifts more than rain; slush is intermediate
* wrapping/recycling does not grow arrays or instantiate nodes

Use batched drawing:

* one canvas item for all precipitation
* pack rain/slush streaks into one multiline/batched submission
* pack snow/slush flakes into the smallest practical additional submission
* no full-screen translucent particle texture or per-particle draw node

The intended ceiling is a few batch submissions for the complete fixed pool,
not hundreds of CanvasItems or draw nodes. If Godot's available API makes a
single submission per primitive type impractical, use the smallest measured
alternative and document the draw-call count.

Do not tie particle direction to the real wind vector: Pygame's particle pool
uses its existing fixed screen-space drift. Wind is used for audio and server
physics.

Hide precipitation below the surface/inside an underground map level unless
the current Pygame level behaviour proves otherwise.

---

## 6. Add ambient puddle ripples

Godot already owns deterministic puddle spots per loaded chunk. Extend those
spots with one deterministic phase value generated by the same per-road RNG;
do not send ripple state from the server.

Match Pygame's presentation constants and rule:

* ripples occur only while rain, slush, or snow is actively falling
* a puddle left wet after precipitation stops has no ambient ripple
* each puddle has a 2.4 s phase cycle
* the visible ripple lasts 1.0 s
* the ring expands and fades during that second
* strength follows the puddle's existing wetness visibility
* puddle polygon geometry and wetness reveal rules remain unchanged

Keep the animated rings separate from static puddle polygons if that avoids
redrawing every puddle shape each frame. Redraw only loaded/visible ripple
geometry while precipitation is active. Do not add timers or nodes per puddle.

---

## 7. Add local taxi splashes

Splashes are visual-only and remain client-side. Use Godot's own deterministic
puddle spots, because those are the puddles the player sees.

Match Pygame's rule:

* test the interpolated taxi position against visible puddles
* probe radius is half the larger of taxi length/width
* require absolute speed at least 1.0 m/s
* spawn only on the transition from outside to inside a visible puddle
* remaining inside does not spawn more splashes
* leaving and entering again may spawn another
* strength is `min(1, abs(speed) * 3.6 / 60)`
* lifetime is 0.5 real seconds
* the ring expands and fades from the entry position
* cap active splashes at 40, discarding oldest excess entries

Use a small chunk/map-layer query over loaded nearby puddle spots. Do not scan
the whole world, duplicate puddle generation, or add physics/collision effects.

Do not spawn splashes while on foot or underground.

---

## 8. Complete weather audio

Reuse the existing generated catalog files and loop system. Add the minimum
loop definitions needed for:

* base rain, `weather.rain` variation 0
* heavy rain, `weather.rain` variation 1
* wind, `weather.wind` variation 0
* strong wind, `weather.wind` variation 1
* wet tyres, `weather.wet_road` variation 0
* slush tyres, `weather.wet_road` variation 1

Match Pygame's formulas:

```text
raining = weather_type is rain or slush
base rain = 0.6 when raining, else 0
heavy rain = 0.7 when raining and is_thunderstorm, else 0
wind speed = length(wind_vector_mps)
wind = clamp(wind speed / 12, 0, 1) * 0.5
strong wind = clamp((wind speed - 10) / 10, 0, 1) * 0.6
wet tyres = 0 when on foot, otherwise clamp(wetness * abs(speed) / 15, 0, 1) * 0.6
wet-tyre variation = slush only when weather_type is slush
```

Snow does not use the rain loop. Existing thunder one-shots and lightning
flash remain unchanged.

An older server without thunderstorm/wind fields must remain safe and quiet
for the missing layers while retaining the current base rain behaviour.

Do not add or regenerate audio assets. Do not redesign buses or the audio
manager.

---

## 9. Scope and protected systems

Do not change:

* weather transitions, wetting/drying, temperature rules, or wind generation
* wind effects on server-side vehicle physics
* historical weather/FMI loading
* lightning generation, thunder events, or lightning rendering
* existing wet-road tint and puddle polygons
* vehicle physics or camera/interpolation
* map streaming, chunks, buildings, night lighting, or navigation
* road rage, fare, fuel, score, or career rules

Do not implement forecasts, temperature HUD, ground/landuse texture, spring
ice floes, engine layers, steam, footsteps, station audio, or speech.

No new dependency or media asset is needed.

---

## 10. Tests

Add the smallest deterministic checks at the layer that owns each behaviour.

### Python/protocol

Cover at least:

1. `is_thunderstorm` and the exact gust-adjusted wind vector reach state
2. clear/rain/slush/snow values remain unchanged
3. finite zero, positive, and negative wind components encode/decode
4. interpolation/backward compatibility with absent new fields is safe
5. no particle, ripple, splash, or volume state was added to the protocol

### Godot precipitation

Cover at least:

1. clear weather hides the layer and submits no particles
2. rain, slush, and snow select their correct visual forms
3. the pool stays fixed at 220 across long updates and weather changes
4. movement uses real delta and each type's Pygame fall/drift factors
5. particles wrap/recycle without array growth
6. rendering is batched with no per-particle nodes
7. resizing keeps particles in screen-fraction positions
8. underground presentation hides precipitation
9. malformed/missing weather state is safe

### Godot ripples and splashes

Cover at least:

1. deterministic puddle phases repeat for identical road data
2. ambient ripples animate only during active precipitation
3. ripple radius/alpha match the 2.4 s cycle and 1.0 s duration
4. wet but clear weather has no ambient ripple
5. entering a visible puddle above 1.0 m/s spawns one splash
6. staying inside, moving too slowly, walking, or being underground does not
   spawn another
7. leaving/re-entering can spawn again
8. strength, 0.5 s lifetime, fade, and 40-entry cap match Pygame
9. overlap queries inspect only loaded/relevant chunks

### Godot audio

Cover at least:

1. rain and slush enable base rain; clear and snow do not
2. only a rainy/slushy thunderstorm enables heavy rain
3. wind and strong-wind volumes match the formulas at boundary speeds
4. wet-tyre volume depends on wetness/speed and is zero on foot
5. slush selects variation 1; other wet roads select variation 0
6. loops update without restarting every state
7. older/malformed state remains safe
8. thunder, city ambience, engine, and train loops remain unchanged

Run at minimum:

```bash
pytest -q tests/test_weather.py tests/test_weather_render.py tests/test_wind.py tests/test_protocol.py tests/test_server_headless.py tests/test_audio.py
make godot-test
make godot-selftest
make audio-check
```

Run the existing Godot benchmark before and after with the same Oulu scene,
resolution, duration, camera path, and warm-up. Record at least average, p99,
worst frame, 1% low, render CPU/GPU time, and draw calls for:

* clear/dry baseline
* rain with ripples and wet tyres
* snow
* rain while driving through puddles

Distinguish unrelated pre-existing failures from regressions.

Manually verify:

1. rain streaks, slush, and snow are visually distinct
2. particles stay screen-relative while driving, zooming, and moving camera
3. puddles ripple only while precipitation falls
4. one splash appears per puddle entry and follows its fixed world position
5. base/heavy rain, wind/strong-wind, and wet/slush tyre loops crossfade
6. lightning and thunder still align
7. clear weather removes particle/ripple cost
8. no visible camera, building, route, input, or driving regression

---

## 11. Performance acceptance

Weather must fit the existing fill-bound frame budget.

Required acceptance:

* no node per particle, ripple, or splash
* fixed particle and bounded splash storage
* no whole-world puddle scan
* no full-screen alpha layer left visible when clear
* unchanged geometry/state is reused
* weather work appears in existing performance counters or one small added
  counter so its CPU cost can be reported
* measurements, not visual judgement alone, determine whether the batched
  implementation is acceptable

If the weather pass causes a material regression, reduce submissions or
visible work within this scope. Do not alter render resolution, camera,
buildings, night lighting, or unrelated effects to conceal the cost.

---

## 12. Documentation

Update only the relevant rows and phase history in
`docs/architecture/godot-pygame-rendering-parity.md`:

* rain/snow/slush particles
* splashes and puddle ripples
* rain, wind, and wet-tyre audio
* weather protocol additions
* `godot-final-06` implementation, tests, and benchmark results

Update protocol/audio documentation if it enumerates weather fields or loops.
Correct the audit's intensity wording to the actual fixed-pool/thunderstorm
model if the implementation confirms the analysis above. Do not rewrite or
re-audit the whole parity document.

---

## 13. Git workflow

Work on the current branch:

```text
release/v0.16.0g-alpha
```

Preserve unrelated existing worktree changes. Create clear commits and push
them when implementation and validation are complete. Do not create or push a
Git tag.

---

## Final report

Report:

### Implementation

* protocol fields added and why no fabricated intensity was added
* particle batching and lifecycle
* ripple and splash derivation
* exact audio formulas/variations
* any existing contract that differed from this prompt

### Tests

* exact commands and results
* manual scenarios checked
* any unrelated failures

### Performance

* comparable baseline/rain/snow/splash benchmark table
* batch/draw-call counts and weather CPU cost
* storage bounds and culling/query behaviour

### Git

* commit hash(es)
* confirmation that the branch was pushed
* explicit confirmation that no Git tag was created

Do not start the next parity phase automatically.
