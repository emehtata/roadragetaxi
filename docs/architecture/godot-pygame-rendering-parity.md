# Pygame → Godot rendering parity (audit, 0.16.0g-alpha)

Audited on 2026-10-03 against `release/v0.16.0g-alpha` at commit `0445643`.

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
| Roads (surface, width by type) | `draw_ways` | polyline, width 2×half_width, 2 colours | partial | high | Godot rendering only | A |
| Road markings: centre lines, dashes | `draw_ways` (`center_lines`) | – | missing | medium | missing protocol data (lanes/oneway not in chunks) | B |
| Road layers: bridges over roads | `draw_ways` layer ordering, bridge pass | `layer` received, not used for ordering | partial | high | Godot rendering only | A |
| Underground / covered roads (map levels) | `draw_level_ways` | – | missing | medium | missing protocol data (`map_level` per way, `car.map_level`) | B |
| Wet roads | `draw_wet_roads` | – | missing | low | Godot rendering only (`weather.wetness` sent) | C |
| Puddles | `draw_puddles` (from road geometry and wetness) | – | missing | low | Godot rendering only (placement derived from road geometry) | C |
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
| Player taxi | `draw_car` (sprite, taxi sign, door animation) | yellow 4.4×1.8 m box | partial | high | Godot rendering only (size is fixed, not the car's own) | A |
| Taxi headlights / taillights / brake lights | `draw_car`, `draw_vehicle_lights` | – | missing | medium | Godot rendering only (`braking`, `engine_on` sent); night needs darkness: missing protocol data | A (brake) / C (night) |
| Taxi turn signals | `draw_car` (`turn_signal` blink) | – | missing | low | missing protocol data (player turn signal not sent) | C |
| Taxi exhaust / crash smoke | `draw_taxi_exhaust`, `draw_taxi_smoke` | – | missing | low | Godot rendering only (`taxi_smoke_timer`, `engine_on` sent) | C |
| NPC vehicles | `draw_npc_cars` (type-specific sprites, taxi sign, police) | boxes in NPC colour, own length/width | partial | high | Godot rendering only (`vehicle_type`, `is_taxi`, `is_police` sent) | A |
| NPC turn signals | `draw_npc_cars` | – | missing | medium | Godot rendering only (`turn_signal`, `turn_signal_elapsed` sent) | A |
| NPC brake lights | `draw_npc_cars` (no braking flag for NPCs) | – | not applicable | – | Pygame draws none for NPCs either | – |
| NPC crash state: fallen, crash smoke | `draw_npc_cars`, `draw_taxi_smoke` style | – | missing | medium | Godot rendering only (`fallen`, `crashed_timer` sent) | A |
| Parked vehicles | `draw_npc_cars` (parked NPCs are NPCs) | drawn as NPC boxes | partial | medium | Godot rendering only (as NPC vehicles) | A |
| Vehicle shadows | – (none in Pygame) | – | not applicable | – | – | – |
| Night headlight beams | `draw_headlight_beams` | – | missing | medium | missing protocol data (darkness) | C |
| Vehicle on-foot drivers (`is_on_foot`) | `draw_npc_cars` / `draw_pedestrians` | drawn as a box | partial | low | Godot rendering only | B |

## Pedestrians

| Element | Pygame | Godot | Status | Importance | Cause | Phase |
|---|---|---|---|---|---|---|
| Pedestrian body | `draw_pedestrians` (top-down character, `appearance`) | circle, `radius_m`, colour | partial | medium | missing protocol data (`appearance`) | B |
| Walking direction | heading-rotated body | – (a circle has none) | missing | low | Godot rendering only (`heading` sent) | B |
| Walk animation | `animation_state`, `animation_time` | – | missing | low | Godot rendering only (both sent) | C |
| Cyclists | `is_cyclist` drawing | circle | partial | low | Godot rendering only (`is_cyclist` sent) | B |
| Cursing bubbles | `draw_pedestrians` (`curse_timer`, `curse_text`) | – | missing | low | Godot rendering only (sent) | C |
| Walking player (on foot) | `draw_pedestrians` (`is_player`) | gold circle | partial | high | Godot rendering only | A |
| Waiting passenger at pickup | `draw_taxi_target` marker + passenger pedestrian | – | missing | high | Godot rendering only (pickup x/y in `current_passenger`) | A |
| Booked rail passenger arrow | `draw_booked_passenger_arrow` | – | missing | high | missing protocol data (meet booking's pedestrian) | A |
| People under roofs (outline) | `draw_pedestrians_under_roofs` | – | missing | low | missing protocol data (roofs) | B |
| Night reflectors | `draw_pedestrian_reflectors` | – | missing | low | missing protocol data (darkness) | C |

## Trains

| Element | Pygame | Godot | Status | Importance | Cause | Phase |
|---|---|---|---|---|---|---|
| Train cars, own length, following track | `draw_trains` | rotated boxes, length − 0.6 m, 3.2 m wide | complete | high | – | – |
| Car colours by profile | `draw_trains` (greens, white locomotive band, restaurant car...) | 2 colours: locomotive or other | partial | low | Godot rendering only (`profile` sent per car) | B |
| Direction / front | white front band | darker locomotive only | partial | low | Godot rendering only | B |
| Under station roofs (outline) | `draw_trains(roof_cover=...)` | – | missing | low | missing protocol data (roofs) | B |
| Clicked car's passengers | `draw_train_car_popup` | – | missing | low | missing protocol data (`passengers.in_car`); needs click input | D |
| Train labels / debug | `draw_trains(show_debug)` | – | debug-only | – | – | D |
| Next train panel | `draw_next_train` (J) | – | missing | medium | missing protocol data (timetable query) | B |

## Taxi job and interaction

| Element | Pygame | Godot | Status | Importance | Cause | Phase |
|---|---|---|---|---|---|---|
| Pickup / drop-off waypoint (pulsing circle and pin) | `draw_taxi_target` | – | missing | high | Godot rendering only (`taxi.state`, `current_passenger.pickup/dropoff` x, y, radius sent) | A |
| Off-screen arrow to the target | `draw_taxi_target` | – | missing | high | Godot rendering only | A |
| Navigation route line (N) | `draw_navigation_route` (route from `traffic_mgr.plan_route` in `main()`) | – | missing | high | missing shared simulation state (routing runs in Pygame's loop, not the simulation step) | A |
| Compass with target bearing (C) | `draw_compass` | – | missing | medium | Godot rendering only (heading and target sent) | A |
| Meet-and-greet panel | `draw_meet_panel` | – | missing | high | missing protocol data (meet booking: who, train, platform, step) | A |
| Nausea warning bubble | `draw_passenger_nausea_bubble` | – | missing | medium | Godot rendering only (`nausea_warning_timer` sent) | A |
| Phone and offers | `draw_phone_offers` (pauses the game) | `phone.gd` (game keeps running) | different by design | high | – | – |
| Game start: city sign, 24 h forecast | `draw_game_start_overlay` | – | missing | low | missing protocol data (city, forecast) | B |
| Start hints (get in, start engine) | `draw_game_start_hint` | HUD hint line | partial | medium | Godot rendering only | A |
| Career city summary | `draw_city_summary` | – | missing | medium | Godot rendering only (`should_stop`, `city_summary` sent) | B |

## Weather and environment

| Element | Pygame | Godot | Status | Importance | Cause | Phase |
|---|---|---|---|---|---|---|
| Rain / snow particles | `draw_rain` (rain streaks, snow flakes) | – | missing | medium | Godot rendering only for type; intensity (heavy rain) missing protocol data | C |
| Splashes | `draw_splashes` (spawned in Pygame's `main()` from puddle overlap) | – | missing | low | Pygame-specific implementation | C |
| Lightning flash | `draw_lightning_flash` (`weather.lightning_intensity`) | – | missing | low | missing protocol data | C |
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
| Speed-camera notice / flash | yes | – | missing | medium | missing protocol data (`speed_camera_notice_msg`, flash) | B |
| Road name, speed limit | yes | – | missing | high | missing protocol data (current way, limit) | A |
| Fuel gauge | yes | – | missing | high | Godot rendering only (`fuel_l`, `fuel_capacity_l` sent) | A |
| Fuel price at a station | yes | – | missing | medium | missing protocol data | B |
| Trip, odometer | yes | – | missing | low | Godot rendering only (sent) | B |
| Rage meter | yes | – | missing | medium | Godot rendering only (`rage_power` sent) | A |
| Water timer (driving in water) | yes | – | missing | medium | Godot rendering only (`water_elapsed` sent) | A |
| Temperature | yes | – | missing | low | missing protocol data | B |
| Speech subtitles (driver / passenger lines) | yes (`comment_text`) | – | missing | low | Pygame-specific implementation (speech chosen client-side in `audio.py`) | C |
| Speed limiter / red-light assist status | yes | – | missing | low | Godot rendering only (the client owns these toggles) | B |
| Lat/lon, ways count, zoom | yes | – | debug-only | – | – | D |
| Resident popup (click a person) | `draw_resident_popup` | – | missing | low | missing protocol data (resident details); needs click picking | D |
| Camera follow other / back button | `draw_camera_back_button` | – | missing | low | Godot rendering only plus input | D |
| Pause / settings / main menus | `render/menus.py` | – | missing | medium | Godot rendering only (UI; settings are client-side) | B |
| Debug overlays: profiler, g-force, NPC panels, spatial grid, intersections, feature inspector, activity | various | F3 text readout | debug-only | – | – | D |

## Camera, coordinates, layering, motion

| Aspect | Pygame | Godot | Status | Notes |
|---|---|---|---|---|
| World → screen | `x_screen = (x − camx)·px_per_m + W/2`, y flipped, north up | `MapMath.point`: (x − origin), y flipped; Camera2D | complete | Same orientation. Godot subtracts a fixed origin for float32 precision. |
| Scale | `px_per_m` 9.0 default (`_DEFAULT_PX_PER_M`), zoom keys | Camera2D zoom 4 px/m, ±25 % keys | partial | Default framing differs: Pygame shows less than half as much ground. |
| Camera target | `camx`/`camy` from the simulation (speed/heading look-ahead) | interpolated player position, no look-ahead | partial | `camx`/`camy` are sent but unused by Godot. |
| Entity rotation | sprites rotated by heading | `draw_set_transform(…, −heading)` | complete | Same heading convention, checked against sent headings. |
| Viewport resize | fixed `SCREEN_W`×`SCREEN_H` | window resizable, default 1280×720 | different by design | – |
| Off-screen culling | explicit viewport culling per call | Godot culls canvas items by bounds; all state entities drawn | partial | Godot draws every NPC and pedestrian the server sends (about 40 + 35), with no client culling. |
| Interpolation | in-process: none needed; `--connect`: `interpolate_state` for player, NPCs, pedestrians (not trains) | `StateBuffer`: player, NPCs, pedestrians, train cars | different by design | – |
| Layering | grass → landuse → water → roads → parking → railways → islands → trees → objects → buildings → tracks → roadworks, curbs, signs → pedestrians → route → target → taxi → NPCs → splashes → roofs → bridge rails → trains → fuel boards → night tint → windows, beams, lamps → weather → labels → HUD → phone | ground → water (z0) → roads, rails, buildings (z1) → trains → NPCs → pedestrians → taxi → walking player (z2) → HUD, phone | partial | **Godot draws trains below NPCs and the taxi; Pygame draws them above, after the bridge rails.** Godot draws buildings below vehicles, as Pygame does. Godot has no roof layer above vehicles. |
| Animations | turn-signal blink, exhaust puffs, smoke, splashes, rain, lightning, pulsing waypoint, pedestrian walk cycle, door opening | none (static shapes, interpolated positions only) | missing | All but door opening use data that is already sent. |

## Counts

Computed from the tables above: 108 rows, each counted once by status.

| Status | Count |
|---|---|
| complete | 7 |
| partial | 22 |
| missing | 71 |
| different by design | 3 |
| debug-only | 3 |
| not applicable | 2 |

Missing and partial rows by cause. The 5 camera/layering
rows have no cause column; all of them are Godot rendering only, since
`camx`/`camy`, headings and every animation input are already sent.

| Cause | Count |
|---|---|
| Godot rendering only | 38 |
| missing protocol data | 47 |
| missing shared simulation state | 1 |
| Pygame-specific implementation | 2 |
| unclear | 0 |

A row whose element is partly rendering and partly data is counted under
the cause written first. For example, "Godot rendering only
(lamp placement from roads); broken lamps need protocol data" counts as
rendering only.

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
