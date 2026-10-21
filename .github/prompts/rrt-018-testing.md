# Road Rage Taxi — Comprehensive Testing Strategy, Regression Prevention, and Release Quality

## Mission

The Road Rage Taxi codebase has grown substantially. Small defects continue to be discovered manually, including bugs that should have been caught by automated tests. One recent example was a passenger identity changing after a ride ended. That bug has already been fixed, but it illustrates a broader problem: important behavioral guarantees are not sufficiently protected by automated testing.

Establish a comprehensive, maintainable testing strategy for the entire game.

The objective is to detect defects early, prevent regressions, verify interactions between subsystems, and establish reliable evidence that the game remains functional as development continues toward version 1.0.

This is a repository-level engineering task, not a request to produce a generic testing document. Inspect the actual implementation, identify gaps, add meaningful tests, run them, and document the resulting test architecture.

## Mandatory constraints

- Inspect the current repository, branch, test infrastructure, and implementation before changing anything.
- Treat the existing implementation and current behavior as the baseline unless a defect is identified and confirmed.
- Keep Python authoritative for server-side simulation, game rules, passenger lifecycle, traffic, NPC behavior, and collisions.
- Keep Godot responsible for client rendering and presentation.
- Preserve existing gameplay, performance, and FPS.
- Do not reintroduce a Pygame renderer or move game rules into Godot.
- Do not introduce a binary map-data architecture.
- Do not attempt to fix the known PBF loading/stuttering issue as part of this testing task.
- Do not rewrite large subsystems simply to make them easier to test. Prefer focused refactoring with demonstrated value.
- Do not add superficial tests that only exercise implementation details or assert that a function returns without throwing.
- Do not weaken, skip, or delete existing tests to obtain a passing result.
- Avoid adding new dependencies unless they provide clear value and are compatible with the project.
- All prompts, code, documentation, test names, and commit messages must be in English.
- Git commits and pushing the working branch are permitted.
- Do not create or push Git tags.

## Phase 1 — Repository-wide testing audit

Inspect the complete project and establish an inventory of the existing test architecture.

Review:
- Python packages and server modules.
- Passenger, taxi, fare, trip, and customer lifecycle logic.
- NPC pedestrians, vehicles, traffic, road networks, and intersections.
- Municipality and population-related systems, where implemented.
- Rail passengers, train schedules, and meet-and-greet behavior.
- Fuel stations, refuelling, vehicle controls, and vehicle state.
- Game clock, date, time-of-day, weather, lighting, and seasonal behavior.
- Map generation, OSM processing, PBF input, and map chunk delivery.
- Server-client protocol, message parsing, and state synchronization.
- Godot scenes, scripts, UI, rendering state, and input handling.
- Asset loading, audio, configuration, and startup/shutdown behavior.
- Packaging, release scripts, and CI workflows.
- Existing automated tests, fixtures, test utilities, and test dependencies.

Identify which important behaviors have no automated coverage and which tests exist but do not provide meaningful regression protection.

Produce a test coverage matrix with:
- Subsystem.
- Important behaviors and invariants.
- Existing tests.
- Missing tests.
- Test level required.
- Priority and rationale.

Prioritize failures that can corrupt game state, break progression, produce incorrect passenger or financial data, or prevent a release.

## Phase 2 — Establish a reliable test foundation

Standardize the testing workflow around the tools already used by the project.

For Python:
- Use the existing test framework where practical, or pytest if no suitable framework exists.
- Make unit and integration tests runnable from a documented, repeatable command.
- Separate fast tests from slower integration, simulation, and performance tests.
- Ensure tests do not depend on the developer's home directory, installed game state, live external services, or a particular working directory.
- Use temporary directories and isolated test data.
- Ensure cleanup occurs even when a test fails.

For Godot:
- Inspect the current Godot version and existing testing capabilities.
- Add headless startup, script validation, and scene/resource loading checks where supported.
- Add automated behavioral tests for important client-side logic using the existing framework or a lightweight compatible approach.
- Do not introduce a large testing framework without a demonstrated need.
- Clearly distinguish a successful project startup from actual behavioral test coverage.

For integration tests:
- Provide a repeatable way to launch the server and client or the relevant components in a controlled test environment.
- Make test failures diagnosable, including logs and the failed assertion.
- Avoid relying on timing-sensitive sleeps where explicit state checks or synchronization are possible.

Document the exact commands needed to run each test category.

## Phase 3 — Define game-wide invariants

Identify critical invariants that must remain true throughout a session.

Create automated tests for these invariants at the appropriate test levels.

### Passenger and trip lifecycle

Explicitly test the recently fixed passenger identity defect.

Add regression tests proving that:
- A passenger's stable identity does not change when a ride ends.
- Passenger identity is not accidentally replaced when a trip object is completed, cleared, recycled, or reused.
- Passenger names and identifiers remain correctly associated with the relevant passenger.
- Completing one ride does not corrupt the next ride.
- Passenger pickup, waiting, boarding, transport, drop-off, and post-trip cleanup preserve valid state transitions.
- A passenger cannot be picked up twice or completed twice unless the game explicitly supports that behavior.
- Cancellation, failed pickup, and exceptional cleanup do not leave orphaned passengers or inconsistent trip state.
- Multiple passengers with similar names remain distinguishable by stable identifiers.

