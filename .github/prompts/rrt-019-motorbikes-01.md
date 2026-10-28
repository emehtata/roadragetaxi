# Implement Motorcycle NPC Traffic in Road Rage Taxi

## Objective

Add motorcycles as a new type of NPC traffic vehicle in Road Rage Taxi. Motorcycles must integrate with the existing traffic simulation, vehicle lifecycle, navigation, rendering, and traffic rules.

Seasonal behavior is essential: **motorcycles must not appear in traffic during the Finnish winter**. Their frequency must vary naturally according to the time of year.

Before implementing anything, inspect the existing architecture and identify the current NPC vehicle creation, traffic simulation, vehicle movement, collision detection, map streaming, and Godot rendering systems. Reuse existing mechanisms wherever possible.

## 1. Architecture and compatibility

- Follow the existing separation of responsibilities: Python remains responsible for authoritative game simulation and traffic rules, while Godot handles rendering.
- Do not introduce client-side physics or collision shapes. Follow the existing server-side collision detection and vehicle interaction architecture.
- Integrate motorcycles into the existing NPC vehicle model rather than implementing a separate, disconnected traffic simulation.
- Inspect existing vehicle types, configuration, spawn logic, road navigation, and vehicle serialization before making changes.
- Reuse existing road-following, pathfinding, traffic-light handling, lane selection, and vehicle lifecycle systems where applicable.
- Preserve existing behavior for cars, buses, trucks, bicycles, and other traffic participants.
- Do not introduce arbitrary NPC limits or reduce existing traffic populations to compensate for the new vehicle type.
- Maintain existing performance characteristics and avoid unnecessary per-frame calculations.
- Keep the implementation compatible with the existing game protocol and map-chunk streaming architecture.

## 2. Seasonal motorcycle availability

Implement a centralized, configurable seasonal motorcycle traffic model based on the simulated in-game date.

The game takes place in Finland. Motorcycle traffic must follow realistic Finnish seasonal patterns.

### Winter: no motorcycles

- Do not spawn motorcycles during the Finnish winter.
- The winter exclusion must be absolute: the motorcycle spawn probability must be zero during the configured winter period.
- Existing motorcycles must not remain active in the world when the simulation transitions into the winter exclusion period. Handle this transition safely using the existing NPC lifecycle mechanisms.
- Do not confuse the operating system date with the simulated game date. Use the authoritative in-game calendar.

### Spring: gradual increase

- Motorcycle traffic begins to appear as the weather and season become suitable for riding.
- Traffic frequency increases gradually rather than switching immediately from zero to full summer traffic.
- Early spring must have substantially fewer motorcycles than late spring.
- The exact seasonal start and transition dates must be configurable.

### Summer: peak season

- Summer has the highest motorcycle traffic frequency.
- Motorcycles should appear naturally among other traffic participants without dominating the traffic population.
- Traffic frequency should vary according to location, time of day, and the existing traffic density model where supported.

### Autumn: gradual decrease

- Motorcycle traffic decreases as autumn progresses.
- Early autumn can still have noticeable motorcycle traffic.
- Late autumn must have substantially fewer motorcycles than summer.
- Motorcycle traffic must reach zero when the configured winter exclusion period begins.

### Seasonal model requirements

- Centralize the seasonal probability calculation instead of scattering month checks throughout the codebase.
- Use the existing simulated date and time systems.
- Make seasonal transition dates and traffic multipliers configurable using the project's established configuration conventions.
- Avoid abrupt traffic changes except at the mandatory winter exclusion boundary.
- Ensure that changing the simulated date or advancing time across a seasonal boundary produces correct results.
- Do not introduce a new weather dependency unless the existing architecture already provides relevant weather data and integrating it is straightforward.

Use a clear seasonal configuration model, with separate controls for:
- Winter exclusion.
- Spring traffic multiplier.
- Summer traffic multiplier.
- Autumn traffic multiplier.
- Seasonal transition dates or equivalent transition parameters.

Choose sensible initial values based on the existing traffic model and document them.

## 3. Motorcycle vehicle behavior

Motorcycles must behave as motor vehicles, not as bicycles.

- Use the existing vehicle movement and road-following systems.
- Follow the applicable Finnish traffic rules already documented in the project.
- Respect traffic lights, road directions, intersections, and applicable speed limits.
- Integrate with existing lane and route navigation behavior.
- Avoid inventing motorcycle-specific traffic rules without a clear gameplay or simulation requirement.
- Reuse existing vehicle speed, acceleration, and braking mechanisms where practical.
- Define appropriate motorcycle-specific configuration values where the existing model supports them.
- Ensure motorcycles do not behave like cars with respect to physical dimensions if the vehicle model supports vehicle-specific geometry.
- Do not implement wheel physics, lean simulation, or other advanced motorcycle physics unless the current architecture already supports these features and they are necessary.

