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
  - `osm.py`: Overpass API querying, disk cache, multipolygon parsing, `Way`/`Water`/`Building`/`Scenery`/`Place` dataclasses, `AutoFetchManager`.
  - `physics.py`: `Car` dataclass, vehicle dynamics, steering, `SpatialWayGrid`, and road boundary containment collision checks.
  - `render.py`: Pygame viewport-culled rendering for roads, waters, buildings, scenery, triangular car, HUD, labels, and compass widget.
  - `main.py`: CLI parser, preset handler (`--preset oulu`/`helsinki`), logging setup, and main game loop.
- `road_rage_trip.py`: Root backward-compatible shim delegating to `theroadragetrip.main`.

Important implementation details for an AI agent
- BBOX order is (south, west, north, east) lat/lon. Presets stored in `BBOX_PRESETS`.
- Transformer is created with `always_xy=True` and expects lon,lat input; be careful not to swap lat/lon.
- Roads filtered by `tags.get("highway", "unclassified")` — adding new OSM types should account for missing tags.
- Waters parsed from `natural=water`, `waterway`, `landuse=reservoir`, and relation multipolygons.
- Widths: see `HIGHWAY_HALF_WIDTH` (half-width meters). Rendering thickness = half_width * 2 * PX_PER_M.
- Units: internal geometry uses meters (EPSG:3067) and rendering scales meters→pixels via `PX_PER_M`.
- CLI & controls: supports `--bbox`, `--preset`, `--force-refresh`, `--use-sample`, `--cache-ttl`, `--px-per-m`, `--log-level`, `--no-cache`, `--auto-fetch`, `--fetch-margin`, `--fetch-tile-size`.
- In-game controls: WASD / Arrows to drive, `+/-` to zoom, `R` to respawn on a random way, `T` to reset trip meter, `L` to toggle labels.

External integrations & failure handling
- Overpass API endpoints are in `DEFAULT_OVERPASS_ENDPOINTS`. Requests have retries, exponential backoff, and per-endpoint attempts.
- On total failure, code falls back to `sample_osm.json` (or `sample_osm_large.json`) via `load_local_sample()`.
- Environment override: `OVERPASS_ENDPOINTS` (comma-separated) can be used to change endpoints at runtime.
- Caching: fetched responses are saved to `osm_cache/` with TTL controlled by `OSM_CACHE_TTL` (seconds) and cache usage can be forced or disabled with `OVERPASS_FORCE_REFRESH` or CLI flags (`--force-refresh`, `--no-cache`).
- Logging: the PoC uses `logging` (configure with `--log-level` or `LOG_LEVEL` env var).

Conventions & patterns
- Single-file PoC (`road_rage_trip.py`) kept intentionally simple; prefer small, local helper functions (geometry, IO, rendering) over large classes for now.
- Use dataclasses for simple domain types (e.g., `Way`, `Car`). Keep code imperative and explicit for readability by humans and LLMs.
- Error handling: network failures are surfaced with print statements; the program exits with `sys.exit(1)` on critical failures (no ways loaded).

Developer workflows / tests
- There are no unit tests yet; `test_fetch_sample.py` is a quick script to validate the bundled sample JSON.
- To add tests: isolate fetching/parsing logic (`fetch_osm_ways`/`build_ways`) and test with sample JSON fixtures.
- Suggestion for CI: cache Overpass responses, stub network calls, and run Pygame display in dummy mode.

Tasks an AI agent can safely start with
- Add caching of fetched OSM responses to disk for repeatable runs.
- Expand `sample_osm.json` with larger/more realistic geometry and add unit tests for `build_ways` and `is_on_road`.
- Add a CLI flag to choose BBOX or to force sample mode.
- Improve logging (use `logging` instead of `print`) and add structured debug messages.

Notes & pitfalls
- Pygame requires a display; CI and headless devs must use `SDL_VIDEODRIVER=dummy` or mock the display.
- Overpass queries can be slow or return 5xx; the code already retries but tests should avoid depending on live Overpass.

If anything is unclear or you want more detail (examples of tests, or a cached-response implementation), tell me which area to expand and I will iterate. ✅

Always use python virtual environments for dependency management, default .venv is fine.

Follow the best practices with type hints, docstrings, and readable code. Add comments where helpful.

Follow the best practices with directory structure and modularization when refactoring the single-file PoC into multiple modules.

Keep tests in a separate `tests/` directory when adding them.

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
