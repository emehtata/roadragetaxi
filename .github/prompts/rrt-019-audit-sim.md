# Road Rage Taxi — Simulation Server Performance Audit

## Objective

Perform a comprehensive, evidence-based performance audit of the Python simulation server in the current repository and branch.

The goal is to determine:

1. Which operations consume the most CPU time during normal gameplay.
2. Which operations cause the worst simulation tick spikes and intermittent stalls.
3. Which systems scale poorly as the numbers of NPC vehicles, pedestrians, residents, activities, and map objects increase.
4. Which computations are redundant, unnecessarily frequent, or more detailed than gameplay requires.
5. Which simulation features could be simplified, updated less frequently, or removed with minimal or no perceptible impact on gameplay.
6. Which optimizations should be implemented in Python before considering a different implementation language.
7. Which specific computational workloads would benefit most from a future native implementation, based on measurements rather than assumptions.

**This task is an audit only. Do not implement optimizations, refactor production code, remove gameplay features, or migrate any code to Rust, C, C++, or another language.**

## Scope

Audit the authoritative Python simulation server and its dependencies, including where relevant:

- The main simulation tick and server update loop.
- NPC vehicle movement, autonomous driving, traffic rules, intersections, collision avoidance, recovery, and despawning.
- NPC population management, spawning, despawning, vehicle parking, destination selection, and resident/vehicle relationships.
- Pedestrian movement, pedestrian pathfinding, collision and safety checks, activities, and population management.
- Spatial indexes, road-network queries, parking-space searches, geometry calculations, and collision detection.
- Route planning, route recovery, destination selection, and map-dependent searches.
- Taxi dispatch, passenger generation, pickup/drop-off logic, fare generation, and other periodically triggered gameplay operations.
- Buses, trams, trains, aircraft, and other transport simulation that executes on the server.
- Traffic lights, roadworks, weather-dependent simulation, animals, and other world systems where they contribute to server CPU or memory usage.
- Map synchronization, chunk state preparation, state serialization, network updates, and background jobs where they affect simulation tick latency.
- Python object allocation, garbage collection, temporary collections, data duplication, and avoidable repeated calculations.
- Threading, asynchronous work, lock contention, the GIL, and work that unexpectedly executes synchronously.

Do not audit or optimize Godot rendering, graphics, shaders, visual effects, or GPU performance. Godot rendering is working well and is explicitly outside the scope of this task.

Do not assume that every subsystem listed above is a performance problem. Establish its actual cost before recommending changes.

## Phase 1 — Establish the current implementation

1. Inspect the current Git branch, working-tree state, repository structure, and existing performance documentation.
2. Identify the actual server entry point, simulation tick rate, tick scheduling mechanism, and all major operations executed during a tick.
3. Trace the call graph from the server's main update loop through the simulation managers.
4. Identify existing profilers, benchmark tools, performance tests, instrumentation, and previous optimization experiments.
5. Verify that the available benchmark scripts and documented findings apply to the current branch and current implementation.
6. Identify existing performance instrumentation that may distort timing results or double-count nested operations.
7. Record the Python version, relevant runtime configuration, and benchmark environment when available.

Do not rely solely on old performance reports. Reproduce important findings on the current branch wherever practical.

## Phase 2 — Measure the actual bottlenecks

Use existing benchmark tools where appropriate. Add temporary or audit-specific instrumentation only when necessary. Avoid unnecessary modifications to production code.

Measure at least:

- Simulation tick duration: p50, p95, p99, maximum, and percentage exceeding the tick budget.
- Time spent in each major simulation subsystem.
- Inclusive and exclusive function execution time, where available.
- Number of calls to expensive functions.
- Number of active and moving NPC vehicles.
- Number of active pedestrians and other simulated entities.
- Number of route searches, spatial queries, collision checks, and candidate evaluations.
- Number and size of temporary allocations, where measurable.
- Garbage collection count and pause duration by generation.
- CPU time versus wall-clock time for suspicious stalls.
- Serialization and state-update costs, including the effect of entity counts.
- Memory usage and object-count growth during extended sessions.
- Performance differences between initialization, population growth, steady-state gameplay, and map streaming.

