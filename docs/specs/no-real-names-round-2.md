# No real names in tests, round 2

## Goal
Finish removing real-world business, venue and place names from tests and
visual scenarios. Behaviour is unchanged; only test names and strings change.

## Rule
- Businesses, venues, buildings and named places become generic test names
  (for example "Test Mall", "Test Hall", "Test Street").
- Persons become placeholders (for example "Alice", "Test Person").
- Municipalities, coordinates and recorded fixtures stay as they are.
- Do not write any real name in specs, commits or PRs, including removals.

## Owner-approved exceptions (keep as is)
- tests/test_level_collision.py:104
- tests/test_navigation_route.py:139
- tests/test_protests.py:233
- godot/tests/run_tests.gd:1704
- tests/test_train_timetable.py:160
- godot/tests/run_tests.gd:291
- The owner-approved home-lane name: approved as a name, wherever it is used
  (tests, godot/tests/data, and the existing docs/specs spec that uses it)
- godot/tests/run_tests.gd:292: league names in the credits check; they are
  the data-source attribution, checked against the game's real credits text
- Train numbers (godot/tests/run_tests.gd, tests/test_rail_meet_greet.py,
  tests/test_train_compositions.py): timetable identifiers, not names
- Competition keys and fixture ids ("liiga", "veikkausliiga:...") in
  tests/test_arena_crowds.py and tests/test_sports_fixtures.py: code and
  fixture identifiers, not names; tests/test_arena_crowds.py:192 asserts
  the bundled fixture
- The colour word "valko" in test building names is needed by the colour
  lookup (colour from a Finnish colour word in the name); it is not a name
- tests/test_save_slots.py:25,104,106: the plain Finnish word for "home
  street" (generic, not the owner-approved home-lane name)
- tests/test_arena_crowds.py:192: asserts the bundled fixture (recorded data)
- Parked roadworks scenario coordinates in tools/visual_scenarios.json

## Files to change (residue to neutralise, file:line)
- tests/test_taxi.py:214,220,882,884
- tests/test_trams.py:117,121,123
- tests/test_arena_crowds.py:36,37,164,173,178,192
- tests/test_server_headless.py:74
- tests/test_build_ways.py:275,277,280
- tests/test_is_on_road.py:142
- tests/test_junction_oneway.py:25,58
- tests/test_static_world.py:4,20
- tests/test_scenery_and_buildings.py:185
- tests/test_station_announcer.py:61,148,156
- tests/test_extract_places.py:53,63,118,201
- tests/test_long_fare.py:93

Where a name is also asserted against code output or a fixture, rename both
sides consistently in the test; do not touch recorded fixtures.

## Acceptance criteria
1. A grep for real business, venue and place names over tests/*.py,
   godot/tests/*.gd and tools/visual_scenarios.json matches only the
   owner-approved exceptions above and municipality names.
2. Full `pytest` passes with the same test count as before the change.
3. Full Godot test run passes with the same counts as before
   (run with `XDG_DATA_HOME=$(mktemp -d)`).
4. Every visual scenario touched by a rename passes its readiness checks
   (docs/visual-testing.md).
5. No test is deselected, skipped or weakened to get there.

## Tests to add
None. Existing tests are the check: each renamed test fails if a rename
breaks a string match (for example in tests/test_extract_places.py and
tests/test_station_announcer.py).

## Commits
- Rename work: atomic commits, one per logical group of files.
- The parked roadworks block in tools/visual_scenarios.json is committed in
  its own separate commit once the tests are clean (criteria 1-4 hold).
- Check `git branch --show-current` before each commit; push only if asked
  per project practice.

## Out of scope
- Names in docs, map data, or recorded fixtures.
- Changing municipality names or coordinates.
- Any behaviour or game-logic change.
