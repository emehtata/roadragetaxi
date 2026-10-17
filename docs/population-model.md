# Population model

How many people and cars are around the player. Code:
`src/theroadragetrip/population.py`. Task: `.github/prompts/rrt-018-population.md`.

## Audit and root cause (before this change)

- `PedestrianManager.population_target` was fixed per game: 4 × the view
  target, about 80 people within 120 m, whether in central Oulu or at a cabin.
- `spawn_pedestrian` puts a person on any pedestrian way within the radius. Near
  a cabin there are only a few such ways, so the whole crowd landed on them.
- `kunnat.json.gz` was used only as a per-attempt rejection probability
  (`ResidentManager.density_spawn_probability`), always with the *start* city's
  density and centre. It slowed filling the target but never lowered it: Sysmä
  (1.9 people/km²) still filled to 80 in a few checks.
- NPC cars scaled their target by the raw count of buildings in a square around
  the player (`NPC_FULL_TRAFFIC_BUILDINGS`), so a sauna counted as much as a
  block of flats.
- An interim cap of 2 people per building plus 2 (3bc9317) is replaced by this
  model.

## Model

1. **People per building**, from its OSM `building=*` type
   (`building_people`):
   - houses: 2.5;
   - flats: footprint × floors / 40 m²;
   - cabins and huts: 0.3 (seasonal);
   - shops, offices, schools and other destinations: footprint × floors / 50 m² visitors;
   - garages, saunas, sheds and the like: none;
   - untagged buildings by size: under 40 m² none, under 200 m² a house, larger like flats.
2. **People within a disc:** the sum over buildings whose centre is inside it.
3. **Walking share** from the municipality whose `kunnat.json.gz` centre is
   nearest the point:
   - 4 % of those people are out walking at once;
   - scaled from 0.4× (a rural municipality) to 1× at 100 people/km² or more.

   Unknown municipality: the full share.

Uses:

- **Pedestrians:** `local_population_target` is the walkers within the spawn
  radius, rounded up, and no more than `population_target` (the per-view
  budget, not a global cap). No buildings means nobody; anyone living there
  means at least one walker. Without building data at all, the old target
  applies.
- **NPC traffic:** `set_local_density` scales the city's target by people
  within its spawn radius / `NPC_FULL_TRAFFIC_PEOPLE` (1,500). The main-road
  floor is unchanged.

Not covered: door, venue, station-passenger, arena and sports spawns. These come
from their own events (a train, a match, a shop door), not from ambient
population.

## Performance

The work is bounded: the buildings in the grid cells the disc touches, once
per population check (2 s) for pedestrians and once per 100 m cell for NPCs.

Measured with 900 houses in a grid (synthetic, Python 3.12, WSL2):

| | Per call | Target at the centre |
| --- | --- | --- |
| Before: building count | 0.15 ms | 80 |
| After: population model | 0.24 ms | 20 |

## Tests

- `tests/test_population.py`: the building types, counting each building once,
  the municipality's walking share, and the isolated-cabin regression.
- `tests/test_pedestrians.py::test_a_rural_cabin_gets_a_walker_at_most_and_a_city_block_the_full_target`
- `tests/test_npc_population.py::test_traffic_follows_the_people_around_the_player`

# Traffic demand

Moving NPC traffic follows the people around, the road and the game clock.
Task: `.github/prompts/rrt-018-traffic.md`. Code: `population.py`
(`traffic_demand`, `hour_demand`, `is_public_holiday`) and
`NPCVehicleManager.set_local_density`.

## Audit and root cause (before this change)

- **Never empty:** `target_moving_count` was at least 1 everywhere. Below that
  target, `_run_population_tick` spawns a passing ("transit") car near the
  player, so an empty remote road got a car at once, and another after each one
  left.
- **Main-road floor:** `NPC_MAIN_ROAD_TRAFFIC_FRACTION` gave a main road at
  least 25 % of the city's traffic, at any hour.
- **No clock:** nothing in NPC traffic read the time. Parked cars started trips
  at 8 % per candidate per tick, day and night.
- **Not causes:** despawning kept `min_count`, but that already scaled with the
  local buildings. Spawn retries are bounded per tick.

## Model

- **Local trips:** the people within the NPC spawn radius (the population
  model) / `NPC_FULL_TRAFFIC_PEOPLE`, at most 1.
- **Passing traffic** (`THROUGH_TRAFFIC`, by OSM highway class): motorway
  0.6, trunk 0.45, primary 0.3, secondary 0.15, tertiary 0.06. A main road
  through an empty municipality still carries cars.
- **Clock** (`hour_demand`): the hourly curve, multiplied by `MONTH_FACTOR`.
  - The curve is `WEEKDAY_HOURLY` on weekdays and `WEEKEND_HOURLY` on weekends
    and public holidays.
  - Public holidays are the fixed-date ones plus Midsummer Eve and Day; Easter
    and Ascension are not covered.
- **Season:** in June–August a cabin counts 2 people instead of 0.3, so
  cottage areas get summer traffic only where cabins are mapped.
- **Demand:** max(local, passing) × clock.
- **Expected moving cars:** city target × `NPC_TARGET_MOVING_FRACTION` × demand.
  - The moving target is the whole part of that, plus 1 when a draw falls
    under the fraction.
  - The draw is re-rolled every `NPC_DEMAND_ROLL_TICKS` (30 ticks of 2 s,
    1 minute), so 0.013 means a car is wanted about one minute in 77, not one
    car always.
- **Parked population:** the people share of the city target, at least one car
  where anyone lives, plus room for the moving target. It does not follow the
  clock: households' cars stay parked at night.
- **Trip starts:** parked cars start trips at
  `NPC_TRIP_START_PROBABILITY_PER_TICK` × the clock.
- **Diagnostics:** `population_diagnostics["traffic_demand"]` holds the parts:
  local, through, hour, demand, people, highway, expected and target moving
  cars.

All curve values are **estimates**, shaped after Finnish automatic traffic
counts (Fintraffic LAM): weekday peaks at 7–8 and 15–17, nights at 2–4 % of the
peak. They are not calibrated against counted volumes.

## Results

Mean moving-traffic target over 2,000 seeded one-minute draws
(`tests/test_traffic_demand.py`, city target 40, or 15 for Sysmä-sized):

| Scenario | Moving cars |
| --- | --- |
| City centre, weekday 16:00 | 19.4 |
| City centre, 01:00 | 0.50 |
| Suburb, 07:30 | 5.6 |
| Suburb, 23:30 | 0.60 |
| Village, 01:00 | 0.021 |
| Remote Sysmä tertiary road, 01:00 in October | 0.013 (before: always ≥ 1) |
| The same road, 14:00 | 0.35 |
| Cabin area, July 14:00 | 0.79 |
| Cabin area, October 14:00 | 0.12 |
| Trunk road in an empty area, 14:00 | 2.5 |
| Trunk road in an empty area, 01:00 | 0.09 |

Cost: the people recount stays once per 100 m cell (and month). The demand is
a few multiplications per population tick.

Not covered:

- Event traffic: arena matches don't add car trips.
- Commuting between specific homes and workplaces.
- Easter and Ascension.
