# The Road Rage Trip 🚗

A top-down 2D driving game proof-of-concept (PoC) in Python and Pygame that proceduralizes environment creation using real-world OpenStreetMap (OSM) data from Finland.

---

## Features

- **Real-World OSM Road Network**: Fetches and renders actual highway ways from Overpass API (motorways, primary, secondary, residential, tracks, paths).
- **Taxi Game Mode**: Pick up passengers at generated street addresses, drop them off at their destinations, and earn points with speed and distance multiplier bonuses.
- **Taxi Stops & Missions**: Taxi offers use street addresses, named buildings, and taxi stops as pickup and destination points.
- **Navigation Waypoints & Compass Pointer**: Displays visual waypoint zones, address tags, off-screen edge indicators, and compass navigation pointers to client locations.
- **Buildings & Scenery**: Renders building footprints, parks, forests, and green spaces with street/place name labels (`L` key).
- **Water & Multipolygon Rendering**: Renders lakes, reservoirs, and waterways under the road network.
- **Autonomous Traffic**: NPC cars follow connected roads, respect lane direction, vary their speed, overtake, react to traffic lights, and avoid overlapping the player.
- **Pedestrians & Cyclists**: Pedestrians and cyclists use roads and crossings, react to traffic lights, and evade approaching vehicles.
- **Traffic Violations**: Red-light, wrong-way, collision, building, and scenery penalties are tracked in the taxi score.
- **Tree Crash Effects**: Tree impacts shake the tree and scatter leaves; impacts above 80 km/h knock the tree down, smoke the taxi, and immobilize it for five seconds.
- **Hidden Police Cameras**: One to twenty directional speed cameras are placed from the connected road-network size; Helsinki has 20. Every taxi stop receives a nearby camera when available. Driving above the local speed limit within its 50-meter approach zone costs 300 points.
- **Finnish & English**: The first launch asks for a language. The language can be changed later from the pause menu and is saved in `roadragetrip.ini`.
- **Audio Settings**: Master, background, and effects volumes are adjustable at runtime from the pause menu and persist in the INI file.
- **Coordinate Projection**: Converts WGS84 (lat/lon) coordinates to metric ETRS-TM35FIN (EPSG:3067) using `pyproj`.
- **Arcade Vehicle Physics & Road Containment**: Responsive throttle, braking, friction, speed-dependent steering, and strict car-road boundary collision containment (blocks driving off-road into pedestrian paths, lakes, or off-road scenery).
- **Trip & Odometer**: Real-time speed, trip distance (resettable with `T`), and total odometer in the HUD.
- **Loading Progress Meters**: Visual progress bar on startup and live scenery streaming progress meter during background auto-fetch.
- **Orientation & Compass**: North-up screen projection with a real-time compass showing vehicle heading and bearing in degrees.
- **Offline & Cache Support**: Local JSON caching (`osm_cache/`) with TTL and fallback to bundled sample data.

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
│       ├── pedestrian.py  # Pedestrian simulation, road crossing, and evasion
│       ├── physics.py     # Car dataclass, vehicle dynamics, road collision, and lane assist
│       ├── police.py      # Hidden speed-camera placement and directional detection
│       ├── localization.py # Finnish and English translations
│       ├── render.py      # Pygame rendering for roads, waters, buildings, traffic, pedestrians, HUD, and compass
│       ├── taxi.py        # Taxi passenger missions, address generator, fares, and violations
│       └── traffic.py     # Autonomous NPC traffic vehicles, lane switching, and overtaking
├── tests/                 # Unit tests (pytest)
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
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Run the Game
```bash
# Recommended launcher (default area: Oulu)
python3 road_rage_trip.py

# Or run as a module
python3 -m theroadragetrip

# Run offline with bundled sample data
python3 road_rage_trip.py --use-sample

# Switch between named presets (e.g. Oulu or Helsinki)
python3 road_rage_trip.py --preset helsinki
python3 road_rage_trip.py --preset oulu

# Custom bounding box: south,west,north,east (lat/lon)
python3 road_rage_trip.py --bbox "60.150,24.88,60.205,25.02"

# Enable dynamic background auto-fetch
python3 road_rage_trip.py --auto-fetch --fetch-margin 50 --fetch-tile-size 500
```

