# Agent instructions

Before work on NPC traffic, pedestrian interactions, routing, parking, road
maintenance or traffic controls, read
[the Finnish NPC traffic-law guide](docs/finnish-npc-traffic-law.md).

Follow its legal references, exceptions, game policies and acceptance scenarios.
The guide specifies requirements; it does not certify current behavior.
Keep traffic decisions on the Python simulation server and preserve map-layer
separation and bounded per-frame work.

Whenever changing UI or Godot code, render the affected view, capture a
screenshot and inspect it visually before considering the change complete.

Godot is installed at
`/home/ubuntu/tools/godot/Godot_v4.7.2-stable_linux.x86_64`.
Use this executable directly if `godot` is not on `PATH`; verify it with
`--version` before concluding that Godot is unavailable.

Python requirements may be added when a maintained dependency is the clearest
and most reliable way to implement the requested behavior.

Commit and push completed changes as atomic commits. Keep each commit focused
on one logical change, and run the relevant checks before committing.
