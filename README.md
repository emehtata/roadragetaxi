# The Road Rage Trip 🚗

A top-down 2D driving game proof-of-concept (PoC) in Python and Pygame that proceduralizes environment creation using real-world OpenStreetMap (OSM) data from Finland.

---

## Features

- **Real-World OSM Road Network**: Fetches and renders actual highway ways from Overpass API (motorways, primary, secondary, residential, tracks, paths).
- **OSM Bus Stops**: Bus stops and platforms are rendered as roadside bays with small road-aligned shelters labeled `BUS`.
- Bus stops are disabled by default; enable them with `bus_stops = true` under `[game]` in `roadragetrip.ini`.
- **OSM Building Entrances**: Doors are rendered at `entrance` nodes from building geometry; buildings without entrance data have no synthetic door.
- **Taxi Game Mode**: Pick up passengers at generated street addresses, drop them off at their destinations, and earn points with speed and distance multiplier bonuses.
- **Taxi Stops & Missions**: Taxi offers use street addresses and named buildings as pickup and destination points. Taxi stands are pickup-only locations.
- **Ride Requests & Taxi Stands**: Ride requests arrive one at a time by phone, 10-60 seconds apart, and expire after 30-90 seconds when no passenger is onboard. Select one with `1`, `2`, or `3`, or reject the selected offer with `X`; phone offers and taxi-stand customers can coexist. The game starts at 18:00. From 20:00 to 00:00, rides favor homes to bars, restaurants, pubs, and nightclubs, plus trips between those venues. From 00:00 to 05:00, passengers leave taxi stands for home addresses; from 05:00 to 08:00, rides run between homes. From 08:00 to 12:00, bar and nightlife destinations are excluded. Phone rides normally start and end at named buildings or street addresses. Wait stopped at a taxi stand and its customer walks visibly to the taxi before boarding. Maps without taxi stands can trigger occasional street hails; only a small share of pedestrians want a taxi. A passing taxi can notice a hail, but the passenger only boards after the taxi stops.
- **Nighttime Passenger Condition**: Passenger nausea is more common between 20:00 and 05:00, with the highest risk from 01:00 to 05:00; venue type adds further risk for bars, pubs, and nightclubs.
- **Passenger After Drop-off**: After a completed fare, the passenger leaves the taxi beside the car and continues as an ordinary walking pedestrian.
- **Situation Chatter**: Passenger and driver lines are selected randomly from situation-appropriate Finnish and English chatter. Driver lines cover rage, collisions, water, traffic violations, police, pickup, and dropoff; passenger lines are filtered by mood.
- **Navigation Waypoints & Compass Pointer**: Displays visual waypoint zones, address tags, off-screen edge indicators, and an optional compass navigation pointer to client locations. The compass is hidden by default and toggled with `C`.
- **Suggested Route**: Press `N` to show a yellow route from the taxi to the active pickup or dropoff target. The route follows connected OSM roads, respects one-way streets, refreshes when the target or streamed map changes, and recalculates when the taxi leaves it.
- **Buildings & Scenery**: Renders building footprints, parks, forests, and green spaces with street/place name labels (`L` key).
- **Street Lighting**: Roadside lamps are placed along urban drivable roads and their warm glow gradually turns on at dusk.
- **Water & Multipolygon Rendering**: Renders lakes, reservoirs, and waterways under the road network.
- **Autonomous Traffic**: NPC cars follow connected roads, respect lane direction, vary their speed, overtake, react to traffic lights, and avoid overlapping the player. The shared road-graph navigator can route NPCs to map targets without cutting through buildings or terrain. Active traffic is reduced at close zoom levels while nearby cars are retained.
- **OSM Parking Traffic**: About half of regular NPC cars use existing OSM parking spaces by default. Parking density is configurable, parked cars remain spatially indexed, and occupied parking spaces stay reserved while a vehicle departs.
- **Pedestrians & Cyclists**: Pedestrians and cyclists use dedicated paths, mapped entrances, and crossings; pedestrians track destinations, use logical traffic signals, wait before unsafe crossings, enter buildings at doors, and update at distance-based LOD rates. Ordinary pedestrians spawn near mapped buildings, while hospitality venues receive extra activity; at night, visible pedestrians show a bright reflector point until a car headlight or street light illuminates them. Cyclists use a top-down image sprite, and active pedestrian/cyclist counts scale down while zoomed in.
- **Rival NPC Taxis**: Some NPC cars are yellow rival taxis. They stop briefly at taxi stands and collect waiting customers before driving on.
- **Traffic Violations**: Red-light, wrong-way, collision, building, and scenery penalties are tracked in the taxi score.
- **Tree Crash Effects**: Tree impacts shake the tree and scatter leaves; impacts above 80 km/h knock the tree down, smoke the taxi, and immobilize it for five seconds.
- **Roadworks**: Random roadworks add temporary traffic lights and can make NPC traffic slow or stop naturally.
- **Hidden Police Cameras**: One to twenty directional speed cameras are distributed across the connected road network; Helsinki has 20. Cameras are not tied to taxi stops. Driving above the local speed limit within its 50-meter approach zone costs 300 points.
- **Finnish & English**: The first launch asks for a language. The language can be changed later from the pause menu and is saved in `roadragetrip.ini`.
- **Audio Settings**: Master, background, and effects volumes plus comment audio and subtitles are adjustable at runtime from the pause menu and persist in the INI file.
- **Coordinate Projection**: Converts WGS84 (lat/lon) coordinates to metric ETRS-TM35FIN (EPSG:3067) using `pyproj`.
- **Arcade Vehicle Physics & Road Containment**: Responsive throttle, braking, friction, speed-dependent steering, and strict car-road boundary collision containment (blocks driving off-road into pedestrian paths, lakes, or off-road scenery).
- **Realistic Acceleration Curve**: Forward acceleration decreases progressively from 0 to 210 km/h instead of staying constant at high speed.
- **Surface Tire Effects**: Hard braking while turning leaves continuous skid marks on roads. Driving across grass leaves persistent dark-brown tire tracks.
- **Trip & Odometer**: Real-time speed, trip distance (resettable with `T`), and total odometer in the HUD.
- **Loading Progress Meters**: Visual progress bar on startup and live scenery streaming progress meter during background auto-fetch.
- **Orientation & Compass**: North-up screen projection with a real-time compass showing vehicle heading and bearing in degrees.
- **Offline & Cache Support**: User-writable JSON caching (`RoadRageTrip/osm_cache/`) with TTL and fallback to bundled sample data.