On the first launch, the game creates `roadragetrip.ini` in the current directory and asks for Finnish or English. Edit that file to set the city, map fetching, zoom, logging, pedestrian, cyclist, traffic, language, audio, and police-camera values. The `[cities]` section contains editable `name = latitude, longitude` entries; add or remove cities there. Set `[police] taxi_stop_cameras = true` to enable cameras near taxi stops for testing; it is disabled by default. Command-line options override the INI values for one launch.

For example, set `preset = helsinki` under `[game]` and `traffic_count = 100` under `[traffic]` to run Helsinki with 100 NPC cars.

### INI Settings

The game reads `roadragetrip.ini` from the current working directory. Missing settings use the defaults below. Boolean values accept `true` or `false`; volume values are between `0.0` and `1.0`.

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

[map]
auto_fetch = true
fetch_margin = 350.0
fetch_tile_size = 2500.0
build_in_process = true

[traffic]
traffic_count =        # blank enables automatic road-network scaling
pedestrian_count = 20
cyclist_count = 8

[audio]
master_volume = 1.0
music_volume = 0.2
effects_volume = 1.0

[police]
taxi_stop_cameras = false

[cities]
helsinki = 60.169525, 24.935446
oulu = 65.012000, 25.468000
```

`[game] language` selects Finnish (`fi`) or English (`en`). Leave it blank only for the first-run language chooser. The pause menu can change and save the language and audio values while playing.

`[police] taxi_stop_cameras` is disabled by default. Set it to `true` when testing cameras near taxi stops; regular speed cameras are still placed from the connected road network. The persistent `user_agent_id` is generated automatically and should not be edited.

The `[cities]` section accepts any city name followed by `latitude, longitude`. Invalid coordinate entries are ignored. Command-line flags override matching INI values for the current launch.

### Windows Release

Push a version tag to build and publish a Windows package containing `RoadRageTrip.exe`:

```bash
git tag v0.2.0beta
git push origin v0.2.0beta
```

GitHub Actions builds the package on Windows with PyInstaller and attaches `RoadRageTrip-windows-x64.zip` to the GitHub Release. Extract the zip and launch `RoadRageTrip.exe`; no Python installation is required.

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
| `R` | Respawn car on a random road (penalizes active fare if client onboard) |
| `X` | Cancel / discard active pickup or onboard passenger mission (score penalty) |
| `T` | Reset trip meter to 0 |
| `L` | Toggle street & feature name labels |
| `K` | Toggle lane keep assist |
| `V` | Toggle speed limiter |
| `B` | Toggle traffic-light assist |
| `Space` | Rage shout: move NPC cars ahead aside within 50 m |
| `P` | Open taxi phone and select a ride |
| `1` - `3` | Select a ride offer in the taxi phone |
| `F1` | Open controls and game objective |
| `Esc` | Open pause menu (Continue, Help, Settings, Change City, Exit) |

The pause menu's **Settings** screen changes language and master, background, and effects volume. Left/right adjusts values; Escape returns to the pause menu.

---

## CLI Options

| Flag | Description |
| :--- | :--- |
| `--preset` | Named preset (`oulu`, `helsinki`, `tampere`, `espoo`, `turku`, `vantaa`, `jyväskylä`, `kuopio`, `lahti`, `sysmä`, `pori`) |
| `--bbox` | Custom bounding box: `south,west,north,east` |
| `--no-menu` | Skip interactive city selection startup menu |
| `--use-sample` | Skip network and use bundled offline sample JSON |
| `--force-refresh` / `--no-cache` | Ignore disk cache and query Overpass fresh |
| `--cache-ttl` | Override cache TTL in seconds (default: 86400 / 24h) |
| `--px-per-m` | Initial camera zoom (default: `0.7`) |
| `--log-level` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `--auto-fetch` | Enable non-blocking background tile fetching near bounds |
| `--no-auto-fetch` | Disable on-demand background map expansion |
| `--fetch-margin` | Margin in meters from bounds triggering auto-fetch (default: `800.0`) |
| `--fetch-tile-size`| Meters to expand when auto-fetching (default: `2500.0`) |
| `--traffic-count` | Target number of autonomous NPC cars (default: `25`) |
| `--pedestrian-count` | Target number of pedestrians (default: `20`) |
| `--cyclist-count` | Target number of cyclists (default: `8`) |

---

## Testing

Run unit tests with pytest:
```bash
pytest tests/ -v
```

Run in headless / CI environments without a physical display:
```bash
SDL_VIDEODRIVER=dummy python3 road_rage_trip.py --use-sample
```
