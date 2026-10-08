# Pygame → Godot rendering parity (audit, 0.16.0g-alpha)

# Parity audit 2 (2026-10-06)

**Repository state:** branch `release/v0.16.0g-alpha`, audited at `4407fd7`.

**Method:** traced each feature from the Pygame source through to the screen,
reading the current code:

Pygame (`main/__init__.py` loop, `render/*.py`, `audio.py`)
→ shared simulation (`simulation.py`, managers)
→ server (`server/__init__.py`)
→ protocol (`protocol.py` `build_state_message`, `map_chunks.py` chunks, command fields)
→ Godot (`godot/*.gd`)
→ what the player sees or hears.

The previous audit and the per-phase history are kept below as history. They
were not used as evidence here.

**Constraints the audit respects:**
- The 3D building layer is the intended Godot 1.x renderer, so it is not a
  gap.
- The camera, vehicle movement and the BIN map are out of scope.
- The server owns all game state.

**Aircraft:** the current Pygame code has no aircraft, aircraft movement,
schedules or airport demand. `world_places.py` only lists airports as places,
and `main()` logs them at city start. There is nothing to port, so aircraft
has no row.

## Executive summary

| Status | Count |
|---|---|
| COMPLETE | 96 |
| PARTIAL | 7 |
| DIFFERENT BY DESIGN | 6 |
| SERVER/PROTOCOL GAP | 11 |
| GODOT RENDERING GAP | 3 |
| GODOT UI GAP | 4 |
| AUDIO GAP | 3 |
| MISSING | 0 |
| PYGAME-ONLY / OBSOLETE | 11 |
| **rows** | **141** |

Incomplete rows by priority: 0 P0 (refuelling done in godot-final-01), 0 P1, 6 P2, 22 P3 (speech and stations in godot-final-07; label modes done; road rage in godot-final-05; weather presentation in godot-final-06; score, toggles and summary done in godot-final-02; taximeter and pump price in godot-final-03; navigation route in godot-final-04).

**What is left by type:**
- **Protocol gaps:** most remaining work is in the protocol. The simulation
  or Pygame's `main()` has the state, but the client never receives it:
  navigation route, live taximeter, road rage, speech, timetable, temperature.
- **Client-only gaps:** a smaller set needs no protocol change, because the
  data already reaches Godot:
  - rain and snow particles
  - the score
  - the career city summary
  - refuelling input (G)
  - limiter and assist toggles
- **Why no MISSING rows:** every gap has a specific cause, so the generic
  MISSING status is not used.

