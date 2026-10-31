# Implement Taxi Driver Conflicts and Fights

## Objective

Implement a lightweight, server-authoritative taxi driver conflict and fighting system in Road Rage Taxi.

The Python simulation server must control conflict initiation, participant selection, state transitions, combat outcomes, and gameplay consequences. Godot must present the events visually through character movement, animations, and sound.

The architecture must support both NPC-versus-NPC conflicts and future player-versus-NPC conflicts. Active player-controlled combat is not required in this implementation, but the participant model and server-side interfaces must not prevent it from being added later.

Preserve the existing architecture, simulation behavior, performance, and networking conventions. Do not introduce a separate NPC simulation or a parallel gameplay protocol.

## Phase 1: Audit the existing implementation

Before making changes, inspect the current codebase and identify:

1. The Python simulation server entry points, simulation update loop, NPC lifecycle, and vehicle ownership.
2. The current NPC driver representation and how driver identities relate to vehicles and passengers.
3. Existing NPC movement, navigation, vehicle stopping, and driver exit/entry behavior.
4. The current client-server protocol, message validation, event delivery, and state synchronization.
5. The Godot character models, animation resources, audio resources, and relevant scene architecture.
6. Existing traffic incidents, collisions, passenger pickup logic, taxi stands, time-of-day systems, and NPC behavior systems that could provide valid conflict triggers.
7. Existing tests, simulation benchmarks, logging conventions, and configuration mechanisms.

Reuse existing systems wherever practical. Do not assume that a feature, animation, asset, configuration key, or protocol message exists until it has been verified in the repository.

Provide a concise implementation plan based on the actual code, then implement the feature.

## Phase 2: Define the conflict model

Introduce a clearly defined conflict state machine. Use the following logical states, adapting names to existing project conventions where appropriate:

- IDLE
- TRIGGERED
- CONFRONTATION
- ESCALATION
- FIGHTING
- RESOLUTION
- COOLDOWN

Each active conflict must have a unique identifier and explicit participant references.

Track the minimum state required to resume, synchronize, resolve, and clean up a conflict, including:

- Conflict identifier.
- Participant identifiers and participant types.
- Current state.
- Conflict location.
- Relevant timestamps or simulation-time deadlines.
- Current combat action, when applicable.
- Resolution outcome.
- Any cooldown or duplicate-trigger prevention data.

Do not create a second driver or NPC identity for a participant who already exists in the simulation.

Validate every state transition. Invalid, stale, duplicated, or out-of-order events must not produce duplicate hits, duplicate rewards, or invalid participant states.

Every conflict must have a bounded lifetime and a guaranteed cleanup path.

## Phase 3: Implement conflict triggers

Implement the following initial trigger categories using existing simulation events and data where available:

### A. Passenger competition

Two taxi drivers compete for the same prospective passenger, or an existing passenger-related event creates a credible dispute.

Do not generate a conflict merely because two taxis are close to each other. Verify that the underlying passenger competition or dispute actually exists.

### B. Traffic incidents

Existing collisions, dangerous driving events, or other suitable traffic incidents may trigger a confrontation.

Do not introduce arbitrary collisions or invent traffic events solely to force a fight.

### C. Nightlife and taxi ranks

Allow the probability of a conflict to vary with location, time of day, and relevant existing world context.

Use existing taxi rank, world-location, and simulation-clock data where available. If nightlife locations are not explicitly represented, use a conservative fallback rather than introducing a large new location database.

### Trigger eligibility

Before starting a conflict, validate at least:

- Both participants exist and are eligible.
- The participants are not already involved in another conflict.
- The trigger is valid and relevant to the participants.
- The participants can reasonably interact at their current locations.
- Neither participant is in a passenger-carrying state that makes the confrontation inappropriate.
- Neither vehicle or driver is already in an incompatible state.
- The trigger has not already been processed.

If a participant is carrying a passenger, reject or safely abort the conflict unless the existing gameplay rules explicitly support that situation.

Centralize tunable probabilities and cooldowns in the project's existing configuration mechanism. Avoid scattered magic numbers and hard-coded trigger probabilities.

Keep conflicts rare by default. Do not invent precise real-world incident rates; choose conservative initial values and make them configurable.

