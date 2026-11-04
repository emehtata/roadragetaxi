# Road Rage Taxi – Deep Simulation Performance Audit

Perform a comprehensive, source-code-driven performance audit of the entire Python simulation and server architecture.

The simulation is still too computationally expensive. We need to identify the actual causes of excessive CPU usage, long simulation ticks, scaling problems and unnecessary work.

This is an investigation and measurement task ONLY.

Do not implement optimizations, refactor production code, change gameplay mechanics or modify simulation behavior during this audit.

## 1. Architectural constraints

Preserve the current architecture:

- Python is authoritative for all simulation logic.
- Godot is responsible for rendering and user interface.
- The server controls NPC behavior, movement, collision detection and world simulation.
- The simulation target is 30 Hz.
- The available processing budget is 33.33 ms per tick.

Do not propose moving authoritative simulation logic to Godot.

Do not introduce CARLA, SUMO, Box2D or other external simulation engines as runtime dependencies.

Do not impose artificial NPC limits or reduce traffic demand to improve benchmark results.

## 2. Establish a measurable baseline

First identify how performance is currently measured.

Determine whether existing profiling instrumentation provides reliable measurements.

Measure and report:

- Average tick duration.
- Median tick duration.
- P95 and P99 tick duration.
- Maximum tick duration.
- Percentage of ticks exceeding 16.67 ms.
- Percentage of ticks exceeding 33.33 ms.
- Percentage of ticks exceeding 50 ms.
- Percentage of ticks exceeding 100 ms.
- CPU utilization.
- Memory consumption.
- Memory allocation behavior.

Identify long-running operations and determine which subsystems contribute to them.

Do not rely exclusively on average execution times.

## 3. Deep subsystem investigation

### NPC routing

Investigate:

- Number of route calculations per tick.
- Route calculation frequency per NPC.
- Duplicate route calculations.
- Repeated graph traversal.
- Inefficient pathfinding data structures.
- Route cache effectiveness.
- Unnecessary route invalidation.
- Route generation triggered by minor state changes.

Determine whether route calculations can safely be performed asynchronously using background workers and precomputed route pools.

Identify dependencies that prevent parallel execution.

### Collision detection

Investigate:

- Building collision calculations.
- Vehicle-to-vehicle collision checks.
- Vehicle-to-NPC collision checks.
- Spatial partitioning.
- Broad-phase and narrow-phase calculations.
- Repeated geometry calculations.
- Unnecessary collision checks involving distant entities.
- Opportunities for spatial indexing and reusable collision data.

Identify the actual computational complexity of the current implementation.

### NPC simulation

Investigate:

- Per-NPC update costs.
- Update frequency.
- Movement calculations.
- Traffic rule evaluation.
- Traffic light processing.
- Pedestrian and animal simulation.
- Vehicle state updates.
- Unnecessary recalculation of unchanged state.

Determine whether different subsystems perform redundant work.

### Spawn system

Investigate:

- Spawn candidate generation.
- Spawn location validation.
- Failed spawn attempts.
- Retry behavior.
- Road network searches.
- Collision checks during spawning.
- NPC initialization costs.

Determine whether spawn failures and excessive retries create additional simulation load.

### World and spatial processing

Investigate:

- Chunk processing.
- Building and road lookups.
- Spatial queries.
- Animal and pedestrian processing.
- Visibility-independent server calculations.
- Repeated traversal of world data.
- Opportunities for indexing and caching.

### Python runtime and memory

Investigate:

- Excessive temporary object creation.
- Repeated list and dictionary construction.
- Deep copies.
- Garbage collection pauses.
- Inefficient data structures.
- GIL limitations.
- Threading and multiprocessing suitability.
- Memory allocation hotspots.

Do not assume that multiprocessing is automatically beneficial.

### Server and client communication

Investigate:

- State serialization.
- Snapshot generation.
- JSON or other encoding overhead.
- Unnecessary state transmission.
- Network message frequency.
- Repeated object conversion.
- Client update preparation.

Separate actual simulation costs from communication overhead.

## 4. Scaling benchmarks

Establish repeatable benchmarks at approximately:

- 10 active vehicles.
- 20 active vehicles.
- 40 active vehicles.
- 60 active vehicles.

Use additional realistic NPC populations where appropriate.

Do not artificially simplify the world or disable gameplay systems to obtain better results.

Measure how execution time changes as entity counts increase.

Identify operations whose computational complexity grows disproportionately.

Pay particular attention to O(N²) behavior and repeated global searches.

## 5. Tick scheduling and overload behavior

Investigate:

- Fixed timestep implementation.
- Tick scheduling.
- Accumulated simulation debt.
- Catch-up behavior.
- Long-running synchronous operations.
- Lock contention.
- Background task scheduling.
- Work that can be distributed across multiple ticks without changing simulation semantics.

Determine whether the server continues accumulating work when it cannot maintain 30 Hz.

Identify whether individual expensive operations block the entire simulation loop.

## 6. Root cause analysis

For every significant performance problem, provide:

1. Exact source file and function.
2. Description of the operation.
3. Measured execution cost, where measurable.
4. Frequency of execution.
5. Impact on total tick duration.
6. Scaling characteristics.
7. Explanation of why the current implementation is expensive.
8. Proposed optimization.
9. Potential behavioral or correctness risks.

Clearly distinguish measured problems from suspected problems.

Do not present speculative optimizations as proven improvements.

## 7. Prioritized optimization roadmap

Produce a prioritized list of proposed improvements.

For each improvement, include:

- Expected performance impact.
- Implementation complexity.
- Risk to simulation correctness.
- Whether it requires architectural changes.
- Whether it can be implemented independently.
- How its performance improvement can be verified.

Prioritize improvements that reduce actual CPU work without changing gameplay behavior.

## 8. Regression and verification strategy

Design repeatable performance benchmarks that can be used before and after each optimization.

The benchmarks must verify:

- Simulation tick duration.
- NPC movement consistency.
- Traffic behavior.
- Collision correctness.
- Spawn success rates.
- Route correctness.
- Traffic demand.
- Long-running simulation stability.

Performance improvements must not be achieved by silently reducing simulation quality.

## 9. Final report

Deliver a comprehensive report containing:

1. Current simulation architecture and execution flow.
2. Measured performance baseline.
3. Subsystem performance breakdown.
4. Identified bottlenecks ranked by impact.
5. Long-tick root cause analysis.
6. Scaling analysis.
7. Memory and CPU analysis.
8. Parallelization opportunities.
9. Prioritized optimization roadmap.
10. Recommended implementation order.
11. Regression benchmark plan.

Include source file references and relevant code locations.

## STRICT RULES

- Do not modify production code.
- Do not change gameplay behavior.
- Do not reduce NPC populations.
- Do not reduce traffic demand.
- Do not simplify collision detection.
- Do not disable simulation systems to improve benchmark results.
- Do not introduce new runtime dependencies.
- Do not perform speculative refactoring.
- Do not create Git tags.
- Do not start implementing the proposed optimizations.

The objective is to understand exactly where simulation performance is being lost and establish an evidence-based optimization roadmap.

Stop after delivering the audit report and wait for approval before implementation.