## 4. Collision detection and interaction

- Integrate motorcycles with the existing authoritative server-side collision detection system.
- Ensure motorcycle dimensions and collision geometry are appropriate to the existing collision model.
- Verify interactions with cars, buses, trucks, bicycles, pedestrians, and static obstacles.
- Prevent duplicate collision events and repeated collision processing.
- Ensure the addition of motorcycles does not introduce disproportionate collision-detection overhead.
- Reuse existing spatial indexing or broad-phase collision filtering if available.
- Do not move collision detection to Godot as part of this task.

## 5. NPC creation and traffic density

- Register motorcycles in the existing NPC vehicle creation and lifecycle systems.
- Apply seasonal availability at the appropriate point in the spawn pipeline.
- Seasonal multipliers must affect motorcycle traffic only, not the total traffic volume of unrelated vehicle types.
- Avoid creating motorcycles only to remove them immediately when a spawn attempt occurs during winter.
- Integrate with existing regional traffic density and time-of-day behavior where applicable.
- Ensure motorcycles can spawn and despawn correctly as map chunks load and unload.
- Prevent duplicate motorcycle spawning when chunks are reloaded.
- Do not introduce special motorcycle behavior that bypasses existing traffic-density rules.

## 6. Godot rendering

- Add motorcycle rendering to the existing Godot vehicle rendering pipeline.
- Inspect the current vehicle model selection and rendering architecture before implementing the new vehicle type.
- Reuse existing rendering mechanisms, transforms, interpolation, and visibility management.
- Use an existing motorcycle asset if the repository already contains one.
- If no suitable asset exists, implement the smallest maintainable extension of the existing vehicle representation and clearly document any temporary visual placeholder.
- Ensure motorcycles have the correct orientation, position, and scale.
- Preserve existing rendering performance and map-chunk visibility behavior.
- Do not modify the Pygame renderer.

## 7. Configuration and observability

- Make motorcycle traffic parameters configurable using established project conventions.
- Add appropriate diagnostic information to distinguish motorcycle spawn decisions from ordinary NPC vehicle creation.
- Avoid excessive logging during normal gameplay.
- If the project has existing debug statistics for NPC populations, include motorcycle counts in those statistics where appropriate.

## 8. Testing requirements

Add automated tests using the project's existing testing framework.

At minimum, verify:

1. Motorcycle spawn probability is zero throughout the configured winter exclusion period.
2. No motorcycles remain active after the simulation transitions into the winter exclusion period.
3. Motorcycle traffic increases gradually during spring.
4. Summer has the highest seasonal motorcycle traffic multiplier.
5. Motorcycle traffic decreases during autumn.
6. Seasonal calculations use the simulated game date, not the host operating system date.
7. Crossing seasonal boundaries during gameplay produces the expected behavior.
8. Seasonal motorcycle multipliers do not unintentionally alter car, bus, truck, or bicycle spawn rates.
9. Motorcycles participate in the existing vehicle lifecycle and navigation systems.
10. Motorcycles interact correctly with the existing collision detection system.
11. Map-chunk loading and unloading do not create duplicate motorcycles.
12. Existing vehicle spawning and traffic simulation tests continue to pass.

Use deterministic tests for seasonal calculations. Avoid flaky tests that depend on random spawn outcomes.

Where practical, add integration tests that verify the resulting motorcycle population under representative winter, spring, summer, and autumn dates.

## 9. Performance requirements

- Measure or estimate the additional cost of motorcycle simulation using existing profiling tools.
- Avoid adding unnecessary work to every simulation tick.
- Do not rebuild static motorcycle configuration or seasonal data repeatedly.
- Ensure that seasonal checks do not introduce avoidable overhead into the simulation hot path.
- Do not reduce the existing NPC population to make the implementation appear faster.

## 10. Documentation and delivery

- Update the relevant traffic simulation and vehicle documentation.
- Document the seasonal model, its configuration, and the winter exclusion behavior.
- Explain any assumptions made about Finnish motorcycle seasonality.
- Identify any missing assets or architectural limitations discovered during implementation.
- Run the relevant automated tests and report their results.
- Review the final diff to ensure that unrelated gameplay systems have not been modified unnecessarily.
- Organize the work into atomic Git commits, following the repository's existing conventions.

## Acceptance criteria

The implementation is complete when:

- Motorcycles use the existing NPC traffic architecture.
- Motorcycle traffic varies naturally throughout the simulated Finnish year.
- No motorcycles operate in the world during the configured winter exclusion period.
- Seasonal transitions work correctly when the simulated date advances.
- Motorcycles are rendered correctly by Godot.
- Existing traffic rules, collision handling, and other vehicle types remain functional.
- Automated tests cover the seasonal behavior and core integration points.
- The implementation does not introduce unnecessary performance overhead.