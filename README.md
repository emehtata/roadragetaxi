# The Road Rage Trip 🚗

A top-down 2D driving game proof-of-concept (PoC) - a Godot client and a Python simulation server - that proceduralizes environment creation using real-world OpenStreetMap (OSM) data from Finland.

## Miksi rattiraivo?

Koska muut kuskit ovat idiootteja ja ajavat miten sattuu. Vähemmästäkin hermostuu, kun joutuu pujottelemaan hidastelijoiden, törttöilijöiden ja arvaamattomien liikkujien seassa. The Road Rage Trip tekee tästä tutusta liikennekaaoksesta pelin ytimen: asiakkaat pitää kuljettaa perille, vaikka muun liikenteen sähläys nostaisi verenpaineen kattoon.

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
- **Resident-First Traffic World**: The runtime traffic architecture contains residents, pedestrians, crossings, traffic lights, roads, and taxi interactions. Autonomous NPC cars, rival taxis, and NPC parking traffic are disabled while the new traffic simulation is developed around persistent residents and pedestrians.
- **Pedestrians**: Pedestrians use dedicated paths, mapped entrances, and crossings; they track destinations, use logical traffic signals, wait before unsafe crossings, enter buildings at doors, and update at distance-based LOD rates. Hospitality venues receive extra activity, including drunk pedestrians with 0.5-3.0 promille, slower unstable walking, and occasional falls; selecting a resident shows their promille value. At night, visible pedestrians show a bright reflector point until a car headlight or street light illuminates them.
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
- **Offline & Cache Support**: User-writable JSON caching (`RoadRageTrip/osm_cache/`) with TTL; bundled sample data requires explicit `--use-sample`.

---

## Project Structure

```text
├── godot/                 # The game client (Godot 4): menus, map, vehicles, HUD, sound
│   ├── main.gd            # Connects to the server, applies its state, handles the keys
│   ├── paths.gd           # Finds (or starts) the bundled simulation server
│   └── ...                # map_chunk / map_layer, entity_layer, hud, instruments, audio_manager...
├── src/
│   └── theroadragetrip/   # The simulation server (Python, no display)
│       ├── __main__.py    # `python -m theroadragetrip` = `python -m theroadragetrip.server`
│       ├── server/        # The server loop, its CLI, and map streaming to the client (map_sync.py)
│       ├── protocol.py    # The JSON messages sent to the client every tick
│       ├── simulation.py  # The per-tick gameplay simulation
│       ├── world_loader.py # Loads and builds the world for a city
│       ├── map_chunks.py  # The static map, cut into chunks for the client
│       ├── osm/           # OSM data models, fetching (Overpass or .osm.pbf), caching, tile streaming
│       ├── physics.py     # Vehicle dynamics, road collision, lane assist
│       ├── npc.py, pedestrian.py, residents.py, traffic_world.py # Traffic and people
│       ├── taxi.py, fare.py, career.py # Taxi missions, fares, career
│       ├── trains.py, station_announcer.py, ... # Railway timetable, trains, announcements
│       ├── street_lights.py, building_style.py, map_style.py, parking.py # Map look shared with the client
│       └── assets/, sounds/ # Data, chatter and sound files
├── tests/                 # Server tests (pytest); the Godot tests are under godot/
├── tools/, utils/         # Asset validation, data importers, TTS generation, audits
├── road_rage_server.py    # Entry point of the bundled server (PyInstaller)
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
# Godot launcher: career, gig/city selection, settings, then the game
make run

# Start with DEBUG-level logging
make run-debug

# Server alone, then the client connected to it (see `make help`)
make run-server PRESET=helsinki
make run-godot

# Read the map from a local .osm.pbf extract instead of Overpass
make run-pbf

```

On the first launch, the game creates `roadragetrip.ini` under the platform configuration directory (`$XDG_CONFIG_HOME/RoadRageTrip/` on Linux, `%APPDATA%/RoadRageTrip/` on Windows) and asks for Finnish or English. Edit that file to set the city, map fetching, zoom, logging, pedestrian, language, audio, and police-camera values. Career progress and the total odometer are stored beside the INI file. The `[cities]` section contains editable `name = latitude, longitude` entries; add or remove cities there. Command-line options override the INI values for one launch.

For example, set `preset = helsinki` under `[game]` to run Helsinki with its resident and pedestrian simulation.

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
overpass_endpoints = https://overpass.openstreetmap.fr/api/interpreter, https://overpass-api.de/api/interpreter
auto_fetch = true
fetch_margin = 350.0
fetch_tile_size = 1000.0
build_in_process = true

[traffic]
pedestrian_count = 20

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