## Phase 4: Implement server-authoritative combat

Represent physical combat as lightweight, discrete simulation actions rather than a continuous physics simulation.

Possible actions include:

- Threatening or intimidating.
- Attempting a strike.
- Dodging or defending.
- Staggering or falling.
- Retreating or surrendering.

Use only as many actions as necessary for a coherent initial implementation.

The Python server must determine action selection, action validity, hit outcomes, and resolution. Godot must never independently decide whether an attack hits or who wins.

Use the existing random-number conventions where available. Support deterministic tests by allowing the relevant random source or seed to be controlled through established project testing mechanisms.

Combat outcomes should depend on a small, explicit set of participant attributes, such as aggression, fighting ability, and willingness to retreat.

Reuse existing character attributes if suitable. Otherwise, introduce minimal, bounded attributes with conservative defaults. Avoid complex RPG statistics, persistent progression, or extensive balancing systems in this initial implementation.

Make sure that:
- Combat actions cannot occur faster than the intended simulation action interval.
- Every action has a valid source state and participant.
- A participant cannot attack themselves.
- A participant cannot continue fighting after the conflict has ended.
- A conflict cannot resolve multiple times.
- Outcomes remain valid if a participant disconnects, despawns, becomes unavailable, or otherwise leaves the simulation.
- Combat does not require frame-by-frame server physics.

## Phase 5: Integrate with vehicle and driver behavior

Integrate conflicts with the existing driver and vehicle lifecycle.

Where supported by existing systems:

1. Stop participating vehicles safely.
2. Prevent normal driving logic from moving the vehicles during the conflict.
3. Transition the drivers into an appropriate temporary on-foot state.
4. Keep vehicle ownership and participant identity consistent.
5. Restore normal driver behavior after resolution.
6. Release any temporary movement restrictions, reservations, or conflict locks.

Do not implement a parallel vehicle movement system or duplicate existing driver exit/entry logic.

If the current implementation cannot support a required transition safely, document the limitation and implement the smallest compatible extension.

Ensure that aborted conflicts cannot leave vehicles permanently stopped or drivers stuck outside their vehicles.

## Phase 6: Integrate Godot presentation

Inspect the existing Godot character and animation systems before implementing presentation.

Add client-side presentation for the supported conflict states, including as many of the following as the existing assets permit:

- Driver exit and approach.
- Confrontational body language.
- Verbal confrontation.
- Strikes and defensive reactions.
- Staggering or falling.
- Retreat and return to the vehicle.

Use existing animations and audio resources where possible. Do not assume that suitable fighting animations or character models already exist.

If suitable assets are unavailable, provide a safe fallback presentation using supported movement, animation, or other existing visual capabilities. Missing assets must never prevent the simulation from resolving a conflict.

Godot must render the server-authoritative state and outcome. It may interpolate character movement and presentation timing, but must not invent combat outcomes.

Presentation must tolerate delayed, duplicated, or missing intermediate updates. A newly connected or resynchronized client must not replay an entire completed fight merely because it receives a state snapshot.

Keep rendering and animation work independent of the server simulation update rate. Avoid expensive per-frame processing for every NPC.

## Phase 7: Protocol and synchronization

Extend the existing protocol only as required.

Follow the project's current message structure, versioning conventions, serialization rules, and validation patterns.

Include enough information for clients to identify the conflict, its participants, current state, relevant action, and final outcome.

Ensure that:
- All incoming client messages are validated.
- Clients cannot submit authoritative combat outcomes.
- Duplicate messages cannot apply a hit or consequence more than once.
- Invalid participant identifiers are rejected safely.
- State updates cannot resurrect a completed conflict.
- Conflict state and presentation are cleaned up after completion.
- Existing clients and unrelated gameplay systems are not broken unnecessarily.

Do not create an unrelated new networking framework.

## Phase 8: Future player participation

Prepare the data model and server-side interfaces for a future player-versus-NPC conflict.

Represent participants through an explicit, extensible participant abstraction or the project's existing equivalent. Support the distinction between NPCs and players without assuming that all participants are NPC drivers.

