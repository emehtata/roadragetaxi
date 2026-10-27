# Implement nightclub music that leaks into nearby streets

Inspect the Road Rage Taxi repository and implement an immersive nightclub audio system in the Godot client.

## Goal

Nightclubs should emit loud electronic dance music that can be heard from nearby streets. The music should sound powerful and bass-heavy near the entrance, become quieter with distance, and be muffled by buildings and walls.

This is an environmental audio feature, not a new gameplay simulation system.

## 1. Repository inspection

Before making changes:

- Inspect the existing Godot audio architecture, world/map loading, building representation, coordinate system, audio buses and resource conventions.
- Find how buildings and other static map features are streamed and unloaded.
- Determine whether nightclub locations or relevant OSM tags already exist.
- Reuse existing systems wherever practical.
- Do not invent configuration variables, protocol fields, map attributes or resource paths. Verify them in the repository.
- Keep the implementation compatible with the existing server-authoritative gameplay architecture. Audio must not affect server-side simulation or collision decisions.

Write a short implementation plan based on the actual code before editing.

## 2. Nightclub locations

Use existing map data to identify suitable nightclub venues where reliable information is available.

- Inspect existing OSM feature parsing and tagging.
- Consider relevant tags such as `amenity=nightclub`, and existing mapped nightlife venues if the project already supports them.
- Reuse existing world coordinates and map-level conventions.
- Do not classify every bar or restaurant as a nightclub.
- If the project has no reliable nightclub data, implement the audio emitter system so it can be tested with a small, clearly documented set of development fixtures. Do not introduce arbitrary production locations.

Nightclub emitters should follow the existing world streaming lifecycle and must not accumulate duplicate audio players as map chunks load and unload.

## 3. Audio playback

Use one music source per active nightclub emitter, with sensible limits on the number of simultaneously audible emitters.

- Load a configurable instrumental nightclub disco/electronic dance music track using the project's existing asset conventions.
- Support seamless looping where the source audio permits it.
- Use Godot's native 3D audio functionality when compatible with the existing renderer and scene architecture.
- If the project uses a top-down presentation with a different established audio approach, adapt the implementation without introducing unnecessary spatial complexity.
- Keep music playback independent of the player's camera orientation.
- Do not restart the track every frame, when the player crosses a chunk boundary, or when audio attenuation changes.
- Handle missing audio assets gracefully without crashing the game.

## 4. Distance attenuation

The music must be clearly audible outside the nightclub, not only when the player enters the building.

Implement a gradual, smooth distance-based reduction in perceived loudness:

- Close to the venue: loud, bass-heavy club music.
- Near the entrance and immediately outside: clearly recognizable dance rhythm.
- Further down the street: quieter, with reduced high-frequency detail.
- Beyond the audible range: effectively inaudible.

Use tunable distance and attenuation parameters consistent with the existing Godot audio architecture. Avoid sudden on/off transitions and audible volume stepping.

Choose the audible radius and attenuation curve based on the game's world scale and validate them during gameplay. Do not assume that Godot world units equal metres without verifying the coordinate conversion.

## 5. Muffled sound outside buildings

When the player is outside the nightclub, the music should sound as if it is passing through the venue's walls and entrance.

- Apply a low-pass filter to reduce high frequencies at a distance and when the sound source is occluded.
- Preserve enough low-frequency energy for the characteristic nightclub bass to remain audible.
- Where building geometry supports a reliable and inexpensive occlusion test, use it to increase muffling when walls obstruct the direct path between the venue and the player.
- Avoid expensive per-frame raycasts against every building or emitter.
- If exact wall occlusion is unavailable, use a documented distance-based filtering approximation rather than pretending that real acoustic propagation has been implemented.
- Smoothly interpolate filter cutoff and volume so movement does not produce audible artefacts.

Do not attempt full acoustic simulation or add a complex indoor/outdoor portal system unless the repository already has the necessary infrastructure.

## 6. Performance and resource management

Preserve the game's performance, especially on older PCs.