The pause-menu **Settings** screen includes **City list**. Select a configured city, type a replacement, then choose a matching catalog suggestion with the mouse or Enter. The selected INI entry is replaced in place and saved immediately. Catalog names and coordinates are loaded from `src/theroadragetrip/assets/kunnat.json.gz`.

The `[map] overpass_endpoints` setting contains a comma-separated list of Overpass API URLs. The in-game **Asetukset / Settings** menu lets you edit this list; changes are saved immediately. The `OVERPASS_ENDPOINTS` environment variable still takes precedence for one launch.

### Comment Audio and Subtitles

The pause-menu **Comment audio** setting controls driver and passenger comment sounds. **Subtitles** displays the selected comment in a cinematic black subtitle bar at the bottom of the screen; audio and subtitles can be enabled independently.

Passenger chatter plays only during an active ride to the destination. One entry is selected randomly every 5–20 seconds from `assets/passenger_chatter.json`; the matching pre-rendered OGG is selected from `sounds/passenger_chatter/` using the passenger's gender, language, and entry hash. Event chatter filters passenger lines by mood for nausea, water, pickup, dropoff, and collisions.

Driver chatter uses `assets/driver_chatter.json` and matching files in `sounds/driver_chatter/`. Lines are filtered by gameplay situation and include a short per-situation cooldown so repeated physics events do not spam audio.

Other common development commands are `make test`, `make compile`, and `make check`. Run `make help` to list all available targets.

### Windows Release

Run the Windows release workflow on the release branch to test the setup installer, then merge the branch and tag `master` to publish the Windows package:

```bash
git tag v0.17.0alpha
git push origin v0.17.0alpha
```

GitHub Actions builds the Godot game and bundled Python server on Windows, installs the setup EXE in a temporary directory for a smoke test, then attaches `RoadRageTrip-windows-x64.zip` and `RoadRageTrip-Setup.exe` to the GitHub Release. Use the EXE installer for a normal Windows installation, or extract the zip and launch `RoadRageTrip.exe`; no Python installation is required.

Recorded sounds (the TTS chatter voices) are stored in `src/theroadragetrip/sounds/`. Generated sound effects (Stable Audio Open) live in `src/theroadragetrip/assets/audio/`, catalogued in `audio_catalog.json`.

Map, timetable and weather data:

- `src/theroadragetrip/assets/places.json` (airports and railway stations) is derived from OpenStreetMap data, © OpenStreetMap contributors, available under the [Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/); the file itself is likewise under the ODbL.
- `src/theroadragetrip/assets/railway_timetable.json.gz` (passenger-train timetable): Source: Fintraffic / [digitraffic.fi](https://www.digitraffic.fi/), license [CC 4.0 BY](https://creativecommons.org/licenses/by/4.0/). Modified: converted from GTFS to a compact one-week timetable by `theroadragetrip/railway_import.py`; the game refreshes its copy from Digitraffic weekly. The data is provided as is, without warranty.
- `src/theroadragetrip/assets/train_compositions.json.gz` (learned train compositions): Source: Fintraffic / [digitraffic.fi](https://www.digitraffic.fi/), license [CC 4.0 BY](https://creativecommons.org/licenses/by/4.0/). Modified: condensed to vehicle type, length and service flags by `theroadragetrip/composition_import.py`, refreshed weekly.
- `src/theroadragetrip/assets/finnish_first_names.json.gz` and `finnish_surnames.json.gz` (resident names): Digital and Population Data Services Agency (DVV) name data, [nimipalvelu.dvv.fi](https://nimipalvelu.dvv.fi/), license [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Modified: the most common names selected and converted to the game's JSON format.
- `src/theroadragetrip/assets/kunnat.json.gz` (municipality population, age structure and area): compiled from Wikipedia, © Wikipedia contributors, license [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Modified: tables combined and converted to the game's JSON format; the file is likewise CC BY-SA 4.0.
- Historical weather, forecasts and snow depth (opt-in, fetched from FMI at runtime and cached locally in `~/.cache/RoadRageTrip/weather_history.db`, not bundled): Finnish Meteorological Institute (FMI) open data, license [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Hourly values are resampled and combined from the nearest stations.

These credits are also shown in the game on the loading, menu and pause screens.

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
| `R` | Respawn car on a random road (penalizes active fare if client onboard) |
| `X` | Reject phone offer, or cancel / discard active pickup or onboard passenger mission (score penalty) |
| `T` | Reset trip meter to 0 |
| `L` | Cycle labels: off, street names, then street plus building/venue names |
| `K` | Toggle lane keep assist |
| `V` | Toggle speed limiter |
| `B` | Toggle traffic-light assist |
| `C` | Toggle compass (off by default) |
| `N` | Toggle yellow route to the active pickup or dropoff target |
| `Space` | Rattiraivo / Road Rage: trigger the taxi rage effect |
| `P` | Open taxi phone and view three ride offers |
| `1` - `3` | Accept a selected ride in the taxi phone |
| `F1` | Open the full tutorial and control list |
| `F3` | Toggle the diagnostic text |
| `E` | Start or stop the engine |
| `F` | Get in or out of the taxi; greet a booked passenger |
| `G` | Refuel at a pump |
| `J` | Show the next train |
| `U` / `F2` | Reset the HUD layout |
| `F12` | Save a screenshot plus the server's diagnostic JSON |
| `Esc` | Open pause menu (Continue, Tutorial, Settings, Change City, Exit) |

The F12 JSON includes all car properties, taxi mission state, map counts and bounds, camera and viewport data, and auto-fetch edge-trigger diagnostics.

The pause menu's **Settings** screen changes language and master, background, and effects volume. Left/right adjusts values; Escape returns to the pause menu. At a taxi stand, customers appear occasionally when a stand enters view, either already nearby or outside the screen, then walk to the stand before boarding. Existing pedestrians can also become customers. In areas without taxi stands, a nearby interested pedestrian can hail the taxi while stopped or while it passes. Completed passengers leave beside the taxi and continue walking.

---

## CLI Options

The server's options (`python -m theroadragetrip.server --help`); the Godot client passes them on after `--`.

| Flag | Description |
| :--- | :--- |
| `--preset` | Named preset from `[cities]` (defaults include `oulu`, `helsinki`, `tampere`, `espoo`, `turku`, `vantaa`, `jyväskylä`, `kuopio`, `lahti`, `sysmä`) |
| `--bbox` | Custom bounding box: `south,west,north,east` |
| `--use-sample` | Skip network and use bundled offline sample JSON |
| `--force-refresh` / `--no-cache` | Ignore disk cache and query Overpass fresh |
| `--osm-source` | `overpass` (default) or `pbf` - read OSM data from a local `.osm.pbf` extract instead of the network, via `osmium extract` (requires `osmium-tool` installed: `apt install osmium-tool` / `brew install osmium-tool`) |
| `--osm-pbf-path` | Path to the `.osm.pbf` file for `--osm-source pbf` (default: `assets/osm/finland-latest.osm.pbf`) |
| `--log-level` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `--auto-fetch` | Enable non-blocking background tile fetching near bounds |
| `--no-auto-fetch` | Disable on-demand background map expansion |
| `--fetch-margin` | Minimum margin in meters from bounds triggering auto-fetch; fast driving extends this with an 8-second lookahead (default: `350.0`) |
| `--fetch-tile-size`| Base auto-fetch tile size in meters (default: `1000.0`) |
| `--build-in-process` | Build auto-fetched map data outside the gameplay process |
| `--pedestrian-count` | Target number of pedestrians (default: `20`) |

When PBF map data is selected in the Godot settings and no usable file is present,
the game offers to download Finland from Geofabrik. It stores the file in Godot's
per-user data directory (`%APPDATA%\\Godot\\app_userdata\\Road Rage Trip (Godot client)\\maps`
on Windows, normally `~/.local/share/godot/app_userdata/Road Rage Trip (Godot client)/maps`
on Linux), never beside the installed executable. If the selected PBF is over
30 days old, the game offers to download a newer copy or continue with the existing file.

Runtime caches use `%LOCALAPPDATA%\\RoadRageTrip` on Windows and
`${XDG_CACHE_HOME:-~/.cache}/RoadRageTrip` on Linux. OSM downloads and FMI
weather history are under `osm_cache/`; built map worlds are under `world/`.
Train timetables and compositions are bundled assets, not runtime caches.

---

## Testing

The game logs important gameplay events at `INFO` level, including taxi mission and fare transitions, phone offers, passenger boarding, passenger chatter playback, police penalties, and major settings changes. Console logging is enabled by default. Set `[game] file_logging = true` in `roadragetrip.ini` to additionally append events to `roadragetrip.log` in the working directory. Use `--log-level DEBUG` when diagnosing lower-level behavior.

Run unit tests with pytest:
```bash
pytest tests/ -v
```

Godot tests and a short self-driving smoke run against a real server:
```bash
make godot-test
make godot-selftest
make audio-check
```
## Binary world cache

Normalized map areas are stored as versioned `.rwc` files under
`~/.cache/RoadRageTrip/world` (or the platform cache directory). Cache hits
load game-ready geometry directly; OpenPass JSON is used only for misses or
forced refreshes. Files are written atomically and validated with checksums.
Run `PYTHONPATH=src python utils/benchmark_world_cache.py` to compare JSON and
RWC timings and peak memory.
