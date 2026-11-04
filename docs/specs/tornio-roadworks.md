# Tornio live roadworks: tidy barriers, taxi not stopped at open lane

## Goal
Live lane-closure pieces from consecutive ways draw one barrier per real run end
(not per piece), and the taxi is stopped only on the genuinely closed half.
Hypotheses H1/H2 below are UNCONFIRMED; measure first, fix only what is confirmed.

## Step 0: measure (no code change)
Use `.claude/skills/repro-at/repro_at.py` with `--road-digitraffic` at 370019.1 7305508.6
(Tie 21 Tornio, ways 1552544935/6). Dump the zones (way id, start, end, lane_closed),
drive the taxi through at heading 0.512, count `entered_roadwork` events and the
zones that bar each. Record numbers in the commit message.
- H1: `open_ends` counts shared endpoints over all rows; pieces of the two ways
  rarely meet at identical (0.5 m snapped) points, so interior pieces look open.
  Confirm: count open ends vs. run ends (expect ~2 per contiguous run).
- H2: `Roadwork.in_closed_lane` uses "right of start->end"; a way digitised against
  travel closes the other half, so both halves can be barred. Confirm: for a point
  on each half, count zones whose `in_closed_lane` is true (expect exactly one half).

## Files to change (only the confirmed ones)
- `godot/entity_layer.gd` `open_ends(rows)`: snap tolerance / match ends across
  ways (endpoint within ~1 m of another row's endpoint counts as joined); a run end = an endpoint with no neighbour. Keep it O(n) via a 1 m `Vector2i` cell
  map (also look up the 3x3 neighbouring cells), cached per state snapshot.
- `src/theroadragetrip/roadworks.py` `Roadwork.in_closed_lane`: closed half must be
  the same physical side per carriageway, independent of piece digitisation. Prefer
  fixing in the builder: `digitraffic_road.py` `match_roadwork` `pieces()` orients
  each piece along the road's direction of travel (from the live feed / way
  `oneway` or the situation's direction) before creating `Roadwork`, so the shared
  `in_closed_lane` stays unchanged. Choose whichever H2 measurement supports.
- `src/theroadragetrip/simulation.py` `_roadwork_bars`: no change expected
  (must keep `applies_to(layer, map_level)`).

## Acceptance criteria
1. A chain of N pieces over two consecutive ways (joined end to end) yields at most 2 open ends per
   contiguous run (no barrier on interior pieces).
2. Genuine run ends of a lone way still report open (barrier drawn).
3. (N/A, H2 refuted: no overlapping ways measured) For overlapping ways digitised in opposite directions, a point on one half of
   the road is `in_closed_lane` for zones on exactly one half, never both.
4. (N/A, H2 refuted; taxi-entry counts not measured, see Step 0 results) Driving the taxi along the open half through the zone triggers
   `entered_roadwork` zero times; driving on the closed half triggers it once.
5. Zones with a different `layer`/`map_level` never bar the taxi.
6. `open_ends` / zone building stay linear in piece count; no new caps.

## Tests to add
- Godot: `godot/tests/run_tests.gd` headless checks for `open_ends` on offset-joined
  rows and an 8-piece chain over two ways (criteria 1, 2); they fail unfixed (H1).
- `tests/test_roadworks.py::test_roadwork_on_another_layer_or_level_never_bars_the_taxi`
  (criterion 5).
  The Python tests for H2 were dropped because H2 was refuted (see Step 0 results).

## Out of scope
- NPC cars without windows (3D model rendering; needs the user's GPU machine).
- Visual acceptance: NEEDS SCREENSHOT (barriers look right, taxi drives through),
  via a named scenario in `tools/visual_scenarios.json` on the GPU machine.
- Traffic-law behaviour for NPCs at roadworks (docs/finnish-npc-traffic-law.md).

## Step 0 results (2026-11-04)
Live repro was not possible: Overpass returned 403/502, so the map did not load. The
measurement uses the zones in `screenshots/screenshot_1793780381910649088.json`
(situation GUID50465811) and the way geometry from the OSM API.
- Ways: 1552544935 (node 14125282619 to 55232726), then 1552544936 (55232726 to
  55232730), 25842924, 1552506696 and 48116333. They join end to end, none is oneway,
  all are digitised in the same direction (north), and none overlaps another.
- H1 CONFIRMED (at a way junction only). Pieces on one way share exact ends. Way
  1552544935's last piece ends at 58.9 m (the way's end); way 1552544936's first piece
  starts at 0.1 m. The ends are about 0.1 m apart and can snap to different 0.5 m
  cells, so the run showed 2 open ends in its middle. With the fix it has 2 open ends
  per run. `entered_roadwork` counts were not measured (no map).
- H2 REFUTED: no overlapping or opposite-digitised ways. Criteria 3 and 4 are N/A.
  `in_closed_lane` and the builder are unchanged, and their tests were not added.
- Out of scope: the "endpoint lying on another row's interior" join. The measured gap
  is an end-to-end junction (0.1 m) and the 1 m end-to-end tolerance covers it. A
  T-junction of pieces is not seen in the data.
- Per-frame cost: `open_ends` runs from `EntityLayer._live_roadworks` (called in
  `_draw`). Its result is cached per state rows array (`is_same`), so it runs once
  per state snapshot, not once per frame.
