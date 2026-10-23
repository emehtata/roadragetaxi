# The Road Rage Trip 🚕

A top-down taxi game on real Finnish streets. Pick up fares, keep the meter
running, and play an antihero whose rage can shout traffic out of the way.
The game uses a Godot client and a Python simulation server.

This is an **alpha**: traffic, routing, map loading and rendering are still being
refined. Bugs and performance problems remain.

## Play

### Windows

Get the installer or portable ZIP from [GitHub Releases](https://github.com/emehtata/roadragetaxi/releases).
Run `RoadRageTrip-Setup.exe`, or extract the ZIP and launch `RoadRageTrip.exe`.
The Windows package includes the simulation server and the tool needed to read
local maps; you do not need to install Python separately. Tagged builds appear
there after the release workflow finishes.

On first launch, choose **Suomi**, **English** or **Deutsch**, then review the
settings. Choose a career or a freelance shift. Freelance mode lets you select
a city or click a starting point on the Finland map, then choose a date and time
from the past year through today. Loading shows the current stage and elapsed
time; a cold map load can take longer than a cached one.

Use **F** to enter the taxi and **E** to start the engine. Open the phone with
**P** or **N** to find your first fare.

### Miksi rattiraivo?

Lyhyt pinna. Yliluonnollinen raivo. Asiakas odottaa, mutta koko katu seisoo.
Sinä et. Kerää tarpeeksi raivoa, huuda muut kuskit sivuun ja paina kaasu pohjaan.
Ei sankaripuheita. Taksamittari käy.

## What is in the game?

- **Real Finnish streets:** cities, roads, buildings, waterways, bridges and
  parking garages based on map data. Garage entrances are currently closed while
  driving support is under development. New areas load as you travel.
- **Fares and a shared phone:** accept requests, wait at taxi stands or pick up
  someone hailing a cab. The same movable phone shows turn instructions,
  distance and street names during an accepted fare. A missing route is shown
  as a GPS error rather than a usable instruction.
- **Group fares:** carry up to four passengers. Children travel with their
  parent under the game's family policy.
- **Rage as a superpower:** with enough rage, **Space** spends a quarter of the
  meter and immediately shifts other cars to the roadside. Clearance stays
  active for at least ten seconds and looks ten driving seconds ahead along
  loaded roads, even at 210 km/h. This is an arcade power, not invulnerability:
  buildings, pedestrians, trains and road edges can still be hazards.
- **Traffic and residents:** moving cars, vans, trucks, buses and work vehicles,
  parking, pedestrians, crossings, traffic lights and roadside arguments.
  Residents have identities and activities. Traffic is enabled, but it is not
  a flawless model of Finnish road behavior.
- **Taxi business:** a time-and-distance fare meter, tips, a game-money balance,
  career progression and a persistent odometer. Passenger satisfaction affects
  tips; rough cornering, speeding and braking can make passengers feel sick.
- **Weather and seasons:** optional real-world weather, rain and puddles,
  water ripples, snow on roads and roofs, snowy tyre tracks, ploughing and
  spring ice floes. Daylight, building shadows, streetlights and headlights
  change the look of a shift. Lunar rise, transit, set and phase are calculated
  for the selected city and currently reported in the startup debug log.
- **Railway activity:** trains and station announcements, real timetable support,
  and prebooked station pickups that may require meeting the passenger on foot.
- **Fuel and consequences:** start/stop the engine, refuel at a pump, and watch
  your consumption. Collisions and traffic violations cost points. Speed cameras
  appear occasionally on main roads during play, not as a batch of twenty at
  startup.
- **Calendar events:** New Year fireworks, Halloween pumpkins and lanterns, and
  Santas on Christmas Eve.
- **Three text languages:** Finnish, English and German menus, notifications and
  speech subtitles. Missing driver/passenger recordings fall back to Finnish
  audio while subtitles retain the selected language. Station announcements
  remain in Finnish.

## Controls

| Key / input | Action |
| :--- | :--- |
| `WASD` / arrow keys | Drive, brake/reverse or walk |
| `Shift` | Run while on foot |
| `F` | Enter/exit the taxi; greet a booked passenger |
| `E` | Start/stop the engine |
| `P` / `N` | Open/close the shared phone: offers when free, navigation during a fare |
| `1`–`3` / `Enter` | Accept an offer by number / accept the selected phone offer |
| `X` | Decline a phone offer, or cancel the active fare when not choosing an offer |
| `Space` | Rage shout when enough rage is available |
| `G` | Refuel while stopped at a pump |
| `K` / `V` / `B` | Toggle lane assist / speed limiter / traffic-light assist |
| `C` | Toggle compass |
| `J` | Toggle train arrivals/departures board |
| `L` | Cycle labels: none, streets, all places |
| `R` | Reset the taxi to a road; an onboard fare can incur a penalty |
| `T` | Reset the trip meter |
| `H` | Return home; stopped in a house yard, press again to confirm a new home |
| `+` / `-` / mouse wheel | Zoom |
| Drag a display / phone header | Move that interface element |
| `U` / `F2` | Reset the interface layout |
| Ctrl+drag / middle-button drag | Pan the view |
| Click a person or vehicle | Inspect and follow it |
| `F1` | Show/hide control help |
| `F3` | Toggle developer diagnostics |
| `F12` | Save a screenshot and matching simulation JSON |
| `Esc` | Close the phone/help or open the pause menu |

Gig saves keep their own homes, one per city. While playing, use
**Settings → Gameplay → Clear current game home** to forget homes only in that
save. Older gig saves start without a home; choose one again with **H** in a
house yard.

The speed limiter starts enabled; press **V** to disable it if you want to drive
above the road's speed limit. Opening navigation also shows the suggested route
on the map; **N** is not a separate route-only toggle.

## Maps, settings and saved data

### Graphics options

**Settings → Graphics** has on/off switches, all enabled by default:

- Building shadows: disabled when 3D buildings are off; the saved preference
  is retained for re-enabling 3D. All other effects are independent.
- 3D buildings: off uses flat footprints without extruded walls. Start a new
  session to apply this option; it never removes building collision geometry.
- Water and puddle ripples.
- Rain and snow particles.
- Tyre splashes.
- Vehicle smoke and exhaust.
- Lightning flashes (thunder sounds remain).

All except the building renderer apply to the current session. Choices are
saved under `[graphics]` in Godot's `settings.cfg`. Turning effects off does not
change the simulation: rain, wet-road grip, snow accumulation, damage, traffic
and collisions continue normally. Road-condition markings, traffic signals and
night-driving lights are intentionally retained. Lower settings can reduce
rendering work; the gain depends on the scene and graphics hardware.

### Map source

Choose the map source in **Settings**:

- **Online map:** retrieves map areas while you play and reuses cached data.
- **Local Finland map (.osm.pbf):** reads the country extract locally.
  If no usable file is found, the game offers to download
  [Finland from Geofabrik](https://download.geofabrik.de/europe/finland-latest.osm.pbf).
  The large download has a progress display and is saved in a user-writable
  directory, not next to the installed executable.

A map file over 30 days old prompts an update offer. **Settings → Finland map**
can force a download or delete the downloaded file. You can also select your
own PBF file. On a source install, local PBF reading needs `osmium-tool` on
`PATH`; the Windows release bundles it. Choosing a local map does not make
optional weather/timetable updates offline.

### Two settings files

- **Godot `user://settings.cfg`:** language, map selection/path, real-weather
  and timetable switches, menu selections and volume settings. Interface
  positions are saved separately in `user://hud_layout.cfg`. Change these
  through the game's menus.
- **Python `roadragetrip.ini`:** server defaults and advanced settings such as
  city definitions, traffic counts, map streaming, speech intervals and logging.
  Godot's selected launch options override the matching server defaults.

The volume controls are **Master**, **Game**, **Environment**, **UI** and
**Music**. Menu music loops across menu screens and pauses during gameplay;
the pause menu plays it again until you resume.
Do not expect the old city-list editor, endpoint editor, or independent comment
audio/subtitle toggles in the Godot settings screen.

Default locations (respecting the relevant OS/XDG environment overrides):

| Data | Linux | Windows |
| :--- | :--- | :--- |
| Godot user directory | `~/.local/share/godot/app_userdata/Road Rage Trip (Godot client)/` | `%APPDATA%\Godot\app_userdata\Road Rage Trip (Godot client)\` |
| Server config and career/home/odometer files | `~/.config/RoadRageTrip/` | `%APPDATA%\RoadRageTrip\` |
| Runtime cache root | `~/.cache/RoadRageTrip/` | `%LOCALAPPDATA%\RoadRageTrip\` |

The Godot directory contains `settings.cfg`, `hud_layout.cfg` and
`maps/finland-latest.osm.pbf`. Under the runtime cache root:

- `osm_cache/`: cached map downloads and extracts;
- `osm_cache/weather_history.db`: weather observations and forecasts;
- `world/`: versioned, checksummed `.rwc` world caches;
- `railway_timetable.json.gz` and `train_compositions.json.gz`: refreshed user
  copies of the bundled railway data.

Weather observations are retained; a failed forecast refresh keeps previous
data, and a missing current hour can use an earlier saved weather hour.
Clearing the map cache preserves weather history. Railway data can be refreshed
online; it is not limited to the bundled copies.

Screenshots go to `screenshots/` under the working directory on Linux and to
`%USERPROFILE%\Pictures\TheRoadRageTrip\` on Windows. **F12** saves the PNG
and asks the server to write its diagnostic JSON beside it.

## Run from source

Use Python **3.12** (the CI version; the package declares 3.10+), Godot **4.7.2**
(the Makefile's pinned version), and
a working graphical desktop. The commands below use a Unix-like shell.
`curl` and `unzip` are needed if Make downloads Godot.

```bash
make install
make run
```

`make install` creates `.venv` and installs `requirements.txt`. On a fresh
checkout, `make run` downloads Godot if the configured binary is missing and
imports the Godot project before opening the launcher. Use
`make run GODOT=/absolute/path/to/godot` to supply your own binary.

```bash
make run-debug                 # launcher with DEBUG logging
make run-pbf                   # launcher using local PBF map data
make help                      # all supported development targets
```

To run server and client separately, keep the first command running in one
terminal, then start the client in another:

```bash
make run-server PRESET=Oulu PORT=8765
make run-godot PORT=8765
```

For an offline sample, start the server with the bundled compressed sample map:

```bash
PYTHONPATH=src .venv/bin/python -m theroadragetrip.server --use-sample --no-historical-weather --no-train-timetable
make run-godot
```

The default server port is **8765**, with a **30 Hz** simulation tick. It is a
local single-player server, not an Internet multiplayer service.

### Advanced server options

`PYTHONPATH=src .venv/bin/python -m theroadragetrip.server --help` lists the
complete CLI. Useful options include:

| Flag | Purpose |
| :--- | :--- |
| `--preset` / `--bbox` | Configured city name / `south,west,north,east` bounding box |
| `--game-mode` | `career` or `gig_driver` |
| `--language` | `fi`, `en` or `de` |
| `--start-time` | Local `YYYY-MM-DDTHH:MM` freelance start |
| `--osm-source` / `--osm-pbf-path` | `overpass` or `pbf`, plus an optional PBF path |
| `--use-sample` | Use the bundled sample instead of fetching a live map |
| `--historical-weather` / `--no-historical-weather` | Enable/disable real weather |
| `--train-timetable` / `--no-train-timetable` | Enable/disable real train timetables |
| `--force-refresh` / `--no-cache` | Bypass cached map data |
| `--no-auto-fetch` | Disable map expansion |
| `--fetch-margin` / `--fetch-tile-size` | Map-streaming distances |
| `--npc-vehicle-count` / `--pedestrian-count` | Traffic-population overrides |
| `--log-level` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |

The Godot launcher forwards its selected settings and supports the
`--log-level`, `--osm-source` and `--osm-pbf-path` overrides after `--`.
It does **not** forward every server CLI option; use a separately started
server for advanced scenarios.

The INI file is created with defaults from
[`config.py`](src/theroadragetrip/config.py). For example, `[speech]`
`min_interval = 45.0` and `max_interval = 120.0` control random passenger
chatter intervals in seconds during an active fare. Situation responses have
separate cooldowns. Use `[game] file_logging = true` for a
`roadragetrip.log` in the working directory; console logging is on by default.
`[map] overpass_endpoints` can be edited in the INI file;
`OVERPASS_ENDPOINTS` takes precedence for a launch.

### Optional PBF index

An index can reduce repeated scans of the country extract. It is not required:

```bash
.venv/bin/python src/theroadragetrip/utils/pbf_index.py /absolute/path/to/finland-latest.osm.pbf
```

The game discovers the index at `<pbf_path>.index` beside the source file.
The utility's `--index-dir` flag changes build output, not the game's lookup path. `make index-pbf` is a convenience
target for the repository's `src/theroadragetrip/assets/osm/finland-latest.osm.pbf`,
not automatically the menu-downloaded file. Updating the source invalidates its
old index. World caches (`.rwc`) and the experimental road-binary scripts are
separate from this optional index; experimental road binaries are not the
default gameplay path.

Enable **Enable intercity fares** in Settings to use major-road navigation
between towns. Download the Finland PBF when prompted; the game initializes
the navigation database before starting and reuses it in later sessions.
Destination streets stream while driving, and the final address is selected
only once nearby map data is available. Unsupported destinations are excluded.
See [national navigation](docs/national-navigation.md) for preparation, coverage
and measurements. The old full-street index is not used by the game.

## Development and testing

```bash
make test                    # Python regression suite
make compile                 # Python compile check
make check                   # tests, compile and diff check
make godot-test              # Godot client checks
make godot-selftest-sample   # short headless client/server smoke test on sample data
make audio-check             # audio catalog, files and references
```

Tests isolate user configuration, saves and caches. Do not point manual
benchmark servers or test replays at your normal player data.

The [Godot client architecture](docs/architecture/godot-client.md) describes the
client/server boundary. For traffic work, read the
[Finnish NPC traffic-law guide](docs/finnish-npc-traffic-law.md): it specifies
requirements and acceptance scenarios, not a certificate of current compliance.
The [performance analysis](.github/performance-analysis/weather-traffic-2026-10-14.md)
is a historical baseline; see the [implementation record](docs/rrt-0.18-progress.md)
for subsequent changes and remaining gaps.

### Project layout

- `godot/`: launcher, presentation, interface, sound and client tests.
- `src/theroadragetrip/server/`: headless server, CLI and map streaming.
- `src/theroadragetrip/`: simulation, taxi fares, traffic, people, weather,
  railways and world loading.
- `src/theroadragetrip/assets/`, `sounds/`, `img/`: bundled data and media
  inside the Python package.
- `tests/`: Python regression tests.
- `tools/`, `utils/`: validation, importers, profiling and asset utilities.
- `web/`: Finnish and English marketing website.

### Windows release workflow

For a candidate build, run the Windows release workflow manually on the branch.
After merging to `master`, create and push a **new, unused** `v*` tag matching
the version in `pyproject.toml`, `godot/project.godot`, Godot export metadata
and `installer/RoadRageTrip.iss`. Do not move or recreate an existing release tag.

The tag workflow builds the Godot client and Python server, smoke-tests the
installer, and publishes the setup EXE, portable ZIP and required third-party
source archives to GitHub Releases. No release assets are built by pushing a
README change alone.

### Audio assets

Runtime speech clips are OGG files under `src/theroadragetrip/sounds/`.
German subtitles are included; German recordings are not required.
The legacy Azure utility supports Finnish/English WAV generation, not German:

```bash
.venv/bin/pip install -r utils/requirements.txt
.venv/bin/python utils/ttsazure.py f src/theroadragetrip/assets/passenger_chatter.json fi
```

It needs `SPEECH_KEY` and `SPEECH_REGION` in `utils/.env` (never commit
credentials), writes WAVs under `utils/output/`, and uses hashes derived from
the Finnish text. It is not part of normal installation or gameplay. Convert
and integrate generated files into the runtime OGG assets separately.

## Licences and data attribution

Synthetic chatter voices (text-to-speech) are stored in `src/theroadragetrip/sounds/` (see its `LICENSE`). Generated sound effects (Stable Audio Open) live in `src/theroadragetrip/assets/audio/`, catalogued in `audio_catalog.json`; the station announcements (Chatterbox TTS) are in `src/theroadragetrip/assets/railway_announcements/`. Their licensing status is in `LICENSE_AUDIT.md`.

Map, timetable and weather data:

- `src/theroadragetrip/assets/places.json.gz` (airports and railway stations) is derived from OpenStreetMap data, © OpenStreetMap contributors, available under the [Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/); the file itself is likewise under the ODbL.
- `src/theroadragetrip/assets/railway_timetable.json.gz` (passenger-train timetable): Source: Fintraffic / [digitraffic.fi](https://www.digitraffic.fi/), license [CC 4.0 BY](https://creativecommons.org/licenses/by/4.0/). Modified: converted from GTFS to a compact one-week timetable by `theroadragetrip/railway_import.py`; the game refreshes its copy from Digitraffic weekly. The data is provided as is, without warranty.
- `src/theroadragetrip/assets/train_compositions.json.gz` (learned train compositions): Source: Fintraffic / [digitraffic.fi](https://www.digitraffic.fi/), license [CC 4.0 BY](https://creativecommons.org/licenses/by/4.0/). Modified: condensed to vehicle type, length and service flags by `theroadragetrip/composition_import.py`, refreshed weekly.
- `src/theroadragetrip/assets/finnish_first_names.json.gz` and `finnish_surnames.json.gz` (resident names): Digital and Population Data Services Agency (DVV) name data, [nimipalvelu.dvv.fi](https://nimipalvelu.dvv.fi/), license [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Modified: the most common names selected and converted to the game's JSON format.
- `src/theroadragetrip/assets/kunnat.json.gz` (municipality population, age structure and area): compiled from Wikipedia, © Wikipedia contributors, license [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Modified: tables combined and converted to the game's JSON format; the file is likewise CC BY-SA 4.0.
- Historical weather, forecasts and snow depth (opt-in, fetched from FMI at runtime and cached locally under the runtime cache root in `osm_cache/weather_history.db`, not bundled): Finnish Meteorological Institute (FMI) open data, license [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Hourly values are combined from the nearest stations and sampled in five-minute steps; temperature is interpolated and all condition transitions (including rain, snow, slush, thunder and clearing) are stably offset within half an hour so they do not change mechanically on the hour. Consecutive hours of the same condition remain continuous.

These credits are shown in the game under **Credits** in the main menu; the map views also show © OpenStreetMap contributors. The licensing audit, with open items, is in `LICENSE_AUDIT.md`; third-party software is listed in `THIRD_PARTY_LICENSES.md`.