Test actual public behavior and lifecycle transitions rather than merely checking private implementation details.

### Taxi, fare, and financial state

Where applicable, test:
- Starting and completing a fare.
- Initial fare and subsequent fare calculations.
- Fare modifiers and bonuses.
- Passenger pickup and drop-off conditions.
- Payment, fuel costs, and balance changes.
- Failed operations that must not charge the player.
- Duplicate commands and repeated input.
- Correct cleanup after completed or cancelled operations.

Use exact expected results for deterministic calculations and tolerances only where floating-point calculations genuinely require them.

### Vehicle and control state

Test:
- Entering and leaving vehicles.
- Acceleration, braking, and stopping.
- Input release and repeated key presses.
- Vehicle state synchronization between server and client.
- Refuelling eligibility, costs, duration, and completion.
- Signals, headlights, and other state transitions where controlled by game logic.
- Invalid or repeated commands.
- Vehicle recovery and despawning, if supported.

### NPC and world state

Test:
- NPC spawning and despawning.
- Passenger and NPC lifecycle cleanup.
- Duplicate spawning prevention.
- Destination selection and route failure.
- Traffic-light phase transitions.
- Roadworks and road restrictions.
- Population and traffic demand constraints where implemented.
- Time-of-day and weather transitions.
- Long-running simulation stability.

Do not invent expected behaviors that the game does not support. Inspect the current rules and document ambiguities before turning them into assertions.

## Phase 4 — Test state machines and lifecycle boundaries

Find entities and processes with multi-step lifecycles, and represent their valid states and transitions explicitly in tests.

Prioritize:
- Passengers and taxi rides.
- NPC vehicles and trips.
- Refuelling.
- Train passengers and meet-and-greet.
- Time-dependent events.
- Server-client connection and disconnection.
- Map chunk loading and unloading.
- Game startup and shutdown.

For each important lifecycle:
1. Identify valid states and transitions.
2. Define forbidden transitions.
3. Test success paths.
4. Test cancellation and failure paths.
5. Test repeated calls and duplicate events.
6. Test cleanup and recovery.
7. Test interactions with the next lifecycle instance.

Where practical, add property-based or randomized state-transition tests using deterministic seeds. Keep these tests reproducible and bounded.

## Phase 5 — Server-client protocol and integration testing

Test the actual boundaries between Python and Godot.

Cover:
- Valid messages and normal state updates.
- Missing, malformed, or unexpected fields.
- Unknown message types.
- Invalid identifiers and out-of-range values.
- Connection loss and reconnection behavior where supported.
- Rapid successive updates.
- Duplicate or delayed commands.
- State changes arriving in an unexpected order.
- Map chunk delivery and entity lifecycle synchronization.
- Server-side authority over gameplay decisions.
- Compatibility between the current server and current client protocol.

Verify that malformed input fails safely rather than crashing the entire simulation or corrupting persistent state.

Do not assume that every message requires backward compatibility. First establish the protocol's actual compatibility policy, then test it.

Use realistic test fixtures and representative protocol payloads from the current implementation. Avoid replacing the actual protocol with a test-only imitation.

## Phase 6 — End-to-end gameplay regression tests

Create a small set of high-value automated scenarios that exercise multiple subsystems together.

Include scenarios such as:
- Start the server and initialize a new gameplay session.
- Load a representative map area.
- Spawn or select a passenger.
- Accept a fare, reach the pickup point, collect the passenger, and complete the trip.
- Verify passenger identity, fare, player balance, and cleanup after completion.
- Start and complete another trip to detect state leakage between rides.
- Refuel a vehicle under valid conditions and reject invalid attempts.
- Process a train-related passenger interaction, where the required fixtures are available.
- Advance game time and verify relevant scheduled transitions.
- Disconnect and reconnect a client, where supported, without corrupting authoritative server state.

Keep end-to-end tests deterministic and relatively few. Test most combinations at lower levels to avoid making the test suite unnecessarily slow.

Where full graphical automation is unreliable, test the underlying behavior at the server or integration level and separately verify that Godot can load the relevant scenes and scripts.

## Phase 7 — Edge cases and failure injection

Systematically test boundaries that are commonly overlooked.

Examples:
- Empty collections and missing optional data.
- Invalid coordinates and unavailable routes.
- Missing or corrupt map assets.
- Unexpected entity removal.
- Duplicate commands.
- Repeated key presses.
- Rapid state transitions.
- Zero or negative quantities where invalid.
- Unexpected disconnections.
- Time advancing across midnight, a day boundary, a month boundary, or a year boundary.
- Missing external data and unavailable services.
- Startup failure and orderly shutdown.
- Repeated initialization and cleanup.
- Exceptions during a multi-step operation.

