# Task: Audit the Traffic Simulation and Evaluate Digitraffic LAM Data Integration

## Objective

Conduct a thorough audit of the existing Road Rage Taxi traffic simulation and determine how Finnish road traffic measurement data from Digitraffic's LAM (traffic measurement station) network could be used to make simulated traffic volumes and congestion more realistic.

**This is an investigation task, not an implementation task.** Do not modify production code or introduce new runtime behavior. The goal is to produce an evidence-based technical report and a practical implementation proposal grounded in the current codebase.

Official data sources:

- LAM documentation: https://www.digitraffic.fi/tieliikenne/lam/
- General road traffic data: https://www.digitraffic.fi/tieliikenne/
- API documentation: https://tie.digitraffic.fi/swagger/

Use the current official documentation. Do not assume that endpoint names, response formats, or available fields match older documentation or examples.

## 1. Audit the Existing Traffic Simulation

Inspect the actual implementation and document:

- Where NPC vehicles are created, spawned, removed, and managed.
- How vehicle spawn locations and routes are selected.
- How road segments and road classifications are represented.
- Whether the simulation already considers population density, urban versus rural areas, time of day, weekdays, weekends, seasons, or weather.
- How traffic density is currently determined.
- Whether vehicle speed depends on road type, speed limits, other vehicles, intersections, traffic lights, or congestion.
- How interactions between vehicles are simulated.
- Whether congestion emerges from individual vehicle interactions or is represented through simplified traffic-density calculations.
- How traffic lights, roadworks, incidents, and other obstacles affect traffic flow.
- Which calculations run every simulation tick and which are performed less frequently.
- Which existing data structures could support traffic profiles without significant architectural changes.

For every important finding, provide file paths, relevant class/function names, and line references where available.

Distinguish implemented behavior from planned features, comments, and assumptions.

## 2. Investigate the Digitraffic LAM Data

Read the current official documentation and determine what data is actually available through the API.

Investigate at least:

- Station locations and identifiers.
- Station metadata and the road locations they represent.
- Traffic volumes, including hourly counts where available.
- Vehicle classifications and which classes can be distinguished.
- Travel directions and lanes.
- Measured speeds and average speeds.
- Historical data availability and temporal resolution.
- Differences between real-time measurements, processed statistics, and historical raw measurements.
- Data publication delays and limitations.
- API usage requirements, caching recommendations, and request limits, if documented.
- Data licensing and attribution requirements relevant to a game distributed commercially.

Identify the exact API endpoints and relevant response fields from the current documentation.

Do not download the entire historical dataset unnecessarily. Use a small number of representative requests, if needed, to verify the documented data format and practical accessibility.

## 3. Evaluate How LAM Measurements Could Map to the Game World

The game uses OpenStreetMap-derived road data and supports a large Finnish game world.

Investigate how LAM stations could be associated with the existing road network.

Consider:

- Matching a station's coordinates to the correct road segment.
- Accounting for travel direction and divided carriageways.
- Avoiding incorrect matches to nearby parallel roads or ramps.
- Representing the road section measured by a station rather than treating its location as a point with universal traffic data.
- Identifying which game roads can be calibrated directly and which require estimated traffic profiles.
- Handling stations outside the currently loaded game area.
- Handling missing, outdated, or incomplete measurements.
- Avoiding the assumption that LAM stations provide complete coverage of Finland's road network.

Assess whether the existing road data and road-segment identifiers are sufficient for reliable matching. Identify any missing information or preprocessing requirements.

Do not assume that a measurement from a major highway can be directly applied to nearby urban streets.

## 4. Propose a Traffic Profile Model

Evaluate how measured traffic volumes could influence the existing simulation.

Consider a model that distinguishes, where supported by data:

- Road class and functional importance.
- Urban, suburban, and rural environments.
- Weekday versus weekend.
- Time of day.
- Seasonal variation.
- Vehicle class.
- Direction of travel.
- Population density and proximity to urban centres.

Determine which factors can be derived from LAM data, which can be obtained from existing game data, and which would require estimates.

Assess whether historical hourly traffic profiles could be preprocessed into compact local data files so that the game does not need a live internet connection during normal gameplay.

Explain how measured counts could be translated into simulated NPC traffic levels when the game world and simulation do not represent every real vehicle individually.

Avoid recommending arbitrary global NPC caps as the primary solution to traffic-density problems. If computational limits require traffic budgets or adaptive simulation, explain how these could preserve realistic traffic distribution and gameplay.

## 5. Evaluate Realistic Congestion

Determine how the existing simulation could use traffic data to create believable congestion.

