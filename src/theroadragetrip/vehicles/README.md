# vehicles

NPC vehicle-type plugin system (see `.github/prompts/NPC-003.md`). Lets
`npc.py`'s Vehicle Core (`NPCVehicle`, `NPCVehicleManager`,
`place_parked_npc`, `update_npc`) ask "how big is this vehicle, how many
passengers does it hold, is it eligible for household ownership" without
ever branching on whether the vehicle is a car, van, truck, bus,
motorcycle, or bicycle. Modeled directly on the existing pedestrian
activity plugin system at `../activities/` - read that package's own
README first if this one is unclear, the two are deliberately close
mirrors of each other.

## Built-in plugins

| id | length_m | width_m | capacity | household_eligible | traffic_weight | max_speed_kmh | notes |
|---|---|---|---|---|---|---|---|
| `car` | 4.3 | 1.8 | 5 | yes | 0.75 | - (road limit only) | the default, unchanged from before this package existed |
| `van` | 5.2 | 2.0 | 8 | yes | 0.08 | - | bigger, still an ordinary household vehicle |
| `truck` | 7.5 | 2.3 | 2 | no | 0.05 | 80 | freight-only background traffic |
| `bus` | 11.0 | 2.5 | 40 | no | 0.02 | 70 | background traffic; not yet routed via real bus lines/stops |
| `motorcycle` | 2.0 | 0.7 | 1 | yes | 0.10 (experimental) | - | off by default - see "Experimental plugins" below |
| `bicycle` | 1.8 | 0.5 | 1 | no | 0.0 (never spawned) | - | see "Why bicycle is never spawned" below |

Only [npc.py](../npc.py) and [config.py](../config.py)/[main/cli.py](../main/cli.py)
consume this package. It is not re-exported from `theroadragetrip/__init__.py`.

## Architecture

```
base.py       VehicleDefinition, VehiclePlugin - the interface
registry.py   VehicleRegistry (register/get/all_plugins) + default_registry()
plugins/      one module per vehicle type, auto-discovered - this is the
              only directory a new vehicle type ever needs to touch
```

`npc.py` (the Vehicle Core) only ever calls the capability-query methods
on `VehiclePlugin` - it never branches on a vehicle's type id. One
important direction: **this package never imports `npc.py`** (the same
one-directional relationship `activities/` has with `pedestrian.py`) -
`npc.py` imports `vehicles.registry.default_registry()`, never the other
way around. This keeps plugin modules free to be pure, dependency-light
data without risking an import cycle.

## The plugin interface

```python
class VehiclePlugin:
    definition: VehicleDefinition

    def has_driver_requirement(self) -> bool: ...
    def get_passenger_capacity(self) -> int: ...
    def requires_parking(self) -> bool: ...
    def can_be_household_owned(self) -> bool: ...
    def can_carry_passengers(self) -> bool: ...
    def can_be_used_for_errands(self) -> bool: ...
    def get_dimensions(self) -> Tuple[float, float]: ...
    def get_max_speed_kmh(self) -> Optional[float]: ...
```

Every method above has a default implementation that just reads the
matching field off `self.definition` - every built-in plugin listed above
is pure data with zero method overrides (exactly like `activities`'
`phone_usage.py`). A future plugin with genuinely different behavior
(e.g. a road-type restriction) can still override any of these.