---

## Project Structure

```text
├── src/
│   └── theroadragetrip/
│       ├── __init__.py    # Package exports
│       ├── __main__.py    # Module entrypoint (`python3 -m theroadragetrip`)
│       ├── geo.py         # Projection and geometric calculations (clamp, segment distance, lat/lon conversion)
│       ├── main.py        # CLI arguments, logging, and Pygame main loop
│       ├── osm.py         # OSM fetching, disk caching, parsing, and AutoFetchManager
│       ├── pedestrian.py  # Pedestrian and cyclist simulation, road crossing, and evasion
│       ├── physics.py     # Car dataclass, vehicle dynamics, road collision, and lane assist
│       ├── police.py      # Hidden speed-camera placement and directional detection
│       ├── localization.py # Finnish and English translations
│       ├── render.py      # Pygame rendering for roads, waters, buildings, traffic, pedestrians, HUD, and compass
│       ├── assets/         # Image sprites and chatter data
│       │   ├── paikkadesi.json       # Country and city coordinates for future customization
│       │   ├── paikkadesi.txt         # Source list for the city coordinate asset
│       │   ├── passenger_chatter.json # 50 Finnish/English passenger lines
│       │   └── driver_chatter.json    # Situation-specific driver lines
│       ├── audio.py        # Optional music, effects, and situation chatter playback
│       ├── career.py       # Career progress and odometer persistence
│       ├── config.py       # INI loading, city configuration, and Overpass endpoints
│       ├── roadworks.py    # Temporary roadwork and traffic-light generation
│       ├── taxi.py        # Taxi passenger missions, hailing, address generator, fares, and violations
│       └── traffic.py     # Autonomous NPC traffic vehicles, lane switching, and overtaking
├── tests/                 # Unit tests (pytest)
├── utils/                 # Optional offline tools, including Azure TTS generation
├── sample_osm.json        # Bundled sample OSM data
├── sample_osm_large.json  # Expanded sample OSM data
├── road_rage_trip.py      # Top-level backward-compatible launch shim
├── requirements.txt       # Dependencies
└── pyproject.toml         # Build & package metadata
```