Distinguish between:

1. Traffic volume: how many vehicles pass a location over a period.
2. Traffic demand: how many vehicles attempt to use a road.
3. Road capacity: how much traffic the road can accommodate.
4. Congestion: the resulting reduction in traffic flow and speed.

Evaluate potential approaches, ordered from simplest to most sophisticated:

- Traffic-volume profiles that influence NPC spawning.
- Road-class-specific baseline traffic levels.
- Time-dependent traffic demand.
- Capacity and bottleneck modelling.
- Congestion caused by intersections, traffic lights, roadworks, and incidents.
- Using measured speeds to calibrate or validate simulated traffic conditions.

Determine which approaches fit the existing simulation architecture and which would require substantial changes.

Do not assume that high traffic volume automatically means congestion. Explain how the proposed model would distinguish a busy road flowing freely from a congested road.

## 6. Assess Performance and Offline Operation

Performance is a critical requirement.

Investigate the expected costs of:

- Loading and querying traffic profiles.
- Mapping measurements to road segments.
- Selecting traffic profiles during simulation.
- Calculating traffic demand over time.
- Simulating additional vehicles and interactions.
- Updating congestion information.

Identify which operations should happen during data preprocessing, world loading, or infrequent simulation updates rather than every simulation tick.

Consider the following requirements:

- No mandatory network requests during normal gameplay.
- Historical traffic profiles should be usable offline.
- Real-time Digitraffic data, if recommended at all, must be an optional enhancement.
- Missing or unavailable data must not prevent the game from running.
- Traffic data processing must not introduce avoidable frame-time spikes or increase simulation cost unnecessarily.
- Preserve the existing separation between the authoritative Python simulation/server and the Godot rendering client.
- Do not move simulation logic to Godot or redesign the client/server architecture as part of this investigation.

Where possible, estimate performance implications from the actual implementation. Clearly label estimates that cannot be verified without benchmarking.

## 7. Identify a Practical Validation Strategy

Propose how to determine whether the new model would improve realism.

Consider:

- Comparing simulated traffic volume with historical measurements at selected LAM stations.
- Comparing weekday and weekend traffic profiles.
- Comparing morning, daytime, evening, and nighttime traffic.
- Comparing urban and rural road behaviour.
- Checking whether congestion occurs at plausible locations and times.
- Measuring simulation performance before and after any future implementation.

Specify measurable metrics where possible. Explain which comparisons would be meaningful even though the game simulates only a fraction of real-world vehicles.

## 8. Produce an Implementation Roadmap

Recommend an incremental implementation plan.

For each proposed phase, describe:

- Its purpose.
- The existing code and data structures it would affect.
- Any required preprocessing tools or generated data files.
- Expected benefits.
- Performance risks.
- Dependencies on earlier phases.
- How the phase could be tested independently.

Prefer small, independently testable changes over a large rewrite.

Consider whether the first implementation should focus on generating historical hourly traffic profiles from a limited, representative subset of LAM stations before expanding to wider geographical coverage.

Keep live traffic integration separate from the initial historical-data approach unless the investigation finds a compelling reason otherwise.

## Deliverables

Create a technical report in the repository's existing documentation structure, using its established documentation conventions.

The report must contain:

1. An executive summary.
2. An audit of the current traffic simulation, with code references.
3. A summary of the verified LAM data and API capabilities, with official source references.
4. A feasibility assessment of mapping LAM stations to the game's road network.
5. A proposed traffic-profile data model.
6. An assessment of congestion modelling options.
7. Performance and offline-operation considerations.
8. A validation and testing strategy.
9. A phased implementation roadmap.
10. A list of unresolved questions and assumptions that must be verified before implementation.

Include a concise table distinguishing:
- Capabilities already present in the game.
- Capabilities that can be added using existing data.
- Capabilities requiring external data.
- Capabilities requiring significant architectural changes.

## Constraints

- Base conclusions on the actual repository and current official documentation.
- Do not invent existing classes, functions, fields, API endpoints, or data files.
- Clearly distinguish verified facts, recommendations, and estimates.
- Do not implement the proposed traffic system during this task.
- Do not change gameplay behaviour or existing simulation algorithms.
- Do not introduce new dependencies unless necessary for a small, isolated investigation; explain any such dependency.
- Do not spend time auditing or optimizing Godot rendering. The scope is the Python simulation and its supporting data.
- Do not make performance claims without evidence or clearly labelled estimates.
- Do not create or push Git tags.
- Keep any documentation changes focused on this investigation.

Commit the completed report as an atomic commit using the repository's existing Git workflow.