For this implementation:
- NPC-versus-NPC conflicts must work end to end.
- Player-versus-NPC conflicts may be recognized as a supported future participant type where the existing architecture allows it.
- Do not implement a complete player combat controller, combat UI, or new player input scheme unless existing project functionality makes a small part of this necessary.
- Do not allow clients to bypass server validation by submitting combat results.

Document the extension points needed to implement active player participation later.

## Phase 9: Consequences and cleanup

Implement only consequences that are supported by existing project systems.

At minimum:
- Record the conflict outcome in the existing logging or event system.
- Release participant and vehicle locks.
- Restore normal NPC behavior.
- Prevent immediate duplicate conflicts through a configurable cooldown.
- Ensure all temporary objects and state are cleaned up.

Nearby NPC reactions may be added if an existing reaction or behavior system supports them without significant overhead.

Do not invent independent police, reputation, hospital, compensation, injury persistence, or vehicle damage systems. If these would require new infrastructure, document them as future extensions.

## Phase 10: Performance requirements

The feature must not significantly increase the cost of the normal simulation when no conflicts are active.

- Avoid scanning every NPC against every other NPC on every simulation tick.
- Prefer existing event-driven triggers, spatial queries, or bounded local candidate searches.
- Process detailed combat logic only for active conflicts.
- Avoid per-frame server-side combat updates.
- Avoid unbounded event queues, persistent conflict records, and stale participant references.
- Avoid blocking I/O and unnecessary serialization.
- Preserve the existing Godot rendering performance.
- Do not reduce existing NPC counts or introduce arbitrary global NPC caps to accommodate this feature.

Measure the impact with the project's existing benchmark or profiling workflow where available. Report the measured results and test conditions rather than claiming performance improvements without evidence.

## Phase 11: Testing

Add automated tests following the repository's existing testing conventions.

Cover at least:

1. A valid conflict can start.
2. Each supported trigger is validated correctly.
3. Invalid or ineligible participants are rejected.
4. A participant cannot join multiple simultaneous conflicts.
5. State transitions follow the defined state machine.
6. Combat outcomes are determined by the server.
7. Deterministic tests can reproduce expected outcomes.
8. Duplicate triggers and messages do not apply duplicate consequences.
9. Conflicts terminate and clean up correctly.
10. A participant disappearing or becoming unavailable does not break the simulation.
11. Drivers and vehicles return to normal operation after resolution.
12. A passenger-carrying taxi does not enter an unsupported confrontation.
13. Cooldowns prevent immediate repeated conflicts.
14. Godot presentation handles state changes and completed-conflict snapshots safely.
15. Existing simulation, protocol, and relevant gameplay tests continue to pass.

Where feasible, add an integration test that runs a complete NPC-versus-NPC conflict from trigger to cleanup.

Include a way to trigger a deterministic test conflict through existing development or test infrastructure. Do not add a player-facing cheat or debug interface unless the project already has an appropriate mechanism.

## Phase 12: Documentation and delivery

Document:
- The conflict state machine.
- Trigger eligibility and configurable parameters.
- Server/client responsibilities.
- Protocol changes.
- Performance considerations.
- Known limitations.
- Extension points for player participation and future consequences.

Run the relevant automated tests, static checks, and existing benchmarks that are available.

Use atomic Git commits organized by logical implementation milestones. Do not create Git tags unless explicitly requested.

## Implementation constraints

- Preserve the existing architecture and gameplay behavior.
- Prefer small, maintainable changes over a broad refactor.
- Do not change the simulation language as part of this task.
- Do not develop a separate Pygame renderer.
- Do not add arbitrary NPC population limits.
- Do not invent file paths, configuration variables, message types, assets, or APIs without inspecting the repository.
- Do not silently skip failing tests. Report failures and distinguish pre-existing failures from regressions where possible.
- Do not claim that a feature or test works unless it has been implemented or verified.

## Final report

When implementation is complete, provide:
1. A summary of the implemented behavior.
2. The main files and architectural components changed.
3. The state machine and trigger logic.
4. Protocol and Godot integration details.
5. Tests run and their actual results.
6. Performance measurements, including test conditions.
7. Known limitations and the concrete next steps for enabling active player participation.

Begin by auditing the existing codebase, then implement the feature in small, testable increments.