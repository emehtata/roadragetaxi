# Implement Ilokapina Protest Groups — Road Rage Taxi

## Context

Road Rage Taxi is a Finnish taxi-driving game with a Python simulation server and a Godot rendering client. The server owns gameplay rules, NPC behavior, traffic simulation, collisions, and authoritative world state. Godot handles rendering and presentation.

Implement a new dynamic world event featuring **Ilokapina**, a fictional satirical protest movement opposing road rage and aggressive driving.

Protesters organize large sit-in demonstrations directly on roads, blocking traffic. The player's taxi cannot pass through an active protest group normally. The player must use the existing road-rage gameplay mechanic to intimidate the protesters into moving aside, temporarily clearing a path.

Before implementing anything, inspect the repository and identify the existing systems for NPC pedestrians, road navigation, road rage, anger state, collision handling, world events, and client-server communication.

## Gameplay requirements

### 1. Protest group spawning

- Introduce Ilokapina as a new type of pedestrian group and dynamic traffic obstruction.
- Spawn protest groups at suitable road locations, preferably where they can meaningfully disrupt traffic without making the entire map impassable.
- Use existing map and road data to position groups correctly on the road surface.
- Protesters should sit in large groups across the roadway, with varied positions, orientations, and animations or visual poses where supported.
- Groups should be more likely to appear during appropriate daytime periods and on suitable days, but the system must support configurable schedules.
- Avoid spawning groups directly on top of the player, inside buildings, at intersections where they would cause unavoidable deadlocks, or in locations where they cannot be rendered correctly.
- Prevent overlapping protest events and excessive event density.
- Make spawning deterministic where the existing simulation architecture requires deterministic behavior.

### 2. Blocking behavior

- An active protest group must block the usable road width so the player's taxi cannot simply drive through it.
- Use the existing authoritative server-side collision and traffic-obstruction mechanisms. Do not implement client-only collision rules.
- Other traffic should respond plausibly to the obstruction, stopping or waiting where appropriate rather than driving through protesters.
- Ensure that blocked traffic does not cause unbounded NPC queues, simulation deadlocks, or excessive processing costs.
- Protesters must not be accidentally displaced by ordinary vehicle movement.

### 3. Road rage interaction

- Integrate the protest interaction with the game's existing road-rage mechanics. Inspect how the player currently activates road rage, how the anger meter works, and how intimidation affects other NPCs.
- A protest group must remain in place when approached normally. Honking or ordinary driving must not automatically clear the road unless existing mechanics explicitly require it.
- When the player activates road rage within a suitable distance of the group, trigger an intimidation response.
- Protesters should react collectively but not instantaneously: they become alarmed, hesitate, and then move toward the roadside, clearing a passage for the taxi.
- Use the existing anger or road-rage state where appropriate rather than introducing a competing system.
- Make the interaction readable and consistent with the existing gameplay controls.
- Road rage should have an appropriate gameplay cost or consequence, using existing systems where available. Do not invent a new monetary penalty or reputation system without first checking what the game already supports.
- Once intimidated, protesters should remain clear long enough for the taxi to pass. They may return to their sit-in after a configurable cooldown if doing so is safe.
- If the player drives away without intimidating the group, the protest should remain active.

### 4. Protester AI and visual presentation

- Represent a group as a single logical event with multiple visible protesters, rather than giving every individual an unnecessarily expensive independent AI simulation.
- Give protesters distinct states such as:
  - `SITTING`: occupying the roadway.
  - `ALARMED`: reacting to the player's road rage.
  - `CLEARING`: moving toward the roadside.
  - `CLEARED`: leaving sufficient space for the taxi to pass.
  - `RETURNING`: cautiously returning to the protest position, if safe.
- Adapt these states to the existing architecture instead of forcing this exact state machine if a more suitable pattern already exists.
- Reuse existing pedestrian models, sprites, or rendering conventions where possible.
- If pedestrian animation support is limited, implement the behavior using the lightest visual approach compatible with the current Godot client.
- The group should be recognizable as a coordinated sit-in protest, not merely a random crowd standing in the road.

### 5. Server-client protocol

- The server must remain authoritative for event creation, state transitions, obstruction behavior, and the conditions under which the road becomes passable.
- Extend the protocol only where necessary. Inspect existing event and NPC synchronization before adding new message fields.
- Ensure that clients joining an already-running session receive the current protest state.
- Handle streamed map chunks and changes in player location without duplicating groups or leaving stale visual objects behind.
- Keep simulation logic independent of Godot rendering code.

### 6. Performance

Performance is a critical requirement. Road Rage Taxi must remain playable on older PCs.

- Profile or inspect existing pedestrian and traffic simulation costs before choosing an implementation.
- Avoid a separate high-frequency update loop for every protester.
- Use distance-based simulation and rendering strategies consistent with the current architecture.
- Avoid unnecessary protocol traffic and repeated full-world scans.
- Do not introduce arbitrary global NPC limits or reduce existing NPC populations to accommodate this feature.
- Preserve existing rendering and simulation performance, especially when multiple traffic systems are active simultaneously.

### 7. Configuration and testing

- Make the number of groups, group size, spawning schedule, intimidation radius, clearing duration, and return delay configurable through the project's existing configuration conventions.
- Add tests for:
  - Valid and invalid spawn positions.
  - Road obstruction while the protest is active.
  - Road rage triggering the intimidation response.
  - Normal driving not clearing the obstruction.
  - Safe passage after protesters move aside.
  - Protesters not returning into the taxi's path.
  - Traffic and pedestrian interaction.
  - Event cleanup when a map chunk unloads or an event expires.
  - Synchronization of current event state to clients.
  - Performance with several simultaneous protest groups.
- Run the relevant existing test suite and add regression tests for any affected systems.

## Implementation workflow

1. Inspect the repository and report the existing systems that can be reused.
2. Identify the smallest architecture-compatible implementation.
3. Implement the authoritative simulation behavior first.
4. Add the necessary protocol changes and Godot-side visuals.
5. Add configuration and automated tests.
6. Run the relevant tests and report their results.
7. Summarize changed files, gameplay behavior, performance considerations, and any remaining limitations.

Do not rewrite unrelated systems, replace the current simulation architecture, or develop new Pygame rendering functionality. Preserve existing gameplay behavior and maintain compatibility with the current release branch.

Do not create or push Git tags. Do not push branches or commits unless explicitly requested.

## Acceptance criteria

The feature is complete when a large Ilokapina sit-in can block the player's route, ordinary driving cannot bypass the obstruction, activating the existing road-rage mechanic causes protesters to move aside, the taxi can safely pass, and the group behaves consistently in the authoritative simulation without a significant performance regression.