# Godot rendering migration backlog

This backlog is built from [godot-pygame-rendering-parity.md](godot-pygame-rendering-parity.md).
Items are grouped by dependency and gameplay need, not by preference. Each
item says what it needs and which layer changes:
- **P**: server protocol (`protocol.py`, `map_chunks.py`)
- **S**: shared simulation state
- **R**: Godot renderer
- **U**: Godot UI

Rule throughout: Godot gets state and draws it. Anything the simulation
decides (traffic-light phase, route, darkness, a booking's step) is sent,
never recomputed in GDScript.

## Status after godot-07 (rendering-only phase)

**Done** (verified against Pygame's renderers; see the parity rows marked
godot-07):
- **Job:** the pickup/drop-off zone, marker and label; the waiting
  customer; the off-screen arrow; the compass; the nausea bubble
- **Vehicles:**
  - appearance by type (car/van, bus, truck; two-wheelers simplified)
  - lamps, brake lights and turn signals
  - crash state and smoke; taxi exhaust
  - Pygame's skip rules: police, drivers on foot drawn as pedestrians, far
    level-of-detail band
  - the taxi's own size
- **Pedestrians:** heading, walk cycle, fallen and indoor states, curse
  bubbles
- **Trains:** profile colours, cab front, restaurant stripe, full length,
  drawn above vehicles
- **HUD:** fuel gauge, rage meter, water timer, trip and odometer
- **Map:** wet roads; puddles (different spots, see the parity doc); roads
  by layer with bridges on top
- **Camera:** 9 px/m default as in Pygame; view culling of entities
- **Two small protocol additions** for rows the audit classified as
  rendering-only: the waiting customer's position and state, and the
  taxi's size

**Not done in Phase A**, because each needs data the server doesn't send:
- the meet-and-greet panel and the booked-passenger arrow
- day/night
- traffic lights, taxi stands, fuel stations, roadworks
- road name and speed limit
- the navigation route, which also needs route planning moved into the
  simulation

**Rendering-only items still open:**
- road colours by type; railway track style; two-wheeler sprites
- street lights (lamp placement)
- rain and snow particles, rain ripples on puddles
- start hints and the HUD job line as in Pygame; the career summary;
  limiter status
- menus; camera follow / back button

## Two protocol extensions most items share

Most protocol gaps fall into two groups. Doing these first unblocks the
rest.

1. **Static map features in chunks (P).** `ChunkIndex` already buckets
   `ways`, `railways`, `waters` and `buildings` by vertex cell. The same
   bucketing can carry more:
   - polygons: sceneries (landuse, parks, forest), parking spaces, traffic
     islands, open-roof buildings
   - points: trees, scenery objects, taxi stands, fuel stations, traffic
     lights, stop and yield signs, speed bumps, speed cameras, crossings,
     bus stops, labels
   - polylines: curbs, railings
   - attributes: bridge/layer and map level per way and railway; building
     tags for facades and height; lane and oneway attributes for markings

   All of this is static and pre-encoded once at startup. Chunk size grows,
   so measure it (today 35 KiB average, 204 KiB maximum).

2. **Per-tick world state the simulation owns (P, maybe S).** Small and
   changing, so it belongs in `state`:
   - darkness / sun altitude, game date, temperature, precipitation
     intensity, lightning
   - traffic-light phases of nearby lights
   - roadwork sections
   - the meet booking: pedestrian id, train, station, platform, step
   - current road name and speed limit; speed-camera notice and flash
   - knocked-over objects and broken lamps; vomit spots; tire tracks
   - the player's turn signal

## Phase A: gameplay-critical visuals

Without these the game can't be played as designed in Godot: you can't see
where to go, what the rules are, or what is happening to the taxi.

| Item | Requires | Changes | Notes |
|---|---|---|---|
| Pickup / drop-off waypoint and off-screen arrow | `taxi.state`, `current_passenger.pickup/dropoff` (x, y, radius): already sent | R | Rendering only. A pulsing ring is a tiny draw or shader. |
| Waiting passenger shown at the pickup | pickup position (sent); the passenger pedestrian is in `pedestrians` | R | Rendering only. |
| Navigation route line | route polyline | **S + P**, R | The route is planned in Pygame's `main()` (`traffic_mgr.plan_route`), not in the simulation step. It moves into the simulation (or a server-side service) and is sent when it changes. Godot must not route. |
| Compass with target bearing | heading, target (sent) | R/U | Rendering only. |
| Meet-and-greet panel and booked-passenger arrow | meet booking: passenger pedestrian id, train, station, platform, step | P | `TaxiManager.meet_booking()` has it; not sent. |
| Day/night tint | sun altitude or a darkness value, date | P | Pygame computes the sun from time, latitude, longitude and date in `main()`. The server should send the result. |
| Traffic lights (posts and live phase) | light positions (chunks), phase per light | P (static + per tick) | The phase must come from the server, not be recomputed from `sim_time`. |
| Taxi stands, fuel stations | positions and prices | P (chunks) | Rail pickups and refuelling depend on finding them. |
| Roadworks | active roadwork sections | P | They block roads. |
| Road layers / bridges | `layer` (sent), bridge flag | R (+P for the rail bridge flag) | Draw ways sorted by layer; split a chunk's top canvas by layer. |
| Taxi and NPC appearance by type; NPC turn signals; crash state | `vehicle_type`, `is_taxi`, `is_police`, `turn_signal(_elapsed)`, `fallen`, `crashed_timer` (all sent) | R | Rendering only: sprites or shaded quads. |
| Brake and tail lights on the taxi | `braking`, `engine_on` (sent) | R | Night glow waits for darkness (above). |
| Trains above the taxi and NPCs | – | R | Layer-order fix: Pygame draws trains after vehicles. |
| HUD: fuel, rage, water timer, job line | `fuel_l`, `fuel_capacity_l`, `rage_power`, `water_elapsed`, `taxi` (sent) | U | Rendering only. |
| HUD: road name and speed limit | current way name, limit | P | The simulation tracks `current_way`; not sent. |
| Nausea warning bubble | `nausea_warning_timer` (sent) | R | Rendering only. |

## Phase B: world detail

The world reads correctly with these: what is a park, a fence or a
crossing, and what will stop the car. Several have collisions in the
simulation (trees, bollards, fences), so seeing them matters, but the game
is playable without them once Phase A is done.

| Item | Requires | Changes |
|---|---|---|
| Landuse fills, parking, traffic islands | sceneries etc. in chunks | P, R |
| Trees, scenery objects (bollards...), knocked-over state | points in chunks; knocked state per tick | P, R |
| Fences, railings, walls, hedges, curbs, construction fences | polylines in chunks | P, R |
| Crossings, speed bumps, stop/yield signs, speed cameras | points in chunks | P, R |
| Road markings | lane/oneway attributes, or prepared centre lines | P, R |
| Railway track style; rail bridges above vehicles | bridge flag (and gauge) | P (bridge), R |
| Underground / covered levels | `map_level` per way, the car's level | P, R |
| Buildings: facades, heights, open-roof canopies (and outlines of people/trains under them) | building tags, open-roof polygons | P, R |
| Map labels | labels/places in chunks | P, R (decluttering is client-side presentation) |
| Pedestrian bodies: heading, appearance, cyclists | `appearance` (P); heading, `is_cyclist` (sent) | P, R |
| Train car colours by profile, front band | `profile` (sent) | R |
| Next-train panel, game-start sign/forecast, career summary | timetable query result; city, forecast; `city_summary` (sent) | P (not for the summary), U |
| HUD: date, temperature, trip/odometer, speed-camera notice, fuel price, limiter status | date, temperature, notice (P); rest sent or client-owned | P, U |
| Menus: pause, settings | client-side | U |

## Phase C: effects and polish

These carry feedback or atmosphere. None blocks play.

| Item | Requires | Changes |
|---|---|---|
| Rain / snow particles, intensity; lightning flash | `weather_type` (sent); intensity, lightning (P) | P, R |
| Wet roads, puddles | `wetness` (sent); road geometry (sent) | R |
| Splashes | car speed over puddles: presentation only once puddles exist in Godot | R |
| Night: headlight beams, vehicle lamps, street lights (+ broken), lit windows, pedestrian reflectors | darkness (P); broken lamps (P); window data (P) | P, R |
| Exhaust, crash smoke, tire tracks, vomit puddles and footprints | smoke timers (sent); tracks, vomit (P) | P, R |
| Pedestrian walk animation, cursing bubbles | `animation_state/time`, `curse_timer/text` (sent) | R |
| Seasons: snow cover, ice | season, snow depth | P, R |
| Speech subtitles | speech lines are chosen client-side in Pygame `audio.py` | S (move speech choice to events) or keep client-side |

## Phase D: optional / debug

Train labels, the train-car passenger popup, the resident popup and camera
follow (need click picking plus resident and passenger data), the profiler,
g-force meter, NPC/spatial-grid panels, the feature inspector, lat/lon and
ways count. Godot's F3 readout covers networking and interpolation; the
rest is developer tooling.

## Performance considerations (measured inputs, not optimisation)

| Feature | Approximate count | Update rate | Batchable | Suggested Godot form | Note |
|---|---|---|---|---|---|
| Static map features (trees, objects, signs, fences) | thousands per chunk area (Oulu: 8,349 ways, 2,367 buildings; trees and objects more) | once per chunk | yes | the chunk's own canvas item, or `MultiMesh` for repeated icons (trees, bollards) | Never one node per feature. Chunk payload grows: re-measure the 35 KiB average. |
| Vehicles and pedestrians | about 40 NPCs, 35 pedestrians, 2–4 trains (Oulu) | per frame (interpolated) | yes | keep immediate drawing, or `MultiMeshInstance2D` with per-instance transform and colour | Godot draws everything in state; add view culling if counts grow. |
| Traffic lights, roadworks | tens near the player | per tick | – | small node set or the entity draw | Send only the ones near the player. |
| Rain / snow | Pygame: a CPU particle pool | per frame | – | `GPUParticles2D` with the camera | Purely presentational; no state beyond type and intensity. |
| Day/night, lit windows, beams | full screen | per frame | – | a `CanvasModulate` darkness tint plus light sprites (`PointLight2D` or additive textures) | Pygame copies the scene to draw light; Godot doesn't need that. |
| Puddles, wet roads | per visible road | when wetness changes | yes | a shader parameter on the road material | Placement stays deterministic from road geometry, as in Pygame. |
| Labels | hundreds | on camera move | – | `Label` pool with decluttering on zoom/pan only | Decluttering is presentation; keep it client-side. |

## Godot-specific approaches (for later, not now)

- **Road layers:** per-layer canvas items with `z_index` instead of
  Pygame's redraw passes for bridges.
- **Night lighting:** `CanvasModulate` plus `PointLight2D` or additive
  sprites for headlights, street lamps and windows, instead of a copied
  scene with per-pixel tint.
- **Weather:** `GPUParticles2D` for rain and snow; a shader for wetness
  and puddles.
- **Repeated features:** `MultiMeshInstance2D` for trees, bollards, signs
  and NPC car bodies.
- **Animations:** `AnimatedSprite2D` or shader time for the walk cycle,
  turn signals and the pulsing waypoint. The timing inputs
  (`turn_signal_elapsed`, `animation_time`) are already sent.
- **Camera:** a `Camera2D` with smoothing toward the sent `camx`/`camy`
  look-ahead, instead of locking onto the player.

## Recommended next phase

After godot-07 the rendering-only part of Phase A is done; the next step
is item 2 below (the per-tick protocol additions). Original order:
1. **Rendering-only items first** (data already in the state): waypoint
   and off-screen arrow, waiting passenger, compass, nausea bubble,
   vehicle appearance, turn signals, crash state, taxi lamps, trains above
   vehicles, HUD fuel/rage/water/job, layer-ordered roads. These need no
   protocol work and are testable with the existing selftest and unit
   tests.
2. **One protocol step for per-tick values:** meet booking, darkness and
   date, traffic-light phases near the player, roadworks, road name and
   limit. All are small additions to `state`.
3. **One chunk extension for gameplay points:** taxi stands, fuel stations
   and prices, traffic-light posts.
4. **Navigation route last:** it is the one Phase A item needing a
   simulation change (moving route planning out of Pygame's `main()`).