---

## Quickstart & Installation

### 1. Set up Virtual Environment
```bash
make install
```

### Azure Passenger Chatter

Install the utility dependency with `pip install -r utils/requirements.txt`, then set `SPEECH_KEY` and `SPEECH_REGION` in `utils/.env`. Generate all Finnish female voices with:

```bash
python utils/ttsazure.py f src/theroadragetrip/assets/passenger_chatter.json fi
```

Use `m` for male voices or `en` for English. The script stores hashes based only on each Finnish sentence in the JSON and writes WAV files named `{gender}_{language}_{hash}.wav` to `src/theroadragetrip/sounds/passenger_chatter/`; set `TTS_VOICE` or `TTS_OVERWRITE=true` to override defaults.

### 2. Run the Game
```bash
# Recommended launcher (default area: Oulu)
make run

# Start with DEBUG-level logging
make run-debug

# Or run as a module
source .venv/bin/activate
PYTHONPATH=src python -m theroadragetrip

# Run offline with bundled sample data
make run-sample

# Switch between named presets (e.g. Oulu or Helsinki)
python3 road_rage_trip.py --preset helsinki
python3 road_rage_trip.py --preset oulu

# Custom bounding box: south,west,north,east (lat/lon)
python3 road_rage_trip.py --bbox "60.150,24.88,60.205,25.02"

# Enable dynamic background auto-fetch
python3 road_rage_trip.py --auto-fetch --fetch-margin 50 --fetch-tile-size 500
```

On the first launch, the game creates `roadragetrip.ini` under the platform configuration directory (`$XDG_CONFIG_HOME/RoadRageTrip/` on Linux, `%APPDATA%/RoadRageTrip/` on Windows) and asks for Finnish or English. Edit that file to set the city, map fetching, zoom, logging, pedestrian, cyclist, traffic, language, audio, and police-camera values. Career progress and the total odometer are stored beside the INI file. The `[cities]` section contains editable `name = latitude, longitude` entries; add or remove cities there. Command-line options override the INI values for one launch.

For example, set `preset = helsinki` under `[game]` and `traffic_count = 100` under `[traffic]` to run Helsinki with 100 NPC cars.

### INI Settings

The game reads `roadragetrip.ini` from the platform configuration directory described above. Missing settings use the defaults below. Boolean values accept `true` or `false`; volume values are between `0.0` and `1.0`.