- Reuse audio players and resources where appropriate.
- Avoid allocating nodes or audio effects every frame.
- Avoid processing distant or inaudible nightclubs unnecessarily.
- Stop or release emitters cleanly when their world chunks unload.
- Prevent duplicate music playback after repeated streaming or scene transitions.
- Avoid adding heavyweight dependencies.
- Keep audio processing and update costs proportional to the number of nearby venues, not the total number of venues in the world.

## 7. Configuration and assets

Follow the existing project conventions for audio assets and configuration.

Document how to add a new nightclub emitter and assign its music track. Keep generated audio assets separate from source code where appropriate.

Do not commit generated music unless that matches the repository's existing asset and licensing workflow. Do not introduce copyrighted commercial music.

## 8. Tests and validation

Add automated tests for any location classification, emitter lifecycle or attenuation logic that can be tested independently.

Verify at minimum:

1. A nightclub emits music when loaded and active.
2. The music becomes quieter smoothly as the player moves away.
3. The music remains recognizable just outside the venue.
4. High frequencies are reduced appropriately when muffling is applied.
5. Moving away beyond the audible range stops unnecessary playback or makes the source inaudible.
6. Loading and unloading map chunks does not create duplicate emitters.
7. Missing music assets do not crash the game.
8. The feature does not change server-side simulation or collision behavior.
9. Performance remains acceptable with several venues in the streamed world.

Run the relevant existing test suite and Godot headless checks where applicable. Report which checks actually ran and their results.

## 9. Deliverables

Provide:

- A summary of the implementation.
- The files changed and the reason for each change.
- The source of nightclub location data.
- The audio attenuation and filtering approach.
- Any configuration needed to tune volume, radius and muffling.
- Test results and any limitations.

Implement the feature in the Godot client only unless repository inspection demonstrates a compelling existing architectural reason otherwise. Preserve the current rendering and gameplay behavior.

## 10. Time-of-day awareness and nightclub operating hours

Nightclub audio must respond to the game's simulated time of day, not the operating system's real-world clock.

### Use the existing game clock

- Inspect and reuse the existing authoritative game-time and time-of-day systems.
- Do not introduce a separate clock or independently calculate the time of day.
- Ensure audio behavior remains synchronized with the accelerated in-game clock and responds correctly when the game time advances quickly.
- Handle time changes and day transitions without abrupt audio jumps.

### Nightclub activity schedule

Nightclub music should reflect realistic opening hours:

- Early morning and daytime: normally inactive, with no music audible outside.
- Evening: venues gradually become active as nightlife begins.
- Late evening and night: music is clearly audible around active nightclubs.
- Early morning: music fades out as venues close.

Use a configurable operating schedule, with sensible defaults based on local nightlife patterns. Support venues whose operating hours cross midnight, such as 22:00–04:00.

Do not assume that every venue is open every night. If the game already models weekdays, weekends or venue schedules, reuse that information. Otherwise, keep the initial implementation simple and avoid inventing a complex business simulation.

### Smooth activation and shutdown

- Fade music in when a venue becomes active and fade it out when it closes.
- Combine the operating schedule with distance attenuation and wall muffling.
- Never abruptly stop or restart an audible track merely because the simulated clock crosses an hour boundary.
- If the player remains outside a closing venue, the music should fade naturally.
- If the venue opens while the player is nearby, the music should gradually become audible.

### Separate time-based and distance-based factors

Keep these factors logically independent:

1. Venue activity determines whether the nightclub is operating.
2. Distance determines the base outdoor loudness.
3. Building occlusion and filtering determine how muffled the sound is.
4. Time-based fades smooth opening and closing transitions.

Combine them into the final audio output without allowing distance changes to reset playback or operating-hour changes to create duplicate audio players.

### Validation

Test at simulated times before opening, during evening opening, late at night, after closing, and across midnight. Verify that advancing or changing the game's simulated clock produces the expected audio behavior without affecting rendering performance or server-side gameplay.