# Task: Replace legacy game audio assets with Stable Audio generated assets

Work on the current branch:

`release/v0.16.0g-alpha`

## Objective

Audit the entire game's audio asset inventory and replace legacy audio files that were not generated with Stable Audio with new AI-generated audio assets produced with Stable Audio Open.

The goal is to make the Godot client use a coherent, modern audio asset set while preserving the existing audio event architecture and gameplay behaviour.

Do not redesign the audio system unless the audit reveals a concrete architectural problem.

Do not remove working legacy assets blindly. Every replacement must be verified in the actual game.

---

## 1. Audit the current audio inventory

Inspect all audio-related files and references in:

* `godot/`
* `src/`
* existing audio asset directories
* `godot/audio/audio_events.json`
* `godot/audio_manager.gd`
* Pygame audio loading/playback code
* any audio metadata/catalog files
* tests referring to audio assets

Create an inventory containing at least:

| Asset | Current format | Used by | Audio type | Stable Audio origin | Godot compatible | Replacement needed |
| ----- | -------------- | ------- | ---------- | ------------------- | ---------------- | ------------------ |

Determine which existing assets were generated with Stable Audio and which were created by other means.

Do not infer Stable Audio origin merely from filename.

If the repository does not contain enough information to establish the origin of an asset, mark it as `unknown` rather than claiming it is Stable Audio generated.

---

## 2. Identify replacement candidates

Prioritize assets that are:

1. Clearly legacy/non-Stable-Audio assets.
2. Audible during normal gameplay.
3. Used by both Pygame and/or Godot.
4. Currently poor, overly simple, technically incompatible, or noticeably different from the newer Stable Audio assets.

Pay particular attention to:

* door open/close
* engine start
* engine idle
* engine driving
* train movement
* city traffic
* vehicle movement
* collision/crash sounds
* rain
* thunder
* environmental ambience
* pedestrian/city ambience
* taxi-related sounds
* UI/gameplay feedback sounds

Do not replace music or radio/news content unless it is explicitly part of the legacy sound-effect inventory.

---

## 3. Generate a replacement specification

Before generating files, create a machine-readable specification, for example:

`docs/audio/stable-audio-replacements.json`

Each entry should contain:

* logical asset name
* existing asset(s)
* intended use
* Stable Audio prompt
* target duration
* suggested number of variations
* target format
* loop/non-loop
* intended Godot audio bus/group
* spatial/non-spatial
* replacement status

Example structure:

```json
{
  "asset": "vehicle.door_open",
  "legacy_files": [
    "..."
  ],
  "type": "vehicle",
  "loop": false,
  "duration_seconds": 1.5,
  "variations": 3,
  "stable_audio_prompt": "...",
  "format": "ogg",
  "godot_bus": "SFX",
  "spatial": false,
  "status": "pending"
}
```

The prompts must describe the actual desired sound, not merely the filename.

For example, do not use:

`car door`

Prefer something describing the acoustic event, such as:

`Realistic compact car interior door opening, mechanical latch click followed by solid vehicle door movement and a soft close-stop resonance, dry recording, no music, no speech`

Adapt the prompts to the actual game situation.

---

## 4. Generate multiple variations

For important frequently repeated sounds, generate several variations rather than one replacement.

At minimum consider multiple variants for:

* vehicle doors
* engine start
* engine sounds
* collisions
* tire/skid sounds
* train movement
* traffic ambience
* weather sounds

The game should be able to randomly select or cycle variations where appropriate so repeated events do not sound identical.

Do not introduce random variation into sounds where deterministic playback is important for tests.

---

## 5. Prefer Godot-compatible formats

The previous audio audit found that the existing door-open sound is FLAC and cannot be loaded by Godot.

Therefore:

**New Godot gameplay assets should use `.ogg` unless there is a documented technical reason to use another format.**

Do not add another FLAC dependency merely to preserve a legacy asset.

Verify that every new asset can actually be loaded by Godot.

---

## 6. Preserve logical audio events

Do not make gameplay code depend directly on individual generated filenames.

Continue using the existing logical audio event/catalog architecture.

For example:

```text
vehicle.door_open
vehicle.engine_start
vehicle.engine_loop
vehicle.collision
train.moving
environment.rain
```

should resolve through the catalog to one or more physical files.

If variation support does not currently exist, implement the smallest clean extension required by the existing architecture.

Avoid a large audio-system rewrite.

---

## 7. Fix the door-open problem as part of this task

The known problem is:

* Pygame currently uses a FLAC door sound.
* Godot cannot load it.
* The catalog has no alternative version.
* The Godot audio test therefore detects silence.

Replace this with a new Stable Audio generated `.ogg` asset.

Add it to the catalog and ensure:

