# Road Rage Taxi — Municipality-Based Population and Realistic Settlement Density

## Objective

Redesign the population distribution and ambient city-life simulation so that pedestrian counts, NPC traffic, and activity levels reflect the actual settlement pattern of the Finnish municipalities represented in the game.

The current simulation can place dozens of people around an isolated cabin. This is incorrect. Urban centers, suburbs, villages, isolated homes, summer cottages, and remote wilderness must have distinctly different population and activity levels.

The project already has a municipality dataset containing, for each municipality:
- Municipality center coordinates
- Total population
- Municipality area

Use this dataset as the authoritative source for municipality-level population totals and geographic scale.

## Mandatory constraints

- Inspect the existing implementation before proposing or changing its architecture.
- Keep the Python server authoritative for population simulation, NPC spawning, schedules, activity, and game rules.
- Keep Godot responsible for rendering. Do not move simulation rules into the client.
- Preserve existing gameplay features and maintain performance.
- Do not introduce an arbitrary global NPC cap as a substitute for a correct population model.
- Do not modify the existing PBF loading/stuttering behavior as part of this task.
- Do not introduce a binary map-data architecture.
- Preserve existing OSM map support and the current municipality dataset unless the audit establishes a specific issue.
- Reuse existing systems where practical rather than implementing competing population or spawn systems.
- Do not create or push Git tags. Pushing the working branch is permitted.
- All code, documentation, tests, and commit messages must be in English.

## Phase 1 — Audit the current simulation

Trace the complete lifecycle of pedestrians, NPC vehicles, residents, destinations, activities, and ambient events.

Identify:
- Every pedestrian and vehicle spawn location and spawn probability.
- Whether spawning is based on buildings, roads, proximity to the player, time of day, or random sampling.
- How isolated residential buildings and cabins are treated.
- Whether a building can generate an unlimited or disproportionate number of people.
- How NPCs are distributed across the map and how they are removed or despawned.
- Whether existing population, settlement, land-use, or municipality data is available.
- Whether the same location can receive NPCs from multiple independent systems.

Find the actual reason why isolated cabins can attract dozens of people. Fix the underlying model rather than adding a special-case cabin rule.

Document the existing behavior and relevant files before implementation.

## Phase 2 — Implement municipality-based population intensity

Build a reusable server-side population distribution model using the existing municipality dataset.

For each municipality, use:
- Population as the target population scale.
- Area as a geographic scale and consistency check.
- Center coordinates as the municipality's geographic reference.
- Actual settlement data to determine where population should be concentrated.

Calculate and expose population density in people per square kilometer when the supplied area units are verified.

Do not assume that population is uniformly distributed over the entire municipality. Finnish municipalities often contain large forests, lakes, sparsely populated countryside, and small settlement clusters.

Important geographic limitation: a center coordinate, population, and area do not define the actual municipal boundary or settlement distribution. Use authoritative municipality boundaries if they are already available or can be obtained from an appropriately licensed source. Otherwise, implement a clearly documented approximation and do not present it as an exact municipal boundary.

Do not let overlapping approximate municipal territories multiply population intensity.

## Phase 3 — Combine population data with actual settlement geography

Create a spatial population-intensity model that combines municipality-level population information with available OSM-derived geographic features.

Use suitable available evidence, such as:
- Residential and built-up land-use areas.
- Residential buildings and building density.
- Existing settlement or population-density datasets.
- Villages and small settlement clusters.
- Roads and access to residential locations.
- Industrial, commercial, recreational, and other non-residential destinations.

Apply the evidence according to its actual meaning and availability. Do not treat every building as residential or every road as evidence of a populated area.

The resulting distribution must distinguish at least:

1. Dense urban centers.
2. Urban residential neighborhoods.
3. Suburbs and detached-house areas.
4. Villages and small settlements.
5. Sparse rural residential areas.
6. Isolated homes and summer cottages.
7. Uninhabited countryside, forests, and wilderness.

Avoid hard-coded assumptions that a specific geographic radius always represents a city or that every municipality has a uniformly populated center.

Where the available data cannot distinguish permanent residences from seasonal cabins, use a conservative default and document the limitation.

## Phase 4 — Make NPC spawning follow population intensity

Integrate the population model with the existing pedestrian, traffic, and ambient activity systems.

Pedestrian and NPC vehicle spawning must be driven by local population intensity, appropriate destinations, time of day, and relevant activity rules.

Required behavior:

- City centers can support dense pedestrian activity and traffic.
- Suburbs should have lower pedestrian density than busy urban centers, but retain plausible local activity.
- Villages should have small, localized activity clusters.
- Isolated homes must not automatically produce crowds.
- A remote cabin should normally have zero or very few nearby pedestrians unless there is a specific reason for visitors.
- Forest roads and remote rural routes should not have urban levels of NPC traffic.
- A settlement should not suddenly become crowded merely because the player enters the area.
- Multiple spawn systems must not independently inflate the same area's population.
- Time-of-day and weekly activity patterns must operate within the limits imposed by local population and land use.

Represent permanent residents, passing traffic, visitors, and event-related crowds as distinct sources of activity where the existing architecture permits it. Special events must not accidentally override the underlying settlement-density model.

## Phase 5 — Keep population, simulation, and rendering separate

Implement a clear separation between:

- Geographic population intensity.
- Local activity and demand.
- NPC spawn selection.
- NPC lifecycle and despawning.
- Client-side rendering.

Use the existing server-authoritative architecture.

Avoid loading or processing the complete geographic dataset repeatedly during gameplay. Precompute reusable spatial indexes or density data where appropriate.

The system must scale to large maps and long-distance player movement without introducing expensive per-frame geographic searches.

Keep any debug visualization or diagnostics optional and disabled during normal gameplay.

## Phase 6 — Add deterministic tests

Add tests for the population model and its integration with the existing simulation.

At minimum, cover:

- A dense urban center.
- A residential suburb.
- A small village.
- A sparsely populated rural municipality.
- An isolated house.
- An isolated summer cottage.
- A remote forest road.
- A large municipality with a small settlement cluster.
- Two nearby municipalities with different population densities.
- A municipality with substantial forest and water coverage, if relevant data is available.
- Repeated player movement into and out of an area.
- Time-of-day and weekly activity changes.
- Prevention of duplicate or runaway spawning.

Use fixed random seeds for reproducible tests.

Test statistical behavior over many samples rather than relying on a single random spawn result. Establish sensible acceptance ranges from the actual input data and model, not arbitrary universal NPC counts.

Include a regression test reproducing the isolated-cabin crowding bug.

## Phase 7 — Performance and diagnostics

Measure the cost of the new population model using representative urban, suburban, and rural locations.

Ensure that:
- Spatial lookups are efficient.
- Population intensity is not recalculated unnecessarily.
- Long-distance movement does not trigger repeated full-map processing.
- NPC lifecycle management remains stable.
- Existing FPS and gameplay behavior are preserved.

Add optional diagnostics that report the municipality or geographic region, local density estimate, relevant settlement features, and the reasons an NPC spawn was accepted or rejected.

## Deliverables

Provide:
- A summary of the root cause of the current overpopulation problem.
- A description of the population model and its geographic assumptions.
- The implementation integrated with the existing simulation.
- Automated tests, including an isolated-cabin regression test.
- Performance measurements before and after the changes.
- Documentation of data sources and any unresolved geographic limitations.
- A list of changed files and a summary of test results.

Do not claim that the simulation matches real population distribution precisely if the available inputs only support an approximation.

Commit the completed work on the current working branch and push it if the existing workflow permits it. Do not create or push Git tags.