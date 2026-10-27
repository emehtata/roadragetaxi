---
name: godot-shot
description: Render the real Road Rage Trip game (Python server + Godot client) and save a screenshot to inspect. Use after any UI or Godot change (AGENTS.md requires a rendered, inspected screenshot), or to see a city, time of day or weather in the actual game.
---

# godot-shot

Starts the simulation server with the given arguments on a free port, runs
the Godot client against it with `--screenshot`, saves the PNG, and stops
the server again (by PID).

```bash
.claude/skills/godot-shot/shot.sh OUT.png [--wait S] [--godot-arg ARG]... [SERVER ARGS...]
```

- `OUT.png`: put it in the session scratchpad (absolute path); then **Read it
  and look at it** - a saved file is not an inspected view.
- `--wait S`: seconds of play first (default 15: the map, phone and
  traffic have settled).
- Server arguments as for `python -m theroadragetrip.server`. Useful ones:
  - `--preset Helsinki` (any menu city or catalog municipality),
    `--bbox S,W,N,E --place-name X` for an exact spot;
  - `--start-time 2026-09-27T00:30` (never in the future: it is clamped to
    today; a past full Moon is 2026-09-27 ~01:00);
  - `--no-historical-weather` for generated, usually clear, weather;
  - `--no-intercity-fares` unless intercity is what you are looking at;
  - `--save-slot NAME` to continue a gig save.
- The server log is `OUT.png.log`.

## Examples

```bash
S=<scratchpad>
.claude/skills/godot-shot/shot.sh $S/night.png --preset Helsinki --start-time 2026-09-27T00:30 --no-historical-weather --no-intercity-fares
.claude/skills/godot-shot/shot.sh $S/day.png --wait 25 --preset Oulu --start-time 2026-10-21T13:00 --no-historical-weather
```

## Rendering a menu or one node instead

`shot.sh` captures gameplay. For the launcher menus (`startup.gd`) or one
layer in isolation, write a throwaway SceneTree script under
`godot/tests/_tmp_*.gd`, run it with
`~/tools/godot/Godot_v4.7.2-stable_linux.x86_64 --path godot --display-driver x11 --rendering-driver opengl3 --script res://tests/_tmp_x.gd`,
save `root.get_texture().get_image()` after `await RenderingServer.frame_post_draw`,
and delete the script afterwards. Instantiate `res://startup.tscn` and call
a menu (`_time_menu()`, `_slot_menu()`, ...) to render it.

## Pitfalls seen

- Never stop processes with `pkill -f <pattern>`: the pattern is also in the
  calling shell's own command line and kills it (exit 144).
- A slow first start is normal after a world-cache format change (the area
  rebuilds); the script waits up to 5 minutes for the port.
- The test scripts must not hit `user://` data the player owns (saves,
  `hud_layout.cfg`): back them up and restore if a shot needs different values.
