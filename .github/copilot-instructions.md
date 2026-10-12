---
description: This file contains instructions for GitHub Copilot on how to assist with the development of The Road Rage Trip project.
applyTo: **
---

# GitHub Copilot instructions for The Road Rage Trip 🚗

Purpose
- PoC top-down driving game on real-world OSM data (Finland). The game is the Godot client (`godot/`) plus the Python simulation server (`src/theroadragetrip/`); the client starts the server and talks JSON to it over TCP.

Quick start (commands)
- Install deps: `make install` (creates `.venv`)
- Run the game: `make run` (Godot; it starts the server)
- Server alone / client alone: `make run-server PRESET=helsinki`, `make run-godot`
- Tests: `make test` (pytest, mocks pyproj), `make godot-test`, `make godot-selftest`, `make audio-check`
- Custom Overpass endpoints: `OVERPASS_ENDPOINTS="https://overpass.kumi.systems/api/interpreter" make run-server`

High-level architecture / data flow
- `server/`: the server loop (`SimulationServer`), its CLI, live map expansion (`map_sync.py`).
- `world_loader.py`: loads and builds a city's world (OSM fetch, caches, derived structures).
- `simulation.py`: one gameplay tick (`advance_simulation`), input as `PlayerCommand`.
- `protocol.py` / `transport.py`: the JSON messages and the per-client sockets.
- `map_chunks.py` / `static_world.py`: the static map in chunks for the client, styles from `building_style.py`, `map_style.py`, `street_lights.py`.
- `osm/`: Overpass/PBF fetching, caching, parsing, tile streaming.
- `physics.py`, `npc.py`, `pedestrian.py`, `traffic_world.py`, `taxi.py`, `trains.py`, `weather.py`, `calendar.py`: the simulation's domains.
- `godot/`: the client - `main.gd` (connection, input, state), `map_chunk.gd` / `map_layer.gd` (map), `entity_layer.gd` (vehicles, people, trains), `hud.gd`, `audio_manager.gd`, `startup.gd` (menus).
- `road_rage_server.py`: entry point of the bundled server (PyInstaller, Windows release).

Important implementation details for an AI agent
- BBOX order is (south, west, north, east) lat/lon. Presets stored in `BBOX_PRESETS` and `CITY_CENTERS`.
- Coordinate systems: OSM and BBOX values use geographic degrees in `(lat, lon)` order; BBOX remains `(south, west, north, east)`. `pyproj` with `always_xy=True` expects `(lon, lat)` and returns EPSG:3067 metric `(x, y)`. Internal geometry, spatial grids, physics, and rendering use `(x, y)` meters; convert back to lat/lon only at OSM/API boundaries. Never pass `(lat, lon)` directly to the transformer or mix degree values with meter geometry.
- World is north-up: world `x` east, world `y` north. Godot's y points down: convert with `MapMath.point` (y flipped), never by hand.
- The server decides, the client draws: anything the simulation decides (traffic-light phase, route, darkness, a booking's step) is sent, never recomputed in GDScript.
- Roads filtered by `tags.get("highway", "unclassified")` - adding new OSM types should account for missing tags.
- Waters parsed from `natural=water`, `waterway`, `landuse=reservoir`, and relation multipolygons.
- Widths: see `HIGHWAY_HALF_WIDTH` (half-width meters).
- Budgeted work: map sync and street-light placement run in resumable steps (`performance.advance_chunked`, `MAP_SYNC_BUDGET_S`) so a 30 Hz tick never stalls.
- CLI: `python -m theroadragetrip.server --help` (the Godot client passes options after `--`).

External integrations & failure handling
- Overpass API endpoints are in `DEFAULT_OVERPASS_ENDPOINTS`. Requests have retries, exponential backoff, and per-endpoint attempts.
- Bundled sample data (`sample_osm.json`) only with `--use-sample`.
- Environment override: `OVERPASS_ENDPOINTS` (comma-separated) can be used to change endpoints at runtime.
- Caching: OSM JSON under the user cache dir with TTL, built worlds as `.rwc` files; `--force-refresh` / `--no-cache` bypass them.
- Logging: `logging` (configure with `--log-level`).

Conventions & patterns
- Modular architecture under `src/theroadragetrip/`.
- Use dataclasses for simple domain types (e.g., `Way`, `Car`, `Pedestrian`, `TaxiPassenger`).
- Keep code imperative and explicit for readability by humans and LLMs.
- Optimize and profile every new world object or feature before considering it complete; world growth must not regress FPS or the tick.
- Error handling: network failures surface logging warnings; exit on unrecoverable errors.

Developer workflows / tests
- Python tests in `tests/` (`pytest tests/`); Godot tests in `godot/tests/` (`make godot-test`). The whole suite must pass.

Notes & pitfalls
- Overpass queries can be slow or return 5xx; the code already retries but tests should avoid depending on live Overpass.

If anything is unclear or you want more detail (examples of tests, or a cached-response implementation), tell me which area to expand and I will iterate. ✅

Always use the project virtual environment for Python work. Create/use `.venv`, activate it before installing dependencies, running tests, compiling, or launching the server: `source .venv/bin/activate`. Never use system Python or install project packages globally.

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