`VehicleDefinition` fields actually in use: `id`, `name`, `sprite_key`,
`length_m`/`width_m`, `capacity`, `max_speed_kmh` (`None` = no cap beyond
the road's own speed limit), `requires_driver`, `requires_parking`,
`is_road_vehicle`, `household_eligible`, `passenger_eligible`,
`errand_eligible`, `traffic_weight`, `experimental`. Add more fields when
a plugin actually needs them - don't add speculative ones.

## Adding a new vehicle plugin

1. Create `plugins/your_type.py`.
2. Subclass `VehiclePlugin`, set `definition = VehicleDefinition(...)`.
3. End the module with `PLUGIN = YourTypePlugin()`.
4. That's it - `plugins/discover()` (`pkgutil.iter_modules` +
   `importlib.import_module`) finds it automatically at startup. No
   central list to edit, no import to add anywhere else, no change to
   `npc.py`, `NPCVehicleManager`, the Resident system, or the traffic
   manager (NPC-003.md section 27's extensibility requirement).

Minimal complete example:

```python
# plugins/taxi.py
from ..base import VehicleDefinition, VehiclePlugin

class TaxiPlugin(VehiclePlugin):
    definition = VehicleDefinition(
        id="taxi", name="Taxi", sprite_key="car",
        length_m=4.3, width_m=1.8, capacity=4,
        household_eligible=False, traffic_weight=0.05,
    )

PLUGIN = TaxiPlugin()
```

A broken plugin module (import error, bad `PLUGIN` attribute) is logged
and skipped by `discover()` - it can never prevent the game from
starting.

## `sprite_key` and rendering

`render/vehicles.py`'s `draw_npc_cars` branches on
`vehicle_type in ("motorcycle", "moped")` for a dedicated sprite and
falls back to the generic tinted-rectangle body for everything else -
that's a rendering detail, not Vehicle Core logic, and is left as-is.
`sprite_key` just documents which of those two paths a plugin uses today
(`"car"` or `"motorcycle"`); adding a genuinely new sprite is a rendering
change in `render/vehicles.py`, independent of this package.

## Why bicycle is never spawned

`bicycle` is registered (NPC-003.md's acceptance criteria explicitly list
it as a representable plugin) but has `traffic_weight=0.0` and
`is_road_vehicle=False`, so `NPCVehicleManager` never picks it for the
general population. `pedestrian.py`'s `CyclistManager` already fully owns
background bicycle traffic through its own pedestrian-network-based
movement/spawn system - routing bicycles through the road-vehicle
Driver/parking pipeline here as well would duplicate that existing
system, which the spec explicitly says not to do (section 1/17). The
plugin exists so a future capability query ("find something that can
carry 1 Resident and doesn't need a road") has an answer, without
claiming today's population spawner uses it.

## Experimental plugins (`enable_two_wheelers`)

`motorcycle.definition.experimental = True`. `NPCVehicleManager`'s default
vehicle distribution (used when no explicit `vehicle_distribution` is
passed) excludes any plugin with `experimental=True` unless constructed
with `include_experimental=True` - wired from config's
`[experimental] enable_two_wheelers` (default `false`) via
`main/cli.py`'s `--enable-two-wheelers`. An **explicit**
`vehicle_distribution` override (e.g. `config`'s `[traffic]
vehicle_distribution`, or a test constructing
`NPCVehicleManager(vehicle_distribution={...})` directly) always bypasses
this gate - `experimental` only affects the *default*, unset case. This
is a generic mechanism (any future opt-in-only vehicle type reuses the
same flag), not a `vehicle_type == "motorcycle"` special case anywhere in
`npc.py`.

## Configuration

`[traffic] vehicle_distribution` in `config.ini` (parsed by
`config.get_vehicle_distribution`): a comma-separated `id:weight` list,
e.g. `car:0.8,van:0.1,truck:0.1`, overriding every registered road-vehicle
plugin's own default `traffic_weight`. Empty (the default) means "use
each plugin's own weight". `[experimental] enable_two_wheelers` gates
`motorcycle` as described above.

## Vehicle Core integration (`npc.py`)

* `NPC_VEHICLE_LENGTH_M`/`NPC_VEHICLE_WIDTH_M`/`NPC_CAR_CAPACITY` are
  derived from the `car` plugin's own `VehicleDefinition` at import time
  - the plugin is the canonical source, these constants are a
  backward-compatible alias so every pre-existing call site keeps working.
* `place_parked_npc(..., vehicle_type=...)` looks up the matching plugin
  for dimensions/capacity (falling back to `car` for an unknown id) -
  the one place a vehicle's physical shape is plugin-derived rather than
  hardcoded.
* `update_npc` clamps `driver.target_speed_mps` against the vehicle's
  plugin `get_max_speed_kmh()`, on top of the road's own speed limit -
  the only place vehicle type affects driving behavior today.
  Acceleration-curve differences per vehicle type are deliberately out of
  scope (would mean threading a new parameter through `physics.py`'s
  shared acceleration curve, used by the player's own car too).
* `NPCVehicleManager._pick_vehicle_type()` does a weighted `random.choices`
  over `self.vehicle_distribution` (road-vehicle plugins only) each time
  a new population vehicle is placed - no per-type branch, just a lookup.
* `NPCVehicleManager._make_household()` only makes a vehicle
  `vehicle_kind="household"` if `plugin.can_be_household_owned()` - a
  truck/bus rolled into the household fraction stays a plain traffic
  vehicle. A household can own up to `NPC_MAX_VEHICLES_PER_HOUSEHOLD` (2)
  vehicles: most household-eligible vehicles found a new one-vehicle
  household, but with probability `NPC_SECOND_HOUSEHOLD_VEHICLE_PROBABILITY`
  a new one joins an existing household that still has room instead (not
  spatial - a household's second car isn't necessarily parked next to the
  first either).
* `NPCVehicleManager.request_vehicle(household, passengers, purpose)` is
  the one generic entry point a future Resident shopping/errand system
  calls: finds an `AVAILABLE` vehicle among `household.vehicle_ids` whose
  plugin can carry the requested passenger count (and, if `purpose` is
  given, is errand-eligible), reserves it atomically
  (`reserve_household_vehicle`), and returns it - or `None`. It does not
  implement shopping/errands itself.

## Lifecycle state mapping

NPC-003.md section 8 lists a broader state vocabulary (`CREATED`,
`PARKED_AT_HOME`, `PARKED_ON_STREET`, `AVAILABLE`, `RESERVED`, `IN_USE`,
`DRIVING`, `WAITING`, `PARKING`, `PARKED_AT_DESTINATION`,
`RETURNING_HOME`, `DESPAWNING`) than `npc.py`'s existing `NPCState` enum
implements literally - "use the existing architecture where appropriate"
(the spec's own words), and every concept is already representable
without a rename:

* `NPCState` (`SPAWNING`/`CRUISING`/`APPROACHING_INTERSECTION`/`WAITING`/
  `TURNING`/`PARKING`/`ARRIVING`/`PARKED`) covers `CREATED`, `DRIVING`,
  `WAITING`, `PARKING`, `PARKED_AT_DESTINATION`.
* `NPCAvailability` (`AVAILABLE`/`RESERVED`/`IN_USE`) covers that trio as
  an orthogonal axis - cleaner than cramming both state machines into one
  enum, since a vehicle can be simultaneously `PARKED` and `RESERVED`.
* `vehicle.returning_home: bool` already *is* `RETURNING_HOME`.
* `PARKED_AT_HOME` vs. `PARKED_ON_STREET` is derivable:
  `vehicle.reserved_parking_space is vehicle.home_parking_space`.
* `DESPAWNING` is a one-shot removal (`NPCVehicleManager`'s despawn step)
  with no observable in-between state.

## Debugging

F7's per-vehicle panel (`render/hud.py`'s `draw_npc_debug_panel`) shows
`plugin=<id>` on its first line. The population panel
(`draw_npc_population_panel`) shows a "by type" breakdown from
`NPCVehicleManager.population_counts_by_type()` alongside the existing
total/parked/driving/reserved/household/autonomous counts.

## Testing a plugin

Follow `tests/test_vehicle_plugins.py`'s shape (mirrors
`tests/test_activities.py`): construct a `VehicleRegistry()` directly and
call `discover()`/`register()` on it rather than only through the shared
`default_registry()` singleton, so a test can't accidentally leak state
into another test. `monkeypatch` `theroadragetrip.vehicles.plugins.importlib.import_module`
to simulate a broken plugin module, the same pattern
`test_activities.py` uses for `activities.plugins`.
