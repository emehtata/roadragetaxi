# Pygame → Godot rendering parity (audit, 0.16.0g-alpha)

Audited on 2026-10-03 against `release/v0.16.0g-alpha` at commit `0445643`;
rows marked godot-07 were updated after that phase (rendering-only parity),
rows marked godot-10 after the re-audit of 2026-10-05 (`734a3b7`; see
[the godot-10 section](#godot-10-re-audit)), rows marked godot-11 after
[phase 2](#godot-11-phase-2-server-state-already-owned), rows marked godot-12 after
[phase 3](#godot-12-phase-3-gameplay-points-in-chunks), rows marked godot-13 after
[phase 4](#godot-13-phase-4-collision-relevant-static-world), rows marked godot-14 after
[phase 5](#godot-14-phase-5-server-calendar-and-daynight), rows marked godot-15 after
[phase 6a](#godot-15-the-static-world-drawing-only-objects-night-seasons), rows marked godot-16 after
[phase 6b](#godot-16-the-rest-of-the-static-world).

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
| Landuse fills: parks, forest, grass, parking areas | `draw_scenery` | chunk `landuse`, clipped to each chunk square, filled in Pygame's kind colours, green kinds through the season — godot-16. Missing: the speckle texture on vegetation | partial | medium | Godot rendering only (speckles) | C |
| Water | `draw_waters` (ice in winter, spring floes) | flat polygons, freezing to Pygame's ice colour with `calendar.season`'s winter weight — godot-15; no spring floes | partial | medium | Godot rendering only (spring floes: position-seeded plates) | C |
| Roads (surface, width by type) | `draw_ways` | polyline by layer, width 2×half_width, colour from `road_color_for_way` (surface, then type) — godot-16. Pygame's paved verges beside paths are not drawn | complete | high | – | – |
| Road markings: centre lines, dashes | `draw_ways` (`center_lines`) | centre line on roads ≥ 6 px wide (dashed 8/6 m, solid on two-way 3+ lanes), one-way chevrons every 40 m, per road layer — godot-16 | complete | medium | – | – |
| Road layers: bridges over roads | `draw_ways` layer ordering, bridge pass | z level per `layer` (bridges above, dark edge), lowest first — godot-07 | partial | high | missing protocol data (Pygame outlines a vehicle under a higher road; the taxi's layer isn't sent) | B |
| Underground / covered roads (map levels) | `draw_level_ways` | below ground (`player.map_level`): a dark view with the level's roads, no surface traffic or street lights; on the surface, the covered level-0 roads — godot-16 | complete | medium | – | – |
| Wet roads | `draw_wet_roads` | `map_chunk.gd` darken + sheen overlays on drivable roads, alpha by wetness in 3/255 steps — godot-07 | complete | low | – | – |
| Puddles | `draw_puddles` (from road geometry and wetness) | 40 % of drivable roads, reveal threshold, size and alpha by wetness — godot-07; spots seeded from geometry (Pygame: OSM ids), no rain ripples | partial | low | Godot rendering only (ripples); exact spots need OSM ids (protocol) | C |
| Parking spaces | `draw_parking_spaces` | chunk `parking`: asphalt bays with a light edge — godot-16 | complete | low | – | – |
| Railways: rails, sleepers, ballast | `draw_railways` | ballast bed (zoomed in), two rails at standard gauge, a sleeper every 2 m — godot-16 | complete | medium | – | – |
| Rail bridges above vehicles | `draw_railways(only_bridges=True)` after vehicles | chunk `rail_decks` (deck, guardrail edge) and `rail_bridges` (track) at z 11 above the vehicles, trains above them — godot-16 | complete | medium | – | – |
| Traffic islands | `draw_traffic_islands` | chunk `traffic_islands` above roads and rails, in their landuse colour — godot-16 | complete | low | – | – |
| Trees | `draw_trees` | chunk `trees`: crown by kind and variation, seeded irregular blob; felled trees lie the way they were hit (`state.fallen_trees`); collision on the server — godot-13; seasonal crown colours from `calendar.season` — godot-15. Missing: the hit's shake and leaf burst (`tree_effects`, not sent), wind lean (`weather.tree_lean_m`, not sent) | partial | medium (collisions) | missing protocol data (shake, leaves, wind lean) | C |
| Scenery objects: benches, bollards, fountains | `draw_scenery_objects` (+ knocked-over state) | bollards and knocked posts (godot-13), fuel pumps (godot-12), and the decorative kinds — bench (along its path), bin, bicycle parking, statue, picnic table, fire pit, fountain, gate — from chunk `scenery_objects` — godot-15 | complete | medium (bollards collide) | – | – |
| Bus stops (option) | `draw_bus_stops` | chunk `bus_stops`: bay, shelter and "BUS" from the nearest road, computed once by the server — godot-16 (Oulu has none: bus stops are off by default) | complete | low | – | – |
| Buildings | `draw_buildings` (cached geometry, facades) | top-down: Pygame's roof colour (a colour in the name, else its texture pick), a height shadow, gabled facets and ridge, door marks at entrances — godot-16. No oblique facades, by design (the brief) | different by design | high | – | – |
| Open-roof canopies over vehicles | `draw_open_roof_overlays` | chunk `canopies`: shadow and posts under the vehicles, the translucent roof above them; fuel pumps show — godot-16 | complete | medium | – | – |
| Tire tracks | `draw_tire_tracks` ×4 | the server's per-tick `tire_mark` (as `main()` decides it), laid along the drawn taxi, at most 4000 points — godot-16. The client keeps the trail, so a reconnect starts a new one | complete | low | – | – |
| Roadworks barriers / cones | `draw_roadworks` | chunk `roadworks`: barriers at both ends (lane or full road), cones between, Pygame's pixel sizes — godot-12 | complete | high (block roads) | – | – |
| Curbs | `draw_curbs` | chunk `curbs`, 0.15 m grey — godot-16 | complete | low (curb bump) | – | – |
| Fences, railings, walls, hedges | `draw_railings` | chunk `railings`: hedges and walls solid (0.25 m), fences and railings dashed 0.8/0.4 m; no collision, as in the simulation — godot-15 | complete | low | – | – |
| Construction fences | `draw_construction_fences` | chunk `construction_fences`: the site's ring as a dashed hazard fence, 1.5 m dash / 1 m gap round the corners; collision (`check_fence_collision`) on the server — godot-13 | complete | low | – | – |
| Zebra crossings | `draw_crossings` | 0.5 m stripes along the road, 0.9 m apart, across its width — godot-16 | complete | medium | – | – |
| Speed bumps | `draw_speed_bumps` | dark rectangles, length by kind — godot-16 | complete | medium | – | – |
| Traffic lights (posts and live phase) | `draw_traffic_lights(sim_time)` | chunk `traffic_lights` posts (render position, angle, 7×18 px housing) lit by `state.traffic_lights`, the server's `get_state` — godot-12. Phases are sent within 600 m of the player: zoomed out past that (about ten zoom steps), farther posts show unlit | complete | high | – | – |
| Taxi stands (TAXI signs) | `draw_taxi_stops` | chunk `taxi_stands`: the TAXI sign on its pole — godot-12 | complete | high (rail pickups) | – | – |
| Stop / yield signs | `draw_stop_signs`, `draw_yield_signs` | octagon with STOP / give-way triangle on a pole, pixel-sized as Pygame's — godot-16 | complete | medium | – | – |
| Speed cameras | `draw_speed_cameras` (+ flash) | box, red lens, yellow arrow; the flash from `state.speed_camera_flash` — godot-16 | complete | medium | – | – |
| Fuel stations (price boards) | `draw_fuel_station_signs` (+ the pumps in `draw_scenery_objects`) | chunk `fuel_stations`: pin and board with the name and the server's price above the vehicles, pumps under the buildings — godot-12 | complete | high (fuel runs out) | – | – |
| Street lights (+ broken lamps dark) | `draw_street_lights` (placed from roads; `broken_lamps`) | chunk `street_lights`, placed by the server with Pygame's own placement; at darkness > 0.25 the pools' union added once (+22) over the tint, then the lamp heads; a knocked street lamp (`state.knocked_posts`) dark — godot-15 | complete | low | – | – |
| Illuminated windows at night | `draw_illuminated_windows` | – (godot-15: drawn on Pygame's oblique facades - roof offset by height, which windows are lit seeded by `id(building)`; Godot's buildings are flat top-down, so there is no facade to light) | missing | low | Pygame-specific implementation (needs the building-detail rendering) | phase 6 |
| Map labels: place and street names | `draw_labels` (decluttered) | `labels.gd`: the server's candidates, decluttered per view by Pygame's rules (priority, unique, no overlap, ≤ 35, zoom gates) — godot-16 | complete | medium | – | – |
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
| Night headlight beams | `draw_headlight_beams` | `night_layer.gd`: the taxi's and NPCs' beams cut out of the tint, minus buildings — godot-15; skipped under a higher road (the taxi's sent road layer and bridge flag; an NPC on a raised layer counts as on its bridge) — godot-16 | complete | medium | – | – |
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
| Night reflectors | `draw_pedestrian_reflectors` | below −7.5° sun, a bright point on pedestrians outside the taxi's beam cone and 10 m of a working street light — godot-15 | complete | low | – | – |

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
| Day/night tint | `draw_day_night_overlay` (sun altitude from time, lat/lon, date) | `Sky/Night`: dark blue at 115 × `state.calendar.darkness`, +95 × sparse where fewer than 12 drivable roads are in view; over the world, under the UI — godot-14 | complete | high (night visibility) | – | – |
| Snow cover / seasons | `draw_grass_texture(season)`, `draw_waters` ice | `calendar.season` weights: snow on the ground with the winter weight, frozen water, seasonal tree crowns — godot-15. Missing: spring ice floes; Pygame's seasonal grass palettes other than snow (tuned to its grass texture); snow depth from observed weather (only in `main()`) | partial | low | missing simulation state (observed snow depth); Godot rendering only (floes, grass texture) | C |
| Weather text | HUD | HUD `weather_type`, wetness | complete | medium | – | – |

## HUD and UI

| Element | Pygame (`draw_hud` unless noted) | Godot | Status | Importance | Cause | Phase |
|---|---|---|---|---|---|---|
| Speed | yes | `hud.gd` | complete | high | – | – |
| Game time | yes (+ date, real-time marker) | `hud.gd`: `state.calendar.date` HH:MM, ` *` while `time_scale` is 1 (a fare) — godot-14 | complete | medium | – | – |
| Money | yes | `hud.gd` | complete | high | – | – |
| Taxi job / passenger | mission bar | `hud.gd` fare line | partial | high | Godot rendering only (fields sent) | A |
| Notifications | yes | `hud.gd` notice | complete | high | – | – |
| Speed-camera notice / flash | yes (notice centred, red border); lens flash at the camera (`draw_speed_cameras`) | notice centred with a red border — godot-11; the lens flash — godot-16 | complete | medium | – | – |
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
| Layering | grass → landuse → water → roads → parking → railways → islands → trees → objects → buildings → tracks → roadworks, curbs, signs → pedestrians → route → target → taxi → NPCs → splashes → roofs → bridge rails → trains → fuel boards → night tint → windows, beams, lamps → weather → labels → HUD → phone | ground (z −2) → landuse (−1) → water (0) → roads by layer with markings (1–4) → wet, puddles, parking, guardrails (5) → rails, islands, trees, objects, pumps (6) → buildings, canopy posts (7) → tyre tracks, curbs/crossings/bumps, railings, fences, roadworks, signs, lights (8) → underground (9) → entities (10) → canopies, rail bridges (11) → trains (12) → fuel boards (13) → night (20) → street lights (21) → reflectors (22) → labels, HUD, phone (UI) — godot-16 | complete | Pygame's order, with Godot z levels. |
| Animations | turn-signal blink, exhaust puffs, smoke, splashes, rain, lightning, pedestrian walk cycle, door opening | godot-07: turn-signal blink, exhaust and crash smoke, walk cycle, curse fade | partial | Missing: splashes and rain (Phase C), lightning (protocol), door opening (Pygame-specific). |

## Counts

Computed from the tables above: 108 rows (109 from godot-10), each counted once
by status. godot-06 is the audit; godot-07 is after the rendering-only phase.

| Status | godot-06 | godot-07 | godot-10 | godot-11 | godot-12 | godot-13 | godot-14 | godot-15 | godot-16 |
|---|---|---|---|---|---|---|---|---|---|
| complete | 7 | 30 | 31 | 35 | 39 | 40 | 42 | 46 | 65 |
| partial | 22 | 18 | 16 | 17 | 17 | 19 | 18 | 19 | 14 |
| missing | 71 | 52 | 52 | 47 | 43 | 40 | 39 | 34 | 19 |
| different by design | 3 | 3 | 4 | 4 | 4 | 4 | 4 | 4 | 5 |
| debug-only | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 3 |
| not applicable | 2 | 2 | 3 | 3 | 3 | 3 | 3 | 3 | 3 |
| rows | 108 | 108 | 109 | 109 | 109 | 109 | 109 | 109 | 109 |

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

## godot-12: phase 3, gameplay points in chunks

Taxi stands, fuel stations, traffic-light posts with their live phases,
and roadworks. All are static data the server already held, added to the
existing chunks, plus one per-tick field for the phases. There's no
simulation change, and no change to how roadworks block driving.

**What existed before:**

| Data | Where | Class |
|---|---|---|
| Taxi stands | `world.taxi_stops` (`TaxiStop` x, y, id); no queue state: waiting people are ordinary pedestrians | protocol/data + rendering |
| Fuel stations | `world.scenery_objects` of kind `fuel` (x, y, name, `direction_angle`, `is_area`); the price is `fuel.fuel_station_price_cents` | protocol/data + rendering |
| Traffic lights | `traffic_mgr.traffic_lights` (OSM posts plus the roadworks' temporary ones, which have **no id**); phase from `TrafficLight.get_state(sim_time)` on the server | protocol/data + rendering |
| Roadworks | `world.roadworks`, made once at load and only when `roadworks_enabled` is set: start, end, lane or full closure; the server already blocks driving into them | protocol/data + rendering |

**Protocol:**

| Field | Source | Consumer | Why | Static/dynamic |
|---|---|---|---|---|
| chunk `taxi_stands`: `[x, y]` | `world.taxi_stops` | `map_chunk._draw_points` | the TAXI sign | static |
| chunk `fuel_stations`: `x, y, angle, is_area, name, price_cents` | fuel scenery objects; `fuel_station_price_cents` | `_draw_fuel_pumps`, `_draw_fuel_boards` | pumps, pin, board with the simulation's price | static |
| chunk `traffic_lights`: `id, x, y, angle` | `traffic_mgr.traffic_lights`; position from Pygame's `_traffic_light_render_position` | `_draw_traffic_lights` | the post; `id` is the list index (stable for the session; roadwork lights have no OSM id) | static |
| chunk `roadworks`: `start, end, lane_closed, half_width_m` | `world.roadworks` | `_draw_points` | barriers and cones | static |
| state `traffic_lights`: `{id: phase}` | `get_state(sim_time)` for posts within 600 m of the player (on foot: the walker) | `map_layer.set_traffic_lights` | lamps; Godot never computes a phase | per tick |

Every point is in exactly one chunk, the one containing it. A roadwork
goes in its midpoint's chunk. So no client draws a point twice, even
though long roads are in several chunks. Older clients ignore the new
lists, and a newer client handles an older server (missing lists draw
nothing).

**Godot:**
- `map_chunk.gd` draws the points into the chunk's own canvas items:
  - pumps at z6, under the buildings, as Pygame draws them
  - roadworks and taxi signs at z8
  - the traffic-light posts as their own z8 node
  - the fuel boards at z11, above the vehicles (`draw_fuel_station_signs`
    runs after them)
- They use Pygame's pixel sizes, so they redraw when the zoom changes,
  never per frame. Chunks without points get no extra nodes.
- The posts redraw only when one of that chunk's own lights changes phase.
- `map_layer.gd` passes the zoom and the phases on. `main.gd` gains two
  lines after the camera is placed, which only read its zoom.

**Bug found and fixed:** post ids arrive as JSON floats, and `str(0.0)` is
`"0.0"`, so every lamp stayed unlit on the real server. Ids are now read
as ints, and the Godot test parses its chunk through JSON like the real
client does (it fails without the fix).

**Verified:**
- Python tests: one chunk per point (a roadwork across a chunk edge goes
  in one), the post id and render position, a non-renderable post left
  out, an empty chunk carries every list, the phases follow `sim_time`
  and nothing is sent far away. Every phase sent names a post the
  server's own chunks carry.
- Godot unit tests (143 checks): points arrive with their chunk and only
  once, chunks without points get no point layers, the board text, the
  lamps by phase (`all-red` reads as red; no phase lights nothing),
  redraw only on change, no phase change without the server, unload and
  reload with the current phases, zoom reaching the points.
- Real Oulu server (roadworks on through a scratch config copy):
  screenshots at a taxi stand, a fuel station (St1, 2.57 €/L), a
  junction's lights and a lane-closure roadwork with its temporary
  lights. Pixel checks at three posts: shots 8 s apart show opposing
  approaches switching green and red with the server. After walking
  4 km away (the chunk unloaded) and back (reloaded), the posts covered
  exactly the same pixels.
- `make godot-selftest`: `ok`, 145 FPS, taxi 0 px off centre, 0 render
  backsteps. Static memory 65.1 → 66.0 MiB.

**Deferred or still open:**
- Fuel pumps under a station's canopy are hidden. Godot draws every
  building as a flat roof, and open-roof canopies are their own missing
  row (phase 6, building detail).
- The HUD's fuel price and refuel prompt near a station (the "Fuel price
  at a station" row) needs the nearest station in `state`. That's a small
  per-tick addition, not done here.
- The speed camera's lens flash still needs camera positions (the static
  world phase).

**Next phase (unchanged order):** the collision-relevant static world
(trees, scenery objects, fences and railings, knocked-over posts and
broken lamps), then the server calendar (day/night), the rest of the
static world, and navigation.

## godot-13: phase 4, collision-relevant static world

**Collision authority.** Every collision with the static world is decided
on the server. `simulation.advance_simulation`, which both Pygame's loop
and the headless server run, calls these `TaxiManager` checks:
- `check_tree_collision`
- `check_fence_collision`
- `check_post_collision`
- `check_building_collision`, the curb and speed-bump checks

The Godot client has no physics and predicts nothing. So this phase
doesn't add collision shapes to Godot, which would make a second
authority. It sends what the server collides with, and the state those
collisions change, and Godot draws it.

| Obstacle | Pygame / server source | Collision (server) | Affects | Godot |
|---|---|---|---|---|
| Trees | `world.sceneries[*].trees`, `tree_kinds`, `tree_variations` (OSM, `osm/trees.py`) | circle of the car's half-diagonal + 1 m around the trunk; trees on car roads exempt; over 80 km/h the tree falls (`fallen_trees`) and the taxi waits 5 s | the player's taxi | chunk `trees`; `state.fallen_trees` |
| Construction fences | `sceneries` of kind `construction` (polygons) | the car's box against the polygon; stops the taxi, −150 points | the player's taxi | chunk `construction_fences` (the ring) |
| Bollards, street lamps | `world.scenery_objects` of kind `bollard`, `street_lamp` (`POST_KINDS`) | the car's box + 0.15 m; under 50 km/h it stops the taxi, at or above it the post bends over (`knocked_angle`), a lamp goes into `broken_lamps`, and the taxi carries on slowed | the player's taxi | chunk `bollards`; `state.knocked_posts` |
| Railings, walls, hedges | `world.railings` | **none**: no simulation code reads them | rendering only | left for phase 6 |

Pedestrians collide only with buildings (`walk_blocked_by_walls`), and
NPC routing doesn't use these obstacles. Nothing here affects navigation.

**Protocol:**

| Field | Source | Consumer | Static/dynamic | Collision relevance |
|---|---|---|---|---|
| chunk `trees`: `[x, y, kind, variation]` | scenery trees | `map_chunk._draw_trees` | static | the trees `check_tree_collision` tests |
| chunk `construction_fences`: rings | `construction` sceneries | `_draw_fences` | static | the polygons `check_fence_collision` tests |
| chunk `bollards`: `[x, y]` | `bollard` scenery objects | `_draw_trees` (same canvas item) | static | the posts `check_post_collision` tests |
| state `fallen_trees`: `[x, y, angle]` | `taxi_mgr.fallen_trees` + `tree_effects` | `map_layer.set_obstacles` | dynamic, grows only, within 600 m | a felled tree |
| state `knocked_posts`: `[x, y, angle, kind]` | scenery objects with `knocked_angle` | `map_layer` (draws them), chunks (hide the standing bollard) | dynamic, grows only, within 600 m | a knocked post no longer blocks |

Each obstacle is in one chunk. A construction site goes in its first
corner's chunk, with the whole ring. That's safe because a site is far
smaller than the 1.5 km of chunks loaded around the player. The dynamic
lists name obstacles by position at 0.1 m, as both sides round them.

Knocked street lamps are drawn from the state alone. A standing lamp is
drawn by Pygame's night street-light renderer, which waits for the
day/night phase. Oulu has 6,851 trees, 8 construction sites and 50
bollards, and chunks grew from 36.9 to 37.6 KiB on average (max 205 →
210 KiB).

**Godot:**
- `map_chunk.gd` draws trees and bollards at z6, before the buildings as
  Pygame does, and fences at z8 with the signs.
- A chunk redraws its trees only when one of its own changes state, and on
  zoom changes (the minimum pixel sizes).
- `map_layer.gd` draws knocked posts from the state.
- `main.gd` passes the two lists on, next to the traffic-light phases.

**Verified:**
- Python tests: each obstacle in one chunk (a site across a chunk edge
  goes in one, whole), lamps and benches aren't bollards. A real
  `TaxiManager` fells a pine at 90 km/h and knocks a bollard at 61 km/h,
  and both reach `_fallen_and_knocked`; nothing is sent far away.
- Godot unit tests (157 checks): obstacles arrive and leave with their
  chunk, once; JSON-parsed data; tree styles as Pygame's palettes; the
  dash pattern over a corner; felled and knocked state matched by
  position; a lamp drawn from the state alone; no redraw for the same
  state; still felled after a reload.
- Real Oulu server, driving with the server's own collision code (a
  scratch launcher, the production config untouched):
  - A tree hit at 90 km/h fell, and the taxi stopped.
  - A bollard at 18 km/h stopped the taxi and stayed up; at 61 km/h it
    bent over and the taxi carried on.
  - A construction fence at 54 km/h stopped the taxi, with −150 points
    and the fence notice.
  - Each time, the walker then went 4 km away (the chunk unloaded) and
    back (reloaded) before Godot's screenshot. The felled tree, the
    knocked bollard and the dashed fence were drawn in place after the
    reload.
  - Collision can't differ before and after a client's reload: it never
    depended on the client.
- `make godot-selftest`: `ok`, 145 FPS, taxi 0 px off centre, 0 render
  backsteps. Static memory 66.0 → 68.1 MiB.

**Remaining:**
- **Trees (protocol and simulation):** the hit's shake and leaf burst,
  and the wind lean, need `tree_effects` and `weather.tree_lean_m` in
  the state. Seasonal colours need the calendar.
- **Decorative scenery objects, railings, walls and hedges (phase 6):**
  rendering and protocol only, since none of them collide.
- **Street lamps and their dark heads when broken:** the night phase.
- **Unchanged from godot-12:** the fuel pumps under the solid canopy, the
  fuel-price HUD, and the 600 m traffic-light phase radius.

**Next phase (unchanged order):** the server calendar and day/night, then
the rest of the static world, then navigation.

## godot-14: phase 5, server calendar and day/night

**Before:**
- Pygame's `main()` kept a `GameCalendar` (date and time, advanced at
  60× game time without a fare and 1× during one), synced the weather's
  season on each new day, and computed the sun from the date, time and
  the city's latitude and longitude (`solar_altitude_and_events`, cached
  20 s of wall clock).
- The headless server had none of this. It kept a separate
  seconds-of-day counter starting at 18:00, used `date.today()` for the
  simulation's `now`, and left the weather's season at its default.
- Godot guessed night from the hour, for its ambience only.

**Now: one authoritative clock.**
- The server keeps the same `GameCalendar`, advanced with the same time
  scale. `game_time_seconds` is derived from it (a property, not a second
  counter), and so are the simulation's `now` and the weather's season
  on every new day.
- It still starts today at 18:00, so the server's timing is unchanged.
  Pygame's career default (31 August) comes from its start screen, which
  the server doesn't have.
- The solar model is now one pure function,
  `calendar.solar_altitude_and_events_on`. Pygame's cached
  `render.common.solar_altitude_and_events` wraps it, so its behaviour is
  unchanged and its existing tests pass.
- Darkness is one function, `calendar.darkness_for_sun_altitude`, used by
  Pygame's night tint, its ambience and the server.

**Protocol:** `state.calendar`, sent every tick (null from a caller
without a calendar; older clients ignore it):

| Field | Unit / range | Meaning |
|---|---|---|
| `date` | `"YYYY-MM-DD"` | the calendar's date; the time of day stays `game_time_seconds` (seconds since local midnight, 0–86400) |
| `time_scale` | game seconds per real second: 60, or 1 during a fare | Pygame's ` *` marker |
| `sun_altitude_deg` | degrees, −90..90 | at the city's latitude and longitude |
| `darkness` | 0 (day: sun ≥ 6° up) .. 1 (night: sun ≤ −12°), linear between | what the night tint, ambience and (later) street lights follow |

All four are authoritative. Godot computes no time, date or sun.

**Godot:**
- A screen-space `Sky` canvas layer sits between the world and the UI.
  `Night` has Pygame's colour (10, 18, 48) and alpha
  `int(115 × darkness)`, plus `int(95 × sparse)` where fewer than 12
  drivable roads are in view: Pygame's `visible_road_count`, counted once
  per road across chunks, every 0.1 s and only at night, from the chunks
  overlapping the view.
- `Flash`, the lightning, moved here from the world layer so that it sits
  above the night tint, as Pygame draws lightning after it.
- Both are recoloured only when their alpha changes. No chunk is redrawn
  for time.
- The ambience loops use `darkness`. The old hour table remains only for
  servers without a calendar.
- The HUD clock shows the date and ` *` during a fare.

**Smoothness:** the server computes the sun every tick, while Pygame
recomputes it at most every 20 s of wall clock (its cache), so at 60× its
tint steps every 20 game minutes. Godot's tint changes continuously. The
values are the same at any moment Pygame refreshes; this is the only
deliberate difference.

**Verified:**
- Python tests on the real `GameCalendar` and solar model: the server's
  game time is the calendar's. Midsummer noon in Oulu is day (sun > 40°);
  a midwinter evening is night (< −12°). The darkness boundaries are 6°,
  −3° and −12°. At 60×, midnight rolls the date and the season follows.
  `state.calendar` survives a JSON round trip and is null for a caller
  without one.
- Godot unit tests (169 checks):
  - the tint alpha against Pygame's numbers (day 0, night 115, dusk 57,
    empty country up to 210)
  - no tint without a calendar
  - the HUD date and ` *`
  - a road in two chunks counted once, a footpath not at all
  - no flash without state
- Real Oulu server, with the calendar set from a scratch control file
  and the production config untouched:
  - At 12:00 the sun is 18° up, darkness 0. At 23:00 it's −27°, darkness
    1; at 19:00 −4.6°, darkness 0.59, advancing at 60×.
  - Each screenshot was a new client connection, so a reconnect shows
    the server's time, not a reset.
  - Solving the drawn pixels against the daytime shot gave tint alpha
    116 at 23:00 (expected 115) and 70 at dusk (expected 115 × 0.61).
  - The HUD showed "2026-10-05 23:06" untinted.
  - godot-13's felled tree was drawn the same after a chunk unload and
    reload.
- `make godot-selftest`: 145 FPS, 0 render backsteps, taxi 0 px off
  centre. Static memory measured 70.3, 68.8 and 71.2 MiB across runs,
  against 69.9 without this phase's chunk change: noise of about
  ±1.5 MiB around godot-13's 68.1, no measurable cost. Startup is
  unaffected.

**Remaining (unchanged scope):**
- **Night effects:** headlight beams, street lights (with broken lamps
  dark), lit windows and reflectors are now rendering-only. Lit windows
  also need window data.
- **Seasons:** snow cover, ice and seasonal tree colours need the season
  (now on the server) and snow depth sent.
- **Temperature:** still the simulation's default 15 °C; the server has
  no temperature model.
- **The sun's position:** taken at the city centre. Pygame re-centres
  it on the taxi every 15 game minutes, a difference of a few kilometres.
- **Deferred:** the godot-12 and godot-13 deferred items are unchanged.

**Next phase (unchanged order):** the rest of the static world, then
navigation.

## godot-15: the static world (drawing-only objects, night, seasons)

All of this is drawing. Nothing here collides in the simulation, so the
client adds no collision (a test asserts there are no physics nodes).

**Protocol:**

| Field | Source | Static/dynamic | Notes |
|---|---|---|---|
| chunk `railings`: `[kind, polyline]` | `world.railings` (fence, railing, hedge, wall) | static | in its first point's chunk, whole |
| chunk `scenery_objects`: `[x, y, kind, angle]` | the decorative `scenery_objects` kinds | static | bollards, fuel pumps and street lamps have their own lists |
| chunk `street_lights`: `[x, y, road direction, pool radius]` | Pygame's own placement (`render/roads.py`), run once by the server over the whole map at startup | static | Oulu: ~21,500 lights, ~1.7 s of startup; Pygame places them per view region |
| state `calendar.season`: `[winter, spring, summer, autumn]` | `GameCalendar.seasonal_appearance`, in 0.05 steps | per tick, changes about daily | the weights Pygame's seasonal palettes blend |

Oulu chunks grew from 37.6 to 41.8 KiB on average (max 210 → 267 KiB).

**Night, as Pygame layers it:**
- **The tint** is now in the world (`night_layer.gd`, z20): a
  `CanvasGroup` with the headlight beams cut out of it. The beams show the
  scene untinted, as Pygame restores its daylight copy inside them.
  - Beams are clipped against building outlines with `Geometry2D`; a
    building wholly inside a beam is tinted again.
  - The group's buffer keeps only a few alpha levels in the compatibility
    renderer (a 0.451 alpha read back as 0.333). So the tint is painted
    opaque inside, and the group's shader applies the alpha.
  - On the real server the drawn tint measured alpha 122 where the client
    asked for 122 (darkness 1, 11 roads in view).
- **Street lights** (z21), when darkness > 0.25:
  - The pools of every loaded chunk are painted into one `CanvasGroup`,
    whose shader adds their union once (+22). Adding each pool separately
    would stack overlaps to white; Pygame paints them into one layer too.
  - Then the lamp heads in Pygame's colour (215, 215, 200).
  - A knocked street lamp (`knocked_posts`, kind `street_lamp`) has no
    pool and no head.
- **Reflectors** (z22) appear below −7.5° sun, on pedestrians outside the
  taxi's beam cone and further than 10 m from a working street light.
- **Lightning** stays above everything (screen-space `Sky/Flash`).

**Seasons:**
- Tree crowns blend Pygame's four palettes by the server's weights, and
  water freezes with the winter weight.
- The ground takes only the snow. Pygame's other palettes are tuned to its
  dark grass texture, and on Godot's lighter flat ground autumn turns
  brown.
- A chunk redraws only when the weights change, about once a game day.

**Performance:**
- 145 FPS (unchanged), 0 render backsteps, taxi 0 px off centre.
- Static memory is about 78.7 MiB, against godot-14's 69–71:
  - ~5 MiB is the bigger chunk data the client holds
  - the rest is drawing
- The first build was at 92.9 MiB. Batching brought it down:
  - one `draw_multiline` per railing style
  - fences as hairlines below 1.5 px
  - one triangle array per chunk for pools and for lamp heads
  - lamp positions in a `PackedVector2Array`
  - building outlines for beams made only on the first night
- Static layers redraw only on zoom or state changes, never with the
  clock.
- Helper nodes are now created in `_ready`. That also ends the leak
  warnings the Godot tests printed when the scene was instantiated without
  a tree. One later run still printed an "ObjectDB instances leaked" line
  once; three reruns were clean.

**Verified:**
- Python tests: each new list in one chunk (a hedge across a chunk edge,
  whole, in one). The server's lights are exactly Pygame's placement, each
  in one chunk. The season weights follow the calendar. 1559 pass.
- Godot unit tests (197 checks):
  - chunk load, unload and reload, without duplicates or stale pools
  - lights only at night; a knocked lamp dark, before and after a reload
  - `lamp_near` skipping broken lamps
  - no physics nodes
  - Pygame's seasonal palette values
  - beam lengths and the long-beam rules (oncoming)
  - beams clipped at a building, and a building inside a beam tinted again
  - the reflector cone
  - the night layer turning off by day
- Real Oulu server (calendar set through a scratch control file; the
  production config untouched):
  - At 23:00, with the taxi driving: the tint, lamp heads (195 pixels in
    exactly Pygame's colour), light pools, and the two beams with caps
    showing the road untinted.
  - A street lamp knocked over at 61 km/h by the server's collision code:
    after a 4 km unload and reload, it lies 4 m east, with no head and no
    pool.
  - At noon on 15 January (season `[1, 0, 0, 0]`): snow ground, frosted
    crowns, frozen water.
  - No client error lines in any run.

**Not done, and why:**
- **Lit windows:** Pygame draws them on its oblique facades. Godot's
  buildings are flat, so this belongs with building detail.
- **Headlight beams:** they don't yet skip vehicles under a higher road
  (needs the taxi's layer).
- **Trees:** no hit shake or leaves, no wind lean.
- **Seasons:** no spring ice floes, and no observed snow depth (only
  `main()` reads weather history).
- **HUD readability:** the white "Trip · Odometer" text is hard to read on
  snow. Not changed here.

**The rest of the static world (not in this phase's brief, still
missing):**
- landuse fills, parking spaces, traffic islands, curbs
- crossings, speed bumps, stop and yield signs, speed cameras (and their
  lens flash), bus stops
- map labels, road markings, road colours by type, railway track style
- buildings: facades, heights, open-roof canopies (which would also
  uncover the fuel pumps), people and trains under roofs
- rail bridges above vehicles, underground levels
- tire tracks, vomit puddles

**Next:** the rest of the static world above (phase 6b), then navigation.

## godot-16: the rest of the static world

Everything Pygame draws from the map is now drawn by Godot. It's all
drawing: no collision, no routing, no client-side simulation (a test
asserts no physics nodes).

**Where the data comes from (all of it was server or map data already):**

| Item | Server source | Sent as | Godot |
|---|---|---|---|
| Road colour, centre line, one-way, bridge | `road_color_for_way`, lanes/oneway, `is_bridge` | fields on each chunk road | `map_chunk._draw_roads` + `chunk_detail.road_markings` |
| Bridge guardrails | road bridges, union with shapely once (outer side edges only) | chunk `guardrails` (segment's midpoint chunk) | z 5 |
| Landuse, traffic islands | `sceneries` (kind colours, green kinds seasonal) | chunk `landuse` / `traffic_islands`, **clipped to each chunk square** | z −1 / z 6 |
| Parking spaces, curbs | `parking_spaces`, `curbs` | chunk lists (first point's chunk) | z 5 / z 8 |
| Crossings, speed bumps, stop/yield signs | snapped OSM points with angles | chunk lists | z 8 |
| Speed cameras | `speed_cameras` (id = index); the flash from `taxi_mgr.speed_camera_flash_*` | chunk `speed_cameras`; state `speed_camera_flash` | z 8 |
| Bus stops | bay/shelter/label from the nearest road (Pygame's geometry), once | chunk `bus_stops` | z 5 |
| Labels | places, named waters/areas/buildings, road names, by Pygame's priority | chunk `labels` (candidates) | `labels.gd`, decluttered per view |
| Buildings | roof colour (`_building_colors_from_name` / texture pick), gabled, height, entrances | chunk `building_styles` (parallel to `buildings`) | z 7, top-down |
| Open-roof canopies | `building=roof` etc. (`_is_open_roof`) | chunk `canopies` (no longer in `buildings`) | posts z 7, roof z 11 |
| Rail bridges | `railways[].is_bridge`; decks: union with shapely once | chunk `rail_bridges`, `rail_decks` | z 11, trains z 12 |
| Underground | `level_ways` (levels), `car.map_level` (the simulation moves it) | chunk `level_roads`; `player.map_level` | z 9 |
| Tire tracks | per tick, with `main()`'s own functions (ground kind, skid, wetness, front lockup, season) | state `tire_mark` | trail kept by the client, ≤ 4000 points |
| Headlights under a higher road | the taxi's `current_way` layer and bridge flag | state `road.layer`, `road.bridge` | `MapLayer.covered` over the chunks' raised roads |

**Ownership.**
- Points belong to the chunk containing them; polylines to their first
  point's chunk; guardrail segments to their midpoint's chunk.
- Area polygons are cut along the chunk grid, so each piece belongs to
  exactly one chunk. A forest relation can span kilometres, more than the
  loaded chunks around the player.
- Everything is computed once at startup (`static_world.py`). The Oulu
  chunk index builds in 1.5 s (was ~0.3 s), and server init is ~6.6 s in
  total.
- Chunks grew from 41.8 to 51.0 KiB on average (max 267 → 392 KiB).

**Batching and memory:**
- Each kind is one canvas item per chunk, drawn with one call per style:
  - multilines for curbs, stripes, rails, sleepers, centre lines,
    chevrons and guardrails
  - polygons only where they're areas
- The first build held the chunk data as parsed JSON. Every point became
  an Array of two Variants, and the client's static memory reached
  105 MiB. Polylines and polygons are now converted once, at load, to
  `PackedVector2Array`s in layer coordinates. That's back to ~79.5 MiB
  (godot-15: 78.7), with all of the above loaded.
- **Chunk load:** 7.5 ms per chunk (4.9 with godot-15's client on the same
  data), and ~13 ms per chunk to draw the first time. A row of chunks
  entering at once would have taken one long frame, so new chunks are now
  added one per frame. 49 at startup take ~0.3 s; a boundary crossing is
  spread over its frames. Unloading takes 0.4 ms for all 49.

**Building detail (top-down, no facades).** Each building gets:
- its roof colour, as Pygame picks it
- a shadow offset by its height
- for gabled roofs, the footprint split along its longest edge into a
  lighter and a darker facet with a ridge line (Pygame's
  `_draw_gabled_roof`, seen from straight above)
- door marks at its OSM entrances

Pygame's slanted facades and their windows are not drawn, by design. **Lit
windows** therefore stay missing: there is no top-down surface where
Pygame's facade windows would be correct.

**Canopies:** the shadow and corner posts are drawn under the vehicles,
and the translucent roof (alpha 185/255) with its edge above them. The
fuel pumps under St1 Limingantie are visible now (godot-12's deferred
item).

**Snow readability:** the trip/odometer text has a dark 4 px outline,
readable on snow and grass. It needs no weather detection.

**Verified:**
- Python tests (1565):
  - landuse clipping: the pieces cover the original, with no overlap
  - every new list in its chunk; canopies are not buildings
  - a "Sininen" building gets a blue roof
  - road style for a two-way four-lane road, a one-way bridge and a path
  - guardrails only on the outer edges of two parallel carriageways
  - bus-stop shapes
  - a tire mark from a real tick; the flash index; the map level
- Godot unit tests (216):
  - layers per kind; packed data in layer coordinates
  - centre-line rules (8 m dashes; none under 6 px; solid; chevrons at
    40/80 m)
  - covered/not covered under a bridge
  - no street lights underground
  - the flash redraws once
  - label rules (priority over an overlap, one per name, the HUD band,
    the 0.35 px/m road gate, at most 35)
  - tire-track bounds (whole oldest trails go)
  - the snow outline
- Real Oulu server (scratch launcher; production config untouched):
  - **Daylight start area:** labels (buildings, streets, Postiaukio),
    crossings, parking bays, curbs, autumn landuse, roofs with door marks,
    railway sleepers, the outlined trip text.
  - **St1 Limingantie:** canopy with the pump visible under it, one-way
    chevrons.
  - **A rail bridge** over water: deck, guardrails, track; a road bridge
    beside it with guardrails.
  - **A speed camera** with its flash, and a stop sign.
  - **Underground:** level −3, dark view with the level's road and the
    taxi.
  - **A park:** the client drove off and dirt tracks were laid behind the
    taxi (both axles), broken where it crossed a paved path.
  - **23:00:** tint, street lights, beams, untinted labels.
  - One run logged a single "triangulation failed". It didn't reproduce;
    puddle outlines and the new bump/bus polygons are now validity-checked.
- `make godot-selftest`: 145 FPS, 0 render backsteps, taxi 0 px off
  centre, ~79.5 MiB.

**Deliberately left as they are:**
- **Landuse speckle texture** (partial): the fills are drawn, not the
  dots on vegetation.
- **Road layers:** Pygame outlines a vehicle under a higher road, and
  that outline isn't drawn (partial). Guardrails and the headlight cut
  are done.
- **Lit windows** (missing): no facades top-down.
- **Ground texture:** a flat ground with snow, not Pygame's textured
  grass.
- **Water:** no spring ice floes.
- **Trees:** no hit animation or wind lean.
- **Vomit puddles and footprints, splashes, rain and snow particles:**
  effects, not static world.
- **Fuel-price HUD:** still deferred. It needs the nearest station in the
  per-tick state.
- **Traffic lights:** phases still sent only within 600 m (godot-12).
- **NPC beams on bridges:** decided by layer > 0, because an NPC's way's
  bridge flag isn't sent.

**Remaining before navigation:** the static world is done. What's left
in the table is effects, HUD details, menus and debug tools, and the
navigation route itself.