```ini
[game]
language =             # fi or en; blank asks on first launch
preset =               # e.g. oulu or helsinki
bbox =                 # south,west,north,east; overrides preset when set
no_menu = false
use_sample = false
force_refresh = false
no_cache = false
px_per_m = 9.0
log_level = INFO
file_logging = false
roadworks_enabled = false

[map]
overpass_endpoints = https://overpass-api.de/api/interpreter, https://overpass.private.coffee/api/interpreter, https://overpass.openstreetmap.fr/api/interpreter
auto_fetch = true
fetch_margin = 350.0
fetch_tile_size = 2500.0
build_in_process = true

[traffic]
traffic_count =        # blank enables automatic road-network scaling
pedestrian_count = 20
cyclist_count = 8
parking_density = 0.5  # fraction of regular NPC cars placed in OSM parking spaces

[audio]
master_volume = 1.0
music_volume = 0.2
effects_volume = 1.0
comments_enabled = true
subtitles_enabled = true

[speech]
min_interval = 5.0
max_interval = 20.0

[experimental]
enable_two_wheelers = false

[cities]
helsinki = 60.169525, 24.935446
espoo = 60.205000, 24.652000
tampere = 61.499113, 23.787117
vantaa = 60.294000, 25.041000
oulu = 65.012000, 25.468000
turku = 60.451483, 22.268686
jyväskylä = 62.241470, 25.720880
kuopio = 62.892382, 27.677028
lahti = 60.982674, 25.661509
sysmä = 61.502271, 25.680613
```

`[game] language` selects Finnish (`fi`) or English (`en`). Leave it blank only for the first-run language chooser. The pause menu can change and save the language and audio values while playing.

The `[cities]` section accepts any city name followed by `latitude, longitude`. Invalid coordinate entries are ignored. Command-line flags override matching INI values for the current launch.

The pause-menu **Settings** screen includes **City list**. Select a configured city, type a replacement, then choose a matching catalog suggestion with the mouse or Enter. The selected INI entry is replaced in place and saved immediately. Catalog names and coordinates are loaded from `src/theroadragetrip/assets/paikkadesi.json`.

The `[map] overpass_endpoints` setting contains a comma-separated list of Overpass API URLs. The in-game **Asetukset / Settings** menu lets you edit this list; changes are saved immediately. The `OVERPASS_ENDPOINTS` environment variable still takes precedence for one launch.

### Comment Audio and Subtitles

The pause-menu **Comment audio** setting controls driver and passenger comment sounds. **Subtitles** displays the selected comment in a cinematic black subtitle bar at the bottom of the screen; audio and subtitles can be enabled independently.

Passenger chatter plays only during an active ride to the destination. One entry is selected randomly every 5–20 seconds from `assets/passenger_chatter.json`; the matching pre-rendered WAV is selected from `sounds/passenger_chatter/` using the passenger's gender, language, and entry hash. Event chatter filters passenger lines by mood for nausea, water, pickup, dropoff, and collisions.

Driver chatter uses `assets/driver_chatter.json` and matching files in `sounds/driver_chatter/`. Lines are filtered by gameplay situation and include a short per-situation cooldown so repeated physics events do not spam audio.

Other common development commands are `make test`, `make compile`, and `make check`. Run `make help` to list all available targets.

### Windows Release

Push a version tag to build and publish a Windows package containing `RoadRageTrip.exe`:

```bash
git tag v0.6.1beta
git push origin v0.6.1beta
```

GitHub Actions builds the package on Windows with PyInstaller and attaches both `RoadRageTrip-windows-x64.zip` and `RoadRageTrip-Setup.exe` to the GitHub Release. Use the EXE installer for a normal Windows installation, or extract the zip and launch `RoadRageTrip.exe`; no Python installation is required.

Game sounds are stored in `src/theroadragetrip/sounds/`. CC0 sounds require no attribution; the included `accelerate.aiff` is CC BY 3.0 and `city-traffic-outdoor.wav` is CC BY 4.0. Attribution details are recorded in the sounds directory license file.

---

## Controls