Do not test invalid inputs blindly. Derive valid ranges and expected error behavior from the actual implementation and requirements.

## Phase 8 — Deterministic simulation and long-running tests

Make important server simulation tests reproducible.

Where possible:
- Control random seeds.
- Control or inject game time.
- Isolate external data.
- Record relevant initial conditions.
- Compare important state outcomes rather than brittle implementation-specific snapshots.

Create bounded simulation tests that run for many in-game minutes or hours and detect:
- Exceptions and crashes.
- Entity count growth without a valid cause.
- Orphaned passengers or vehicles.
- Duplicate active trips.
- Impossible lifecycle transitions.
- Stuck NPCs or repeatedly failed state transitions.
- Memory growth that indicates a leak.
- Unexpected changes in player balance or trip state.

Use representative urban, suburban, and rural scenarios when corresponding map fixtures are available.

Long-running tests must have clear timeouts and useful diagnostics. Keep them separate from the fastest unit-test suite.

## Phase 9 — Performance and resource regression tests

Establish a baseline before making performance-related changes.

Measure:
- Python test and simulation execution time.
- Server update cost and relevant entity-processing costs.
- Startup time and map initialization where reproducible.
- Memory usage during a controlled session.
- Godot headless startup and resource loading where applicable.
- FPS in a repeatable graphical benchmark where automation supports it.
- Behavior with representative map sizes and entity counts.

Use fixed seeds and repeatable scenarios where possible. Document hardware, rendering mode, resolution, duration, and workload for graphical measurements.

Do not introduce fragile CI assertions based on one noisy timing measurement. Use performance thresholds only when the measurement is sufficiently stable and the threshold is justified.

Preserve the current game's performance. Do not use this task to redesign map loading or address the known PBF stuttering issue.

## Phase 10 — CI and release gates

Inspect the current CI setup and extend it to run the appropriate tests automatically.

The proposed workflow should distinguish:
1. Fast unit tests.
2. Integration and protocol tests.
3. Godot validation and headless checks.
4. End-to-end gameplay tests.
5. Longer simulation tests.
6. Performance benchmarks.
7. Packaging and release validation.

Run fast checks for every relevant change. Run slower suites at suitable stages, such as pull requests, scheduled runs, or release candidates.

A release candidate must not be considered validated solely because unit tests pass.

Report test failures clearly, retain useful logs, and make it easy to reproduce failures locally.

If a test cannot run in the available CI environment, document the limitation and provide a repeatable manual procedure instead of silently skipping the test.

## Phase 11 — Regression tests for every discovered bug

Establish a permanent bug-fix workflow:

1. Reproduce the bug with the smallest reliable test.
2. Add a regression test that fails before the fix, whenever feasible.
3. Implement the fix.
4. Verify that the regression test passes.
5. Run relevant subsystem and integration tests.
6. Record the test in the coverage matrix.
7. Document any behavior that remains unverified.

Where a reported bug cannot be reproduced automatically, document the exact reproduction steps and the reason automation is currently impractical.

Do not consider a bug fully regression-protected merely because the original symptom no longer appears manually.

## Phase 12 — Maintainable test architecture

Design the test suite so that future contributors and coding agents can understand and extend it.

Provide:
- `TESTING.md` with commands, test categories, setup, and troubleshooting.
- A test coverage matrix organized by subsystem and critical behavior.
- Reusable fixtures for common entities and scenarios.
- A documented approach to deterministic time and randomness.
- Guidance for writing regression tests.
- A list of important behaviors that still require manual verification.
- A short explanation of how test failures should block or permit release progression.

Use clear names and small, focused tests. Avoid excessive mocking that hides integration defects. Prefer stable public interfaces and observable state.

Do not pursue a numerical code-coverage target at the expense of meaningful behavioral tests. Use coverage measurements as a diagnostic tool to find untested critical code, not as the primary measure of quality.

## Delivery plan

Work in incremental, reviewable stages:

1. Audit and baseline the existing tests.
2. Establish or improve the shared testing infrastructure.
3. Add critical lifecycle and identity regression tests.
4. Add protocol and subsystem integration tests.
5. Add representative end-to-end scenarios.
6. Add deterministic long-running and performance checks.
7. Integrate appropriate checks into CI.
8. Document remaining gaps and release criteria.

Prioritize meaningful regression protection over the number of tests added. Avoid a massive one-shot rewrite.

## Final report

Report:
- The existing testing infrastructure and its initial weaknesses.
- The most important untested behaviors discovered.
- The passenger identity regression test and its results.
- Tests added, grouped by subsystem and test level.
- Exact commands executed and their results.
- Tests that could not run and why.
- Performance results and any measurable impact.
- CI changes and release-gate behavior.
- Remaining testing gaps and manual verification requirements.
- All changed files and the commits created.

Do not claim comprehensive coverage unless the actual evidence supports it.

Commit the work on the current working branch and push it if the existing workflow permits it. Do not create or push Git tags.