Distinguish nested timing measurements from independent costs. Do not add inclusive timings together as though they were separate CPU costs.

Use repeated runs and report variance. Prefer deterministic scenarios and fixed random seeds where practical. Clearly label measurements that include profiling overhead.

## Phase 3 — Benchmark representative scenarios

Create or reuse reproducible scenarios covering:

1. **Dense urban traffic:** many moving NPC vehicles, intersections, pedestrians, and traffic rules.
2. **Rural nighttime driving:** low population density and low traffic demand.
3. **Population initialization and replenishment:** NPC spawning, destination selection, parking searches, and resident associations.
4. **Pedestrian-heavy areas:** pathfinding, movement, activities, crossings, and collision avoidance.
5. **Long-running simulation:** memory growth, garbage collection, entity lifecycle management, and recurring scheduled operations.
6. **Transport-heavy areas:** buses, trams, and other active transport systems where supported by the current implementation.
7. **Long-distance driving and map streaming:** separate simulation CPU cost from map extraction, map integration, synchronization, and network overhead.
8. **Peak-load conditions:** high but valid entity counts and simultaneous expensive events.

Record the scenario configuration and actual entity counts for every run. Do not compare scenarios with materially different workloads without explaining the difference.

Use realistic gameplay conditions as the primary benchmark. Artificial stress tests are useful for finding scaling problems but must be labelled separately.

## Phase 4 — Find algorithmic and architectural inefficiencies

Inspect measured hotspots for:

- Linear scans over large collections that could use existing spatial indexes.
- Repeated searches for the same nearby roads, parking spaces, destinations, or entities.
- Repeated geometry calculations for unchanged map objects.
- Rebuilding candidate lists when iteration could stop after enough valid candidates are found.
- Repeated sorting, filtering, or allocation of intermediate collections.
- Expensive calculations performed every tick even though their inputs change infrequently.
- Synchronous operations that can be safely divided into bounded work units.
- Repeated route planning or route recovery without meaningful changes in the world.
- Unnecessarily frequent updates for distant or inactive entities.
- Excessive detail in the simulation of entities that cannot currently affect the player.
- Redundant state construction or serialization.
- Object references and lifecycle structures that retain obsolete entities.
- Poor scaling with entity counts, road-network size, map size, or the number of loaded chunks.
- Duplicate work between managers or between consecutive ticks.
- Inefficient Python data structures and object-heavy numerical operations.

For every suspected inefficiency, distinguish between a measured problem and a code-inspection hypothesis.

Do not recommend a spatial index merely because one is theoretically faster. Check whether the project already has an appropriate index and whether the expensive query actually uses it.

## Phase 5 — Assess gameplay value and simplification opportunities

For every significant subsystem or expensive operation, evaluate whether its current simulation fidelity is necessary for the player's experience.

Consider these categories:

A. Essential gameplay behavior that must remain authoritative and correct.

B. Behavior that can be computed less frequently without perceptible degradation.

C. Behavior that can use a simplified model for distant or inactive entities.

D. Results that can be cached or incrementally updated.

E. Detail that can be removed with little or no perceptible effect on gameplay.

F. Expensive behavior that must remain unchanged because simplifying it would damage gameplay, realism, safety, or consistency.

Explicitly investigate opportunities to reduce unnecessary work in:

- Distant NPC vehicle behavior.
- Distant pedestrian activities and movement.
- Population density and entity replenishment.
- Route planning and destination selection.
- Repeated collision and geometric checks.
- Background world activities and transport simulation.
- Scheduled operations and periodic calculations.

Do not assume that a feature is expendable merely because it is expensive. Evaluate its contribution to gameplay, interactions with other systems, and correctness requirements.

Do not recommend simply lowering all entity limits, disabling traffic rules, removing pedestrian avoidance, or reducing the simulation to cosmetic behavior.

Any proposal to reduce simulation frequency must account for game-time acceleration, collisions, intersections, route completion, entity lifecycle transitions, and reactivation when the player approaches.

