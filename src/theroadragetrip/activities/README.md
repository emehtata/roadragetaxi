# activities

Ambient pedestrian activity plugin system (see `.github/prompts/residents-live.md`
for the original spec). Lets an ordinary walking `Pedestrian` spontaneously
sit on a bench, check their phone, throw away trash, or relax in a park,
then resume walking - without `pedestrian.py` or this package's core
knowing which specific activities exist.

Only [pedestrian.py](../pedestrian.py) consumes this package. It is not
re-exported from `theroadragetrip/__init__.py`.

## Architecture

```
base.py       ActivityDefinition, ActivityLocation, ActivityInstance,
              ActivityContext, ActivityPlugin - the plugin interface
registry.py   ActivityRegistry (register/get/all_plugins) + default_registry()
manager.py    ActivityManager - selection, location reservation, cooldowns
plugins/      one module per activity, auto-discovered - this is the only
              directory a new activity ever needs to touch
```

The core (`manager.py`, and `pedestrian.py`'s `_consider_activities`/
`_update_activity`/`_end_activity`) only ever calls the six `ActivityPlugin`
hooks below. It never branches on an activity's id or kind - see
`ActivityManager.select_activity`, which loops over
`registry.all_plugins()` generically.

## The plugin interface

```python
class ActivityPlugin:
    definition: ActivityDefinition

    def can_start(self, context: ActivityContext) -> bool: ...
    def find_location(self, context: ActivityContext) -> Optional[ActivityLocation]: ...
    def score(self, context: ActivityContext, location) -> float: ...
    def start(self, context: ActivityContext, instance: ActivityInstance) -> None: ...
    def update(self, context: ActivityContext, instance: ActivityInstance, dt: float) -> bool: ...
    def finish(self, context: ActivityContext, instance: ActivityInstance) -> None: ...
```

