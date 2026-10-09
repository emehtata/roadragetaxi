# Task: Final audio quality review and cleanup

Work on the current branch:

`release/v0.16.0g-alpha`

The Stable Audio replacement work is now implemented in commits:

* `aea938d`
* `6e33ea5`
* `35228fe`

These commits are not pushed yet.

Do not redesign the audio architecture. This task is a focused quality-review and cleanup pass.

## 1. Review the generated audio assets

The following legacy gameplay sounds have been replaced:

* `car-door-open.flac`
* `city-traffic-outdoor.wav`
* `censored-cursing.wav`

The generated replacements are Stable Audio Open OGG files.

The original files are intentionally preserved under:

```text
src/theroadragetrip/sounds/legacy/
```

Do not delete them yet.

### Manual listening review

The previous automated tests verified playback, levels, timing and cleanup, but nobody has listened to the generated sounds yet.

Inspect the generated files and, where possible, perform a manual listening review.

Start with:

```text
pedestrian_curse_03.ogg
```

It previously exhibited heavy clipping before normalization.

Also listen to:

* all door-open variations
* both city-day ambience loops
* all pedestrian-curse variations
* regenerated `vehicle.speed_bump`
* regenerated `taxi.meter_start`
* regenerated `ui.phone_open`

The purpose is to detect problems that waveform measurements cannot establish:

* clipping
* obvious generation artifacts
* unnatural sounds
* excessive noise
* abrupt loop boundaries
* clicks/pops
* excessive compression
* inappropriate duration
* sounds that do not actually match their logical event

Do not claim that an asset is subjectively good if no human listening has actually occurred.

If this environment cannot perform meaningful human listening, document that clearly and leave the assets available for manual review rather than pretending the quality has been verified.

---

## 2. Fix the pedestrian curse if necessary

If `pedestrian_curse_03.ogg` is audibly clipped or otherwise defective:

* regenerate it rather than trying to hide the problem with aggressive post-processing
* preserve the Stable Audio generation metadata
* update `docs/audio/stable-audio-assets.json`
* update the replacement specification if the filename or generation changes
* rerun all audio validation

Generate enough variation to maintain the existing three-variation design.

Do not change the logical event name:

```text
pedestrian.curse
```

---

## 3. Make the day ambience actually use both variations

Current behaviour:

> Both clients always play the first of the two day loops.

Fix this.

The two generated city ambience loops should both be usable.

Use the existing audio catalog architecture.

Preferred behaviour:

* select a variation when starting the ambience
* avoid immediately selecting the same variation again if ambience restarts
* do not require runtime audio generation
* do not introduce unnecessary randomisation into tests

If Pygame and Godot already have variation-selection mechanisms, reuse them.

If a small shared logical-catalog change is needed, make that change rather than hard-coding filenames.

Add or update tests proving that both day ambience variations can be selected.

The test must not rely on probabilistic randomness to pass.

---

## 4. Do not alter the existing logical audio API

Continue using:

```text
vehicle.door_open
pedestrian.curse
ambient.city_day
```

and the other logical audio event names.

Do not introduce direct references to generated filenames into gameplay code.

The audio catalog remains the source of truth.

---

## 5. Investigate the packaging gap

There is a pre-existing packaging issue:

`pyproject.toml` currently uses:

```text
assets/*
```

which does not include the audio subdirectories.

Investigate exactly how this affects:

* source-tree execution
* installed Python packages
* built distributions
* Pygame audio
* generated Stable Audio assets

Do not change packaging merely because it looks suspicious.

If the audio assets are genuinely missing from the built package, fix the packaging configuration and add a regression test.

If the current packaging mechanism intentionally handles the files elsewhere, document why and leave it unchanged.

The important requirement is:

> A packaged installation must contain every runtime audio asset required by the game.

Do not introduce a broad packaging refactor.

---

## 6. Re-run all validation

Run:

```text
make audio-check
make godot-test
make godot-selftest
```

and the complete Python test suite.

Expected Python result remains:

* all normal tests passing
* only the 3 known BIN map-format failures may remain

Do not modify the BIN/map system as part of this task.

The audio validator must continue to report:

```text
0 problems
```

for the valid catalog.

---

## 7. Re-run the real-window audio test

Run the existing real-window audio test after all changes.

Verify at minimum:

* day ambience
* night ambience
* rain
* taxi boarding / door-open
* engine start
* engine running
* engine stop
* train movement
* spatial left/right event
* repeated door events
* master mute
* disconnect cleanup

Record the results.

Again, distinguish:

### Objectively measured

* playback occurred
* signal level
* number of playback events
* silence/mute behaviour
* cleanup
* timing

from:

### Subjective

* whether the sound actually sounds realistic
* whether it fits the game
* whether it is pleasant/appropriate
* whether generation artifacts are noticeable

Do not convert measurements into claims about subjective quality.

---

## 8. Keep legacy assets until manual approval

Do not delete:

```text
src/theroadragetrip/sounds/legacy/
```

during this task.

The legacy assets should remain available until the new assets have received a manual listening review.

Once the review has happened in a later step, they can be removed in a separate cleanup commit.

---

## 9. Final report

At the end, report:

### Audio quality

For each generated replacement:

* filename
* logical event
* automated validation
* human listening status
* issues found
* action taken

### Day ambience

Confirm whether both variations are now selectable and tested.

### Packaging

State whether the audio packaging gap is real and whether it was fixed.

### Tests

Report exact results for:

* `make audio-check`
* `make godot-test`
* `make godot-selftest`
* Python tests
* real-window audio test

### Git changes

Do not push or tag anything.

Do not create unrelated commits.

Keep the changes focused on this audio quality/cleanup task.

## Acceptance criteria

The task is complete when:

1. `pedestrian_curse_03.ogg` has been reviewed and fixed/regenerated if necessary.
2. Both day ambience variations are actually usable.
3. No gameplay code depends directly on generated filenames.
4. All catalog references are valid.
5. Packaging is either fixed or explicitly verified to be correct.
6. Audio validation reports zero problems.
7. Godot tests pass.
8. Godot self-test passes.
9. Python tests pass except for the three known BIN-format failures.
10. The real-window audio test passes.
11. Legacy assets remain preserved for manual comparison.
12. No unrelated networking, map, UI or gameplay work is introduced.
