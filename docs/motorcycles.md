# Motorcycles

Motorcycles are ordinary NPC road traffic: one more vehicle type in
`vehicles/base.py`, picked by the same weighted draw as cars, vans and
trucks (`NPCVehicleManager._pick_vehicle_type`), routed, parked, collided
and retired by the same code. They follow the car rules of
[the traffic-law guide](finnish-npc-traffic-law.md); nothing in the law
the game models treats them differently, so there are no motorcycle-only
rules.

| | |
| --- | --- |
| Footprint | 2.2 × 0.8 m (bike and rider); collisions use it like any vehicle's |
| Speed | the road's limit, the car acceleration and braking model |
| Peak weight | `traffic_weight` 0.03: about 3 % of new road vehicles in summer |
| Households | may own one (parked at home, used for trips) |

## The riding season

`motorcycle_season.py` is the one place that decides how much motorcycle
traffic the **in-game date** allows - never the host's clock. It returns a
factor that multiplies the motorcycle weight only; every other type keeps
its own weight, so their mix among themselves never changes.

```
factor
1.0 |            ____________
    |          /              \
    |        /                  \
0.1 |      /                      \
0.0 |_____|                        |_____
      Jan  Apr  Jun          Sep    Nov  Dec
```

| Period (defaults) | Factor |
| --- | --- |
| 1 Nov - 31 Mar: winter | 0, absolute |
| 1 Apr - 31 May: spring | 0.1 rising linearly to 1.0 |
| 1 Jun - 31 Aug: summer | 1.0 |
| 1 Sep - 31 Oct: autumn | 1.0 falling linearly to 0.1 |

The only jump is the mandatory one into winter.

### Configuration

`[motorcycles]` in the game config (`config.py`):

```ini
[motorcycles]
season_start = 04-01
summer_start = 06-01
autumn_start = 09-01
winter_start = 11-01
spring_multiplier = 0.1
summer_multiplier = 1.0
autumn_multiplier = 0.1
```

Dates are month-day. A value that does not parse keeps its default; dates
out of order fall back to the whole default season.

### Assumptions about Finland

Bikes go on the road as the streets dry and the grit is swept, typically in
April; many owners insure and register them for the summer months only;
riding peaks in June-August and tails off with the cold, wet autumn, and
virtually no one rides on winter roads. The defaults model that; weather is
not consulted (a warm March or a snowy April changes nothing).

## Winter, and the date changing

The factor is recomputed once per game day (`_update_motorcycle_season`,
first thing in `NPCVehicleManager.update`). On the first day of the winter
exclusion every motorcycle - moving, parked or crashed - is retired through
the ordinary `retire_vehicle` cleanup, and none is drawn again until the
season starts. No motorcycle is created to be removed: the draw simply
never picks one at factor 0.

Before the game date is known (the initial fill during loading, before
the server's calendar exists) the factor is 0, so the first motorcycles of
the season join with the regular top-ups rather than being placed in a
winter world.

## Map streaming

The NPC population is not spawned per map chunk: vehicles are placed by
the population ticks around the player and discarded outside the active
area (`discard_outside`), so a chunk loading again cannot duplicate them.

## Observability

`npc_manager.population_diagnostics` (in the F12 debug snapshot):
`motorcycle_season_factor`, `motorcycles_spawned` (draws that picked one)
and `motorcycles_retired_for_winter`.

## Rendering

`godot/entity_layer.gd` draws a motorbike from above: rear and front
tyres, the tank and tail in its paint, seat, handlebar, headlight (lit
with the engine on), a tail light that brightens when braking; while
ridden, the rider with a helmet in the bike's colour. No sprite asset.

## Cost

One date comparison per frame, and one extra weight in the vehicle-type
draw; the yearly winter purge is one pass over the vehicles.