- **`can_start`** - a cheap eligibility gate that doesn't need a location
  (e.g. `garbage_disposal`'s "is this pedestrian carrying something to
  throw away" roll). Default `True`.
- **`find_location`** - find and return one `ActivityLocation`, or `None`
  if nothing suitable is nearby. Only called when
  `definition.requires_location` is `True`; skipped entirely otherwise
  (see `phone_usage`, which never overrides it).
- **`score`** - a multiplier on `definition.base_weight` for
  context-sensitive ranking among competing candidates (time of day,
  weather, distance, ...). Default `1.0` - none of the 4 built-in plugins
  override it yet.
- **`start`** - called once, right after the pedestrian arrives at the
  location (or immediately, if there's no location). Stash whatever the
  activity needs in `instance.data` (a plain dict, yours to use however
  you like - the core never reads it).
- **`update`** - called every frame while performing the activity. Return
  `True` once finished.
- **`finish`** - called once, right after `update` returns `True`, before
  the core resets the pedestrian to walking.

`ActivityDefinition` fields actually in use: `id`, `name`,
`requires_location`, `min_duration_s`/`max_duration_s` (yours to sample
from in `start`, the core doesn't enforce them), `cooldown_s` (this
activity's own re-trigger cooldown), `base_weight`. Add more fields when a
plugin actually needs them (e.g. `min_participants` for a future group
activity) - don't add speculative ones.

## Adding a new activity

1. Create `plugins/your_activity.py`.
2. Subclass `ActivityPlugin`, set `definition`, override whichever hooks
   you need (all have harmless defaults).
3. End the module with `PLUGIN = YourActivityPlugin()`.
4. That's it - `plugins/discover()` (`pkgutil.iter_modules` +
   `importlib.import_module`) finds it automatically at startup. No
   central list to edit, no import to add anywhere else.

Minimal complete example (no location, the simplest shape - see
`phone_usage.py` for the real one this mirrors):

```python
# plugins/whistling.py
import random
from ..base import ActivityContext, ActivityDefinition, ActivityInstance, ActivityPlugin

class WhistlingPlugin(ActivityPlugin):
    definition = ActivityDefinition(id="whistling", name="Whistling a tune",
        requires_location=False, min_duration_s=5.0, max_duration_s=15.0,
        cooldown_s=30.0, base_weight=0.5)

    def start(self, context, instance):
        instance.data["duration_s"] = random.uniform(5.0, 15.0)
        instance.data["elapsed_s"] = 0.0

    def update(self, context, instance, dt):
        instance.data["elapsed_s"] += dt
        return instance.data["elapsed_s"] >= instance.data["duration_s"]

PLUGIN = WhistlingPlugin()
```

If a plugin needs a location, return an `ActivityLocation(x, y,
reservation_key=..., extra=...)` from `find_location`:
- `reservation_key` - any hashable, made exclusive to one pedestrian at a
  time by `ActivityManager` (e.g. `("bench", id(bench))`). Use `None` if
  many pedestrians can share the spot (see `park_leisure` - an open lawn
  fits everyone).
- `extra` - your own object reference (the `SceneryObject`/`Scenery`/...
  the location came from), for your own later hooks to read back via
  `instance.location.extra`. The core never touches it.

For finding nearby OSM features, use the two kind-agnostic queries on
`PedestrianManager` (see `bench_sitting.py`/`garbage_disposal.py` for
point objects, `park_leisure.py` for polygons):

```python
context.pedestrian_manager.nearby_scenery_objects(x, y, radius_m)  # -> List[SceneryObject]
context.pedestrian_manager.nearby_sceneries(x, y, radius_m)        # -> List[Scenery]
```

Filter the result by `.kind` yourself - these methods have no notion of
which kinds exist (see `osm/build.py`'s OSM-tag-to-`kind` mapping for what
values are possible, e.g. `"bench"`, `"waste_basket"`, or raw
`leisure=`/`landuse=` values like `"park"`/`"grass"`).

A broken plugin module (import error, bad `PLUGIN` attribute) is logged
and skipped by `discover()` - it can never prevent the game from starting.

## Lifecycle

```
walking (ped.activity is None)
  -> _consider_activities() picks a plugin+location, sets ped.activity
     and ped.state = "walking_to_activity"
  -> _update_activity(): walks there via the existing _walk_route_to
     helper (or arrives instantly if location is None), then calls
     plugin.start(), ped.state = "performing_activity"
  -> _update_activity(): calls plugin.update() every frame until it
     returns True, then plugin.finish()
  -> _end_activity(): releases the reservation, stamps cooldown flags on
     ped.activity_flags, ped.activity = None, ped.state = "walking"
```

`ped.state` uses two new bare string literals
(`"walking_to_activity"`/`"performing_activity"`), consistent with
`pedestrian.py`'s existing partial-enum convention (e.g.
`"walking_to_building"` already coexists with `PedestrianState` the same
way). `animation_state = "idle"` while performing - already a rendered
state (used by `IN_BUILDING`/`ENTERING_VEHICLE`), so no render changes are
needed for a new activity that just stands still.

Selection (`_consider_activities`) runs once per the existing 5-second
population-management tick, not every frame - `PedestrianManager.update()`
already batches population/despawn work there. A pedestrian mid vehicle-
passenger-lifecycle (`linked_vehicle_id`/`reserved_vehicle_id`/
`current_vehicle_id` set) or already walking to a taxi stop is never
considered - that state machinery (`_update_linked_driver`) owns those
pedestrians exclusively.

## Testing a plugin

Follow `tests/test_activities.py`'s shape (mirrors `tests/test_pedestrians.py`):
build a `PedestrianManager([way], target_count=0, scenery_objects=[...],
sceneries=[...])`, construct an `ActivityContext` directly, and call your
plugin's hooks directly rather than only through the full `.update()`
loop. `monkeypatch` pins `random` calls for determinism (this module's
`random.random`/`random.choice`/`random.uniform`, not a shared instance).
