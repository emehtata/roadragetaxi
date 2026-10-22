---
name: repro-at
description: Reproduce a Road Rage Trip bug headlessly at the exact map spot of a player's F12 screenshot (or given world coordinates) - load the real map around it, fake the client view, tick the simulation and measure. Use when a report comes with a screenshot (screenshots/*.json) about traffic, people, collisions, routing, fares or anything the server decides.
---

# repro-at

Bug reports here usually come with an F12 screenshot: `screenshots/screenshot_N.png`
plus `screenshot_N.json` (the server's state - car pose, taxi, NPC counters,
auto-fetch, world bounds). Reproduce **at that spot on the real map** before
theorising; measure before and after a fix.

1. Read the newest dump: `ls -t screenshots | head -2`; view the PNG, read the JSON.
2. Copy the template to the scratchpad and edit `probe()`:
   ```bash
   cp .claude/skills/repro-at/repro_at.py <scratchpad>/repro_x.py
   PYTHONPATH=src timeout 1500 .venv/bin/python <scratchpad>/repro_x.py --json screenshots/screenshot_N.json --speed 25 --seconds 30
   ```
   Options: `--at X Y` (EPSG:3067 metres) instead of `--json`, `--heading`,
   `--city`, `--start-time`, `--speed` / `--seconds` (driven straight along the
   heading), `--box-km` (default 3), `--view W H` (default 142 x 80 m, the
   1280x720 view at the default zoom - simulation bounds follow it).
3. `probe(server, car, report)`: `server.world` has ways, buildings,
   railings, waters, npc_manager, pedestrian_mgr, taxi_mgr, traffic_mgr;
   `run(server, car, seconds, speed, report)` ticks while driving and prints
   tick time; `report(label)` prints NPC / people / taxi counters.
4. To compare with the code before your change: `git stash` (stashes test
   files too - or copy the old file from `git show HEAD:path`), run, restore.

## Notes

- The first run in an area after a world-cache format change, or a new area,
  rebuilds the world (several minutes, sometimes >10): run it with
  `run_in_background` rather than a short timeout.
- The script must stay guarded by `if __name__ != "__main__": raise SystemExit` -
  the server's helper process re-imports it (without the guard everything
  runs twice).
- The car keeps driving straight off the 3 km box at speed: no map streams in
  headless runs, so traffic vanishes there - keep runs inside the box.
- The straight drive ignores streets: it crashes into buildings, trees and
  fences (score and notes change). Pick a heading along a road, or measure
  standing still, when crashes would muddle what you are looking at.
- Fares and rail pre-bookings open only when a client connects; the template
  opens them itself.
- Useful counters: `npc_manager.population_diagnostics`,
  `npc_manager.route_job_stats` (including `discard_reasons`).
- Project a world point onto the screenshot: screen x = 640 + (x - cam_x) * px_per_m,
  y = 360 - (y - cam_y) * px_per_m (`world.camera` in the JSON) - draw the
  footprint on the PNG with PIL to compare with what the game shows.