**The single most important gap was refuelling** (fixed in
[godot-final-01](#godot-final-01-refuelling)). The simulation supports it
(`PlayerCommand.refuel`, `simulation.py:275`), but `godot/main.gd` `send()`
always sends `"refuel": false` and binds no key. A Godot player cannot
refuel, and the tank runs dry.

## Feature matrix

Priority: P0 core gameplay, P1 major world/presentation, P2 secondary, P3
polish. Complete rows have no priority.

| Area | Feature | Pygame implementation | Godot implementation | Status | Exact gap | Data source/dependency | Performance risk | Priority |
| ---- | ------- | --------------------- | -------------------- | ------ | --------- | ---------------------- | ---------------- | -------- |
| World | Ground / grass | `render/scenery.py` `draw_grass_texture` (seasonal texture) | `map_layer.gd` flat ground, snow with `calendar.season` | PARTIAL | no grass texture, no seasonal grass palettes | `state.calendar.season` | LOW | P3 |
| World | Landuse fills | `draw_scenery` | `chunk_detail.gd` `draw_areas`, seasonal greens | PARTIAL | vegetation speckle texture | chunk `landuse` | LOW | P3 |
| World | Water, winter ice | `render/waters.py` `draw_waters` | `map_chunk.gd` water, ice by winter weight | PARTIAL | spring ice floes | chunk `waters`, `calendar.season` | LOW | P3 |
| World | Roads (surface, width, colour) | `render/roads.py` `draw_ways` | `map_chunk.gd` `_draw_roads` | COMPLETE | (paved path verges not drawn) | chunk `roads` | – | – |
| World | Road markings, one-way arrows | `draw_ways` | `map_chunk.gd` | COMPLETE | – | chunk `roads` | – | – |
| World | Bridges / road layers | `draw_ways` layer order; vehicle outlined under a higher road | z per layer (`map_chunk.gd`) | PARTIAL | a vehicle under a higher road is not outlined | `state.road.layer`, npc `layer` | LOW | P2 |
| World | Underground / covered levels | `draw_level_ways` | `map_layer.gd` `_draw_underground`, `player.map_level` | COMPLETE | – | chunk `level_roads` | – | – |
| World | Wet roads | `render/weather.py` `draw_wet_roads` | `map_chunk.gd` wet overlays | COMPLETE | – | `weather.wetness` | – | – |
| World | Puddles | `draw_puddles` | `map_chunk.gd` `_draw_puddles`; ambient ripples in `weather_layer.gd` while it falls (godot-final-06) | COMPLETE | – | `weather.wetness`, `weather_type` | – | – |
| World | Parking spaces | `draw_parking_spaces` | `chunk_detail.gd` `draw_parking` | COMPLETE | – | chunk `parking` | – | – |
| World | Railways (ballast, rails, sleepers) | `draw_railways` | `chunk_detail.gd` `draw_tracks` | COMPLETE | – | chunk `railways` | – | – |
| World | Rail bridges above vehicles | `draw_railways(only_bridges=True)` | `map_chunk.gd` z 11 | COMPLETE | – | chunk `rail_decks`, `rail_bridges` | – | – |
| World | Traffic islands | `draw_traffic_islands` | `chunk_detail.gd` `draw_areas` | COMPLETE | – | chunk `traffic_islands` | – | – |
| World | Trees (felled, seasonal) | `draw_trees` | `map_chunk.gd` `_draw_trees` | COMPLETE | – | chunk `trees`, `state.fallen_trees` | – | – |
| World | Scenery objects, knocked posts | `draw_scenery_objects` | `map_chunk.gd`, `map_layer.gd` `_draw_knocked_posts` | COMPLETE | – | chunk `scenery_objects`, `state.knocked_posts` | – | – |
| World | Bus stops | `draw_bus_stops` | `chunk_detail.gd` `draw_bus_stops` | COMPLETE | – | chunk `bus_stops` | – | – |
| World | Buildings: shapes, heights, pitched roofs | `render/buildings.py` `draw_buildings` (2.5D) | `buildings_3d.gd` 3D layer (gables closed, godot-23) | DIFFERENT BY DESIGN | – | chunk `buildings`, `building_styles` | – | – |
| World | Building windows and doors | `draw_buildings` facades | `buildings_3d.gd` `_windows`, `_doors` | COMPLETE | – | `building_styles` floors, category, entrances | – | – |
| World | Night windows | `draw_illuminated_windows` | `buildings_3d.gd` lit windows (godot-lights-01) | COMPLETE | – | `calendar.sun_altitude_deg` | – | – |
| World | Open-roof canopies | `draw_open_roof_overlays` | `chunk_detail.gd` `draw_canopies`, 3D projection | COMPLETE | – | chunk `canopies`, `canopy_heights` | – | – |
| World | Tyre tracks | `draw_tire_tracks` | `entity_layer.gd` `_lay_track` | COMPLETE | – | `state.tire_mark` | – | – |
| World | Roadworks | `draw_roadworks` | `map_chunk.gd` `_draw_points` | COMPLETE | – | chunk `roadworks` | – | – |
| World | Curbs | `draw_curbs` | `chunk_detail.gd` | COMPLETE | – | chunk `curbs` | – | – |
| World | Railings, walls, hedges | `draw_railings` | `chunk_detail.gd` | COMPLETE | – | chunk `railings` | – | – |
| World | Construction fences | `draw_construction_fences` | `map_chunk.gd` `_draw_fences` | COMPLETE | – | chunk `construction_fences` | – | – |
| World | Zebra crossings, speed bumps | `draw_crossings`, `draw_speed_bumps` | `chunk_detail.gd` `draw_road_features` | COMPLETE | – | chunk | – | – |
| World | Traffic lights (live phase) | `draw_traffic_lights` | `map_chunk.gd` `_draw_traffic_lights` | COMPLETE | – | chunk `traffic_lights`, `state.traffic_lights` (600 m) | – | – |
| World | Taxi stands | `draw_taxi_stops` | `map_chunk.gd` `_draw_points` | COMPLETE | – | chunk `taxi_stands` | – | – |
| World | Stop / yield signs | `draw_stop_signs`, `draw_yield_signs` | `chunk_detail.gd` `draw_signs` | COMPLETE | – | chunk `signs` | – | – |
| World | Speed cameras + flash | `draw_speed_cameras` | `chunk_detail.gd` `draw_signs` | COMPLETE | – | chunk `speed_cameras`, `state.speed_camera_flash` | – | – |
| World | Fuel stations (pumps, price boards) | `draw_fuel_station_signs`, pumps | `map_chunk.gd` `_draw_fuel_pumps`, `_draw_fuel_boards` | COMPLETE | – | chunk `fuel_stations` | – | – |
| World | Street lights, broken lamps | `draw_street_lights` | `map_chunk.gd` pools and heads | COMPLETE | – | chunk `street_lights`, `state.knocked_posts` | – | – |
| World | Place and street labels | `render/labels.py` `draw_labels` | `labels.gd` | COMPLETE | – | chunk labels | – | – |
| World | Vomit puddles and footprints | `draw_vomit_puddles` ×2, `draw_vomit_footprints` | – | SERVER/PROTOCOL GAP | `taxi_mgr.vomit_puddles`, `pedestrian_mgr.vomit_puddles` and `vomit_footprints` exist in the simulation but are not sent | `taxi.py:226`, `simulation.py:681` | LOW | P3 |
| Weather | Rain / slush / snow particles | `render/weather.py` `draw_rain` (fixed pool of 220) | `weather_layer.gd`: the same pool, real time, batched (godot-final-06) | COMPLETE | – | `weather.weather_type` | – | – |
| Weather | Splashes | `draw_splashes` (spawned in `main()` on puddle entry) | `weather_layer.gd` on Godot's own puddle spots, entry edge, cap 40 (godot-final-06) | COMPLETE | – | puddles, `player` | – | – |
| Weather | Lightning flash | `draw_lightning_flash` | `main.gd` Sky/Flash | COMPLETE | – | `weather.lightning_intensity` | – | – |
| Time | Day/night tint | `draw_day_night_overlay` | `daylight.gd` + `main.gd` CanvasModulate (godot-lights-01) | COMPLETE | – | `calendar.sun_altitude_deg` | – | – |
| Time | Seasons | grass, ice, trees by season | snow, ice, tree crowns (`calendar.season`) | COMPLETE | (details in the ground/landuse/water rows) | `calendar.season` | – | – |
| Vehicle | Taxi body, roof sign, size | `render/vehicles.py` `draw_car` | `entity_layer.gd` `_vehicle` | COMPLETE | – | `player.length_m`, `width_m` | – | – |
| Vehicle | Headlights, tail and brake lamps | `draw_car`, `draw_vehicle_lights` | `entity_layer.gd` | COMPLETE | – | `player.engine_on`, `braking` | – | – |
| Vehicle | Reversing lamp (taxi, NPCs) | `_draw_vehicle_lights(reversing=speed < −0.05)` | – | GODOT RENDERING GAP | white lamp between the tail lamps not drawn | `player.speed`, npc `speed` | LOW | P3 |
| Vehicle | Exhaust, crash smoke | `draw_taxi_exhaust`, `draw_taxi_smoke` | `entity_layer.gd` `_smoke` | COMPLETE | – | `engine_on`, `taxi.taxi_smoke_timer` | – | – |
| Vehicle | Night headlight beams | `draw_headlight_beams` | `night_layer.gd`, additive gradient beams (godot-lights-01) | COMPLETE | – | npcs, `player` | – | – |
| Vehicle | Rage shout bubble ("PRKL!") | `draw_car(shout_timer, shout_text)` | `entity_layer.gd` `shout_for` + `_bubble` from `state.road_rage` (godot-final-05) | COMPLETE | – | server `_road_rage` | – | – |
| Vehicle | Water / in-water timer | `draw_hud(water_time_remaining)` | `instruments.gd` | COMPLETE | – | `water_elapsed` | – | – |
| Vehicle | Passenger nausea bubble | `draw_passenger_nausea_bubble` | `entity_layer.gd` | COMPLETE | – | `nausea_warning_timer` | – | – |
| NPC | Vehicles by type, colour | `draw_npc_cars` sprites | `entity_layer.gd` car, van, bus, truck, two-wheeler | PARTIAL | two-wheelers are body + rider, not Pygame's sprites | npc `vehicle_type` | LOW | P3 |
| NPC | Turn signals | `draw_npc_cars` | `entity_layer.gd` | COMPLETE | – | npc `turn_signal`, `turn_signal_elapsed` | – | – |
| NPC | Crashes: fallen, smoke | `draw_npc_cars` | `entity_layer.gd` | COMPLETE | – | npc `fallen`, `crashed_timer` | – | – |
| NPC | Parked vehicles, lamps off | `draw_npc_cars` | `entity_layer.gd` | COMPLETE | – | npc `state` | – | – |
| NPC | Police, on-foot, distant culling | `draw_npc_cars` skips `is_police`, `is_on_foot`, `lod_level ≥ 2` | `entity_layer.gd` `drawn_as_vehicle` (same rule) | COMPLETE | – | npc fields | – | – |
| Pedestrian | Body appearance (clothing, hair, legs) | `render/pedestrians.py` `appearance` | defaults from `color` (`render_style.gd`) | SERVER/PROTOCOL GAP | `PedestrianAppearance` not sent | `pedestrian.py:416` | LOW | P3 |
| Pedestrian | Direction, walk animation | `draw_pedestrians` | `entity_layer.gd` `_pedestrian` | COMPLETE | – | `heading`, `animation_state`, `animation_time` | – | – |
| Pedestrian | Fallen, indoors, cursing | `draw_pedestrians` | `entity_layer.gd` | COMPLETE | – | `state`, `curse_timer`, `curse_text` | – | – |
| Pedestrian | Walking player | `draw_pedestrians(is_player)` | standing figure | SERVER/PROTOCOL GAP | `player_pedestrian` has only x, y, heading: no walk animation | `protocol.py:363` | LOW | P2 |
| Pedestrian | Waiting / walking customer tag | `draw_taxi_target` + passenger | `entity_layer.gd` `[P]` / `[TO TAXI]` | COMPLETE | – | `current_passenger.ped`, `is_walking_to_car` | – | – |
| Pedestrian | Booked passenger arrow | `draw_booked_passenger_arrow` | `entity_layer.gd` `_booked_arrow` | COMPLETE | – | `state.meet.arrow` | – | – |
| Pedestrian | People under roofs (outline) | `draw_pedestrians_under_roofs(roof_cover)` | – | GODOT RENDERING GAP | canopy polygons now reach Godot; the outline pass is not drawn | chunk `canopies` | LOW | P3 |
| Pedestrian | Night reflectors | `draw_pedestrian_reflectors` | `entity_layer.gd` `_draw_reflectors` | COMPLETE | – | pedestrians, street lights | – | – |
| Trains | Cars, length, direction, colours, restaurant stripe | `draw_trains` | `entity_layer.gd` `_train_car`, `render_style.gd` profiles | COMPLETE | – | `trains[].cars` | – | – |
| Trains | Draw order above bridges / canopies | `draw_trains` after bridges | `entity_layer.gd` trains z 12 | COMPLETE | – | – | – | – |
| Trains | Trains under station roofs (outline) | `draw_trains(roof_cover)` | – | GODOT RENDERING GAP | outline under canopies not drawn | chunk `canopies` | LOW | P3 |
| Trains | Station / platform behaviour, timetable | `trains.py`, `train_timetable.py` | server-run, trains move and stop | COMPLETE | – | `trains[].state` | – | – |
| Trains | Next-train panel (J) | `draw_next_train` | `hud.gd` board from `state.railway`, J local (godot-final-07) | COMPLETE | – | `RailwayManager.next_arrivals/departures` | – | – |
| Trains | Clicked car's passengers | `draw_train_car_popup` | – | SERVER/PROTOCOL GAP | `passengers.in_car` not sent; no click picking | `train_passengers.py` | LOW | P3 |
| Taxi | Pickup / drop-off zone, marker, address tag | `render/navigation.py` `draw_taxi_target` | `entity_layer.gd` `_target` | COMPLETE | – | `current_passenger.pickup/dropoff` | – | – |
| Taxi | Off-screen target arrow + distance | `draw_taxi_target` | `nav_overlay.gd` | COMPLETE | – | `EntityLayer.current_target` | – | – |
| Taxi | Customer name / address (mission bar) | `draw_hud` mission bar | `hud.gd` fare line | COMPLETE | – | `taxi.state`, `current_passenger` | – | – |
| Taxi | Live taximeter, fare distance, happiness, elapsed time | `draw_hud` mission bar (`live_fare_cents`, `fare_distance_m`, `passenger_happiness`, `elapsed_time`) | `hud.gd` `fare_details` on the drop-off line, from `state.taxi` (godot-final-03) | COMPLETE | – | `taxi.py` TaxiManager | – | – |
| Taxi | Score | `draw_hud` score box | `hud.gd` top row beside the money (godot-final-02) | COMPLETE | – | `state.taxi.total_score` | – | – |
| Taxi | Offers and pre-bookings | `draw_phone_offers` (pauses) | `phone.gd` (game keeps running) | DIFFERENT BY DESIGN | – | `state.phone` | – | – |
| Taxi | Pre-booking surcharge | phone booking row | `phone.gd` "Pre-booking fee" | COMPLETE | – | `phone[].surcharge_cents` | – | – |
| Taxi | Meet-and-greet panel | `render/menus.py` `draw_meet_panel` | `hud.gd` `_meet` | COMPLETE | – | `state.meet.lines` | – | – |
| Taxi | Customer walks to taxi / stand; boarding | `taxi.py`, `rail_bookings.py`, `station_passengers.py` | server-run, `WALKING` shown | COMPLETE | – | `taxi.state`, `boarded` | – | – |
| Taxi | Fare, payment, starting fare | `fare.py`, `taxi.py` | server-run; balance and notices shown | COMPLETE | – | `taxi.balance_cents`, `notification_msg` | – | – |
| Taxi | Career city summary | `draw_city_summary` | `hud.gd` full-screen summary, latched; driving commands stop (godot-final-02) | COMPLETE | – | `state.should_stop`, `city_summary` | – | – |
| Taxi | Game start overlay (city sign, 24 h forecast) | `draw_game_start_overlay` | – | SERVER/PROTOCOL GAP | city name and forecast not sent; forecast is `main()`-only | `main/__init__.py` `weather_history` | LOW | P3 |
| Taxi | Start hints | `draw_game_start_hint` | `hud.gd` hint line | PARTIAL | one control line, not Pygame's timed get-in/engine hints | `on_foot`, `engine_on` | LOW | P3 |
| Navigation | Route line (N) | `draw_navigation_route`; `traffic_mgr.plan_route` in `main()` (`main/__init__.py:2714`) | server `navigation_route.py` → `state.navigation.points`; `entity_layer.gd` `_route`, N in `nav_overlay.gd` (godot-final-04) | COMPLETE | – | `traffic_world.py` `plan_route_steps`, `level_routes` | – | – |
| Navigation | Compass (C) | `draw_compass` | `nav_overlay.gd` | COMPLETE | – | current target | – | – |
| HUD | Speed | `_draw_analog_speedometer` + assist indicators | `hud.gd` text km/h | GODOT UI GAP | no analog dial or its lane/limiter/nav indicators | `player.speed` | LOW | P3 |
| HUD | Game time, date, real-time marker | `draw_hud` clock | `hud.gd` | COMPLETE | – | `calendar.date`, `time_scale` | – | – |
| HUD | Temperature | `draw_hud(temperature_c)` | – | SERVER/PROTOCOL GAP | server has no temperature (fixed 15 °C into the simulation) | `main/__init__.py:1568` | LOW | P3 |
| HUD | Money | `draw_hud` balance | `hud.gd` | COMPLETE | – | `taxi.balance_cents` | – | – |
| HUD | Notifications, speed-camera notice | `draw_hud` | `hud.gd` | COMPLETE | – | `notification_msg`, `speed_camera_notice` | – | – |
| HUD | Speed-limit sign, road name | `draw_hud` | `instruments.gd`, F3 readout | COMPLETE | – | `state.road` | – | – |
| HUD | Fuel gauge, reserve, economy | `_draw_fuel_meter` | `instruments.gd` `_draw_fuel` | COMPLETE | – | `player.fuel_l` and economy fields | – | – |
| HUD | Fuel price at a station (gauge) | `_draw_fuel_meter(fuel_station_price_cents)` | `instruments.gd` "G: REFUEL x.xx €/L" from `taxi.fuel_station_price_cents` (godot-final-03) | COMPLETE | – | `nearest_fuel_station`, `fuel_station_price_cents` | – | – |
| HUD | Trip, odometer | `draw_hud` meters | `instruments.gd` | COMPLETE | – | `trip_m`, `odometer_m` | – | – |
| HUD | Rage meter | `draw_hud` faces, %, bar | `instruments.gd` `_draw_rage` | COMPLETE | – | `rage_power` | – | – |
| HUD | Water timer | `draw_hud` | `instruments.gd` | COMPLETE | – | `water_elapsed` | – | – |
| HUD | Speech subtitles | `draw_hud(comment_text)` | `hud.gd` one subtitle from the server's `speech` events (godot-final-07) | COMPLETE | – | `speech` events | – | – |
| HUD | Speed limiter / red-light assist toggles (V, B) | key toggles + HUD status | `main.gd` V/B session toggles in every command, ON/OFF in the hint (godot-final-02) | COMPLETE | – | `PlayerCommand` fields | – | – |
| HUD | Lane assist (K) | `car.lane_assist_enabled` toggle | – | SERVER/PROTOCOL GAP | not a command field | `physics.py:240` | LOW | P2 |
| HUD | FPS counter | normal HUD | F3 readout | DIFFERENT BY DESIGN | – | – | – | – |
| UI | Pause / settings (language, volumes, subtitles) | `render/menus.py` `draw_pause_menu`, `draw_settings_menu` | – | GODOT UI GAP | no menus; settings are client-side | client settings | LOW | P2 |
| UI | Tutorial screen | `draw_tutorial_screen` | – | GODOT UI GAP | – | – | LOW | P3 |
| UI | Mode and city selection, loading | `draw_mode_selection_menu`, `draw_city_selection_menu` | server CLI chooses | DIFFERENT BY DESIGN | – | server `--preset` | – | – |
| UI | Resident popup (click a person) | `draw_resident_popup` | – | SERVER/PROTOCOL GAP | resident details not sent; no click picking | `residents.py` | LOW | P3 |
| UI | Follow another entity + back button | `camera_focus.py`, `draw_camera_back_button` | – | GODOT UI GAP | ids are in the state; no picking or follow mode | npc/pedestrian ids | LOW | P3 |
| UI | Label modes (L) | `label_mode` 0–2 | `labels.gd` L cycles off (start) → street names → all; hint shows it | COMPLETE | – | – | – | – |
| UI | Trip reset (T) | `reset_trip(car)` | – | SERVER/PROTOCOL GAP | not a command; `trip_m` is the server's | `PlayerCommand` | LOW | P3 |
| Gameplay | Refuel at a station (G) | `refuel_pending` → `PlayerCommand.refuel` | `main.gd` G → `command_for(refuel)`; the server applies each press once (godot-final-01) | COMPLETE | – | `simulation.py:275` | – | – |
| Gameplay | Road rage (SPACE): rage cost, horn, shout, nearest NPC provoked | `main/__init__.py` SPACE (now only queues the press) | shared `advance_simulation` (`PlayerCommand.road_rage`), server press count, Godot SPACE (godot-final-05) | COMPLETE | – | `npc.py` `trigger_road_rage` | – | – |
| Gameplay | Manual respawn (R) | `main()` respawn | – | SERVER/PROTOCOL GAP | not a command (the in-water respawn is in the simulation) | `simulation.py:405` | LOW | P2 |
| Gameplay | Historical weather (FMI observations) | `weather_history.py` in `main()` | server weather | SERVER/PROTOCOL GAP | the server does not use `WeatherHistory` | `main/__init__.py:1559` | LOW | P2 |
| Gameplay | Weather transitions, wetness, drying | `weather.py` | server-run | COMPLETE | – | `weather` | – | – |
| Gameplay | Accelerated time, 1:1 during a fare | `GameCalendar`, `time_scale` | server-run, `*` marker | COMPLETE | – | `calendar.time_scale` | – | – |
| Gameplay | Fuel use, out of fuel | `fuel.py`, `simulation.py:267` | server-run | COMPLETE | – | `player.fuel_l` | – | – |
| Gameplay | Speed-camera fines, collisions, curbs, water | `simulation.py` | server-run | COMPLETE | – | state + events | – | – |
| Gameplay | Nausea, vomiting | `taxi.py` | server-run; bubble shown | COMPLETE | (visuals: vomit row) | `current_passenger` | – | – |
| Gameplay | Rail bookings, meet-and-greet lifecycle | `rail_bookings.py` | server-run, phone + meet panel | COMPLETE | – | `phone`, `meet` | – | – |
| Camera | World → screen, north up, zoom | `px_per_m`, ± keys | `MapMath`, Camera2D zoom | COMPLETE | – | – | – | – |
| Camera | Camera target | `camx`/`camy` look-ahead | interpolated player position | DIFFERENT BY DESIGN | – | (godot-08/09 jitter fix) | – | – |
| Camera | Interpolation | `interpolate_state` (`--connect`) | `state_buffer.gd` | DIFFERENT BY DESIGN | – | – | – | – |
| Camera | Off-screen culling | per draw call | entity cull + chunks | COMPLETE | – | – | – | – |
| Audio | Engine | `audio.update_engine`: idle loop + 3 accelerate layers by throttle | `main.gd` one `engine` loop, pitch by speed | PARTIAL | no throttle layers; the server does not forward loops | `player.speed`, `engine_on` | LOW | P3 |
| Audio | Simulation one-shots | `simulation.py`: collisions, brake, water splash, curb/speed bump, doors, engine start, fuel empty, refuel, meter start, payment, speed camera, meet-and-greet, penalty, new offer, vomit, curse, tree fall | `audio_manager.gd` `handle_event` (server `EventAudio`) | COMPLETE | – | `events` `sound` | – | – |
| Audio | City day / night ambience | `audio.update_ambience` | `main.gd` `city_day`/`city_night` | COMPLETE | – | `calendar.darkness` | – | – |
| Audio | Rain loop, heavy rain | `update_ambience` `rain`, `rain_heavy` | `main.gd` `weather_loops`: rain/slush 0.6, thunderstorm 0.7 (godot-final-06) | COMPLETE | – | `weather_type`, `is_thunderstorm` | – | – |
| Audio | Wind, strong wind, wet tyres | `update_ambience` | `main.gd` `weather_loops` from `weather.wind_vector_mps`, wetness, speed (godot-final-06) | COMPLETE | – | `state.weather` | – | – |
| Audio | Thunder | `weather.thunder` | server event | COMPLETE | – | `events` | – | – |
| Audio | Damaged-taxi steam loop | `set_loop("steam", vehicle.damaged_steam)` | – | AUDIO GAP | loop not derived from `taxi_smoke_timer` | `taxi.taxi_smoke_timer` | LOW | P3 |
| Audio | Footsteps on foot | `update_footsteps` | – | AUDIO GAP | loop not derived (on foot + player movement) | `on_foot`, player positions | LOW | P3 |
| Audio | Train running, brakes, doors, horn | `_play_rail_sounds` in `main()` | `main.gd` `train_running` loop; `train_arrived`/`train_departed` events | COMPLETE | – | `trains`, events | – | – |
| Audio | Station ambience, crowd, luggage | `_play_rail_sounds` | `main.gd` `station_ambience`: the loudest station, two placed loops (godot-final-07) | COMPLETE | – | `state.railway.stations` | – | – |
| Audio | Station announcements | `station_announcer.py` in `main()` | server `StationAnnouncer.event` → `station_announcement`; `audio_manager.gd` one loudspeaker, FIFO (godot-final-07) | COMPLETE | – | manifest clips | – | – |
| Audio | Driver / passenger speech and chatter | `audio.play_driver_line`, `play_passenger_line`, `update_passenger_speech` | shared `speech.py`; `EventAudio` → `speech` events; `audio_manager.gd` one voice (godot-final-07) | COMPLETE | – | chatter catalogs + WAVs | – | – |
| Audio | Phone UI: reject, new booking, missed booking, menu | `main()` `ui.*` groups | `phone.gd` only `ui.phone_open`; `ui.accept` from the server | AUDIO GAP | the other UI cues are not played | `phone` statuses | LOW | P3 |
| Obsolete | BIN map loading | `main()` city bin | – | PYGAME-ONLY / OBSOLETE | superseded by OSM chunks | – | – | – |
| Obsolete | Debug overlays: profiler, g-force, NPC panels, spatial grid, intersections, feature inspector, activity | `render/hud.py` debug panels | F3 readout | PYGAME-ONLY / OBSOLETE | developer UI | – | – | – |
| Obsolete | Debug HUD line (lat/lon, ways, zoom) | `draw_hud(show_debug_hud)` | F3 readout | PYGAME-ONLY / OBSOLETE | developer UI | – | – | – |
| Obsolete | Debug keys: PageUp/Down time skip, HOME respawn, F-keys | `main()` | – | PYGAME-ONLY / OBSOLETE | developer tools | – | – | – |
| Obsolete | Taxi door opening animation | `draw_car(door_open_progress)` | – | PYGAME-ONLY / OBSOLETE | `main()` never passes a progress: it always draws closed | – | – | – |
| Obsolete | Taxi turn signals | `draw_car` reads `car.turn_signal` | – | PYGAME-ONLY / OBSOLETE | the player `Car` has none; Pygame's taxi never blinks | – | – | – |
| Obsolete | NPC brake lights | – | – | PYGAME-ONLY / OBSOLETE | Pygame draws none | – | – | – |
| Obsolete | `draw_cyclists` | `render/pedestrians.py` | – | PYGAME-ONLY / OBSOLETE | never called; cyclists are pedestrians | – | – | – |
| Obsolete | 2.5D building renderer | `render/buildings.py` | `--buildings 2d` (comparison only) | PYGAME-ONLY / OBSOLETE | replaced by the 3D layer | – | – | – |
| Obsolete | Draggable HUD layout (U reset) | `hud_layout` | – | PYGAME-ONLY / OBSOLETE | Godot anchors its HUD | – | – | – |
| Obsolete | Police siren, tyre squeal | `audio.update_police_siren` (never called); squeal disabled (`simulation.py:417`) | – | PYGAME-ONLY / OBSOLETE | inactive in Pygame too | – | – | – |

## Server/protocol gaps

Only missing state or data:

1. **Navigation route.** `plan_route` (`traffic_world.py:439`) runs only in
   Pygame's `main()`. The server would compute a route for the current
   target and send it, for example as `state.navigation.points`, decimated.
2. **Live taximeter.** `TaxiManager` has `live_fare_cents`,
   `fare_distance_m`, `passenger_happiness` and `elapsed_time`;
   `state.taxi` sends none of them.
3. **Road rage.** The rage cost, horn, shout text/timer and
   `npc_manager.trigger_road_rage` are all in `main()`. They need a command
   field and the shout state.
4. **Speech.** Driver/passenger lines and chatter are chosen in the
   simulation, but `EventAudio` drops them. They need `speech` events with
   text, for audio and subtitles.
5. **Timetable / next trains.** No query or state reaches the client.
6. **Station announcements.** `station_announcer.py` is `main()`-only.
7. **Historical weather and temperature.** `WeatherHistory` is
   `main()`-only, and the server gives the simulation a fixed 15 °C.
8. **Fuel station at the taxi** (price in the gauge).
9. **Commands:** lane assist (K), manual respawn (R) and trip reset (T).
   The limiter and red-light assist (V, B) already exist as fields.
10. **Walking player animation:** `player_pedestrian` has no animation
    state.
11. **Pedestrian appearance:** `PedestrianAppearance` is not sent.
12. **Vomit puddles and footprints.**
13. **Clicked entity details:** resident popup and train car passengers.
14. **Game start overlay:** city name and forecast.

## Godot rendering gaps

Only presentation; the data is already in Godot:
- **Rain / snow particles:** `weather_type` is sent; intensity would need
  protocol data. Performance risk MEDIUM: full-screen particles on a
  fill-bound frame (godot-18).
- **Splashes:** puddles and the taxi are known. MEDIUM (particles).
- **Reversing lamp:** from the sign of `speed`. LOW.
- **People and trains under canopies, outlined:** canopy polygons are in the
  chunks. LOW.
- **Partial rows:**
  - a vehicle outlined under a higher road (LOW)
  - grass texture and seasonal palettes (LOW)
  - landuse speckle (LOW)
  - spring ice floes (LOW)
  - puddle ripples (LOW, animated)
  - two-wheeler sprites (LOW)

## Godot UI gaps

The state or command field exists, but the UI is missing:
- **Pause / settings menu:** language, volumes, subtitles.
- **Analog speedometer** with indicators.
- **Tutorial screen.**
- **Label modes.**
- **Follow-entity camera and back button.** This is planning only; the
  camera is not to be changed.

## Audio gaps

| Feature | Godot equivalent | Silent? | Asset exists | Playback logic | Missing part |
|---|---|---|---|---|---|
| Wind, strong wind | none | silent | `weather.wind` | none | logic + `wind_vector_mps` in the protocol |
| Wet tyres | none | silent | `weather.wet_road` | none | logic (wetness, speed) |
| Damaged steam | none | silent | `vehicle.damaged_steam` | none | logic (`taxi_smoke_timer`) |
| Footsteps | none | silent | `pedestrian.footsteps` | none | logic (on foot, moving) |
| Station ambience, crowd, luggage | none | silent | `station.ambience` | none | logic (near a station) |
| Phone reject / new booking / missed booking / menu | `ui.phone_open` only | silent | `ui.reject`, `ui.booking_new`, `ui.booking_missed`, `ui.menu` | none | logic in `phone.gd` |
| Engine throttle layers | one pitched loop | partial | `vehicle.engine_accelerate` (3), `engine_idle` | partial | layering by throttle |
| Heavy rain | rain loop | partial | `weather.rain` variants | partial | variant by intensity |
| Speech / chatter, announcements | none | silent | `driver.chatter`, `passenger.chatter`, announcements | none | **server/protocol** (above) |

Assets exist for every gap, so all of them are implementation work.
Replacing assets is not a parity issue.

## Gameplay gaps

Behaviour differs from Pygame, independent of drawing:
- **Road rage absent:** P1. No horn, shout, rage spend or NPC reaction.
- **No navigation route:** P1.
- **Limiter always on, red-light assist always off, lane assist
  unavailable:** P2.
- **No manual respawn or trip reset:** P2 / P3.
- **Weather not historical:** P2. The server does not use FMI
  observations or temperature.
- **No pause:** design. The phone does not pause the game, and there is no
  pause menu yet.

## Intentional differences

- **3D building layer:** smooth, aligned facades without 2D tricks; the
  Godot 1.x architecture (godot-21 to godot-23).
- **Phone doesn't pause:** the game runs on a shared server clock that one
  client can't stop.
- **Camera follows the interpolated player, no look-ahead:** the godot-08/09
  stability fix. It must not be changed.
- **Interpolation buffer:** the client renders between server states.
- **City and mode chosen by the server CLI:** the server owns the world. A
  client menu can come later as a server request.
- **FPS in the F3 readout,** not the normal HUD.

## Pygame-only / obsolete

Not to be ported:
- the BIN map loading
- Pygame's debug overlays, debug HUD line and debug keys
- the never-animated door
- taxi turn signals and NPC brake lights, which don't exist in Pygame
- `draw_cyclists`, which is never called
- the 2.5D building renderer
- the draggable HUD layout
- the police siren and tyre squeal, both inactive

## Prioritized gaps

- **P0:** none (refuel done in godot-final-01).
- **P1:**
  - navigation route
  - live taximeter, fare distance and happiness
  - road rage (horn, shout, NPC)
  - career city summary
  - rain and snow particles
- **P2:**
  - score
  - speech + subtitles
  - station announcements
  - next-train panel
  - limiter / assist toggles
  - lane assist
  - manual respawn
  - historical weather
  - fuel price in the gauge
  - walking-player animation
  - pause/settings menu
  - vehicle outline under bridges
- **P3:** every other incomplete row.

## Recommended next phases

1. **Core controls and economy.**
   - **Features:** refuel (G, done in godot-final-01); speed limiter and red-light assist toggles
     with status; score in the HUD; the career city summary.
   - **Why together:** client-only work on fields that already exist, plus
     one key binding each.
   - **Dependencies:** none.
   - **Result:** the player can refuel, see the score and finish a career
     city.
   - **Performance risk:** LOW.
2. **Taxi information.**
   - **Features:** live taximeter, fare distance, happiness and elapsed time
     in `state.taxi`, shown in the mission bar; fuel station price in the
     gauge.
   - **Why together:** one protocol extension of `state.taxi`, one HUD
     change.
   - **Dependencies:** a protocol field addition.
   - **Result:** the fare reads as in Pygame.
   - **Performance risk:** LOW.
3. **Navigation route.**
   - **Features:** the server computes the route (`plan_route`) when the
     target changes and sends decimated points; Godot draws the line (N
     toggles).
   - **Why together:** it is one feature end to end.
   - **Dependencies:** routing cost on the server tick (route on change,
     not per tick).
   - **Result:** turn-by-turn route line.
   - **Performance risk:** MEDIUM (server routing; the line itself is
     cheap).
4. **Road rage.**
   - **Features:** a `road_rage` command; the server spends rage, provokes
     the NPC and sends shout state and a horn event; Godot shows the bubble.
   - **Why together:** the mechanic, its audio and its visual are one loop.
   - **Dependencies:** move the `main()` logic into the simulation.
   - **Result:** SPACE works as in Pygame.
   - **Performance risk:** LOW.
5. **Weather presentation.**
   - **Features:** rain/snow particles (intensity in the protocol), splashes,
     puddle ripples; wind and wet-tyre audio (wind vector in the protocol).
   - **Why together:** they share the weather state and the frame budget.
   - **Dependencies:** a protocol weather extension.
   - **Result:** visible precipitation.
   - **Performance risk:** MEDIUM. The frame is fill-bound, so particles
     must be batched (one draw).
6. **Speech and stations.**
   - **Features:** speech events with text (audio + subtitles); station
     announcements and ambience; next-train panel.
   - **Why together:** all are server-side `main()` logic moved into the
     simulation, plus client playback.
   - **Dependencies:** `EventAudio` speech events; timetable state.
   - **Result:** talking passengers, announced trains.
   - **Performance risk:** LOW.
7. **Settings and polish.**
   - **Features:** pause/settings menu; lane assist, respawn and trip-reset
     commands; walking-player animation; appearance; reversing lamp;
     outlines under canopies and bridges; vomit; steam, footsteps and phone
     sounds; engine layers.
   - **Why together:** small independent items.
   - **Dependencies:** small protocol additions.
   - **Result:** Pygame's remaining details.
   - **Performance risk:** LOW.
8. **Historical weather** (server).
   - **Features:** run `WeatherHistory` on the server; send temperature;
     the start forecast overlay.
   - **Why together:** they share the same observations.
   - **Dependencies:** network fetch and cache on the server.
   - **Result:** real Oulu weather and temperature.
   - **Performance risk:** LOW (I/O off the tick thread).

## godot-final-01: refuelling

**Rules (unchanged; Pygame's shared simulation rule, `simulation.py` `if
command.refuel`).** The pump must be within 8 m (`FUEL_STATION_RANGE_M`), with
the driver in the taxi, stopped (|speed| ≤ 0.5 m/s), and the tank not full.
- **Instant fill:** fills up to `fuel_capacity_l`, or as much as the balance
  buys.
- **Price:** set per station by `fuel_station_price_cents`, 1.50–3.00 €/l.
- **Cost:** rounded up to a cent, and never overdraws the balance.
- **Feedback:** the `taxi.refuel` sound, and a 4 s notice with the litres
  and cost, or the reason nothing was bought: no pump in range, enter the
  taxi, stop the taxi, tank full, no money.

**Godot.**
- **Key:** G sets a press that the next command carries once
  (`main.gd` `command_for`).
- **Feedback:** the notice, sound, gauge and balance already came from the
  state. The driving hint names G.

**Server fix.** `refuel` is now edge-triggered like `interact`
(`_pending_refuels`). The server replays its latest command every tick, so
before the fix a press was either lost when the next command arrived in the
same tick, or applied again every tick.

**Rule fix.** A top-up under 0.05 l now counts as a full tank
(`FULL_TANK_TOLERANCE_L`). Idling after a fill-up had made a second press
buy "0.0 l" for a cent. The fix is in the shared simulation, so Pygame
gets it too.

**Deferred.** Pygame's "G: REFUEL" and price inside the fuel gauge at a
station belong to the separate "fuel price at a station" row (protocol gap,
P2).

**Tests.**
- **Server:** `test_a_refuel_press_buys_fuel_once`. One press followed by
  another command in the same tick buys exactly once: fuel, cost, the sound
  event, and the gauge and balance values in the state. It also covers a full
  tank after idling, an empty balance, and out of range. It fails without the
  fix.
- **Godot:** `command_for` carries the press, and the hint names G.
- **Existing:** `tests/test_fuel.py` purchase rules.

**Scripted check against the real Oulu server.** The commands were the same
JSON that Godot sends, at a real Oulu pump (2.44 €/l):
- 20 m away: "drive closer"
- moving: "stop the taxi"
- nearly empty: 58.0 l for 141.53 €, with the sound
- full: "tank full"
- 5 € left: 2.0 l for 5.00 €
- no money: "not enough money"
- driving away: normal consumption

## godot-final-02: core controls and economy

Client-only: no Python, protocol or server change.

- **V / B:** session toggles in `main.gd` (`speed_limiter`, default on;
  `red_light_assist`, default off). Non-echo key presses flip them, and
  `command_for()` reports both in every command, so the server applies its
  unchanged rules. F and G stay one-shot. Losing window focus clears held
  keys but keeps the toggles. The driving hint shows `V limiter ON/OFF · B
  red-light assist ON/OFF`.
- **Score:** `state.taxi.total_score`, read from each state, shown in the
  top row after the money. Negative values show as they are; a missing
  score shows `–`.
- **City summary:** the first state with `should_stop` latches a
  full-screen panel in `hud.gd` with Pygame's `draw_city_summary` lines:
  title, city, score, fares, then either the next city or "Career complete"
  with the total career score. It hides the rest of the UI and stops all
  driving commands. It stays when states stop arriving.
  - **Malformed summaries:** `city_summary` that is absent or malformed
    shows "This city is complete." rather than made-up values.
  - **No Enter hint:** Pygame's "Enter to continue" is left out, because
    the server has no continue request.

**Contract finding (not changed, server-side).** `should_stop` is
per tick and stays true while `total_score ≥ CAREER_SCORE_LIMIT`, so the
server re-sends it, and calls `save_career` again, every tick after a city
is done. The server never stops or loads the next city: Pygame's `main()`
does that itself. That is why the client latches the summary.

**Tests.** `run_tests.gd` `test_controls_and_economy`, through a real
`main.tscn`:
- defaults, V/B through `_unhandled_input`, both toggles kept by later
  commands, F/G still one-shot
- the hint's ON/OFF
- positive, zero, negative and missing scores
- both summary variants, and malformed summaries
- the summary hides the UI, survives an empty state, and suppresses
  commands (that check fails with the guard removed)

Godot 385 checks. `tests/summary_shot.gd` renders both summaries.

## godot-final-03: taxi information

**Protocol, additive.** Five fields in `state.taxi`, read directly from
production state construction (`protocol.py`). The protocol version is
unchanged.
- **The running fare:** `elapsed_time`, `live_fare_cents`, `fare_distance_m`
  and `passenger_happiness` come from `TaxiManager`. The last three are null
  while `fare_started_at` is unset, because Pygame shows them only once the
  meter runs.
- **The pump price:** `fuel_station_price_cents` is the price of
  `nearest_fuel_station(scenery_objects, car)` within `FUEL_STATION_RANGE_M`,
  priced by `fuel_station_price_cents`. That is the same lookup and price
  refuelling uses. It is null when no pump is in range.

No rule changed.

**Godot.**
- **Fare line:** the drop-off line gains Pygame's mission-bar details, for
  example "Drive Aino to Rautatientori · 62 s · meter 12.34 € · 2.35 km ·
  happiness 50%". Absent, null or malformed values are left out. The pickup,
  walking and no-fare texts are unchanged.
- **Fuel gauge:** it shows "G: REFUEL  2.44 €/L" in Pygame's amber, inside
  the existing box, only while the server sends a price. The price is part of
  the gauge's redraw key.

**Existing behaviour noticed (not changed).** After a drop-off,
`taxi.state` stays `DROPOFF` and the meter fields keep their last values
until the next fare. The passenger is null, so the HUD shows "No fare", as
Pygame does.

**Cost.** `nearest_fuel_station` is a linear scan of the scenery objects
once per state (30 Hz), as Pygame does every frame. On the client it is one
string format.

**Tests.**
- **Python** (`tests/test_server_headless.py`):
  - the four fare fields: null before the meter starts, exact values, zero and
    boundary values, encode/decode
  - the price: null at 8.5 m; the nearest of two in range, equal to
    `nearest_fuel_station` and `fuel_station_price_cents`; refuelling charges
    that price
- **Godot** (`test_taxi_information`):
  - fare, zero and cent formats
  - before the meter starts, an older server, malformed values
  - pickup, walking and no-fare texts
  - price formats, null, absent and invalid prices
  - gauge redraw on another pump and on leaving

Godot 403 checks.

**Scripted Oulu run.** Real server, real phone offer:
- before boarding, the meter fields are null
- the meter then ran 8.00 → 8.20 → 8.40 → 8.50 €, distance 0 → 152 m, time
  0 → 12 s, happiness 50 → 49 → 72 %
- the fare completed
- at a real pump, the price showed at 4 m but not at 12 m (2.44 €/l); 10 l
  cost 24.40 €; the price cleared after driving away

A Godot screenshot at the pump shows the gauge line.

## godot-final-04: navigation route

**Server ownership** (`navigation_route.py`, `SimulationServer.navigation`,
updated once per tick after the simulation step). This is Pygame's `main()`
lifecycle, computed whether or not a client shows it.
- **Lifecycle:**
  - no target means no route, and no search starts
  - a new target replans: the target is keyed on its coordinates and address,
    never an object id
  - so does a new map level, and a new `route_graph_revision` (the old line
    stays until the new route is done)
  - so does being more than 35 m from every segment of the cached route; the
    check runs only on a finished route
  - an unreachable target gives `[]`, without retrying every tick, as in
    `main()`
- **Search:** surface routes run as `plan_route_steps`, honouring the road
  layer. The generator is kept between ticks and advanced 2 ms a tick
  (`ROUTE_BUDGET_S`). Off the surface, `world.level_routes.plan` gives this
  level's leg, synchronously as in Pygame.
- **Publishing:** a job belongs to its target, level and revision key and is
  dropped when the key changes, so a stale search can never publish. Only a
  finished route is published.

**Protocol.** `state.navigation = {"points": [[x, y], ...]}`, in world
metres, rounded to 1 cm, `[]` while there is none. The points are compacted
once per route with iterative Douglas-Peucker at 0.5 m
(`simplify_polyline`), which keeps both endpoints, and cached. Interpolation
copies it from the newest state, never blending it. A new client's first
state carries the cached route. The protocol version is unchanged.

**Godot.**
- **Toggle:** N in `nav_overlay.gd` (`show_route`, off by default, non-echo
  presses). It is local only, so no command field. C is unchanged, and the
  hint shows `N navigation ON/OFF`.
- **Drawing:** `entity_layer.gd` `_route` draws it in world space via
  `MapMath.point`:
  - dark edge (60, 45, 5) at max(5 px, 0.8 m), gold centre (255, 215, 35) at
    max(2 px, 0.45 m), Pygame's widths
  - after the pedestrians, before the target marker, the taxi and the NPCs
  - within the entity layer (z 10): above roads and buildings, under
    canopies, rail bridges (z 11) and trains (z 12)
- **Caching:** points are converted only when the received route changes.
  Nothing is drawn while hidden, when there is no target, or for malformed
  data, including non-finite, one-point or missing routes. `--navigation`
  starts with it shown, for screenshots.

**Measured (Oulu, 11,835 route nodes).**
- **Search steps:** a single step is at most 1.04 ms (the first, nearest
  nodes); later steps are at most 0.62 ms, over 20 random routes of 4–5,933
  steps.
- **Worst slice:** 2.9–4.0 ms in three runs, i.e. the budget plus one step.
- **Point counts:** routes went 59 → 10, 91 → 36, 60 → 21 and 116 → 33 points.
- **Slow ticks:** 50–250 ms ticks occur with the route job idle, and with
  route planning off entirely (224 ms max). They are the server's existing
  spikes.
- **Godot:** two polylines of ≤ 36 points a frame; the selftest ran at 145 FPS
  headless (147 before).

**Tests.**
- **`tests/test_navigation_route.py`,** on a real TrafficWorld grid:
  - no target, no search
  - an exact start and end; no replan when nothing changes
  - the drop-off replaces a running pickup job, which never publishes
  - at 35 m it keeps the route; at 36 m it replans
  - a new graph revision replans and keeps the old line meanwhile
  - a level leg, then back to the surface
  - unreachable: `[]`, no retry
  - a multi-tick job within its budget
  - simplification: endpoints, error ≤ 0.5 m, reduction
- **`test_server_headless.py`:** empty by default, the encode/decode round
  trip, a new client's snapshot, discrete under interpolation.
- **Godot `test_navigation_route`:**
  - N default, toggle, echo; C independent; the hint
  - origin conversion; malformed routes
  - hide/show at once, replacement, the unchanged-route cache
  - no target; draw order and z

Godot 428 checks.

**Scripted Oulu run** (real offer, Godot screenshots with `--navigation`):
- the pickup route follows the roads
- 30 m beside it keeps the route; 60 m replans from the new position
- boarding switches to the drop-off route
- after the fare the route clears

**Noticed, not changed.** A long fare line plus the godot-final-03 meter
details can overflow the top row at 1280 px.

**Fix after play-testing: routes on the opposite carriageway and the wrong
way up one-way streets.** There were two causes, both reproduced on Oulu
(300 routes from cars on real one-way roads):
1. **Bridge ends were dead ends.** Route nodes merge per OSM layer, so a
   bridge or ramp (layer 1) ending on the ground road's shared node
   (layer 0) was never joined to it. One-way ramps reached only 1–3 nodes.
   `RouteGraphBuild` now links nodes at exactly the same point on different
   layers. A bridge passing over a road shares no node with it, so that stays
   apart. Those ramps now reach 11,029 of 11,835 nodes, and nodes with no
   way out fell from 34 to 13. This is the shared graph, so NPCs can now
   drive those junctions too.
2. **The search started from the cheapest nearby node** (4 × the straight
   distance), often across the road or behind the taxi on a one-way street.
   With `on_road=True`, used by navigation only so NPC routing is unchanged,
   the start and target join their own road segment within 12 m, in its
   allowed directions, costed along it. A target further along the same
   segment is a straight line. Off the car network (service roads, parking
   aisles), or when no route exists that way, it falls back to the old
   candidates.

Routes starting against the taxi's one-way fell from 81 to 14 of 300. The
rest are cars on roads outside the car graph, or isolated pockets of the data.
Each segment lookup is its own job step, and the longest step is 1.38 ms.

Two tests in `tests/test_navigation_route.py` fail without the fix: the
bridge-end link (and no link to a road crossed below), and a divided road
whose carriageway leads on, round and back.

## godot-final-05: road rage

**Shared rule.** `advance_simulation` handles `PlayerCommand.road_rage`
first, as Pygame did with the key press before the step. With `rage_power >=
RAGE_SHOUT_COST` (0.25):
- the driver line (a no-op on the server until the speech phase)
- `vehicle.horn` at 0.45
- the cost, clamped at 0
- `random.choice(RAGE_SHOUTS)`
- `npc_manager.trigger_road_rage(car.x, car.y, car.heading, sim_time)`, once

It returns `rage_shout`. Below the cost nothing happens. The constants moved
from `main/__init__.py` to `simulation.py`. Pygame's SPACE handler now only
queues the press, still not while the phone is open, and starts its
five-second timer from the result. `--connect` takes the server's.
`trigger_road_rage` and its constants are unchanged: 40 m ahead, 6 m
sideways, 8 s, 1.5 m/s.

**Server and protocol.**
- **The press:** `road_rage` is a command press like `refuel`. It is
  stripped from `_latest_command` and counted, and at most one is applied per
  tick, so two presses act on two ticks.
- **The shout:** `state.road_rage = {"text", "timer"}` while it lasts. The
  server counts it down by `dt`, clears it at 0, and sends it to every state,
  so a client connecting mid-shout sees the rest. Interpolation keeps the
  newest. The horn is the simulation's own `vehicle.horn` sound event;
  `audio_events.json` maps it to volume 0.45.

**Godot.**
- **The press:** a non-echo SPACE sets one pending press, sent once in the
  next command (`command_for(..., road_rage)`). It is never sent while the
  phone is open or after the career summary. The client never checks rage.
- **The bubble:** `entity_layer.gd` `shout_for(state)` validates the shout
  (a non-empty string, a finite positive timer), with alpha
  `min(1, timer / 0.5)`. `_bubble` draws it above the interpolated taxi at
  max(22 px, 0.7 × length) + 6 px, with red (240, 40, 40) text, a
  (200, 30, 30) border and a white fill, at a constant screen size. It comes
  after the taxi body and before the NPC vehicles, as in `draw_car`.
- **Hint:** `SPACE road rage`.

**Tests.**
- **Python:**
  - `test_npc.py`: crashed, behind, too far and too lateral are skipped; the
    nearest eligible gets 8 s
  - `test_server_headless.py`:
    - 0.2 does nothing
    - 0.25 is accepted down to 0, with one horn and one trigger (the car's
      position, heading and the sim time as the tick starts)
    - a valid shout, 5 s, counting down and clearing
    - two presses give two actions, no replay
    - interpolation keeps it discrete
    - `main()` no longer calls the trigger
  - `test_client_server_integration.py`: encode/decode and the false
    default; a press and an ordinary command in one tick act once; a
    connecting client receives the remaining shout
- **Godot** (`test_road_rage`):
  - SPACE once; echo and held commands don't repeat it
  - phone-open and post-summary suppression; G stays independent
  - text and fade; invalid states don't draw
  - draw order and constant size
  - the horn resolves at 0.45; the hint

Godot 471 checks.

**Scripted Oulu run.**
- **20 % rage:** nothing.
- **60 % behind a moving NPC 20 m ahead:** rage fell 25 points, with one horn
  and the shout "PSKA!" for 5 s. That NPC alone was provoked, for 8 s, and
  slowed 6.1 → 1.5 m/s. 20 ordinary (held) commands repeated nothing.
- **Two presses at 35 %, nothing ahead:** the first was accepted; the second
  had too little rage.
- **Godot:** the screenshot shows the server's shout above the taxi.

## godot-final-06: weather presentation

**No precipitation intensity.** The audit row's "heavy-rain intensity"
assumed a state that doesn't exist. Pygame has:
- `weather_type`: clear, rain, slush or snow
- one fixed pool of 220 particles while it falls
- `is_thunderstorm`, which adds the heavy-rain loop

Godot uses exactly that, so no intensity field was added.

**Protocol, additive.** `state.weather.is_thunderstorm` and
`wind_vector_mps` (the gust-adjusted `[east, north]`, rounded to 1 mm/s,
non-finite as 0), read straight from `WeatherSystem`. Nothing else: no
particles, ripples, splashes or volumes. The version is unchanged.

**Godot** (`weather_layer.gd`): one presenter owning only client presentation
state, drawing into three canvas items:
- **Precipitation** (screen space, Sky layer above the lightning flash):
  - 220 particles allocated once in a `PackedFloat32Array`, moved in real
    seconds by weather.py's fall and drift factors (rain 1/1, slush
    0.55/1.35, snow 0.22/1.8), recycled in place
  - rain: pale streaks 9–20 px; snow: flakes, radius 1 or 2; slush: flakes
    plus short streaks
  - at most 3 `draw_multiline` submissions a frame
  - hidden when clear or underground, as Pygame's `surface_world` check
- **Ripples** (world, z 5): each puddle spot gains a `phase` from the same
  per-road seed. While it falls, a ring for each visible puddle in its 1 s of
  every 2.4 s, from 0.25 to 1.1 of the radius, with alpha 70 × (1 − progress)
  × strength. All rings go in one `draw_multiline_colors`; wet but clear
  means no ripples.
- **Splashes** (world, z 11, above the vehicles): the interpolated taxi
  against the loaded chunks around it. The probe radius is half the larger of
  length and width, and the puddle must be showing at this wetness. A splash
  spawns on the edge into "in a puddle at ≥ 1 m/s", with strength
  min(1, km/h / 60). Each lasts 0.5 s, growing 0.25 + progress × 1.4 ×
  strength m, with alpha 200 × (1 − p) × (0.5 + 0.5 s). At most 40; never on
  foot or underground. One submission.
- **Audio** (`main.gd` `weather_loops`, `main()`'s `update_ambience`):

  | Loop | Volume | Variation |
  |---|---|---|
  | rain | 0.6 in rain or slush | 0 |
  | rain_heavy | 0.7 in rain or slush during a thunderstorm | 1 |
  | wind | clamp(\|wind\| / 12) × 0.5 | 0 |
  | wind_strong | clamp((\|wind\| − 10) / 10) × 0.6 | 1 |
  | wet_tires | clamp(wetness × \|speed\| / 15) × 0.6, 0 on foot | 0 |
  | wet_slush | the same, in slush only | 1 |

  These are new loops in `audio_events.json`, with existing assets only. An
  older server without the new fields keeps only the base rain.

**Benchmark** (llvmpipe, 1280×720, `--bench 30`, the Oulu spawn, a
real-time server with forced weather). The new presenter's own CPU per frame
is update 0.08 ms + precipitation 0.10 ms + ripples 0.16 ms (about 5 rings
in view).

| scenario | before: avg / p99 / worst / 1 % low | after | render CPU/GPU before → after | draws |
|---|---|---|---|---|
| clear, dry | 35.5–36.6 / 59–60 / 64–66 / 15.6–16.3 | 35.1–36.1 / 56–57 / 62–67 / 16.1–17.1 | 23.5–23.8 → 22.6–23.8 | 4,291 → 4,274–4,300 |
| rain, wet | 39.3–40.0 / 61–64 / 70–82 / 14.4–15.5 | 40.7–41.6 / 62–66 / 74–78 / 14.2–14.7 | 26.0–27.4 → 27.4–27.9 | 5,333–5,367 → 5,337–5,371 |
| snow | 38.9 / 61.5 / 73.7 / 14.7 | 40.2 / 64.1 / 67.6 / 15.2 | 25.6 → 27.3 | 5,314 → 5,308 |
| rain, driving through puddles | 38.5 / 59.9 / 67.8 / 15.8 | 41.3 / 64.7 / 74.9 / 14.8 | 25.4 → 27.6 | 5,374 → 5,356 |

**Attribution** (rain, `--bench-hide`):
- all on: 40.7 ms
- without precipitation: 40.1 ms
- without ripples: 40.6 ms
- without both: 39.7 ms, i.e. the old client's

So the layer costs about 1 ms a frame in rain or snow (fill on llvmpipe) and
nothing when clear. One rain pair measured +6 ms; it did not repeat.

**Fix after play-testing: no visible puddles or ripples in rain.** Two
causes, both measured in the live client:
- **Too few.** Pygame gives each OSM way one 40 % chance, whatever its
  length. On Oulu that is about one small puddle per screen; the live view
  had 1 of 1,231 spots.
- **Too faint.** The colour, navy (32, 40, 54) at 150, vanished on the
  wet-darkened road, and 1 px rings at alpha ≤ 70 can't be seen.

Godot now gives each `PUDDLE_STRETCH_M` (8 m) of drivable road a 40 % chance,
placed uniformly along the road from the same per-road seed: about 5
puddles per 100 m. Puddles are a blue-grey (92, 108, 128) at 170, and ripple
and splash rings are 2 px wide, ripples at alpha up to 150. These are
deliberate differences from Pygame. Rain measured 38.6 ms a frame; ripples
take 0.31 ms of CPU.

**Noticed, not changed.** The server passes a fixed 15 °C to the simulation,
and `WeatherSystem` turns falling snow and slush into rain above freezing. So
a server session can't yet have snow or slush; it needs the historical
weather / temperature row (P2). The benchmark and screenshots disable that
conversion on the test server only.

**Tests.**
- **Python** (`test_server_headless.py`): the thunderstorm and the exact wind
  vector reach the state; the four types unchanged; zero, negative and
  non-finite wind encode; the weather keys are exactly the five.
- **Godot** (`test_weather_presentation`, 37 checks):
  - the fixed pool and per-type motion in real seconds; recycling without
    growth; no work when clear
  - visibility for rain, underground, wet-but-clear; three canvas items
  - deterministic phases; the ripple maths
  - the splash edge cases: outside, entering, staying, too slow, on foot,
    underground, re-entering; strength, ring, cap and lifetime
  - only nearby chunks are queried
  - all the loop formulas and variations; malformed and older states

Godot 508 checks. Screenshots of rain, slush and snow were taken through the
same server.

## godot-final-07: speech and stations

**Speech (server decides, client plays).**
- **`speech.py`:** the chatter catalogs and `audio.py`'s rules, unchanged and
  pygame-free:
  - situation moods
  - the Finnish driver recording when there is none in the requested
    language (the subtitle keeps the requested text)
  - a 3 s cooldown per driver situation
  - one line at a time
  - passenger chatter every 5–20 s at random while riding
  - a specific line by its Finnish text

  Pygame's `AudioManager` now uses it, with its channel as the busy flag.
- **The server's `EventAudio`** uses it on the simulation clock: a line is
  "busy" for its recording's length, read from the WAV header. Each accepted
  line becomes one event:
  `{"type": "speech", "speaker", "speaker_name", "gender": "f"|"m",
  "language" (the recording's), "hash", "text", "duration_s": 4.0}`.
  Events go through the existing due-event path once.
- **Godot:**
  - **The voice:** `audio_manager.gd` `speak` resolves only
    `sounds/<speaker>_chatter/<g>_<lang>_<hex>.wav`, decodes it once
    (`AudioStreamWAV`) and plays it on one `AudioStreamPlayer` (Game bus).
    Nothing plays over a line already playing; malformed events or missing
    files are ignored.
  - **The subtitle:** `hud.gd` `show_subtitle` shows one label, "name or
    Driver/Passenger: text", white on black (205), centred at height − 82,
    word-wrapped, for the event's seconds in real time.

**Announcements.**
- **The event:** `StationAnnouncer.event` uses the same script, phrases,
  `clips()` (pauses included) and platform source as `announce`. It gives
  one `station_announcement` per arrival or departure:
  `{"clips": [manifest-relative files in order], "at": the platform point
  nearest the taxi (else the stop), "text", "station"}`. It doesn't depend
  on an audio device; the existing `train_arrived`/`train_departed` events
  stay.
- **Godot:** `announce` accepts only clips under
  `assets/railway_announcements` (no `..`, no absolute paths). One
  `AudioStreamPlayer2D` (Game bus, range 300 m) plays the clips in order,
  starting each on `finished`. Whole announcements queue; one still waiting
  after 20 s is dropped.

**`state.railway`** (`protocol.railway_state`):
`{"stations": [{name, x, y, waiting}], "nearest_station", "arrivals": [{time
"HH:MM", train_type, number, origin, track}], "departures": [... destination
...]}`. It comes from `RailwayManager.stations`, `next_arrivals` and
`next_departures` (5) at the server's game time, and the station passengers'
`waiting_count`. It is `{}` without a railway. On Oulu it takes 0.9 ms and
about 1 KB a state.

**Station ambience** (`main.gd` `station_ambience`, `_play_rail_sounds`):
- **Which station:** of the stations with people waiting, the one heard
  loudest, by audio.py's gain (full within 15 m, 1/d, faded over the last
  quarter of 150 m).
- **Loops:** `station_crowd` (variation 0) at min(1, waiting / 30) × 0.6 and
  `station_luggage` (variation 1) × 0.4, placed and updated, not restarted.

**J board:** a local toggle that sends no command and is ignored while the
phone is open. `hud.gd` `next_train_text` lays out the station, "Next
trains:" and "Departing trains:" with up to 5 rows each ("HH:MM track N  IC
28 Rovaniemi"), top right at y 116, in pale blue on dark with a blue border.
It hides when empty or malformed. The one-time "Train timetables available.
Press J." is the client's own 6 s hint, so it never overwrites a server
notice.

**Bounded:** one voice, one subtitle, one loudspeaker with a queue, two
station loops and one board. Streams are cached by path. No nodes are created
per event.

**Tests.**
- **Python** (`tests/test_speech.py`, 8):
  - no pygame import; driver Finnish fallback with the English text
  - busy, cooldown, moods, the specific line, the random interval
  - missing catalogs; the announcement event equals
    `clips(phrases)`/`sentence`, and is None without a service or stop
  - `railway_state`: the nearest station, five rows, JSON-safe, `{}`
    without a railway
- **Godot** (33 checks):
  - a real WAV plays once; traversal and missing files are rejected; stop
    on disconnect
  - the clip order, the 300 m placement, traversal rejected, the queue and
    staleness
  - the subtitle text and lifetime; the board format, the five-row cap and
    malformed boards
  - J is local and phone-gated; the hint
  - station selection, the gain, malformed stations, the loop variations

Godot 541 checks.

**Oulu run** (a real offer and fare):
- three passenger lines in the passenger's name: the pickup line ("Voitin
  liput kesän konserttiin."), chatter, and the drop-off line
- the driver lines were blocked while the passenger spoke, as Pygame
- 7 station announcements, e.g. "Hyvät matkustajat. InterCity kaksikymmentä
  kahdeksan Rovaniemeltä saapuu raiteelle yksi"
- 16 waiting at Oulu
- the J board screenshot shows Oulu's arrivals and departures

---

# Audit 1 (godot-06, 2026-10-03) and per-phase history

The sections below are the first audit and its phase-by-phase updates,
kept as history. Parity audit 2 above supersedes their statuses.

Audited on 2026-10-03 against `release/v0.16.0g-alpha` at commit `0445643`;
rows marked godot-07 were updated after that phase (rendering-only parity),
rows marked godot-10 after the re-audit of 2026-10-05 (`734a3b7`; see
[the godot-10 section](#godot-10-re-audit)), rows marked godot-11 after
[phase 2](#godot-11-phase-2-server-state-already-owned), rows marked godot-12 after
[phase 3](#godot-12-phase-3-gameplay-points-in-chunks), rows marked godot-13 after
[phase 4](#godot-13-phase-4-collision-relevant-static-world), rows marked godot-14 after
[phase 5](#godot-14-phase-5-server-calendar-and-daynight), rows marked godot-15 after
[phase 6a](#godot-15-the-static-world-drawing-only-objects-night-seasons), rows marked godot-16 after
[phase 6b](#godot-16-the-rest-of-the-static-world), rows marked godot-17 after
[the 2.5D buildings](#godot-17-25d-buildings); godot-18 changed no rows
([performance](#godot-18-performance-investigation)), rows marked godot-19 after
[the first GTA1-style extrusion](#godot-19-gta1-style-top-down-building-extrusion),
godot-20 after the screenshot-authoritative radial correction, and godot-21
after [the 3D building layer prototype](#godot-21-lightweight-3d-building-layer-prototype);
godot-22 and godot-23 changed no rows ([culling and FOV](#godot-22-back-face-culling-and-fov),
[render pass and geometry](#godot-23-render-pass-measurements-gables-canopies-headlights)).

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


## godot-lights-01: continuous night lighting

The old tint polygon over the world (darker plus lights cut out of it) is
gone; the lights had only ever made it whiter. Now:

- `daylight.gd`: pure functions of the sun's altitude
  (`state.calendar.sun_altitude_deg`, else back from `darkness`):
  `ambient` (smootherstep -16° .. 8°), `artificial` (lights, 1 at -8° .. 0
  at 10°), `ambient_color` (white → bluish twilight → cold blue night,
  never black). No day/dusk/night states, no steps; tested for continuity
  and monotonicity.
- `main.gd`: one CanvasModulate multiplies the world by `ambient_color`
  (zero fill cost). Lamp heads, traffic lights and fuel boards use
  `emissive.tres` (unshaded) and stay bright.
- Street lights (`map_chunk.gd`): per lamp a soft ellipse leaning toward its
  road, warm amber core → dim shoulder → nothing, additive and unshaded, in
  one mesh per chunk (no polygon unions); fade in with `artificial`.
- Headlights (`night_layer.gd`): the beam quads as one additive vertex-
  coloured batch, slightly warm white at the lamps fading to nothing.
- Windows (`buildings_3d.gd`): one viewport; the building albedo follows the
  ambient colour, lit windows fade in warm (±18 % per window) with
  `artificial`. No second lit viewport, no silhouettes.
- `--sun-altitude DEG` overrides the altitude for screenshots and benches.

Bench (Oulu dense, 1280×720, llvmpipe, 30 s): night p50 34.3 → 23.7 ms,
p95 47.3 → 33.2 ms, draw calls 4,315 → 1,743, memory 112 → 97 MiB; day
21.4 → 21.0 ms (unchanged). This also covers godot-final-09.

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
| Buildings | `draw_buildings` (cached geometry, facades) | godot-21 (prototype, default): real 3D volumes seen by a top-down perspective camera in a SubViewport, composited at z 7; facades open toward the view centre continuously. `--buildings 2d`: godot-20 radial renderer: GTA1/GTA2-style screen-relative radial facade extrusion (godot-20): ground footprints stay exact; roofs project away from the live view centre by height × 0.35, exposing camera-facing walls toward the play area. Windows, doors and gabled roofs use the same volume geometry. Roads and the camera remain top-down. | different by design | high | – | – |
| Open-roof canopies over vehicles | `draw_open_roof_overlays` | chunk `canopies`: shadow under the vehicles; raised by their own height (`canopy_heights`) as open structures, posts from the ground corners, the translucent roof above the vehicles - pumps visible under it (godot-16, -17) | complete | medium | – | – |
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
| Illuminated windows at night | `draw_illuminated_windows` | on the extruded walls (godot-19): Pygame's rules - from darkness 0.25 fading to 165/255 by 0.5, its lit colour, 12 % of windows (houses 8 %, storefronts 3 %) - seeded by the building's position (Pygame: `id()`, which changes every run); additive over the night tint | complete | low | – | – |
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

| Status | godot-06 | godot-07 | godot-10 | godot-11 | godot-12 | godot-13 | godot-14 | godot-15 | godot-16 | godot-17 |
|---|---|---|---|---|---|---|---|---|---|---|
| complete | 7 | 30 | 31 | 35 | 39 | 40 | 42 | 46 | 65 | 66 |
| partial | 22 | 18 | 16 | 17 | 17 | 19 | 18 | 19 | 14 | 14 |
| missing | 71 | 52 | 52 | 47 | 43 | 40 | 39 | 34 | 19 | 18 |
| different by design | 3 | 3 | 4 | 4 | 4 | 4 | 4 | 4 | 5 | 5 |
| debug-only | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 3 |
| not applicable | 2 | 2 | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 3 |
| rows | 108 | 108 | 109 | 109 | 109 | 109 | 109 | 109 | 109 | 109 |

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

## godot-17: 2.5D buildings

**The game stays top-down.** Roads, markings, terrain, landuse, railways,
vehicles, pedestrians, labels and the camera are unchanged. Only the
volume of a building is projected, and its footprint stays exactly where
the map has it. Navigation will use the ground plane.

**Projection model** (`godot/buildings_25d.gd`). A point at height *h*
metres on a building is drawn at:

    ground position + LEAN × min(h × HEIGHT_SCALE, MAX_DEPTH_M)

- `LEAN = (−0.7, −1)` is up and a little left on screen.
- `HEIGHT_SCALE = 0.35`.
- `MAX_DEPTH_M = 11.1`.

These are Pygame's oblique roof offset and cap (`roof = (x − 0.7d,
y − d)`, `d = 0.35 h` px/m, at most 100 px), expressed in map metres. The
offset is one direction for every building. It doesn't depend on the
player or the camera position, and the camera zoom scales it like
everything else, so heights stay coherent at any zoom.

**Height.** The server's authoritative height
(`render/buildings.py _building_render_height`): the OSM height or
levels, else 4.5 m for an untagged detached house, else at least 3 m.
In Oulu that's 3 m (10th percentile), 7.2 m (median), 20 m (90th
percentile) and up to 66 m. Heights above about 32 m reach the cap. The
client never guesses a height.

**Drawing.**
- **Visible walls:** a wall is visible when its outward normal points
  away from the lean (the south and east sides). This works for any simple
  polygon, either winding; an L-shape's notch top faces north and stays
  hidden.
- **Order within a building:**
  1. a soft ground shadow away from the lean
  2. the footprint base
  3. the visible walls, far to near, shaded by facing, in Pygame's wall
     colour (paired with the roof colour, or named in the building's name)
  4. windows, floor by floor by Pygame's rules: the OSM floor count or
     height ÷ 3, at most one floor per 3 px of facade; up to 3 windows a
     floor; houses 2, on every other floor; commercial ground floors as
     storefronts
  5. doors at the OSM entrances, on the nearest wall when it's visible,
     one storey high
  6. the roof, lifted by the full height, with gabled facets and ridge
- **Order across buildings:** within a chunk, buildings are drawn far to
  near along the lean. Across chunks, the map layer keeps one building
  group ordered the same way.
- **One owner per building:** each building now belongs to the chunk
  containing its centre. A volume drawn twice by two chunks would paint
  over its neighbours.

**Lit windows** follow Pygame's rules:
- they appear from darkness 0.25 and fade in to 165/255 by 0.5
- the lit colour is Pygame's (232, 189, 108)
- 12 % of windows are lit (houses 8 %, storefronts 3 %)
- they're seeded by the building's position, so a reloaded chunk shows the
  same windows (Pygame seeds by `id()`)
- the glow is a separate additive list per chunk above the night tint,
  faded by `modulate`, never redrawn for time

**Canopies** are raised by their own height (`canopy_heights`, 5.5–8 m in
Oulu) as open structures:
- the shadow and the posts from the ground corners are drawn under the
  vehicles
- the translucent roof is drawn above them
- pumps under a canopy remain visible through it (checked by pixel colour
  at the Neste station)

At St1 Limingantie a 19.4 m retail building 7 m south of the pumps now
covers them with its raised roof. That's the projection's own occlusion of
what stands behind a tall building, as in Pygame, which draws scenery
before its oblique buildings. The station's pin and price board, above
everything, still mark it.

**Night and the rest.**
- The night tint, street lights, lightning and seasons apply unchanged.
- Headlight beams are clipped against each building's projected volume
  (the hull of footprint and roof), not just its footprint.
- Bridges and rail bridges (z 11) stay above the buildings (z 7).
- Underground, the dark level view (z 9) covers them.

**Memory and performance.**
- Each chunk's buildings are one coloured triangle list, built at load and
  handed to the renderer. The client's own copy is dropped after the draw;
  keeping it cost ~15 MiB. It's rebuilt identically if ever needed. Only
  the hulls stay.
- Selftest: 145–151 FPS, 0 render backsteps, taxi 0 px off centre, static
  memory 80.8–81.6 MiB (godot-16: 79.5).
- 49 real Oulu chunks: parse and add 12.0 ms per chunk (godot-16: 7.5 ms;
  the difference is the building geometry, still one chunk per frame), the
  first frame drawing them 595 ms (639), unload 0.7 ms (0.4).

**Verified:**
- Godot unit tests (238):
  - the lift and its cap
  - visible walls for a box (either winding) and an L-shape
  - wall and roof vertices; roof and window colours from the style
  - deterministic rebuild, lit windows included
  - more floors on a taller building
  - gabled facets and ridge
  - a door shown on the south wall, hidden on the north wall
  - a scattering of lit windows
  - far-to-near chunk order; hulls for headlights; canopy height
  - underground and bridge z-order; buildings freed with their chunk; no
    collision
- Python test: a building across a chunk edge belongs to one chunk, its
  style carries Pygame's wall/roof pair and floors and category, and
  canopies carry their heights.
- Real Oulu server (scratch launcher; production config untouched):
  - **The start area at noon:** south and east facades with windows and
    doors, roofs raised by height, the ground unchanged.
  - **23:00:** scattered lit windows over the night tint.
  - **Dusk at the 19.4 m Liiketulli:** deep facades with many floors.
  - **Winter:** snow ground with the buildings intact.
  - **St1 and Neste canopies:** raised with posts.
  - **Bridges and the underground view:** unchanged.
  - No client error lines.
- **Finding (not from this phase):** a fourth fuel station, outside Oulu's
  map data, isn't in any chunk.

**Deliberately different from Pygame:**
- not its oblique renderer, and not pixel parity
- shop signs on facades are not drawn
- roofs don't take snow (neither do Pygame's)
- across chunks, overlapping volumes are ordered by chunk rather than per
  building

## godot-18: performance investigation

No parity rows changed; the visuals are the godot-17 ones (compared at a
pinned position, day and night).

**Root causes of the <15 FPS drops:**
- **The earlier FPS figures were misleading.** `make godot-selftest` runs
  `--headless`, so its 145–151 FPS never included rendering.
- **The frame is fill-bound** on this machine's software renderer
  (llvmpipe): a full-screen rect costs about 6.6 ms, an empty frame 4.4 ms.
  Layers that covered the whole screen were the main cost:
  - the night tint and the headlight pools were two `CanvasGroup`s, about
    20 ms each (screen copy plus composite)
  - invisible full-screen layers still drawn: the lightning flash at alpha
    0, the 200 km ground rect, and the wet overlays when dry
  - chunk geometry was not clipped to the chunk, so roads and water were
    drawn several times over
- **Main-thread spikes:**
  - chunk JSON parse (up to 26 ms)
  - the 2.5D building build (up to 69 ms)
  - pool cutting (up to 254 ms)
  - label redraws (5 ms)

**Changes, each measured before and after:**
- **Ground:** the clear colour replaces the 200 km rect.
- **Flash:** visible only during lightning.
- **Wet overlays and puddles:** hidden when dry.
- **Chunk geometry:** roads, railways, rail bridges and water are clipped
  to the chunk bounds. This also fixed a godot-07 bug: wet roads used
  `clip_polyline_with_polygon`, which returns the part *outside* the chunk.
- **Night tint:** a plain `Node2D` drawing the view minus the beams as
  pieces, with buildings re-tinted inside the beams.
- **Headlight pools:** disjoint pieces drawn additively, no `CanvasGroup`.
  They are cut on a worker thread.
- **Chunk parsing and 2.5D building build:** moved to `WorkerThreadPool`
  tasks; a chunk unloaded mid-parse is cancelled.
- **Labels:** candidates are cached per chunk, only chunks in view are
  checked, and text sizes are cached.
- **Tried and reverted:** batching roads into one triangle list cut draw
  calls but not render time.

**Benchmark** (`--bench 60`, a 7.5 km route through central Oulu at
12 m/s, llvmpipe, 1280×720; render times are Godot's own measured times):

| | day before | day after | night before | night after |
|---|---|---|---|---|
| average FPS | 17.7–19.7 | 21.6–27.7 | 12.0 | 16.4–18.4 |
| 1 % low FPS | 8–12 | 9.7–14.9 | 6.1 | 8.7–12.0 |
| worst frame | 95–146 ms | 77–110 ms | 171 ms | 95–122 ms |
| render per frame | 36–38 ms | 25–31 ms | 62 ms | 39–46 ms |

**Other numbers:**
- **Worst chunk add:** 67 ms before, 23–34 ms after.
- **Label draw:** 5 ms before, 0.3–1.0 ms after.
- **Static memory:** 87–104 MiB with 49–56 chunks loaded.
- **Worst area:** 2,533 buildings, 11,187 walls, 62,238 windows, 7,231 lit.

**Remaining:**
- Software rendering stays below 30 FPS, because the frame is fill-bound.
  With z1–z4 hidden it reaches 33 FPS.
- Pool cutting still takes up to 243 ms, but on a worker thread, so it
  only delays the pools.

**Diagnostics:**
- `perf.gd` keeps section timings and counters.
- `--bench SECONDS` prints `BENCH {json}`; `--bench-hide` hides layers.
- F3 shows frame stats and building counts.

**Tests:** Godot 255 checks, Python 1566.

## godot-19: GTA1-style top-down building extrusion

**What looked isometric:** godot-17 lifted every point at height h along
Pygame's oblique vector, `(-0.7, -1) × min(0.35 h, 11.1 m)`. Roofs slid
diagonally north-west of their footprints, and buildings leaned.

**Now:** a GTA1-style top-down vertical building extrusion
(`buildings_25d.gd`):
- `lift(h) = UP × h × BUILDING_HEIGHT_SCALE`, with `UP = (0, -1)` and a
  scale of 0.35 screen metres per metre of height. There is no cap.
- The camera never rotates, so "up" out of the map is always straight up
  the screen. x never changes with height, and nothing depends on the
  player or the zoom.
- **Visible walls:** those whose outward normal points down the screen
  (normal · UP < 0). The test works for either winding and for concave
  footprints.
  - An axis-aligned box shows only its south wall; its east and west
    walls are edge-on, which is correct for a vertical extrusion.
  - A box turned 45° shows its two lower walls.
- **Roof:** the footprint moved straight up by the lift. Gabled facets and
  the ridge are cut on that roof.
- **Windows and doors:** they are laid on the visible walls. Their rules
  are unchanged, and lit windows are still seeded by the building's
  position.
- **Canopies:** the posts rise straight up; the roof stays open.
- **Draw order:**
  - within a chunk, far (north) to near
  - across chunks, by row from north to south, then west to east, so the
    order no longer depends on load order
- The old diagonal path is removed; no second renderer is kept.

**Parity:** no count changes; the buildings row stays "different by
design".

**Verified:**
- **Godot unit tests (267):**
  - vertical lift with no cap
  - visible walls of a box (either winding), a turned box and an L-shape
  - L walls rising straight up from their ground edges
  - at 5, 20 and 100 m: the ground edge where the footprint is, and the
    volume spanning exactly the footprint's x
  - windows lying on the south wall; the pitched roof over the footprint
  - deterministic rebuild; doors on visible walls, hidden on others
  - chunk row order; bridges and underground z-order; no collision
- **`tests/building_scene.gd`:** a dev scene drawn by the real map layer
  at zooms 4, 7 and 12, with red ground outlines. It contains:
  - low, 60 m, L-shaped, pitched, commercial, entrance and turned
    buildings
  - a canopy and roads
- **Real Oulu server** (scratch launcher; production config untouched):
  - the central pinned spot at noon and 23:00
  - Liiketulli at dusk, the 66 m tower, winter
  - St1 Limingantie and Neste: open canopies, pumps and price boards
    visible
  - the rail bridge and the underground view, unchanged
  - no client errors

**Performance** (the godot-18 benchmark, llvmpipe, two runs each):

| | godot-18 | godot-19 |
|---|---|---|
| day average FPS | 21.6–27.7 | 24.0–29.1 |
| day 1 % low / worst | 9.7–14.9 / 77–110 ms | 16.0–20.4 / 53–77 ms |
| night average FPS | 16.4–18.4 | 17.5–20.0 |
| night 1 % low / worst | 8.7–12.0 / 95–122 ms | 12.7–13.9 / 78–80 ms |

- **No regression:** the geometry has the same triangle count (walls are
  still one quad each). The vertical walls are a little thinner on screen,
  since east and west walls are edge-on, so they cover fewer pixels.
- **Other numbers:**
  - chunk add 5.7–6.8 ms average, 29 ms worst
  - building build 12.5–13.4 ms average on the worker
  - static memory 89–106 MiB
  - 2,533 buildings, 11,166 walls, 62,226 windows, 7,280 lit
- **Remaining:**
  - very tall buildings (60–66 m) have roofs 21–23 m up the screen, so
    they cover the street north of them, as in GTA1. If that hurts
    readability, a cap would be a separate constant.
  - software rendering is still under 30 FPS (godot-18).

## godot-20: screen-relative radial facades

The reference screenshots supersede godot-19's single upward vector. For a
building centre `b`, view centre `c`, and height `h`, the roof offset is:

`normalize(b - c) × h × 0.35`

Thus a top-screen roof moves farther upward and its facade runs down toward
the play area; bottom, left, and right buildings reverse or rotate that
relationship naturally. The ground footprint never moves. An edge is visible
when its winding-independent outward normal points opposite the roof offset.
Windows and visible entrances are generated on those wall quads; pitched roofs
and open canopies receive the same radial offset.

The camera remains an ordinary top-down `Camera2D`; roads, terrain, vehicles,
and pedestrians receive no projection. Geometry remains batched per chunk.
Camera movement updates a chunk when its view angle changes by 0.06 radians,
avoiding a full-city rebuild every frame while keeping the facade direction
screen-relative.

## godot-21: lightweight 3D building layer (prototype)

**Status: prototype, on by default; `--buildings 2d` restores the godot-20
renderer for comparison.** Only the buildings are 3D. Roads, terrain,
vehicles, pedestrians, labels and the HUD are unchanged, and the server is
unchanged.

**Why perspective, not orthographic.** A straight-down orthographic camera
shows no walls. A tilted orthographic one shows walls on one side only (the
godot-19 look) and squashes the ground by cos(tilt), so footprints no longer
match the 2D map. A straight-down **perspective** camera (what GTA1/GTA2 did)
keeps the ground plane exact and pushes every point at height `h` out from
the view centre by `r × h / (D − h)`. Facades open toward the player, deeper
near the screen edges and for taller buildings, and change continuously as
the camera moves. No code picks walls; the depth buffer does.

**Coordinate mapping.** 2D layer `(x, y)` (metres, y down) → 3D `(x, 0, y)`.
Height is the 3D `y`.

**Camera.** `Camera3D` at `(cx, D, cy)`, rotation `(-90°, 0, 0)` (screen up =
−z = 2D up), vertical FOV 40° (30° since godot-22; `buildings_3d.gd FOV`, the one tuning knob),
`KEEP_HEIGHT`. `D = view_height_m / 2 / tan(FOV / 2)`, with `view_height_m =
viewport_px / zoom`, so the ground plane fills exactly the `Camera2D` view.
Each frame it copies the `Camera2D`'s screen centre and zoom.

**Geometry.** One `ArrayMesh` per chunk, built on a worker thread. Every
footprint edge is extruded from 0 to the server height, the roof is the
triangulated footprint at that height, and a pitched roof is two planar
halves rising to a ridge (0.3 × half width, at most 4 m). Windows (Pygame's
slot rules, deterministic) and doors are quads 5 cm in front of the walls.
Materials are unshaded vertex colours with no culling. There are no lights
and no shadows; walls are shaded by their direction.

**Composition.** A transparent `SubViewport` renders the meshes. Its texture
is a `Sprite2D` at z 7, at the camera centre and scaled by 1/zoom, so one
texel is one screen pixel. Roads stay below it and vehicles and the night
tint stay above. Lit windows use a second camera on the same `World3D`. It
renders the lit-window mesh, and the building mesh again in black as an
occluder. That pass is added at z 21 over the night tint, and it isn't
rendered at all by day.

**Checks.**
- `tests/building_scene.gd -- OUT 3d|2d` renders low, tall, L-shaped,
  irregular, pitched, commercial and turned buildings at three zooms. It
  also pans the camera across them in five steps. Footprints stay on their
  red outlines, and facades turn smoothly through the view centre.
- In real Oulu (Rantakatu, at dusk) streets stay readable and footprints
  stay on the map.

**Benchmark** (stationary at the Oulu spawn, `--bench 30`, llvmpipe,
1280×720, day, 49 chunks; the godot-18 route script was not available):

| | 2D radial (godot-20) | 3D prototype |
|---|---|---|
| average FPS | 43.4 | 33.9 |
| 1 % low FPS | 35.7 | 27.5 |
| worst frame | 31.1 ms | 38.9 ms |
| p99 frame | 26.5 ms | 34.6 ms |
| static memory | 104.5 MiB | 107.9 MiB |
| buildings / walls | 2,315 / 10,631 visible | 2,315 / 21,121 (all) |
| windows | 60,112 | 119,838 |
| chunk building build (worker) | 7.0 ms avg, 27 ms max | 14.4 ms avg, 59 ms max |
| 3D objects | – | 2–3 `MeshInstance3D` per chunk (~150) |

**Known limitations.**
- About 22 % slower on software rendering, because every wall and window is
  sent to the GPU, not only the visible ones. Back-face culling with
  consistent winding would cut that roughly in half.
- Facades are deep at FOV 40° (a 60 m building near the screen edge covers
  much of the street). Lower `FOV` for shallower facades.
- Canopies still use the godot-20 radial lift.
- Headlight beams clip at the footprint, not at the projected volume.
- Gable-end triangles are left open.
- The night pass renders the whole view twice.

**Tests:** Godot 347 checks (all pass), Python 1562 passed, 3 failed (`test_main_city_bin_integration.py`, Pygame city-bin loading; no Python was changed in this phase).

## godot-22: back-face culling and FOV

**Culling.** The building material uses `CULL_BACK`. All triangles go
through one helper (`_tri`), which takes the surface's outward normal (walls,
windows and doors: the wall normal; roofs: up) and swaps two vertices when
needed. Godot's front faces are clockwise, so every triangle faces out
whichever way the footprint winds. A test checks every triangle of three
footprints, in both windings and with a pitched roof, door, storefront and
lit windows.
- **Pixel check:** the culled building scene matches the unculled one
  within 0–85 edge pixels per 1280×720 frame, across eight frames.
- **Proof culling is active:** deliberately flipping the winding changes
  155,815 pixels, because roofs and front walls disappear.

**Benchmark method.** The spawn and weather are random per server start
(2,315, 2,531 or 2,533 buildings loaded), and the game clock starts at 18:00
and runs at 60×. So each run starts a fresh server with Python's `random`
seeded to 22, without changing the server. Runs are interleaved before /
after / 2D. Each run is `--bench 30`, standing, 1280×720, llvmpipe, at a
seeded spot (Hallituskatu, 2,533 buildings). The Windows host's load
changed between the two sets, so compare within a set only.

| | before culling | after culling | 2D renderer |
|---|---|---|---|
| set 1 (FOV 40), average FPS | 27.1 | 27.6 (+2 %) | 36.0 |
| set 1, 1 % low | 18.0 | 16.8 | 20.4 |
| set 1, worst frame | 58.3 ms | 63.9 ms | 57.2 ms |
| set 2 (FOV 30), average FPS | 20.5 | 21.7 (+6 %) | 25.9 |
| set 2, 1 % low | 9.6 | 10.6 (+10 %) | 11.7 |
| set 2, worst frame | 112.8 ms | 104.5 ms | 96.0 ms |
| memory | 104.9–108.3 MiB | 106.7–109.9 MiB | 103.3–107.0 MiB |

**Why the gain is small.** `--bench` now measures the 3D view's own render
time. It is 3.5–4 ms per frame with or without culling, against about
22–27 ms for the main view. On llvmpipe, rejecting back faces is cheap, and
a culled back face had covered only pixels that its front faces cover anyway.
Triangle count is not the bottleneck; the 3D layer's cost is fill:
- clearing and drawing a 1280×720 3D target
- blending it full-screen into the 2D frame

`--bench-hide composite3d` / `buildings3d` hides those for attribution, but
host noise was larger than the effect in those runs. The remaining gap to
the 2D renderer is roughly that fill cost.

**FOV.** Tried 40°, 35°, 30°, 25° and 20°, in the building scene at zoom 4,
7 and 12, and in Oulu with `--building-fov`. At 40° a 60 m building covers
much of the street beside it. At 25° and below, low buildings (4 m) lose
their visible facades at normal zoom. **30°** keeps tall buildings clearly
volumetric with about a quarter less facade depth than 40°, and low ones
still show walls. Footprints stay on their outlines at every value: the
camera height follows the FOV, so ground alignment does not depend on it.

**Unchanged (deferred):** canopies, headlight clipping, pitched-roof gable
caps and the night's second building pass.

## godot-23: render-pass measurements, gables, canopies, headlights

**The render path as built.**
- **3D target:** a `SubViewport` exactly the window's size (1280×720),
  `transparent_bg`, RGBA8, MSAA off, no HDR (Compatibility renderer), no
  mipmaps.
- **Updates:** it renders every frame (the default `UPDATE_WHEN_VISIBLE`).
- **Composite:** one full-screen `Sprite2D` with nearest filtering, at the
  camera centre, blended over the whole screen every frame, empty pixels
  included. The texture is used directly, never copied.

**Baseline.** Same method as godot-22: fresh seeded server, `--bench 30`,
standing, 1280×720, llvmpipe. Each figure is the mean of 3 runs.

| | frame | main view render | 3D pass |
|---|---|---|---|
| no 3D layer (`--bench-hide buildings3d`) | 38.6 ms | 29.4 ms | – |
| 3D pass rendered, not composited (`composite3d`) | 42.9 ms | 28.2 ms | 3.9 ms |
| full 3D layer | 47.2 ms (21.2 FPS) | 32.5 ms | 4.3 ms |
| 3D pass with every mesh hidden (`meshes3d`) | 39.1 ms | 28.2 ms | 1.0 ms |

So the layer costs about 8.6 ms a frame:
- about 4.3 ms is the 3D pass: about 1 ms fixed (clear and set-up) plus
  about 3.2 ms for the meshes
- about 4.3 ms is the composite: one full-screen blend into the main view

(With the sprite hidden, Godot also skips rendering the viewport, so
`composite3d` now forces the pass to keep updating.)

**Lower internal resolution: tried, rejected.** Two runs each:

| target scale | 3D pass | frame |
|---|---|---|
| 1.0 | 4.0–4.3 ms | 41.6–42.3 ms |
| 0.75 | 3.6–3.7 ms | 45.0–45.5 ms |
| 0.5 | 3.5–3.7 ms | 42.2–46.6 ms |

Halving the pixels saves only about 0.5 ms of the 3D pass, so the pass is not
pixel-bound. The composite still covers every screen pixel, and its upscale
needs linear filtering, which blurs edges and windows. The frame did not get
faster, so the code was reverted.

**Partial viewport: not done.** In the city, buildings cover most of the
screen, so a scissor or partial target would rarely shrink the blend. It
would also need per-frame bounds work.

**Transparency.** The cost is the blend over every screen pixel. The layer
must be transparent to sit between roads and vehicles. The cheaper
alternative is the 3D pass rendering straight into the main view, with the
roads drawn as its background canvas (`Environment.BG_CANVAS`). That means
moving the 2D map into `CanvasLayer`s, which is an architecture change, so it
was left out of this phase.

**Conclusion.** The remaining cost is inherent to compositing a full-screen
SubViewport. Nothing was changed for performance.

**Final daytime run** (mean of 3, no intended change): 44.4 ms, 22.6 FPS,
1 % low 10.8, worst 101.2 ms, 106–110 MiB; 3D pass 4.1 ms. This is within the
spread of the baseline (47.2 ms, 21.2 FPS, 1 % low 9.7, worst 111.4 ms,
109 MiB).

**Night.** After about 120–150 s of game clock, the passes cost:
- main 3D pass: 4.2 ms (the same as by day)
- lit-window pass: 1.4 ms

The whole night frame is 63–69 ms. Its cost lies elsewhere (the night tint,
light pools, beams), so the second pass was left unchanged.

The "daytime" benchmark spans game time 18:00 to about 18:40 on today's date.
On 5 October the sun sets in Oulu around 18:45, so its last part is dusk and
the lit pass already runs. All godot-21 to godot-23 runs share this.

**Geometry fixes.**
- **Gables:** each wall under a sloping roof edge now continues up to the
  roof, including the peak where the ridge crosses it. The pitched roof is a
  closed volume. The triangles go through the same winding helper, so the
  outward-facing test covers them. A new test checks that both gable ends
  reach the ridge.
- **Canopies:** they stay translucent 2D roofs above the vehicles (z 11).
  Their corners and posts now use `lift_point`, the 3D camera's exact
  projection of a point at height `h`:
  `c + (p − c) × D / (D − h)`.
  So they line up with the 3D buildings. Chunks in view redraw them each
  frame, so there is no angle-bucket stepping. The 2D renderer keeps the old
  radial lift.
- **Headlights:** each building keeps its top (the ridge on pitched roofs).
  `buildings_in` returns the hull of the footprint and its projected roof,
  the visible silhouette, which is computed only for buildings near the
  beams. A concave building is clipped at its convex hull, as in godot-17.
  Tests check the projection and the silhouette bounds; a night screenshot
  had no beam reaching a building.

**Tests:** Godot 355 checks (5 new), selftest ok (taxi 0 px off centre, no
render backsteps), audio check 0 problems. Python: 1562 passed, plus the 3
known `test_main_city_bin_integration.py` failures.
