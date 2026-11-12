# Moped closure

## Goal
Close the realism-audit moped item (fix 5 of `docs/specs/vehicle-realism-audit.md`) by recording that no traffic source spawns mopeds and the YAGNI drop is in place.

## Closure rule
A vehicle kind is drawn/defined only if a traffic source spawns it. A kind with no spawner has no `VehicleDefinition` and is not in `VEHICLES_3D` / `TWO_WHEELERS`. Fix 5 allowed either a definition (with a spawner) or the drop; the drop applies.

## Evidence (2026-11-06)
- `grep -rni moped src godot/*.gd tools` finds only: `src/theroadragetrip/assets/moped.xpm` (unreferenced 2D art), the `godot/assets/vehicles/moped*` licence entry in `tools/license_inventory.json` (lines ~196-202). No `.gd` or `.py` code mentions a moped.
- `godot/entity_layer.gd:18` `TWO_WHEELERS := ["motorcycle", "bicycle"]`; `:1029` `VEHICLES_3D` has no moped. `godot/buildings_3d.gd` and `src/theroadragetrip/vehicles/base.py` contain no "moped".
- `tests/test_vehicle_definitions.py` already pins `VEHICLE_DEFINITIONS` to ten ids without a moped, but does not say why or cover the Godot lists.

## Decision
Closed: no spawner. `godot/assets/vehicles/moped.glb` (and its licence entry, commit 23f875b) is kept for a future traffic source. Reopening needs a spawner, a `VehicleDefinition("moped", ...)`, and the kind added to both Godot lists in one change.

## Files to change
- `docs/specs/vehicle-realism-audit.md`: line 18 table row and line 39 mismatch 5 / line 50 fix 5 marked "closed: no spawner (see moped-closure.md)"; add a "moped: closed" line to the open/closed list.
- `tests/test_vehicle_definitions.py`: add the test below.

## Acceptance criteria
1. `"moped" not in VEHICLE_DEFINITIONS` and `vehicle_definition("moped").id == "car"` (unknown falls back).
2. `"moped"` does not occur in the `TWO_WHEELERS` or `VEHICLES_3D` constants of `godot/entity_layer.gd`.
3. No Python source under `src/theroadragetrip` (excluding assets) mentions a moped spawn, so a spawner can't be added without failing criterion 1's test and forcing a spec update.
4. The audit doc's open-list/fix-5 lines say "closed".

## Tests to add
- `tests/test_vehicle_definitions.py::test_moped_has_no_spawner_or_drawn_kind`: asserts 1-3 by reading `entity_layer.gd` text and grepping `*.py` under `src/theroadragetrip` for "moped". Fails if someone adds a moped definition, spawner, or Godot list entry without reopening this spec.

## Out of scope
New moped model or definition, removing `moped.glb`/`moped.xpm`, NPC traffic changes, other audit items.
