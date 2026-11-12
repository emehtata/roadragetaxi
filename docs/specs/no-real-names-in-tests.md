# No real-world names in tests and scenarios

## Goal
Public repo: remove real street, district, square and station names from tests and
scenario files; keep coordinates, "Keskusta" and the cleared campsite name. Rename only.

## Scan result (names are NOT repeated here; N = line numbers, grep the tier patterns)
Tier A (clearly real, must go):
- tools/visual_scenarios.json: street name in "description"/"why" at lines 5-6, 37, 72,
  107, 173, 200, 228, 364; a district name at 173, 256, 364, 477-478 (also id, line 476);
  second district-street pair at 256, 283, 392; street at 332; motorway name at
  508-509, 536-537 (also in the "why"); bridge/street pair at 656-657; ids at line 4
  (district) and 476 (district station); ferry id at 421, 448, 450.
- godot/tests/run_tests.gd: square name at 1304, 1688, 2559, 2562.
- godot/tests/phone_apps.gd: square name at 20.
- tests/test_protocol.py: square name at 104.
- tests/test_navigation_route.py: square name at 94.
- tests/test_trams.py: real square at 105, 109 (OSM-style fixture, keep lat/lon).
- tests/test_extract_places.py: district/ferry-terminal name at 161, 164.
- tests/test_traffic_lights.py: real road names in comments/vars at 243, 262, 367 and
  487-518 (street + road variants).
- tests/test_ferries.py:55: ferry name in a comment.
Tier B (common Finnish street/square words, exist in real cities; neutralise too):
- "Kirkko-", "Tori-", "Iso-" street names: godot/tests/run_tests.gd 1687, 1750-1751,
  2402-2433, 2475, 2559-2563, 2674-2677, 3048, 3090-3094; tests/test_navigation_route.py
  61-126; tests/test_taxi.py 30-36, 312, 664-727; tests/test_localization.py:47;
  tests/test_rail_bookings.py:20; tests/test_rail_meet_greet.py:32;
  tests/test_ride_lifecycle.py:20; tests/test_parking_garages.py 72-79;
  tests/test_is_on_road.py 19-34; tests/test_crossings.py 105-178;
  tests/test_map_chunks.py 594-598; tests/test_server_headless.py 456-457;
  tests/test_protocol.py:103; godot/tests/phone_apps.gd:20.
- Market-square words: tests/test_trams.py 11, 172-179; tests/test_long_fare.py:62;
  tests/test_activities.py:242 (generic bus-stop word; owner decides).
Leave: Keskusta, the cleared campsite, city names (Oulu etc.: world/city ids, not streets),
"The owner-approved home-lane name" ("home lane", already generic), fmi_* XML fixtures (station metadata), coordinates.

## Replacement rule
Generic descriptive name: "Test Street", "Main Street 4", "Market Square", "Station
Square", "Harbour Road", "City-centre street", "Motorway". Keep each name consistent inside
its test (same string in setup and assertion). Scenario text: "city-centre street",
"inner-city district", "motorway through a mid-size city". Do not touch lat/lon.

Person names: no first name, surname or full name from the game's resident-name lists
(src/theroadragetrip/assets/finnish_first_names.json.gz, finnish_surnames.json.gz) in
tests/, godot/tests/ or scenario text; use "Test Person N", numbered per file so each is
unique within a test. Brands and companies (shop chains, fuel brands, operators, venues):
use neutral names ("Test Grocery", "Fuel Station", "Test Garage"). Recorded fixtures
(tests/data, tests/fixtures, godot/tests/data) stay as recorded; a test that needs a
fixture's real value reads it from the fixture instead of a literal.

## Scenario id renames (risk)
Ids appear as: registry key (tools/visual_scenarios.json), result folder
`<out>/<id>/<time>_<stamp>_<commit>/` (tools/visual_test.py:74), `scenario` field of
result.json (visual_test.py:110,132; godot/visual_test.gd:436), and docs.
Only four ids contain real names. Neither tools/visual_test.py nor godot/visual_test.gd
hard-codes any id (they read the registry), so readiness code is unaffected.
- district windshield id (line 4) -> `windshield_city_day`. Refs: docs/specs/sky-cloud-cover.md:25.
- district station id (line 476) -> `train_station_day`. Refs: none outside the registry.
- ferry ids (421, 448, 450 ) -> `ferry_car_3d`, `ferry_car_2d`. Refs: docs/ferries.md:76 and
  the "why" at 450. (Optional: ferry may be tier B; decide with owner.)
- `windshield_oulu_day` is a city name, keep.
Existing result folders under old ids are NOT renamed; new runs create new folders. compare
takes folder paths, so old/new pairs still compare. Search screenshots/ and any
`visual-results` dir for old ids only to note them, never rename.

## Acceptance
1. `grep -rnE '<tier A+B patterns>' tests godot/tests tools/visual_scenarios.json` -> no hits
   (pattern list kept out of the repo; run from the scan notes).
2. docs/specs/sky-cloud-cover.md and docs/ferries.md reference only new ids; grep old ids
   across repo (excl. .git, screenshots/) -> no hits.
3. `.venv/bin/python -m pytest` count identical to before (record before/after).
4. Godot tests (XDG_DATA_HOME=$(mktemp -d), Linux godot headless run_tests.gd): same
   pass/fail counts as before.
5. Run the four renamed scenarios via tools/visual_test.py; each passes readiness where it did
   before (record before status first).
6. One commit per concern: tests, scenarios+docs.

## Out of scope
Renaming existing result folders or screenshots; real names in src/ assets (announcement
ogg names), map data, docs outside the two ids; rewriting git history; city names;
coordinates.
