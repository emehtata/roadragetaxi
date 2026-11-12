# Implement First-Person Walking Mode – Taxi Driver Perspective

## Objective

Introduce a fully functional first-person gameplay mode in Road Rage Taxi.

The player must be able to leave their taxi, walk freely around the existing 3D game world, look around, explore locations and interact with the environment.

This is not a separate game mode with a separate world. It is a new way of experiencing the existing simulation.

The player remains the same taxi driver throughout the experience.

## 1. Architecture audit

Before implementation, inspect:

- Existing Godot 3D rendering architecture.
- Current player representation and player ID.
- Python server-side player and vehicle state.
- Network protocol and update frequency.
- Existing vehicle entry and exit mechanics.
- Existing map chunk streaming.
- Building geometry and collision information.
- Existing pedestrian models and animations.
- Existing interaction systems.

Determine which systems can be reused.

Do not create a parallel player simulation or duplicate existing game-world state.

Document the findings before making architectural changes.

## 2. First-person camera

Implement a dedicated first-person camera attached to the player character.

Requirements:

- Realistic human eye height, approximately 1.65–1.75 metres.
- Mouse-controlled horizontal and vertical looking.
- Natural camera rotation.
- Configurable mouse sensitivity.
- Vertical camera rotation limits.
- Smooth camera transitions when entering and leaving vehicles.
- Camera must follow the actual server-authoritative player position.

Avoid excessive camera movement or unnecessary head bobbing.

The camera must work correctly both indoors and outdoors.

## 3. Player movement

Implement walking controls:

- W: Forward
- S: Backward
- A: Left
- D: Right
- Mouse: Look around
- Shift: Sprint
- E: Interact
- Escape: Release mouse / open game menu

Requirements:

- Natural walking speed.
- Separate sprinting speed.
- Smooth acceleration and deceleration.
- Correct movement relative to camera direction.
- No sliding through buildings, walls or other solid objects.
- Proper ground alignment.
- Support for different terrain elevations and slopes.
- No walking through vehicles.

Use configurable movement parameters.

Do not implement jumping unless the existing gameplay architecture supports it appropriately.

## 4. Server-authoritative movement

This is a critical architectural requirement.

The Python server remains authoritative for player position and movement.

Godot handles:

- Input collection.
- Camera rotation.
- Visual player representation.
- Movement interpolation.
- Animation presentation.

The server handles:

- Player position.
- Movement validation.
- Walking speed and sprint speed limits.
- Collision detection.
- Ground elevation.
- Interaction distance validation.

Do not introduce client-authoritative physics or client-side collision shapes.

Investigate whether existing server-side collision and building geometry systems can be reused for pedestrian movement.

If necessary, implement a lightweight server-side pedestrian collision model.

Avoid introducing expensive operations into the existing 30 Hz simulation tick.

## 5. Leaving and entering the taxi

Implement a complete vehicle transition.

### Leaving the taxi

- Player presses the configured exit key.
- Server validates that exiting is possible.
- Player is positioned beside the vehicle, preferably near the driver's door.
- Vehicle door opens if door animation is supported.
- First-person camera transitions to the player's eye position.
- Player can immediately start walking.

### Returning to the taxi

- Player approaches the driver's door.
- Interaction prompt appears.
- Player presses E.
- Server validates proximity and vehicle availability.
- Player enters the driver's seat.
- Camera transitions to the existing vehicle camera.
- Existing driving controls become active.

Important:
- Preserve vehicle state when the player exits.
- The taxi must not disappear.
- The vehicle must not teleport.
- The vehicle must not start moving without a driver.
- Existing vehicle simulation must remain functional.

Initially, implement driver's-seat entry and exit only.

## 6. Player character representation

Create a reusable 3D human character representation.

Requirements:

- Appropriate human proportions.
- Natural standing posture.
- Basic walking animation.
- Sprint animation if practical.
- Character orientation follows movement direction.

The player character should not be visible from inside their own first-person camera.

However, the character must remain available for:
- Third-person inspection if introduced later.
- NPC interactions.
- Other players if multiplayer is introduced in the future.
- Animation and interaction systems.

Reuse existing pedestrian assets or animation infrastructure where practical.

## 7. Environment interaction

Create a reusable interaction framework.

Initially support:

- Entering and exiting the taxi.
- Interacting with vehicle doors.
- Approaching and inspecting buildings.
- Interacting with suitable world objects.

Show contextual interaction prompts only when the player is within valid interaction distance.

All important interactions must be validated by the server.

Do not implement building interiors in this phase unless an existing interior system can be reused without significant additional work.

## 8. World integration

The first-person mode must use the existing world.

Verify:

- Actual 3D buildings.
- Correct building scale and ground placement.
- Forests with visible 3D trees, including trunks.
- Roads, sidewalks and terrain.
- Streetlights and other lighting.
- Parked and moving vehicles.
- Pedestrians and animals.
- Existing map chunk streaming.

The player must be able to walk along streets, sidewalks and through suitable open areas.

Do not replace existing world geometry with a separate FPS environment.

## 9. Streaming and simulation continuity

The existing map chunk system must continue to work.

Requirements:

- Chunks load around the walking player.
- Chunks unload when sufficiently distant.
- Walking must not cause missing geometry.
- The player must not get stuck at chunk boundaries.
- NPC traffic and pedestrians continue operating.
- Server simulation remains independent of camera mode.

Ensure that chunk loading does not repeatedly reset or invalidate player state.

## 10. Testing

Create reproducible test scenarios using actual locations in the game world.

Do not position the player randomly without considering the environment.

Test at least:

1. Exiting a parked taxi on a normal city street.
2. Walking along a sidewalk.
3. Turning around and looking at nearby buildings.
4. Walking through a park.
5. Walking into a forest.
6. Approaching another vehicle.
7. Re-entering the original taxi.
8. Walking across different terrain elevations.
9. Moving between map chunks.
10. Walking while NPC traffic continues operating.

Use actual game locations with suitable surroundings.

Capture screenshots from the running game.

## 11. Performance

Maintain the existing performance targets:

- Stable performance above 60 FPS.
- Preserve the Python simulation's 30 Hz tick.
- Avoid expensive per-frame server operations.
- Avoid unnecessary network traffic.
- Use interpolation for remote world state.
- Avoid creating excessive Godot nodes.

Measure performance both while standing still and while walking through dense urban and forest environments.

## 12. Implementation phases

Implement incrementally:

Phase 1:
- First-person camera.
- Basic walking.
- Server-authoritative player movement.
- Basic collision handling.

Phase 2:
- Taxi exit and re-entry.
- Camera transitions.
- Interaction prompts.

Phase 3:
- Character model and animations.
- Environment interaction framework.

Phase 4:
- Integration testing.
- Performance audit.
- Visual refinement.

Each phase must be independently testable.

## 13. Delivery requirements

Provide:

- Architecture audit.
- Description of the implemented player state.
- Network protocol changes.
- Files changed.
- Screenshots of actual gameplay.
- Performance measurements.
- Known limitations.

Commit each logically complete implementation step separately.

Do not create Git tags.

Do not declare the feature complete until the player can reliably leave a taxi, walk around the actual game world, explore it and return to the same taxi.