| Key | Action |
| :--- | :--- |
| `W` / `Up Arrow` | Accelerate / Throttle |
| `S` / `Down Arrow` | Brake / Reverse |
| `A` / `Left Arrow` | Steer Left |
| `D` / `Right Arrow` | Steer Right |
| `+` / `=` | Zoom in (increase pixels per meter) |
| `-` | Zoom out (decrease pixels per meter) |
| `PageUp` / `PageDown` | Advance or rewind the debug clock by one hour |
| `R` | Respawn car on a random road (penalizes active fare if client onboard) |
| `Home` | Debug respawn near a random current map bbox edge (for auto-fetch testing) |
| `X` | Reject phone offer, or cancel / discard active pickup or onboard passenger mission (score penalty) |
| `T` | Reset trip meter to 0 |
| `L` | Cycle labels: off, street names, then street plus building/venue names |
| `K` | Toggle lane keep assist |
| `V` | Toggle speed limiter |
| `B` | Toggle traffic-light assist |
| `C` | Toggle compass (off by default) |
| `N` | Toggle yellow route to the active pickup or dropoff target |
| `Space` | Rattiraivo / Road Rage: move NPC cars ahead aside within 50 m |
| `P` | Open taxi phone and view three ride offers |
| `1` - `3` | Accept a selected ride in the taxi phone |
| `F1` | Open the full tutorial and control list |
| `F3` | Toggle the diagnostic text HUD |
| `F12` | Save screenshot plus matching runtime diagnostic JSON in `screenshots/` |
| `Esc` | Open pause menu (Continue, Tutorial, Settings, Change City, Exit) |

The F12 JSON includes all car properties, taxi mission state, map counts and bounds, camera and viewport data, and auto-fetch edge-trigger diagnostics.

The pause menu's **Settings** screen changes language and master, background, and effects volume. Left/right adjusts values; Escape returns to the pause menu. At a taxi stand, customers appear occasionally when a stand enters view, either already nearby or outside the screen, then walk to the stand before boarding. Existing pedestrians can also become customers. In areas without taxi stands, a nearby interested pedestrian can hail the taxi while stopped or while it passes. A rival NPC taxi may arrive first and take a stand customer. Completed passengers leave beside the taxi and continue walking.

---

## CLI Options

| Flag | Description |
| :--- | :--- |
| `--preset` | Named preset from `[cities]` (defaults include `oulu`, `helsinki`, `tampere`, `espoo`, `turku`, `vantaa`, `jyväskylä`, `kuopio`, `lahti`, `sysmä`) |
| `--bbox` | Custom bounding box: `south,west,north,east` |
| `--no-menu` | Skip interactive city selection startup menu |
| `--use-sample` | Skip network and use bundled offline sample JSON |
| `--force-refresh` / `--no-cache` | Ignore disk cache and query Overpass fresh |
| `--px-per-m` | Initial camera zoom (default: `9.0`) |
| `--log-level` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `--auto-fetch` | Enable non-blocking background tile fetching near bounds |
| `--no-auto-fetch` | Disable on-demand background map expansion |
| `--fetch-margin` | Margin in meters from bounds triggering auto-fetch (default: `350.0`) |
| `--fetch-tile-size`| Meters to expand when auto-fetching (default: `2500.0`) |
| `--build-in-process` | Build auto-fetched map data outside the gameplay process |
| `--traffic-count` | Target number of autonomous NPC cars (default: scales with available streets, capped at 200) |
| `--pedestrian-count` | Target number of pedestrians (default: `20`) |
| `--cyclist-count` | Target number of cyclists (default: `8`) |
| `--parking-density` | Fraction of regular NPC cars spawned in existing OSM parking spaces (default: `0.5`) |

---

## Testing

The game logs important gameplay events at `INFO` level, including taxi mission and fare transitions, phone offers, passenger boarding, passenger chatter playback, police penalties, and major settings changes. Console logging is enabled by default. Set `[game] file_logging = true` in `roadragetrip.ini` to additionally append events to `roadragetrip.log` in the working directory. Use `--log-level DEBUG` when diagnosing lower-level behavior.

Run unit tests with pytest:
```bash
pytest tests/ -v
```

Run in headless / CI environments without a physical display:
```bash
SDL_VIDEODRIVER=dummy python3 road_rage_trip.py --use-sample
```
