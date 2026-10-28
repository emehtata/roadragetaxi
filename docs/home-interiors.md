# Selected-home floor plans

Choose a home with the existing **H** action while stopped in a detached house's
yard. Open **Esc → Home floor plan** to inspect it. **Back / Esc** returns to the
pause menu; Resume returns to driving. No physical entry into the house is needed.
The UI and errors support English, Finnish and German.

## Architecture audit and implementation

- `osm/build.py` imports `Building.points_m`, bounds, house type, address and
  entrances. `Building` does not retain OSM object IDs. Generated house parking
  already identifies its source building by bounds rounded to centimetres
  (`parking._house_parking_key`). Home selection reuses this identity rather than
  changing the importer, caches or exterior chunks.
- `home.py` already saves a yard position and heading per city, either in the
  career homes file or the gig save slot. It now adds an optional `building_key`.
  Existing positional saves still work and acquire a building key when their
  loaded house is first inspected. Clearing homes clears the key too; ordinary
  save-slot writes preserve it. Selection validates the actual house polygon and
  keeps the previous home when validation fails.
- `SimulationServer` resolves the house through the existing building grid around
  the saved yard. A generated parking bay's source key takes precedence over a
  nearer neighbour. It never substitutes a neighbour for a saved building key.
- The existing newline-delimited JSON protocol carries an optional strict boolean
  `home_interior` on a command envelope. The server replies once to that connection
  with `{"type":"home_interior","version":1,"plan":...}`. Layouts are not added
  to recurring state or world-chunk messages.
- `interior.py` owns generation independently of Godot. Shapely was already a
  project dependency. The footprint is validated and normalized, translated into
  local metres and aligned temporarily with its longest bounding-box axis. A
  straight hall divides clipped wings into connected, non-overlapping rooms.
  Doors remove openings from the shared wall linework and swing into their
  destination room. Furniture candidates must fit the room and clear doors,
  other furniture and routes from the doors to a room's interior point.
- The seed uses SHA-256 of the existing building key and generator version.
  A bounded eight-entry cache includes the complete normalized footprint,
  entrance and generator version, so changed source geometry regenerates a plan.
  Generation happens only on request, with at most six wing rooms and bounded
  furniture candidates. No geometry work is added to normal frame updates.
- `startup.gd` adds the action to the existing pause menu. The separate
  `home_interior.gd` Control uses the shell's foreground CanvasLayer, simple
  procedural furniture shapes, room colours and a numbered legend. It uniformly
  scales the complete plan and flips the map's north-positive Y for Godot.
  While waiting for the reply, the shell polls the paused `SimClient`; it does
  not change its processing mode, the game camera or the game's pause state.
  Held driving keys are cleared before opening. Closing is safe during loading,
  after an error, or after a lost connection.

## Changed files

- Generation and persistence: `src/theroadragetrip/interior.py`, `home.py`,
  `server/__init__.py`, `localization.py`.
- Presentation and transport: `godot/home_interior.gd`, `startup.gd`,
  `sim_client.gd`, `i18n.gd` and the new Godot script UIDs.
- Checks: `tests/test_home_interior.py`, updated home fixtures in
  `tests/test_home.py`, `godot/tests/home_interior.gd`, and its `Makefile` entry.

## Validation (2026-10-28)

- **139 Python tests passed** across home/interior, save-slot, protocol,
  headless-server, home preparation and client/server integration suites.
  Geometry cases include rectangular, irregular convex, concave, tiny, narrow,
  U-shaped, rotated, reversed-winding, invalid and non-finite footprints.
  Checks cover deterministic regeneration, changed seeds and geometry/version
  cache keys, room coverage and overlap, room connectivity, door openings and
  swings, furniture containment and clearance, and furnished bedrooms.
- A real loopback TCP test selects a house through H, persists its identity and
  receives its generated plan through the actual server dispatch and transport.
- **3,522 Godot checks passed** with isolated temporary user data. The broader
  existing suite still reports shutdown resource leaks and synthetic input
  diagnostics; these are not introduced or fixed here.
- The dedicated Godot lifecycle script passed: menu discoverability, missing-home
  guidance, connection failure, Esc and Back, cleared driving keys, unchanged
  camera and client processing mode, and return to the pause menu and game.
  It is included in `make godot-test`.
- Rendered and visually inspected rectangular, concave and compact Python-generated
  plans in the real viewer at **1280×720 and 800×600**. Screenshots are in
  `/tmp/rrt-home-{rectangle,concave,compact}-{1280,800}.png` for this session.
  Also started the real sample-map Python server and Godot game and inspected
  night/day exterior screenshots. Rendering used Linux Godot 4.7.2 with Mesa;
  no native GPU performance claim is made.
- Python static analysis and `git diff --check` passed.

## Intentional limits

These are generated ground-floor concepts, not surveyed interiors. A footprint
that cannot support the straight hall receives an open-layout fallback; an
extremely small house may have no furniture. There are no additional floors,
walkable interiors, physics or NPC interior activities.

The house must already exist in the loaded map. An unloaded or changed home
shows guidance instead of fetching more map data. Its identity follows the
existing parking key: changed bounds require selecting the house again, and
coincident duplicate footprints share that identity. Persisting OSM object IDs
would require a separate importer/cache migration.

The automated network test and visual fixture/lifecycle tests exercise separate
parts of the flow. A human driving to a real OSM house, selecting it, quitting and
reopening its viewer has not been manually exercised in this session.

Ponytail was used to keep this within existing home, save, geometry and UI
systems. Graphify was requested but no executable, skill, connected tool or local
installation was available; references and callers were traced directly with
repository searches instead. Shared Godot skill symlinks were broken; the local
`godot-shot` workflow was available and used.