* getting into the taxi triggers it
* it is audible in Godot
* it plays exactly once
* it does not leak after disconnect
* it does not interfere with engine startup

Add/update an automated test for this behaviour.

---

## 8. Update the audio catalog

Update:

`godot/audio/audio_events.json`

so that every replaced logical event points to the new asset(s).

Keep the catalog readable and deterministic.

Do not leave dead references to removed assets.

Where multiple variations exist, use the catalog structure rather than hard-coding filenames in GDScript.

---

## 9. Preserve audio behaviour already validated

The existing audio work has already established important behaviour.

Do not regress:

* bus muting
* master muting
* day/night ambience
* rain
* engine start/stop
* engine volume changes while driving
* left/right spatial event attenuation
* train movement audio
* cleanup when simulation disconnects
* no duplicate playback
* no leftover audio players

The replacement work must preserve these semantics.

---

## 10. Add an audio asset validation tool/test

Extend the existing audio analysis/testing infrastructure where useful.

The validation should detect at least:

* missing files
* unsupported formats
* catalog entries pointing to nonexistent assets
* duplicate logical assignments
* empty catalog groups
* assets that Godot cannot load
* assets with zero/near-zero usable audio
* unexpectedly long files
* unexpectedly short files
* invalid loop definitions

Do not make loudness thresholds overly strict. Some ambience is intentionally quiet.

The existing day ambience was measured around −45 dBFS, so do not classify that as invalid merely because it is quiet.

---

## 11. Stable Audio metadata

For generated replacement assets, preserve enough metadata to reproduce or audit the asset.

Add a metadata file such as:

`docs/audio/stable-audio-assets.json`

containing, where known:

* asset filename
* logical event
* prompt
* generation date
* model/version
* duration
* variation number
* source/reference information if applicable

Do not invent generation parameters that are not actually known.

---

## 12. Test the actual Godot client

After replacements are installed:

Run:

```text
make godot-selftest
```

and all relevant Python tests.

Also run the existing scripted real-window audio test.

The audio test must verify at least:

1. day ambience
2. night ambience
3. rain
4. getting into taxi
5. engine start
6. engine running
7. engine stop
8. train movement
9. spatial left/right event
10. master mute
11. disconnect cleanup
12. repeated events

For the door-open event specifically, verify that the actual Godot system output contains non-silent audio.

Do not claim that audio sounds good based only on waveform measurements. Measurements can verify playback, silence, levels and timing, but subjective sound quality must remain a manual listening check.

---

## 13. Compare old and new assets

For each replaced asset, record:

* old filename
* new filename
* reason for replacement
* format
* duration
* whether it is looped
* whether it is spatial
* whether gameplay code changed
* test result

Do not delete old assets immediately.

Initially move obsolete assets into a clearly identified legacy location or otherwise preserve them until the replacement has been verified.

Only remove them after confirming that no active code or catalog references them.

---

## 14. Performance considerations

Do not introduce unnecessary runtime processing.

Prefer:

* pre-generated audio
* normal Godot-compatible compressed files
* catalog lookup
* reusable audio players
* cached resources where appropriate

Do not decode or transform audio on every playback.

Keep the existing audio lifecycle and cleanup model.

---

## 15. Deliverables

At the end of the task, provide:

### A. Asset inventory

A complete list of:

* existing Stable Audio assets
* legacy assets
* unknown-origin assets
* replaced assets
* intentionally retained legacy assets

### B. Stable Audio replacement specification

```text
docs/audio/stable-audio-replacements.json
```

### C. Stable Audio metadata

```text
docs/audio/stable-audio-assets.json
```

### D. Updated catalog

```text
godot/audio/audio_events.json
```

### E. New audio files

Prefer:

```text
.ogg
```

for Godot gameplay audio.

### F. Tests

Update/add tests required to verify:

* catalog integrity
* asset existence
* Godot compatibility
* playback
* cleanup
* variation handling where implemented

### G. Documentation

Update the relevant audio/client architecture documentation.

---

## 16. Acceptance criteria

The task is complete only when:

* every legacy gameplay sound has been audited
* every replacement candidate has a documented reason
* new replacement sounds are generated with Stable Audio
* new gameplay sounds are Godot-loadable
* the door-open sound works in Godot
* the Godot catalog contains no broken references
* no existing validated audio behaviour regresses
* no audio leaks occur after disconnect
* repeated events do not create duplicate players
* `make godot-selftest` passes
* Python tests pass except for the already-known BIN map-format failures
* the real-window audio test passes
* the final report clearly distinguishes measured playback correctness from subjective sound quality

Do not start unrelated UI work.

Do not modify the networking architecture unless required to fix an audio regression.

Do not introduce BIN-related changes; the current map architecture is outside the scope of this task.
