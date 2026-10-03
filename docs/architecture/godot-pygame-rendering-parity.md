# Pygame → Godot rendering parity (audit, 0.16.0g-alpha)

Audited on 2026-10-03 against `release/v0.16.0g-alpha` at commit `0445643`;
rows marked godot-07 were updated after that phase (rendering-only parity).

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
| Roads (surface, width by type) | `draw_ways` | polyline, width 2×half_width, 2 colours (drivable / path), ordered by layer | partial | high | Godot rendering only (colours and edges by highway type) | B |
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
| Taxi turn signals | `draw_car` (`turn_signal` blink) | – | missing | low | missing protocol data (player turn signal not sent) | C |
| Taxi exhaust / crash smoke | `draw_taxi_exhaust`, `draw_taxi_smoke` | 4 rising puffs from `engine_on` / `taxi_smoke_timer` — godot-07 | complete | low | – | – |
| NPC vehicles | `draw_npc_cars` (type-specific sprites, taxi sign, police) | car/van with cabin and taxi sign, bus, truck as Pygame; two-wheelers as body + rider, not Pygame's sprites; police, on-foot, LOD ≥ 2 skipped as Pygame — godot-07 | partial | high | Godot rendering only (two-wheeler sprites) | B |
| NPC turn signals | `draw_npc_cars` | amber corner lamps, `turn_signal_elapsed % 0.9 < 0.45` — godot-07 | complete | medium | – | – |
| NPC brake lights | `draw_npc_cars` (no braking flag for NPCs) | – | not applicable | – | Pygame draws none for NPCs either | – |
| NPC crash state: fallen, crash smoke | `draw_npc_cars`, `draw_taxi_smoke` style | fallen two-wheelers on their side, smoke from `crashed_timer` — godot-07 | complete | medium | – | – |
| Parked vehicles | `draw_npc_cars` (parked NPCs are NPCs) | drawn as NPC boxes | partial | medium | Godot rendering only (as NPC vehicles) | A |
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
| Booked rail passenger arrow | `draw_booked_passenger_arrow` | – | missing | high | missing protocol data (meet booking's pedestrian) | A |
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
| Meet-and-greet panel | `draw_meet_panel` | – | missing | high | missing protocol data (meet booking: who, train, platform, step) | A |
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
| Pause / settings / main menus | `render/menus.py` | – | missing | medium | Godot rendering only (UI; settings are client-side) | B |
| Debug overlays: profiler, g-force, NPC panels, spatial grid, intersections, feature inspector, activity | various | F3 text readout | debug-only | – | – | D |

## Camera, coordinates, layering, motion

| Aspect | Pygame | Godot | Status | Notes |
|---|---|---|---|---|
| World → screen | `x_screen = (x − camx)·px_per_m + W/2`, y flipped, north up | `MapMath.point`: (x − origin), y flipped; Camera2D | complete | Same orientation. Godot subtracts a fixed origin for float32 precision. |
| Scale | `px_per_m` 9.0 default (`_DEFAULT_PX_PER_M`), zoom keys | Camera2D zoom 9 px/m default (godot-07), ±25 % keys | complete | – |
| Camera target | `camx`/`camy` from the simulation (speed/heading look-ahead) | interpolated player position, no look-ahead | partial | `camx`/`camy` are sent but unused by Godot. |
| Entity rotation | sprites rotated by heading | `draw_set_transform(…, −heading)` | complete | Same heading convention, checked against sent headings. |
| Viewport resize | fixed `SCREEN_W`×`SCREEN_H` | window resizable, default 1280×720 | different by design | – |
| Off-screen culling | explicit viewport culling per call | entities culled against the camera view + 30 m (godot-07); map chunks culled by Godot | complete | – |
| Interpolation | in-process: none needed; `--connect`: `interpolate_state` for player, NPCs, pedestrians (not trains) | `StateBuffer`: player, NPCs, pedestrians, train cars | different by design | – |
| Layering | grass → landuse → water → roads → parking → railways → islands → trees → objects → buildings → tracks → roadworks, curbs, signs → pedestrians → route → target → taxi → NPCs → splashes → roofs → bridge rails → trains → fuel boards → night tint → windows, beams, lamps → weather → labels → HUD → phone | ground → water (z0) → roads, rails, buildings (z1) → trains → NPCs → pedestrians → taxi → walking player (z2) → HUD, phone | partial | Godot-07: trains now above vehicles as in Pygame; roads by layer, wet overlays and puddles above roads, buildings above, entities above all (z 10). Still no roof layer above vehicles, no bridge-rail layer. |
| Animations | turn-signal blink, exhaust puffs, smoke, splashes, rain, lightning, pedestrian walk cycle, door opening | godot-07: turn-signal blink, exhaust and crash smoke, walk cycle, curse fade | partial | Missing: splashes and rain (Phase C), lightning (protocol), door opening (Pygame-specific). |

## Counts

Computed from the tables above: 108 rows, each counted once
by status. godot-06 is the audit; godot-07 is after the rendering-only phase.

| Status | godot-06 | godot-07 |
|---|---|---|
| complete | 7 | 30 |
| partial | 22 | 18 |
| missing | 71 | 52 |
| different by design | 3 | 3 |
| debug-only | 3 | 3 |
| not applicable | 2 | 2 |

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