## Phase 6 — Evaluate optimization options

For each confirmed hotspot, compare appropriate options such as:

- Improving the existing Python algorithm.
- Reusing or caching results with explicit invalidation rules.
- Improving an existing spatial index.
- Eliminating duplicate work.
- Replacing full recomputation with incremental updates.
- Processing noncritical work in bounded units.
- Reducing update frequency where gameplay permits.
- Using lower-fidelity simulation for distant entities.
- Reducing unnecessary allocations and data duplication.
- Using native code only for computationally intensive, well-isolated workloads.

Estimate the likely benefit, implementation effort, regression risk, and validation requirements of each option.

Do not assume that a native implementation will automatically be faster. Identify the specific workload, input/output boundary, data-transfer cost, and expected bottleneck before recommending it.

No language migration is to be implemented or started as part of this audit.

## Deliverables

Create a performance audit report in the repository, preferably under `.github/performance-analysis/`, using a descriptive filename.

The report must contain:

### 1. Executive summary

Identify the five most important performance findings, ranked by measured impact and confidence.

### 2. Measured hotspot table

Include:

- Rank.
- Subsystem and exact function/file locations.
- Measured CPU or wall-clock cost.
- Call frequency.
- Relevant entity counts and benchmark scenario.
- Whether the issue affects average performance, tail latency, memory, or all of these.
- Confidence level and supporting evidence.

### 3. Tick-budget analysis

Explain what consumes the simulation tick budget, which operations exceed it, and whether the problem is steady-state CPU load or occasional long-running work.

### 4. Scaling analysis

Describe how the main workloads scale with the number of NPC vehicles, pedestrians, map objects, route nodes, and active activities.

Identify potential quadratic or worse behavior only when supported by code analysis or measurements.

### 5. Gameplay simplification matrix

For each candidate feature or operation, document:

- Current behavior.
- Current performance cost.
- Proposed simplification or removal.
- Expected gameplay impact.
- Correctness and regression risks.
- Recommendation: retain, optimize, reduce frequency, simplify, or investigate further.

### 6. Prioritized action plan

Group recommendations into:

- P0: severe stalls or clear correctness-independent waste.
- P1: major sustained CPU or scaling problems.
- P2: secondary improvements.
- P3: speculative improvements requiring more evidence.

For every item, provide an estimated benefit range only when defensible, implementation effort, risks, and measurable acceptance criteria.

### 7. Native-code suitability assessment

Rank the specific computational workloads that could benefit from a future Rust implementation. Separate workloads that should first be optimized in Python from workloads that may genuinely warrant native code.

This is an assessment only, not a migration plan or implementation task.

### 8. Reproducibility

Document the exact commands, benchmark configurations, Python version, relevant environment settings, raw result locations, and known limitations.

Provide a baseline that can be reused to evaluate later optimizations.

## Quality requirements

- Base conclusions on the current branch and reproducible evidence.
- Link findings to exact source files and functions.
- Clearly separate measured facts, code-inspection findings, and hypotheses.
- Report both average performance and worst-case behavior.
- Do not confuse simulation tick latency with rendered FPS.
- Do not attribute a stall to a function merely because it appears in a sampled stack.
- Do not treat profiler overhead as actual production cost.
- Do not invent benchmark results, entity counts, or expected speedups.
- Do not duplicate existing reports without adding current measurements or useful analysis.
- Preserve existing gameplay behavior, simulation architecture, and working-tree changes.

## Execution constraints

This is a read-only audit of production behavior.

Do not implement optimizations, change gameplay, remove features, rewrite algorithms, migrate code to another language, or alter release configuration.

Audit-specific scripts, benchmark fixtures, and documentation may be added if needed, but keep them isolated from production behavior. Do not overwrite existing benchmark results or reports.

Use atomic commits for any audit artifacts that are ready to be committed, following the repository's existing workflow.

At completion, summarize the strongest findings, the evidence supporting them, the largest remaining uncertainties, and the recommended first optimization to investigate. Do not begin implementing that optimization without a separate instruction.