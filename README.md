# The Road Rage Trip 🚗

A top-down 2D driving game proof-of-concept (PoC) in Python and Pygame that proceduralizes environment creation using real-world OpenStreetMap (OSM) data from Finland.

---

## Features

- **Real-World OSM Road Network**: Fetches and renders actual highway ways from Overpass API (motorways, primary, secondary, residential, tracks, paths).
- **Taxi Game Mode**: Pick up passengers at generated street addresses, drop them off at their destinations, and earn points with speed and distance multiplier bonuses.
- **Navigation Waypoints & Compass Pointer**: Displays visual waypoint zones, address tags, off-screen edge indicators, and compass navigation pointers to client locations.
- **Buildings & Scenery**: Renders building footprints, parks, forests, and green spaces with street/place name labels (`L` key).
- **Water & Multipolygon Rendering**: Renders lakes, reservoirs, and waterways under the road network.
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

On the first launch, the game creates `roadragetrip.ini` in the current directory. Edit that file to set the city, map fetching, zoom, logging, pedestrian, cyclist, and traffic counts. The `[cities]` section contains editable `name = latitude, longitude` entries; add or remove cities there. Command-line options override the INI values for one launch.

For example, set `preset = helsinki` under `[game]` and `traffic_count = 100` under `[traffic]` to run Helsinki with 100 NPC cars.

### Windows Release

Push a version tag to build and publish a Windows package containing `RoadRageTrip.exe`:

```bash
git tag v0.1.0
git push origin v0.1.0
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
| `Space` | Rage shout: move NPC cars ahead aside within 50 m |
| `Esc` | Open pause menu (Continue, Change City, Exit) |

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
