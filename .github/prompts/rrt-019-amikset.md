# Implement bass-heavy car audio for selected NPC vehicles

Inspect the Road Rage Taxi repository and implement an immersive car-audio feature in the Godot client. Some NPC vehicles should have heavily customized sound systems and play loud bass-heavy electronic pop music that can be heard by nearby traffic and pedestrians.

## 1. Inspect the existing architecture

Before changing code:

- Inspect NPC vehicle definitions, vehicle spawning, vehicle movement, world streaming, time-of-day handling, weekday/weekend logic and existing audio systems.
- Determine how NPC vehicle identity and lifecycle are represented.
- Reuse existing systems and conventions.
- Do not invent protocol fields, configuration variables or NPC properties without verifying the repository.
- Keep this feature client-side. Do not add audio processing to the authoritative simulation server.
- Preserve the existing vehicle simulation, rendering performance and collision behavior.

Write a short implementation plan based on the actual repository before making changes.

## 2. Select vehicles with customized sound systems

Only a subset of NPC cars should have powerful aftermarket car-audio systems.

- Represent the feature as a vehicle attribute or an equivalent lightweight property consistent with the existing architecture.
- Choose a small, configurable proportion of eligible passenger cars.
- Use deterministic selection based on existing vehicle identity or simulation seed where possible, so vehicle streaming does not randomly change which cars have sound systems.
- Make these vehicles more common on Friday and Saturday evenings and nights than during weekday daytime.
- Account for the existing simulated weekday and time of day. Never use the operating system's clock.
- Avoid assigning the feature to every vehicle or to unsuitable vehicle classes.
- Do not repeatedly reroll vehicle attributes as chunks load or unload.

If the simulation already has weekday-dependent traffic composition, reuse it. Otherwise, implement a lightweight client-side selection mechanism without changing the server protocol unless strictly necessary.

## 3. Music playback

Use a configurable instrumental electronic-pop track generated for the game.

The musical character should include:
- Deep, powerful sub-bass and punchy 808-style bass.
- Strong electronic kick drums.
- Bright, catchy electro-pop synthesizers.
- Energetic modern dance-pop rhythms.
- A youthful street-car cruising atmosphere.

Requirements:

- Use the existing audio asset conventions.
- Loop the track seamlessly where possible.
- Start playback only when the vehicle is active and the sound source is needed.
- Do not restart music on every frame, vehicle update or map-chunk transition.
- Avoid creating a separate audio player every frame.
- Stop and clean up playback when a vehicle is removed or no longer needs an audio source.
- Handle missing audio assets gracefully.
- Do not add copyrighted commercial tracks.

## 4. Spatial audio and exterior sound

The music must sound as if it is coming from a vehicle with an aftermarket sound system, not from the player's own speakers.

- Use Godot spatial audio where appropriate for the current scene and coordinate system.
- Attach the audio source to the moving NPC vehicle so it follows the vehicle's position.
- Keep the music independent of camera orientation.
- Verify the project's world-unit-to-distance conversion before choosing attenuation values.

At close range:
- The electronic rhythm and bass should be clearly recognizable.
- The bass should sound strong and physically imposing.
- Bright synths and percussion should remain audible.

At medium range:
- Reduce overall loudness smoothly.
- Preserve some low-frequency energy while reducing high-frequency detail.
- Apply a low-pass filter or an equivalent existing audio effect to approximate sound propagation outside the car.

At long range:
- The music should fade naturally into the ambient soundscape and become inaudible beyond a configurable distance.

Do not simulate full acoustic propagation. Use lightweight distance attenuation and filtering.

If feasible within the existing audio architecture, distinguish bass leakage from the vehicle cabin sound. Do not introduce a complex multi-source system unless profiling demonstrates that it is affordable.

## 5. Vehicle motion

The music source must follow the vehicle smoothly as it moves.

- Avoid audible position jumps when the vehicle is interpolated between network or simulation updates.
- Reuse the existing vehicle interpolation and transform-update path.
- Do not change vehicle movement or physics to improve audio.
- Avoid restarting the music when the vehicle changes lanes, turns or moves between map chunks.
- Ensure that audio sources are cleaned up correctly when vehicles despawn.

## 6. Time-of-day and weekend behavior

Integrate with the existing game clock and calendar.

- Customized sound-system vehicles should be more prevalent during Friday and Saturday evenings and nights.
- They should be less prevalent during weekday daytime and early morning.
- Do not assume that every weekend vehicle plays music.
- Existing vehicles should retain their identity and audio configuration throughout their lifetime.
- Do not abruptly cut off music merely because the simulated clock crosses an hour boundary.
- If a vehicle's sound system is active only during certain hours, fade it smoothly according to a configurable schedule.

Keep vehicle selection frequency separate from playback volume and distance attenuation.

## 7. Performance

Preserve stable frame rates, particularly on older PCs.

- Limit active music sources to nearby relevant vehicles.
- Avoid expensive work for distant vehicles.
- Reuse audio resources and players where practical.
- Avoid per-frame allocations, repeated resource loads and unnecessary audio-effect creation.
- Ensure the implementation scales with nearby audible vehicles rather than the total number of NPC vehicles in the world.
- Prevent duplicated playback when vehicles or map chunks are recreated.
- Profile the feature with several sound-system vehicles nearby.

## 8. Tests and validation

Add tests for deterministic vehicle selection and time/day-of-week rules where these can be tested independently.

Validate:
1. Only a subset of eligible NPC cars receive sound systems.
2. Such cars are more prevalent during Friday and Saturday evenings and nights.
3. Music follows moving vehicles.
4. Loudness decreases smoothly with distance.
5. Bass remains audible at short and medium range while high frequencies are progressively muffled.
6. Despawning vehicles releases their audio resources.
7. Repeated chunk streaming does not duplicate music players.
8. Missing music files do not crash the game.
9. Existing simulation, collisions, protocol behavior and rendering remain unchanged.
10. Performance remains acceptable with multiple audible vehicles.

Run relevant tests and Godot headless checks where possible. Report actual test results and any unverified behavior.

## 9. Deliverables

Summarize:
- Files changed.
- How customized vehicles are selected.
- How the simulated calendar affects their prevalence.
- Audio attenuation, filtering and lifecycle handling.
- How to configure the track, vehicle proportion and audible radius.
- Test results and any known limitations.

Implement the feature in the Godot client unless repository inspection demonstrates a compelling reason otherwise.