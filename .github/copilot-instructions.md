---
description: This file contains instructions for GitHub Copilot on how to assist with the development of The Road Rage Trip project.
applyTo: **
---

# GitHub Copilot instructions for The Road Rage Trip 🚗

Purpose
- This repo is a PoC top-down driving game using real-world OSM data for procedural environments. The primary script is `road_rage_trip.py`.

Quick start (commands)
- Install deps: `pip3 install -r requirements.txt` ✅
- Run the game (recommended): `python3 road_rage_trip.py` (requires an interactive display; install deps with `pip3 install -r requirements.txt`)
- Quick fallback check: `python3 -m theroadragetrip --use-sample` (verifies bundled samples)
- Run tests: `pytest -q` (tests mock pyproj so pyproj isn't required for unit tests)
- To force using custom Overpass endpoints: `OVERPASS_ENDPOINTS="https://overpass.kumi.systems/api/interpreter" python3 road_rage_trip.py`
- Headless CI: set `SDL_VIDEODRIVER=dummy` or stub Pygame display.

High-level architecture / data flow
- Package split into modular submodules under `src/theroadragetrip/`:
  - `geo.py`: Coordinate projections (`pyproj`), `clamp`, `compute_bbox`, `clip_polygon_to_rect`, `dist_point_to_segment`, `point_in_polygon`, `meters_to_latlon`.
  - `osm.py`: Overpass API querying, disk cache, multipolygon parsing, `Way`/`Water`/`Building`/`Scenery`/`Place`/`TrafficLight`/`Crossing` dataclasses, `AutoFetchManager`, city presets.
  - `physics.py`: `Car` dataclass, vehicle dynamics, steering, `SpatialWayGrid`, road boundary containment collision checks, and lane assist.
  - `taxi.py`: Taxi missions, passenger spawn/pickup/dropoff, fares, and violation checks (red light, collision, wrong-way).
  - `traffic.py`: Autonomous NPC traffic simulation, lane positioning, overtaking, and speed-limit compliance.
  - `pedestrian.py`: Pedestrian walking simulation on footpaths/sidewalks, traffic light crossings, and car dodging.
  - `render.py`: Pygame viewport-culled rendering for roads, waters, buildings, scenery, traffic, pedestrians, car, HUD, menus, and compass widget.
  - `main.py`: CLI parser, preset/city selection menu, pause menu, logging setup, and main game loop.
- `road_rage_trip.py`: Root backward-compatible shim delegating to `theroadragetrip.main`.

Important implementation details for an AI agent
- BBOX order is (south, west, north, east) lat/lon. Presets stored in `BBOX_PRESETS` and `CITY_CENTERS`.
- Transformer is created with `always_xy=True` and expects lon,lat input; be careful not to swap lat/lon.
- Roads filtered by `tags.get("highway", "unclassified")` — adding new OSM types should account for missing tags.
- Waters parsed from `natural=water`, `waterway`, `landuse=reservoir`, and relation multipolygons.
- Widths: see `HIGHWAY_HALF_WIDTH` (half-width meters). Rendering thickness = half_width * 2 * PX_PER_M.
- Units: internal geometry uses meters (EPSG:3067) and rendering scales meters→pixels via `PX_PER_M`.
- CLI & controls: supports `--bbox`, `--preset`, `--no-menu`, `--force-refresh`, `--use-sample`, `--cache-ttl`, `--px-per-m`, `--log-level`, `--no-cache`, `--auto-fetch`, `--no-auto-fetch`, `--fetch-margin`, `--fetch-tile-size`, `--traffic-count`, `--pedestrian-count`.
- In-game controls: WASD / Arrows to drive, `+/-` to zoom, `R` to respawn, `X` to discard fare, `T` to reset trip meter, `L` to toggle labels, `K` to toggle lane assist, `Esc` for pause menu.

External integrations & failure handling
- Overpass API endpoints are in `DEFAULT_OVERPASS_ENDPOINTS`. Requests have retries, exponential backoff, and per-endpoint attempts.
- On total failure, code falls back to `sample_osm.json` (or `sample_osm_large.json`) via `load_local_sample()`.
- Environment override: `OVERPASS_ENDPOINTS` (comma-separated) can be used to change endpoints at runtime.
- Caching: fetched responses are saved to `osm_cache/` with TTL controlled by `OSM_CACHE_TTL` (seconds) and cache usage can be forced or disabled with `OVERPASS_FORCE_REFRESH` or CLI flags (`--force-refresh`, `--no-cache`).
- Logging: the PoC uses `logging` (configure with `--log-level` or `LOG_LEVEL` env var).

Conventions & patterns
- Modular architecture under `src/theroadragetrip/`.
- Use dataclasses for simple domain types (e.g., `Way`, `Car`, `NPCCar`, `Pedestrian`, `TaxiPassenger`).
- Keep code imperative and explicit for readability by humans and LLMs.
- Error handling: network failures surface logging warnings; fallback to local sample where appropriate; exit on unrecoverable errors.

Developer workflows / tests
- Tests in `tests/` run with `pytest tests/ -v`. Tests mock pyproj when needed.
- Headless CI / test run: set `SDL_VIDEODRIVER=dummy`.

Tasks an AI agent can safely start with
- Add caching of fetched OSM responses to disk for repeatable runs.
- Expand `sample_osm.json` with larger/more realistic geometry and add unit tests for `build_ways` and `is_on_road`.
- Add a CLI flag to choose BBOX or to force sample mode.
- Improve logging (use `logging` instead of `print`) and add structured debug messages.

Notes & pitfalls
- Pygame requires a display; CI and headless devs must use `SDL_VIDEODRIVER=dummy` or mock the display.
- Overpass queries can be slow or return 5xx; the code already retries but tests should avoid depending on live Overpass.

If anything is unclear or you want more detail (examples of tests, or a cached-response implementation), tell me which area to expand and I will iterate. ✅

Always use the project virtual environment for Python work. Create/use `.venv`, activate it before installing dependencies, running tests, compiling, or launching the game: `source .venv/bin/activate`. Never use system Python or install project packages globally.

Follow the best practices with type hints, docstrings, and readable code. Add comments where helpful.

Follow the best practices with directory structure and modularization when refactoring the single-file PoC into multiple modules.

Keep tests in a separate `tests/` directory when adding them.

Update `README.md` whenever adding new features, files, commands, settings, or user-facing behavior.

When in doubt, prefer the simplest solution that produces a visible working PoC quickly.

## Core Directives

- **Terse Output**: One sentence max per thought. No elaboration unless asked. Target 50–70% fewer tokens than normal mode.
- **Structure**: Bullets, short code blocks, tables. No prose paragraphs. No greetings, summaries, meta-commentary.
- **Word Budget**: Answer in fewest words that convey meaning. Trim every sentence.
- **Code Same**: Code output is standard (readable, well-formatted). Only chat responses are terse.

## Communication Rules

- Use short, 3-6 word sentences.
- No emojis. No padding. No "here's what I did" narration.
- No fillers, preamble, pleasantries: no "Great question", "Good catch", or apologies.
- Drop articles: "Me fix code" not "I will fix the code."
- Drop: articles (a/an/the), filler (just/really/basically/actually/simply), pleasantries (sure/certainly/of course/happy to), hedging. Fragments OK.
- Short synonyms (big not extensive, fix not "implement a solution for").
- Technical terms exact. Code blocks unchanged. Errors quoted exact.
- Abbreviate (DB/auth/config/req/res/fn/impl), strip conjunctions, arrows for causality (X → Y), one word when one word enough

Pattern: `[thing] [action] [reason]. [next step].`

## Exception: When to Expand

- User asks "explain" → give context, still terse.
- Complex logic needs pseudocode → provide it.
- Architecture decision unclear → ask one concise question.
- Otherwise: stay terse.

---
