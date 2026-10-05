# Pygame → Godot rendering parity (audit, 0.16.0g-alpha)

Audited on 2026-10-03 against `release/v0.16.0g-alpha` at commit `0445643`;
rows marked godot-07 were updated after that phase (rendering-only parity),
rows marked godot-10 after the re-audit of 2026-10-05 (`734a3b7`; see
[the godot-10 section](#godot-10-re-audit)), rows marked godot-11 after
[phase 2](#godot-11-phase-2-server-state-already-owned).

The Pygame side is the actual per-frame draw sequence in
`main/__init__.py`: about 80 `draw_*` calls between lines 2771 and 3446,
in `render/*.py`. The Godot side is what `godot/` really draws:
- `map_chunk.gd`: water, roads, railways, buildings
- `entity_layer.gd`: trains, NPCs, pedestrians, taxi, walking player
- `hud.gd`, `phone.gd`, and the F3 debug label in `main.gd`

The Godot client gets only what `protocol.py` and `map_chunks.py` send:
- **chunks:** `roads` (`points`, `half_width_m`, `kind`, `drivable`,
  `layer`), and `railways`, `waters`, `buildings` as bare polylines or
  polygons
- **state:** `player`, `player_pedestrian`, `npcs`, `pedestrians`,
  `trains`, `weather` (`weather_type`, `wetness`), `taxi`, `phone`,
  `events`, `game_time_seconds`, `sim_time`, `camx`/`camy`, `rage_power`,
  `water_elapsed`, `should_stop`, `city_summary`

**Status** (as the task defines):
- `complete`: same information shown under the same rules
- `partial`: drawn, but with concrete differences, listed
- `missing`: not drawn by Godot
- `different by design`
- `debug-only`
- `not applicable`

**Cause** (for anything not complete):
- `Godot rendering only`: the data already reaches Godot
- `missing protocol data`: the simulation has it, the protocol doesn't
  send it
- `missing shared simulation state`: it only exists in Pygame's `main()`
  loop or renderer, not in the simulation step the server runs
- `Pygame-specific implementation`
- `unclear`

**Importance** is about gameplay: `high` means needed to play (navigate,
find customers, avoid hazards); `medium` means world-reading or feedback;
`low` means decoration.

**Phase** refers to [godot-rendering-migration.md](godot-rendering-migration.md).

## World

| Element | Pygame (render call) | Godot | Status | Importance | Cause | Phase |
|---|---|---|---|---|---|---|
| Ground / grass | `draw_grass_texture` (seasonal texture) | flat green rect (`map_layer.gd`) | partial | low | Godot rendering only (season: missing protocol data) | C |
| Landuse fills: parks, forest, grass, parking areas | `draw_scenery` | – | missing | medium | missing protocol data (sceneries not in chunks) | B |
| Water | `draw_waters` (ice in winter, spring floes) | flat blue polygons | partial | medium | missing protocol data (ice, season) | B |
| Roads (surface, width by type) | `draw_ways` | polyline, width 2×half_width, 2 colours (drivable / path), ordered by layer; the highway type (`kind`) is in the chunk but unused — godot-10 | partial | high | Godot rendering only (colours and edges by highway type) | B |
| Road markings: centre lines, dashes | `draw_ways` (`center_lines`) | – | missing | medium | missing protocol data (lanes/oneway not in chunks) | B |
| Road layers: bridges over roads | `draw_ways` layer ordering, bridge pass | z level per `layer` (bridges above, dark edge), lowest first — godot-07 | partial | high | missing protocol data (Pygame outlines a vehicle under a higher road; the taxi's layer isn't sent) | B |
| Underground / covered roads (map levels) | `draw_level_ways` | – | missing | medium | missing protocol data (`map_level` per way, `car.map_level`) | B |
| Wet roads | `draw_wet_roads` | `map_chunk.gd` darken + sheen overlays on drivable roads, alpha by wetness in 3/255 steps — godot-07 | complete | low | – | – |
| Puddles | `draw_puddles` (from road geometry and wetness) | 40 % of drivable roads, reveal threshold, size and alpha by wetness — godot-07; spots seeded from geometry (Pygame: OSM ids), no rain ripples | partial | low | Godot rendering only (ripples); exact spots need OSM ids (protocol) | C |
| Parking spaces | `draw_parking_spaces` | – | missing | low | missing protocol data | B |
| Railways: rails, sleepers, ballast | `draw_railways` | one dark line, 1.4 m | partial | medium | Godot rendering only (track gauge and style) | B |
| Rail bridges above vehicles | `draw_railways(only_bridges=True)` after vehicles | – | missing | medium | missing protocol data (bridge flag/layer on railways) | B |
| Traffic islands | `draw_traffic_islands` | – | missing | low | missing protocol data | B |
| Trees | `draw_trees` | – | missing | medium (collisions) | missing protocol data | B |
| Scenery objects: benches, bollards, fountains | `draw_scenery_objects` (+ knocked-over state) | – | missing | medium (bollards collide) | missing protocol data (objects, knocked state) | B |
| Bus stops (option) | `draw_bus_stops` | – | missing | low | missing protocol data | B |
| Buildings | `draw_buildings` (cached geometry, facades) | flat grey polygons | partial | high | missing protocol data (facades, heights: building tags not in chunks) | B |
| Open-roof canopies over vehicles | `draw_open_roof_overlays` | – | missing | medium | missing protocol data (open-roof buildings) | B |
| Tire tracks | `draw_tire_tracks` ×4 | – | missing | low | missing protocol data (`taxi_mgr` track state) | C |
| Roadworks barriers / cones | `draw_roadworks` | – | missing | high (block roads) | missing protocol data | A |
| Curbs | `draw_curbs` | – | missing | low (curb bump) | missing protocol data | B |
| Fences, railings, walls, hedges | `draw_railings` | – | missing | medium (collisions) | missing protocol data | B |
| Construction fences | `draw_construction_fences` | – | missing | low | missing protocol data | B |
| Zebra crossings | `draw_crossings` | – | missing | medium | missing protocol data | B |
| Speed bumps | `draw_speed_bumps` | – | missing | medium | missing protocol data | B |
| Traffic lights (posts and live phase) | `draw_traffic_lights(sim_time)` | – | missing | high | missing protocol data (positions and phase; the phase must come from the server, not be recomputed) | A |
| Taxi stands (TAXI signs) | `draw_taxi_stops` | – | missing | high (rail pickups) | missing protocol data | A |
| Stop / yield signs | `draw_stop_signs`, `draw_yield_signs` | – | missing | medium | missing protocol data | B |
| Speed cameras | `draw_speed_cameras` (+ flash) | – | missing | medium | missing protocol data (positions; flash state not sent) | B |
| Fuel stations (price boards) | `draw_fuel_station_signs` | – | missing | high (fuel runs out) | missing protocol data | A |
| Street lights (+ broken lamps dark) | `draw_street_lights` (placed from roads; `broken_lamps`) | – | missing | low | Godot rendering only (lamp placement from roads); broken lamps need protocol data | C |
| Illuminated windows at night | `draw_illuminated_windows` | – | missing | low | missing protocol data (window/facade data, darkness) | C |
| Map labels: place and street names | `draw_labels` (decluttered) | – | missing | medium | missing protocol data (labels/places) | B |
| Vomit puddles and footprints | `draw_vomit_puddles` ×2, `draw_vomit_footprints` | – | missing | low | missing protocol data | C |

## Vehicles

| Element | Pygame | Godot | Status | Importance | Cause | Phase |
|---|---|---|---|---|---|---|
| Player taxi | `draw_car` (sprite, taxi sign, door animation) | body, cabin, roof sign, lamps, own `length_m`/`width_m` — godot-07; no door-opening animation | partial | high | Pygame-specific implementation (door progress is a `main()` variable) | C |
| Taxi headlights / taillights / brake lights | `draw_car`, `draw_vehicle_lights` | lamps from `engine_on`, `braking` (brake lamps 1.2× brighter red) — godot-07 | complete | medium | – (night glow: see headlight beams) | – |
| Taxi turn signals | `draw_car` reads `getattr(car, "turn_signal", "")`, but the player `Car` has no turn signal: Pygame's taxi never blinks — godot-10 | – | not applicable | – | – | – |
| Reversing lamp (taxi and NPCs) | `_draw_vehicle_lights(reversing=speed < −0.05)`: white lamp between the tail lights — godot-10 | – | missing | low | Godot rendering only (`speed` is sent for both) | A |
| Taxi exhaust / crash smoke | `draw_taxi_exhaust`, `draw_taxi_smoke` | 4 rising puffs from `engine_on` / `taxi_smoke_timer` — godot-07 | complete | low | – | – |
| NPC vehicles | `draw_npc_cars` (type-specific sprites, taxi sign, police) | car/van with cabin and taxi sign, bus, truck as Pygame; two-wheelers as body + rider, not Pygame's sprites; police, on-foot, LOD ≥ 2 skipped as Pygame — godot-07 | partial | high | Godot rendering only (two-wheeler sprites) | B |
| NPC turn signals | `draw_npc_cars` | amber corner lamps, `turn_signal_elapsed % 0.9 < 0.45` — godot-07 | complete | medium | – | – |
| NPC brake lights | `draw_npc_cars` (no braking flag for NPCs) | – | not applicable | – | Pygame draws none for NPCs either | – |
| NPC crash state: fallen, crash smoke | `draw_npc_cars`, `draw_taxi_smoke` style | fallen two-wheelers on their side, smoke from `crashed_timer` — godot-07 | complete | medium | – | – |
| Parked vehicles | `draw_npc_cars` (parked NPCs are NPCs; lamps off by `_vehicle_engine_on`: `state != "PARKED"`) | drawn as NPC vehicles by type, lamps off by the same rule — godot-10 | complete | medium | – | – |
| Vehicle shadows | – (none in Pygame) | – | not applicable | – | – | – |
| Night headlight beams | `draw_headlight_beams` | – | missing | medium | missing protocol data (darkness) | C |
| Vehicle on-foot drivers (`is_on_foot`) | drawn by `draw_pedestrians` | drawn as pedestrians — godot-07 | complete | low | – | – |

## Pedestrians

| Element | Pygame | Godot | Status | Importance | Cause | Phase |
|---|---|---|---|---|---|---|
| Pedestrian body | `draw_pedestrians` (top-down character, `appearance`) | shadow, legs, body in its colour, hair and head; `appearance` defaults — godot-07 | partial | medium | missing protocol data (`appearance`) | B |
| Walking direction | heading-rotated body | head toward the heading — godot-07 | complete | low | – | – |
| Walk animation | `animation_state`, `animation_time` | legs step with `sin(animation_time·10)`, interpolated; fallen pose; outline indoors — godot-07 | complete | low | – | – |
| Cyclists | drawn as ordinary pedestrians (`draw_cyclists` exists but `main()` never calls it) | ordinary pedestrians | complete | low | – | – |
| Cursing bubbles | `draw_pedestrians` (`curse_timer`, `curse_text`) | white bubble, red text, fades in the last 0.5 s — godot-07 | complete | low | – | – |
| Walking player (on foot) | `draw_pedestrians` (`is_player`) | pedestrian figure, standing pose — godot-07 | partial | high | missing protocol data (the player's animation state/time) | B |
| Waiting passenger at pickup | `draw_taxi_target` marker + passenger pedestrian | customer disc with heading notch and `[P]` / `[TO TAXI]` name tag (fields added to `current_passenger`) — godot-07 | complete | high | – | – |
| Booked rail passenger arrow | `draw_booked_passenger_arrow` | downward arrow over the booked passenger, drawn at their interpolated position (by id, else the sent one), only while `meet.arrow` is set: waiting or met, as `main()` — godot-11 | complete | high | – | – |
| People under roofs (outline) | `draw_pedestrians_under_roofs` | – | missing | low | missing protocol data (roofs) | B |
| Night reflectors | `draw_pedestrian_reflectors` | – | missing | low | missing protocol data (darkness) | C |

## Trains

| Element | Pygame | Godot | Status | Importance | Cause | Phase |
|---|---|---|---|---|---|---|
| Train cars, own length, following track | `draw_trains` | rotated boxes, full length, 3.2 m wide — godot-07 | complete | high | – | – |
| Car colours by profile | `draw_trains` (greens, white locomotive band, restaurant car...) | `PROFILES` palette (test-checked), locomotive cab, restaurant stripe, roof line — godot-07 | complete | low | – | – |
| Direction / front | white front band | white locomotive cab front — godot-07 | complete | low | – | – |
| Under station roofs (outline) | `draw_trains(roof_cover=...)` | – | missing | low | missing protocol data (roofs) | B |
| Clicked car's passengers | `draw_train_car_popup` | – | missing | low | missing protocol data (`passengers.in_car`); needs click input | D |
| Train labels / debug | `draw_trains(show_debug)` | – | debug-only | – | – | D |
| Next train panel | `draw_next_train` (J) | – | missing | medium | missing protocol data (timetable query) | B |

## Taxi job and interaction

| Element | Pygame | Godot | Status | Importance | Cause | Phase |
|---|---|---|---|---|---|---|
| Pickup / drop-off waypoint (zone, marker, label) | `draw_taxi_target` | zone, centre marker and `[Pickup]` / `[Destination]` address tag — godot-07 | complete | high | – | – |
| Off-screen arrow to the target | `draw_taxi_target` | `nav_overlay.gd`: edge arrow (130 px margin) with PICKUP/DROPOFF distance — godot-07 | complete | high | – | – |
| Navigation route line (N) | `draw_navigation_route` (route from `traffic_mgr.plan_route` in `main()`) | – | missing | high | missing shared simulation state (routing runs in Pygame's loop, not the simulation step) | A |
| Compass with target bearing (C) | `draw_compass` | `nav_overlay.gd`, C toggles, off by default — godot-07 | complete | medium | – | – |
| Meet-and-greet panel | `draw_meet_panel` | `hud.gd` panel, Pygame's colours, the three lines from the server's `meet_prompt` (localized there) — godot-11 | complete | high | – | – |
| Nausea warning bubble | `draw_passenger_nausea_bubble` | bubble with tail above the taxi while dropping off — godot-07 | complete | medium | – | – |
| Phone and offers | `draw_phone_offers` (pauses the game) | `phone.gd` (game keeps running) | different by design | high | – | – |
| Game start: city sign, 24 h forecast | `draw_game_start_overlay` | – | missing | low | missing protocol data (city, forecast) | B |
| Start hints (get in, start engine) | `draw_game_start_hint` | HUD hint line | partial | medium | Godot rendering only | A |
| Career city summary | `draw_city_summary` | – | missing | medium | Godot rendering only (`should_stop`, `city_summary` sent) | B |

## Weather and environment

| Element | Pygame | Godot | Status | Importance | Cause | Phase |
|---|---|---|---|---|---|---|
| Rain / snow particles | `draw_rain` (rain streaks, snow flakes) | – | missing | medium | Godot rendering only for type; intensity (heavy rain) missing protocol data | C |
| Splashes | `draw_splashes` (spawned in Pygame's `main()` from puddle overlap) | – | missing | low | Pygame-specific implementation | C |
| Lightning flash | `draw_lightning_flash` (`weather.lightning_intensity`) | full-world flash at the sent, fading intensity (max alpha 145/255), under the UI; thunder as a server sound event once per strike — godot-11 | complete | low | – | – |
| Day/night tint | `draw_day_night_overlay` (sun altitude from time, lat/lon, date) | – | missing | high (night visibility) | missing protocol data (sun altitude or darkness, date) | A |
| Snow cover / seasons | `draw_grass_texture(season)`, `draw_waters` ice | – | missing | low | missing protocol data (season, snow depth) | C |
| Weather text | HUD | HUD `weather_type`, wetness | complete | medium | – | – |

## HUD and UI

| Element | Pygame (`draw_hud` unless noted) | Godot | Status | Importance | Cause | Phase |
|---|---|---|---|---|---|---|
| Speed | yes | `hud.gd` | complete | high | – | – |
| Game time | yes (+ date, real-time marker) | `hud.gd` HH:MM | partial | medium | missing protocol data (date, time scale) | B |
| Money | yes | `hud.gd` | complete | high | – | – |
| Taxi job / passenger | mission bar | `hud.gd` fare line | partial | high | Godot rendering only (fields sent) | A |
| Notifications | yes | `hud.gd` notice | complete | high | – | – |
| Speed-camera notice / flash | yes (notice centred, red border); lens flash at the camera (`draw_speed_cameras`) | notice centred with a red border from `taxi.speed_camera_notice` — godot-11; no lens flash | partial | medium | missing protocol data (the flash is drawn at the camera itself: needs camera positions in chunks) | B |
| Road name, speed limit | limit sign always; road name in the debug HUD line | `instruments.gd` limit sign; road line in the F3 readout, both from `state.road` — godot-11 | complete | high | – | – |
| Fuel gauge | yes (needle gauge, reserve zone, econometer) | `instruments.gd`, same gauge — godot-07 | complete | high | – | – |
| Fuel price at a station | yes | – | missing | medium | missing protocol data | B |
| Trip, odometer | yes | `instruments.gd` — godot-07 | complete | low | – | – |
| Rage meter | yes (face frames, %, bar) | `instruments.gd`, frames cut from the same atlas — godot-07 | complete | medium | – | – |
| Water timer (driving in water) | yes | `instruments.gd` countdown box — godot-07 | complete | medium | – | – |
| Temperature | yes | – | missing | low | missing protocol data | B |
| Speech subtitles (driver / passenger lines) | yes (`comment_text`) | – | missing | low | Pygame-specific implementation (speech chosen client-side in `audio.py`) | C |
| Speed limiter / red-light assist status | yes | – | missing | low | Godot rendering only (the client owns these toggles) | B |
| Lat/lon, ways count, zoom | yes | – | debug-only | – | – | D |
| Resident popup (click a person) | `draw_resident_popup` | – | missing | low | missing protocol data (resident details); needs click picking | D |
| Camera follow other / back button | `draw_camera_back_button` | – | missing | low | Godot rendering only plus input | D |
| Pause / settings / main menus | `render/menus.py` (pause, settings, mode and city selection, tutorial, loading screen) | – | missing | medium | Godot rendering only (UI; settings are client-side); city and mode choice is made by the server at startup | B |
| Debug overlays: profiler, g-force, NPC panels, spatial grid, intersections, feature inspector, activity | various | F3 text readout | debug-only | – | – | D |

## Camera, coordinates, layering, motion

| Aspect | Pygame | Godot | Status | Notes |
|---|---|---|---|---|
| World → screen | `x_screen = (x − camx)·px_per_m + W/2`, y flipped, north up | `MapMath.point`: (x − origin), y flipped; Camera2D | complete | Same orientation. Godot subtracts a fixed origin for float32 precision. |
| Scale | `px_per_m` 9.0 default (`_DEFAULT_PX_PER_M`), zoom keys | Camera2D zoom 9 px/m default (godot-07), ±25 % keys | complete | – |
| Camera target | `camx`/`camy` from the simulation (speed/heading look-ahead) | interpolated player position from the frame's one sample, no look-ahead | different by design | godot-08/09 made the camera and every entity share one sample, which is what removed the jitter; `camx`/`camy` are sent but unused. A look-ahead, if wanted, must be computed from that same sample (godot-10). |
| Entity rotation | sprites rotated by heading | `draw_set_transform(…, −heading)` | complete | Same heading convention, checked against sent headings. |
| Viewport resize | fixed `SCREEN_W`×`SCREEN_H` | window resizable, default 1280×720 | different by design | – |
| Off-screen culling | explicit viewport culling per call | entities culled against the camera view + 30 m (godot-07); map chunks culled by Godot | complete | – |
| Interpolation | in-process: none needed; `--connect`: `interpolate_state` for player, NPCs, pedestrians (not trains) | `StateBuffer`: player, NPCs, pedestrians, train cars | different by design | – |
| Layering | grass → landuse → water → roads → parking → railways → islands → trees → objects → buildings → tracks → roadworks, curbs, signs → pedestrians → route → target → taxi → NPCs → splashes → roofs → bridge rails → trains → fuel boards → night tint → windows, beams, lamps → weather → labels → HUD → phone | ground → water (chunk z0) → roads by layer (z1–z4) → wet overlays, puddles (z5) → railways (z6) → buildings (z7) → entities (z10): pedestrians → target → taxi → NPCs → smoke → trains → HUD, overlay, phone (godot-10: as in `entity_layer.gd`) | partial | Godot-07: trains now above vehicles as in Pygame; roads by layer, wet overlays and puddles above roads, buildings above, entities above all (z 10). Still no roof layer above vehicles, no bridge-rail layer. |
| Animations | turn-signal blink, exhaust puffs, smoke, splashes, rain, lightning, pedestrian walk cycle, door opening | godot-07: turn-signal blink, exhaust and crash smoke, walk cycle, curse fade | partial | Missing: splashes and rain (Phase C), lightning (protocol), door opening (Pygame-specific). |

## Counts

Computed from the tables above: 108 rows (109 from godot-10), each counted once
by status. godot-06 is the audit; godot-07 is after the rendering-only phase.

| Status | godot-06 | godot-07 | godot-10 | godot-11 |
|---|---|---|---|---|
| complete | 7 | 30 | 31 | 35 |
| partial | 22 | 18 | 16 | 17 |
| missing | 71 | 52 | 52 | 47 |
| different by design | 3 | 3 | 4 | 4 |
| debug-only | 3 | 3 | 3 | 3 |
| not applicable | 2 | 2 | 3 | 3 |
| rows | 108 | 108 | 109 | 109 |

Missing and partial rows by cause, after godot-07. The 3
camera/layering rows have no cause column.

| Cause | Count |
|---|---|
| Godot rendering only | 14 |
| missing protocol data | 49 |
| missing shared simulation state | 1 |
| Pygame-specific implementation | 3 |
| unclear | 0 |

A row whose element is partly rendering and partly data is counted under
the cause written first.

### What godot-07 changed

**Newly complete (rendering-only):**
- the taxi's lamps, exhaust and crash smoke
- NPC turn signals and crash state; NPC drivers on foot drawn as
  pedestrians
- pedestrian heading, walk cycle and curse bubbles
- train colours, cab front and full length
- the pickup/drop-off marker, the off-screen arrow and the compass
- the waiting customer; the nausea bubble
- the fuel gauge, rage meter, water timer, trip and odometer
- wet roads; scale and culling

**Newly partial:**
- road layers: bridges on top, but no outline of vehicles under them
- puddles: spots differ from Pygame's; no rain ripples
- the taxi and NPC vehicle bodies: no door animation; two-wheelers aren't
  sprites
- the walking player: no animation data

**Protocol additions:** two small ones, allowed for audit rows classified
as rendering-only:
- `current_passenger.ped`, `is_walking_to_car`, `boarded` and
  `rail_booking`: the waiting customer
- `player.length_m` and `width_m`

**Still missing:**
- everything classified as missing protocol data: darkness/date, traffic
  lights, roadworks, road name and limit, static map features, the meet
  booking, lightning and rain intensity, and the rest
- the navigation route, which needs route planning in the simulation
- the effects in Phase C: rain and snow particles, splashes

## How the Godot side was verified

- Every "Godot" entry above points at an actual draw call in
  `map_chunk.gd`, `entity_layer.gd`, `hud.gd`, `phone.gd` or the F3 label
  in `main.gd`. Nothing else in `godot/` draws.
- `audio_test.gd` is a test mode, and the `map_math.gd` helpers draw
  nothing.
- **Visible in gameplay:** the windowed screenshots from phases 1 and 2
  showed map, trains, NPCs, taxi and HUD.
- **Exercised by tests:**
  - `make godot-selftest` counts `drawn_entities` and `map_chunks`, and
    checks the HUD speed and money text
  - `make godot-test` covers HUD values, phone, chunk add/remove and
    interpolation
  - No test compares pixels.

## godot-10 re-audit

Re-audited on 2026-10-05 at `734a3b7`, after the stability phases
(godot-08: render clock and one sample per frame; godot-09: 64-bit
interpolation relative to the map origin; held keys owned by the client).
Every row was rechecked against the code, not the previous tables.

**What changed since godot-07.** No commit after `6ae6837` touched
`protocol.py`, `map_chunks.py`, `render/` or the Pygame draw sequence in
`main/__init__.py`. The Godot changes (`main.gd`, `entity_layer.gd`,
`state_buffer.gd`, `drive_input.gd`) are timing, camera and input only.
Every draw path from godot-07 is still called from `entity_layer._draw` and
`map_chunk.setup`; none was disabled. Row corrections:

- **Taxi turn signals:** missing → **not applicable**. `draw_car` reads
  `getattr(car, "turn_signal", "")`, but the player `Car` has no such field
  (only `npc.py` has one), so Pygame's taxi never blinks either.
- **Reversing lamp:** new row, **missing**. `_draw_vehicle_lights` draws
  a white lamp when `speed < −0.05`; Godot draws none. `speed` is sent for
  the taxi and NPCs.
- **Parked vehicles:** partial → **complete**. Both clients draw them as
  NPCs by type, with lamps off for `state == "PARKED"`.
- **Camera target:** partial → **different by design**. The camera follows
  the same interpolated sample the entities are drawn from. That is the
  jitter fix, and it is protected.
- **Roads:** still partial, but more precisely: the highway type (`kind`)
  is already in every chunk road. Colours by type are rendering-only.
- **Layering:** the Godot description was out of date. It now lists the
  real z order (chunks z0–z7, entities z10, trains last).

### Stability fix check (section 9 of the task)

- `main._process` calls `entities.update_frame()` first, then sets
  `camera.position = entities.player_position()` from that same sample.
  The selftest reports `taxi_off_centre_px: 0.0`, `render_backsteps: 0`
  and `max_backstep_ms: 0.0`; 95 % of frame-to-frame camera step changes are
  0.11 px or less.
- `StateBuffer.blend` lerps in GDScript's 64-bit floats and subtracts the
  origin before converting to `Vector2`. `MapMath.point` does the same for
  static geometry, so the map and the entities use one coordinate rule.
- The off-screen arrow and the compass take `state["player"].heading`,
  also when on foot. Pygame passes `car` to `draw_compass` too, so this is
  parity, not a bug.

### Data availability for every incomplete row

The classes are the task's own: **A** Godot already receives the data;
**B** the server has it but doesn't send it; **C** the server doesn't
compute it; **D** Pygame-specific; **E** different by design. P0–P3 are
the task's priorities.

The server (`server/__init__.py`) matters for B vs C. It runs
`WeatherSystem.update` and `advance_simulation` and keeps `current_way`. It
has **no game calendar**: `now` is `date.today()`, the outside temperature
is `advance_simulation`'s default 15 °C, there's no season, and the sun's
altitude isn't computed. In Pygame, all of these come from `main()`
(`GameCalendar`, `solar_altitude_and_events`, `outside_temperature`).

| Feature | Server state | Sent | Godot draws | Class | Priority |
|---|---|---|---|---|---|
| Navigation route | `traffic_mgr.plan_route` and `world.level_routes.plan` exist; the trigger, re-plan rules (new target, 35 m off route, new map level) and the route itself live in Pygame's `main()` | no | no | C (architecture) | P0 |
| Meet-and-greet panel, booked-passenger arrow | `taxi_mgr.meet_booking()`, `meet_context()` | only `current_passenger.rail_booking` as a bool | no | B | P0 |
| Road name, speed limit (HUD) | `current_way` (`name`, `speed_limit_kmh`), kept by the server | no | no | B | P1 |
| Traffic lights: posts | `TrafficLight` x, y, layer, direction, `render_offset_m` (incl. roadwork temporaries) | no | no | B (static, chunks) | P1 |
| Traffic lights: phase | `TrafficLight.get_state(sim_time)` from `signal_group`, `cycle_time`, `offset`; `sim_time` *is* sent | no (only the clock) | no | B (per tick, lights near the player) | P1 |
| Day/night tint, date | not computed; no calendar on the server | no | no (Godot's `_night()` hour table drives only the ambience loops) | C (small: server computes sun altitude from game time, city lat/lon, date) | P1 |
| Taxi stands | `world.taxi_stops` | no | no | B (static) | P1 |
| Fuel stations, price boards, price in HUD | `fuel.py` stations in the world | no | no | B (static) | P1 |
| Roadworks | `world.roadworks`, made once at load (`create_roadworks`); **off unless `roadworks_enabled`** | no | no | B (static for the session) | P1 (P2 while off by default) |
| Trees, bollards and other scenery objects (collide) | `world` trees, `scenery_objects` | no | no | B (static) | P1 |
| Fences, railings, walls, hedges (collide) | `world` railings | no | no | B (static) | P1 |
| Knocked-over posts, broken lamps | `taxi_mgr.knocked_posts`, `broken_lamps` | no | no | B (per change) | P2 |
| Landuse, parking spaces, traffic islands, curbs, construction fences | `world.sceneries`, `parking_spaces`, `curbs` … | no | no | B (static) | P2 |
| Crossings, speed bumps, stop/yield signs, speed cameras, bus stops | `world` | no | no | B (static) | P2 |
| Buildings: facades, heights, open roofs; people and trains under roofs | building tags, open-roof buildings | no | flat polygons | B (static) | P2 |
| Map labels | `world.places`, way names | no | no | B (static) | P2 |
| Rail bridges above vehicles | railway bridge/layer | no | no | B (static) | P2 |
| Underground / level ways, the player's level | `level_ways`, `car.map_level`, `car` layer | no | no | B | P2 |
| Speed-camera notice and flash | `taxi_mgr` notice | no | no | B (per tick) | P2 |
| Lightning flash | `weather.lightning_intensity`, `lightning_event_id` (server-updated) | no | no | B | P2 |
| Rain intensity | `weather.is_precipitating`, `rain_particles` state | only `weather_type` | no | B | P2 |
| Pedestrian appearance | `Pedestrian.appearance` | no | default look | B | P3 |
| Walking player animation | `player_pedestrian` | x, y, heading | standing pose | B | P3 |
| Next-train panel (J) | timetable | no | no | B (query) | P2 |
| Vomit puddles and footprints | `taxi_mgr`/`pedestrian_mgr.vomit_puddles` | no | no | B | P3 |
| Game-start city sign and forecast | city name; forecast needs the calendar | no | no | B / C | P3 |
| Temperature (HUD) | fixed 15 °C on the server | no | no | C | P3 |
| Seasons: snow cover, ice | no season on the server | no | no | C | P3 |
| Night: headlight beams, street lights, lit windows, reflectors | need darkness (C); lamp placement is from roads (A) | – | no | C, then A | P2 |
| Tire tracks | the `tire_tracks` list in Pygame's `main()`; `skid_amount` not sent | no | no | C (or E: client-side from the interpolated taxi path) | P3 |
| Road colours by type | `kind` | **yes** | 2 colours | A | P2 |
| Road markings | lanes/oneway | no | no | B | P2 |
| Railway track style | rail polylines | **yes** | one dark line | A | P2 |
| Reversing lamp | `speed` | **yes** | no | A | P3 |
| Two-wheeler sprites | `vehicle_type` | **yes** | body and rider | A | P3 |
| Rain and snow particles by type | `weather_type` | **yes** | no | A (intensity: B) | P2 |
| Splashes | spawned in Pygame's `main()` (`weather.spawn_splash`) | – | no | E (client effect from taxi speed over its own puddles) | P3 |
| Puddle ripples | `wetness`, `weather_type` | **yes** | no ripples | A | P3 |
| Puddle spots | Pygame seeds from OSM ids | – | seeded from geometry | E | – |
| Ground texture (season) | – | – | flat green | A (season: C) | P3 |
| Career city summary | `should_stop`, `city_summary` | **yes** | no | A | P2 |
| Start hints; HUD job line as Pygame's mission bar | `taxi`, `player` | **yes** | simplified | A | P2 |
| Speed limiter / red-light assist status | owned by the client (`PlayerCommand`) | – | no | A | P3 |
| Menus: pause, settings, tutorial | client-side | – | no | A (UI) | P2 |
| Game time: date, time scale | no calendar | no | HH:MM | C | P3 |
| Taxi door animation | `main()` variable | – | no | D | P3 |
| Speech subtitles | lines chosen client-side in Pygame's `audio.py` | – | no | D | P3 |
| Clicked train-car passengers, resident popup, camera follow / back button | `passengers.in_car`, resident data; click picking | no | no | B + client input | P3 |
| Walking player's layer under bridges (vehicle outline) | `car` layer | no | no | B | P3 |

The table groups the 68 incomplete rows (52 missing + 16 partial) into 49
feature lines; several rows share one line, such as crossings, bumps and
signs. By line, using the first class where a line has two:

| Class | Lines | Meaning for the next phases |
|---|---|---|
| A — data already in Godot | 11 | Godot-only work, testable with the existing unit tests |
| B — server has it, not sent | 27 | protocol work; most of it is **static** world data for the chunks |
| C — server doesn't compute it | 7 | darkness/date/season/temperature (one server "calendar" step), navigation, tire tracks, night effects |
| D — Pygame-specific | 2 | door animation, speech subtitles |
| E — different by design | 2 | splashes as a client effect; puddle spots seeded from geometry |

### Previous protocol gaps, rechecked

The godot-07 table counted 49 rows as "missing protocol data". Rechecked:
- **Still genuine B gaps:** all static world data (one chunk extension)
  plus the small per-tick values in the table above.
- **Moved to C:** darkness and date, season and snow, temperature, the
  game-start forecast, illuminated windows and the other night effects.
  The server has no calendar, so adding a protocol field wouldn't help
  yet.
- **No longer a gap:** the taxi turn signal (not applicable).
- **Not needed as a protocol field:**
  - The traffic-light *phase* function is deterministic from `sim_time`
    (already sent) and per-light cycle data. The rule stays: the server
    sends the phase, and Godot doesn't recompute it. Sending only the
    lights within the 60 m `_nearby_traffic_lights` radius, or within the
    view, keeps it small.
  - Roadworks are static per session, so they belong in the chunks or
    the `world` message, not in every `state`.
  - Tire tracks and splashes can be client effects (E) instead of
    protocol.

### Navigation (section 8 of the task)

- **Pygame:** `main/__init__.py` around line 2700. When N is on and there
  is a target, it calls `traffic_mgr.plan_route(car, target,
  layer=current_way.layer)` on the surface, or `world.level_routes.plan(…)`
  off it. It re-plans when the target changes, the map level changes, or
  the car is more than 35 m off the route.
- **Server:** has `traffic_mgr` and its route graph, but never calls
  `plan_route`.
- **Godot:** doesn't route, and must not.
- **Protocol:** no route field.

The route is **gameplay** in Pygame: it's how a driver finds a far-away
address. The arrow and compass only give the bearing. The data and the
algorithm exist on the server; what's missing is the ownership. Future
direction:
- a per-player route service on the server, using the same three
  re-plan triggers
- the route as a polyline in `state` only when it changes (or sent
  as a separate `route` message)
- `plan_route_steps`, which is already resumable, run with a deadline so
  a tick never stalls

Not implemented here.

### Findings documented, not fixed

- `tests/test_packaging.py` imports `tomllib`, which needs Python ≥ 3.11.
  On a 3.10 venv the whole `make test` run stops at collection. Excluding
  that file, 1543 tests pass.
- Godot's `main._night()` turns the hour into night 0..1 for the ambience
  loops. That is a client-side derivation. When the server sends
  darkness, the loops should use it.
- The server's game date is the real date (`date.today()`), and its time
  of day starts at 18:00. Any darkness the server sends will follow that
  until it has a calendar.
- Roadworks are off unless `roadworks_enabled` is set in the config, so
  in a default session there's nothing to draw.

### Performance risks (flagged, not optimised)

- **Static chunk data (trees, objects, fences, labels):** the largest
  risk to chunk size, which today averages 35 KiB with a 204 KiB maximum.
  Re-measure when adding these. Draw them into the chunk canvas items or
  with `MultiMesh`, never one node per feature.
- **Traffic lights:** hundreds per city. Send phases only for nearby or
  visible lights.
- **Rain and snow particles:** use `GPUParticles2D`. A CPU pool like
  Pygame's would show in `interp_draw_ms`.
- **Street lights and night lighting:** one light per lamp is
  expensive. Use a `CanvasModulate` plus additive sprites, batched per
  chunk.
- **Labels:** decluttering on every camera move. Do it on zoom or chunk
  change.
- **Navigation route:** cheap to draw, but planning on the tick thread can
  stall. Run it resumably with a deadline.

### Roadmap (replaces the godot-07 "recommended next phase")

Small phases, each touching as few layers as possible:

1. **Rendering-only quick wins (A, Godot only):**
   - road colours and edges by `kind`
   - railway track style
   - the reversing lamp
   - rain and snow particles by `weather_type`
   - the career city summary
   - the start hints and job line as in Pygame
   - limiter status
   - puddle ripples

   No server change.
2. **Per-tick values the server already has (B, `state` only):**
   - the meet booking (pedestrian id, train, station, platform, step)
   - `current_way` name and speed limit
   - the speed-camera notice
   - lightning intensity and precipitation

   Then the meet panel, the booked-passenger arrow, the road and limit
   HUD and the lightning flash in Godot.
3. **Gameplay points in chunks (B, static):**
   - taxi stands
   - fuel stations and prices
   - traffic-light posts, plus their phases near the player in `state`
   - roadworks
4. **Collision-relevant static world (B, static):** trees, scenery
   objects, fences and railings, with knocked-over posts and broken lamps
   as per-change state. Measure the chunk size.
5. **Server calendar (C):** game date, season, temperature and sun
   altitude computed on the server as Pygame's `main()` does, then
   darkness in `state`. Godot follows with the day/night tint, headlight
   beams, street lights and reflectors (switch `_night()` to the sent
   value).
6. **The rest of the static world (B):**
   - landuse, parking, islands, curbs
   - crossings, bumps, signs, cameras
   - labels, building detail and roofs
   - rail bridges, map levels
7. **Navigation (C, architecture):** route ownership on the server, as
   described above.

Larger work, deliberately postponed: phases 5 to 7; menus and click
picking (popups, camera follow); speech subtitles; tire tracks.

**Recommended next phase: phase 2.** It closes the P0 meet-and-greet gap
and the P1 road name and limit HUD. It adds a few fields to `state`,
whose data the server already computes, plus Godot UI, with no
simulation change and no chunk-format change. Phase 1 can run alongside
it, or right after, since it doesn't touch the server.

### Tests at the time of the re-audit

| Check | Result |
|---|---|
| `make godot-test` | PASS (108 checks, 0 failed) |
| `make godot-selftest` | PASS (`ok: true`, 49 chunks, 24 NPCs, 34 pedestrians, 2 trains, 145 FPS on llvmpipe, taxi 0 px off centre) |
| `make audio-check` | PASS (126 files, 50 groups, 0 problems) |
| Python tests | PASS: 1543 passed with `tests/test_packaging.py` excluded. That file can't be collected on this machine's Python 3.10 (`tomllib`), so plain `make test` fails at collection. |

## godot-11: phase 2, server state already owned

Phase 2 of the godot-10 roadmap. Data the server already computed is now
in `state`, and Godot draws it. There's no simulation change and no
chunk-format change.

**Protocol (`protocol.py`, all optional for older clients):**

| Field | Contents | Why |
|---|---|---|
| `meet` | `null`, or `status`, `lines` (3 strings), `arrow` (`null` or `id`, `x`, `y`, `radius_m`) | `taxi_mgr.meet_prompt(player_pedestrian)` decides the step, as in Pygame's `main()`; the server localizes the lines in its language. `arrow` is set only for `PASSENGER_WAITING` / `PASSENGER_MET` with a pedestrian, the same condition as `main()`. |
| `road` | `name` (OSM name, else the highway type title-cased; `null` off-road), `speed_limit_kmh` (`null` when unknown) | The server's `current_way`, with Pygame's naming rule. Godot never works out a limit itself. |
| `taxi.speed_camera_notice` | bool | The current `notification_msg` is a speed-camera hit (its 4 s timer is running); Pygame styles it differently. |
| `weather.lightning_intensity` | 0..1, 1 at a strike, fading | Pygame's flash alpha. Thunder is a `sound` event (`weather.thunder`) the server emits once per `lightning_event_id`, as `main()` does. |

Not sent, because no Godot renderer uses it yet: precipitation intensity
(`is_precipitating`, the particle pool). Godot has no rain or snow
particles yet, so that row stays missing and belongs with the rendering
quick wins (godot-10 phase 1).

**Godot:**
- `hud.gd`: the meet panel, and the camera-hit notice style
- `instruments.gd`: the limit sign
- `entity_layer.gd`: the booked-passenger arrow and the lightning flash
- `main.gd`: only the road line in the F3 readout

The camera, `StateBuffer` and `drive_input.gd` are unchanged. The selftest
still reports the taxi 0 px off centre and 0 render backsteps.

**Deliberate differences:**
- The meet panel sits under the notice line (y = 100) instead of
  Pygame's y = 50, because the Godot notice uses that place.
- Like Pygame, the arrow is drawn only where the passenger is. It isn't
  an off-screen indicator: the panel text says where to go.

**Still open from this phase's rows:** the speed camera's lens flash.
It's drawn at the camera, so it needs camera positions in the chunks
(the static phase).

**Verified:**
- Python tests: every meet step through `protocol._meet_to_dict` with the
  real `TaxiManager` fixtures (train due without an arrow, at the stand,
  getting out, walking, greeting, met, none, missed); road naming;
  the notice flag and its expiry; one thunder per strike.
- Godot unit tests: 128 checks. They cover the HUD values, the panel
  showing and going, the arrow following the interpolated passenger and
  never going stale, and the flash alpha.
- Against the real Oulu server: the limit sign while driving, and road
  changes logged from the running simulation (named road with limit,
  "Service" for an unnamed one, off-road with no limit).
- With scripted states: screenshots of the meet panel, arrow, camera
  notice and lightning flash.
- **Not reproduced live:** a full rail meet-and-greet and a natural
  thunderstorm. Both need long in-game waits.

**Next phase (unchanged order):** gameplay points in chunks — taxi stands,
fuel stations, traffic-light posts and nearby phases, roadworks — then the
collision-relevant static world, the server calendar (day/night),
the rest of the static world, and navigation.
