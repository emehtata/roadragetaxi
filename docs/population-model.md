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
