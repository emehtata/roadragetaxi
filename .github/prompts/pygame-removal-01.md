# Release 0.17.0alpha: remove Pygame completely

Branch: `release/0.17.0alpha` (from master at 5a02ffe). The game is the Godot
client plus the Python simulation server; the Pygame client goes.

Rules for every step: the whole test suite passes (`pytest tests/` with
nothing deselected, `make godot-test`, `make godot-selftest`,
`make audio-check`), one commit per step, check the branch before every
commit and push, never push to master.

## Where things stand (2026-10-11)

The Godot client never touches Pygame. The Python server still leans on
Pygame-era code:

1. **World loading** - `server/__init__.py` builds its world with
   `_load_world()` and picks the city with `_choose_city()`, both in
   `src/theroadragetrip/main/__init__.py` (3,447 lines), still with
   loading-screen / event-loop code inside (`screen`, `pygame.display`).
   Also from `main/`: `cli.parse_args`, `configure_logging`,
   `_level_structures`, `startup_screens._clamp_start_datetime`,
   `debug_tools._write_debug_snapshot`.
2. **Game logic inside `render/`**, used by the server, `map_chunks.py`,
   `static_world.py` and `server/map_sync.py`:
   - `render/roads.py`: street-light placement, parking poles
     (`parking_row_lamps`), `_snapshot_street_light_job`...
   - `render/buildings.py`: colours (incl. Finnish colour names), heights,
     window rules, open roofs
   - `render/common.py`: `road_color_for_way`, `get_viewport_bounds`
   - `render/scenery.py`: `SCENERY_COLORS`, speckle kinds
   - `render/labels.py`: `DISTRICT_PLACE_KINDS`
   - `render/__init__.py`: `generate_detached_house_parking_chunk`,
     `SCREEN_W` / `SCREEN_H`
3. **pygame imports outside the client**: `pygame.time.Clock` in the server,
   `pygame.mixer` in `station_announcer.py` and `audio.py`,
   `tools/validate_audio_assets.py` (`make audio-check`).

Size: `main/` + `render/` about 16,000 lines; 47 of 134 test files import
pygame.

## Phases

### 1. Separate the shared logic (nothing deleted yet)

- `world_loader.py` (new, headless): `_load_world`, `_choose_city`,
  `_resolve_osm_fetch_func`, `_level_structures`, `_latlon_to_world_metres`;
  progress through a callback instead of drawing a loading screen.
- Out of `render/` into plain modules:
  - `street_lights.py` - lamp placement, parking poles
  - `building_style.py` - colours, heights, windows, open roofs,
    building-part colours (`inherit_part_colours` from static_world)
  - `map_style.py` - road / scenery colours, label kinds
  - `parking.py` - detached-house parking generation
- The server's own CLI (merge `main/cli.py` into `server/cli.py`), the debug
  snapshot (`debug_tools`), the start-time clamp, viewport constants.
- The old names stay as thin re-exports so Pygame keeps working in this
  phase; tests move with the logic.

### 2. Make the server pygame-free

- Server tick pacing: plain time-based, no `pygame.time.Clock`.
- `station_announcer.py`: keep the event building (sent to Godot), drop the
  mixer playback.
- `tools/validate_audio_assets.py`: `wave` + file checks, no pygame.
- A guard test: importing the server (and `simulation`, `protocol`,
  `map_chunks`, `world_loader`) never imports pygame.

### 3. Delete the Pygame client

- `road_rage_trip.py`, the rest of `main/`, `render/`, `audio.py`'s
  `AudioManager`, menus / startup screens / menu input.
- Makefile: `run-sample`, `run-pbf-pygame`, any other Pygame target
  (check `audit-ai`); `make run` / `run-pbf` stay (Godot).
- `windows-release.yml`: drop the Pygame zip build.
- `pygame-ce` out of `requirements.txt` / `pyproject.toml`.
- Delete the Pygame drawing tests; the logic tests already moved in phase 1.

### 4. Documentation and release

- Archive `docs/architecture/godot-pygame-rendering-parity.md`; rewrite
  `godot-client.md` and the README as Godot client + Python simulation;
  remove Pygame controls and options.
- Version 0.17.0alpha: `godot/project.godot`, `godot/export_presets.cfg`,
  `installer/RoadRageTrip.iss`, `pyproject.toml`.
- One Windows artifact (game + bundled server + installer); website text.

## Decide before phase 3

Partial in Godot (parity doc) - port first, or accept as they are:

| Feature | Pygame | Godot |
|---|---|---|
| Ground | textured, seasonal grass | flat ground |
| Landuse | vegetation speckle texture | plain fills |
| Water in spring | ice floes | none |
| Bridges | vehicles outlined under a higher road | plain vehicle |
| Two-wheelers | sprites | body + rider |
| Engine sound | idle + three throttle layers | one loop, pitch by speed |
| Start hints | timed get-in / engine hints | done (blue hint box) |

Also ~11 items already marked "Pygame-only / obsolete" (debug overlays,
debug keys, the 2.5D building renderer...) go without replacement.

## Risks

- `_load_world` (~450 lines) is tangled with screen code: the riskiest step.
- Hidden pygame imports through `render/__init__.py` (it imports most of
  the package) - the guard test catches them.
- The career city choice (`_choose_city`) shows Pygame screens when no city
  is given; the server always passes one - keep that path headless.
