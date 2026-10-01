# Fix Railway Station Announcement Playback

Work on branch:

`release/0.15.0alpha`

## Goal

Fix the existing railway station announcement playback so that the already-generated Finnish announcement assets play smoothly, in the correct order, without clipped words, gaps inside numbers, repeated/restarted audio, or audio stuttering.

**Do NOT generate new audio.**

**Do NOT modify Chatterbox or the audio-generation tooling.**

The complete railway announcement asset collection already exists in:

`src/theroadragetrip/assets/railway_announcements/`

The problem is the runtime playback implementation.

---

# 1. First inspect the existing implementation

Before changing anything, inspect the actual current implementation on this branch.

At minimum inspect:

* `src/theroadragetrip/station_announcer.py`
* `tests/test_station_announcer.py`
* `src/theroadragetrip/assets/railway_announcements/manifest.json`
* `src/theroadragetrip/assets/railway_announcements/README.md`
* the game's existing audio/mixer implementation
* where `StationAnnouncer` is created
* where `StationAnnouncer.announce()` is called
* where `StationAnnouncer.update()` is called
* existing spatial audio handling in `audio.py`
* existing Pygame mixer/channel conventions

Do not assume that the architecture described in this prompt exists if the repository says otherwise.

Use the actual repository implementation as the source of truth.

---

# 2. Important: the audio assets already exist

The railway announcement collection is already generated and accepted.

The asset directory is:

`src/theroadragetrip/assets/railway_announcements/`

It contains:

```text
railway_announcements/
├── manifest.json
├── numbers/
│   ├── units/
│   ├── teens/
│   ├── tens/
│   ├── hundreds/
│   └── thousands/
├── place_forms.json
├── places/
├── train_types/
├── platforms/
├── phrases/
└── connectors/
```

The README documents the intended design.

Examples:

```text
523 = 500 + 20 + 3
519 = 500 + 19
47  = 40 + 7
115 = 100 + 15
1008 = 1000 + 8
```

Finnish numbers 11–19 are already separate assets and must remain intact.

For example:

```text
519
→ numbers/hundreds/500.ogg
→ numbers/teens/19.ogg
```

Do not change this asset architecture.

---

# 3. Critical bug in the current implementation

The current `StationAnnouncer.announce()` implementation loads the individual clips and then does essentially this:

```python
self._clip(file).get_raw()
```

and then:

```python
pygame.mixer.Sound(buffer=b"".join(parts))
```

This is NOT an acceptable way to concatenate the existing OGG assets.

The individual files are OGG Vorbis files.

Their decoded PCM data may be combined only if the audio format and mixer assumptions are explicitly correct, but the current implementation is using `get_raw()` plus a newly-created `Sound(buffer=...)` as an ad-hoc audio composition mechanism.

Do not continue this approach.

The announcement playback should instead treat every generated asset as an independent `pygame.mixer.Sound`.

---

# 4. Required runtime playback architecture

Keep the existing `AnnouncementScript` concept.

It already correctly converts an announcement into phrases and clip filenames.

For example:

```text
[
    ["phrases/attention.ogg"],
    [
        "train_types/intercity.ogg",
        "numbers/tens/50.ogg",
        "numbers/units/7.ogg"
    ],
    ["places/from/helsinki.ogg"],
    ["phrases/arriving.ogg"],
    [
        "platforms/raiteelle.ogg",
        "numbers/units/3.ogg"
    ]
]
```

The playback layer should play those individual sounds sequentially.

The conceptual flow must be:

```text
train event
    ↓
AnnouncementScript
    ↓
phrases
    ↓
clip filenames
    ↓
cached pygame.mixer.Sound objects
    ↓
single announcement playback channel
    ↓
next clip starts only after previous clip has finished
```

Do not create one giant dynamically constructed `Sound`.

---

# 5. Preserve phrase boundaries

The existing `phrases()` method deliberately groups clips into phrases.

That distinction is important.

For example:

```text
[train type + number]
```

must be played continuously:

```text
InterCity
viisikymmentä
seitsemän
```

There must NOT be an artificial pause between:

```text
50
7
```

Likewise:

```text
500
19
```

must sound like:

```text
viisisataa yhdeksäntoista
```

not:

```text
viisisataa ... yhdeksäntoista
```

The current tests explicitly protect this behaviour.

Keep the existing phrase structure.

---

# 6. Use connector pauses only between phrases

The manifest already has:

```text
connectors/pause_short.ogg
connectors/pause_medium.ogg
connectors/pause_long.ogg
```

Use the existing connector assets rather than synthesising silence.

The current implementation already identifies:

```python
pause_short
```

from the manifest.

Use it as an actual cached `pygame.mixer.Sound`, not via `get_raw()`.

The intended behaviour is:

```text
[attention]
SHORT PAUSE
[train type + number]
SHORT PAUSE
[from/to place]
SHORT PAUSE
[arriving/departing]
SHORT PAUSE
[platform + number]
```

Do not insert pauses between individual components inside one phrase.

---

# 7. Implement a clip-level playback queue

Refactor `StationAnnouncer` so that an announcement is converted into a sequence of playback items.

For example:

```text
announcement
    attention.ogg
    pause_short.ogg
    intercity.ogg
    50.ogg
    7.ogg
    pause_short.ogg
    helsinki-from.ogg
    pause_short.ogg
    arriving.ogg
    pause_short.ogg
    raiteelle.ogg
    3.ogg
```

Each item should be an already-loaded/cached `pygame.mixer.Sound`.

The queue must contain enough information to preserve:

* sound
* spatial position
* announcement identity/logging information

Do not reload audio files for every clip.

---

# 8. Cache the individual Sound objects

Keep and improve the existing `_clips` cache.

For example:

```python
self._clips[file]
```

should contain the corresponding:

```python
pygame.mixer.Sound(...)
```

After the first load, subsequent announcements must reuse it.

Do not repeatedly read the same OGG files from disk while the game is running.

The announcement asset collection is static.

---

# 9. One playback channel owns an announcement

The station announcement system should have exactly one active railway-announcement playback channel.

While that channel is busy:

* do not restart the current clip
* do not call `play()` again on the current clip
* do not replace the current announcement
* do not create a second overlapping railway announcement channel

Instead, queued announcements wait.

This is especially important for:

* arrival immediately followed by departure
* two trains arriving close together
* multiple station events in the same frame

The existing test:

`test_a_departure_soon_after_the_arrival_waits_its_turn`

must continue to pass.

---

# 10. Advance the queue only when the current Sound has finished

Do not use arbitrary timers to guess the duration of an audio clip.

Do not use:

```python
time.sleep(...)
```

Do not block the game loop.

Use the Pygame channel state:

```python
channel.get_busy()
```

to determine whether the current clip is still playing.

Once it finishes:

1. advance to the next queued clip
2. start it
3. apply the correct spatial volume
4. continue on the next game update

This must be non-blocking.

---

# 11. Preserve spatial audio

The announcement is a located station sound.

The existing system already uses:

```python
audio.levels("railway.announcement", 1.0, at=position)
```

Preserve that architecture.

Do not replace it with global volume.

The announcement should become quieter as the player moves away from the station, exactly like other located sounds.

Inspect the existing audio implementation and use its established conventions.

Do not invent a second spatial-audio system.

---

# 12. Important: handle spatial volume correctly during a multi-clip announcement

A single announcement may last several seconds.

The player can move while it is playing.

Do not assume that the volume calculated at the moment `announce()` is called remains correct forever.

When each next clip starts, calculate its current volume using the stored announcement position:

```python
audio.levels(
    "railway.announcement",
    1.0,
    at=announcement_position,
)
```

Then:

```python
channel.set_volume(left, right)
```

Use the existing audio API and conventions.

Do not alter unrelated spatial audio behaviour.

---

# 13. Announcement queue semantics

Keep the existing stale-announcement protection.

The current code uses:

```python
MAX_WAIT_S = 20.0
```

An announcement waiting too long should be discarded instead of being played long after the train has left.

Do not discard an announcement merely because it is currently being played.

The 20-second age limit applies to queued announcements waiting for playback.

Preserve this behaviour unless inspection proves that the existing implementation has a specific bug.

---

# 14. Avoid duplicate announcements

Inspect the actual train event code carefully.

Determine whether the same arrival/departure event can call:

```python
announce(...)
```

more than once.

If duplicate event delivery is possible, fix it at the appropriate event/state level rather than trying to hide the problem in the audio mixer.

An announcement must not be restarted every frame.

In particular, do NOT do something equivalent to:

```python
if train_is_arriving:
    announcer.announce(...)
```

every frame.

The announcement should correspond to a discrete train event.

Use the existing train/station event lifecycle.

Do not rewrite the train simulation.

---

# 15. Do not generate audio at runtime

Absolutely do not introduce:

* Chatterbox
* TTS
* subprocess calls
* WAV generation
* speech synthesis
* network TTS
* audio generation
* runtime audio conversion

The game already has the final OGG assets.

Runtime responsibilities are only:

```text
load/cache
select
queue
play
spatialize
advance
```

---

# 16. Do not concatenate OGG files

Never do:

```python
get_raw()
```

followed by:

```python
pygame.mixer.Sound(buffer=...)
```

to assemble an announcement.

Never concatenate OGG file bytes.

Never construct a synthetic complete announcement from raw audio buffers.

Play the existing assets individually.

---

# 17. Inspect Pygame mixer initialization

Before changing mixer settings, inspect how the game currently initializes:

```python
pygame.mixer
```

Determine:

* frequency
* format
* channels
* buffer
* number of mixer channels
* reserved channels, if any
* existing sound/music channel allocation

Do NOT blindly change the mixer buffer to "fix" the stuttering.

Do NOT globally change the game's audio format unless the existing implementation genuinely requires it.

The railway assets are documented as:

```text
24 kHz
mono
OGG Vorbis
```

Make the playback implementation compatible with the existing mixer configuration.

If a mixer-format mismatch is discovered, fix it deliberately and document why.

---

# 18. Keep music and other sound effects independent

Railway announcements must not:

* stop music
* restart music
* steal an unrelated effects channel
* alter global mixer volume
* change other sound effects

Use the existing game's audio-channel architecture.

Inspect it before modifying channel allocation.

---

# 19. Preserve AnnouncementScript

Do not unnecessarily rewrite:

```python
AnnouncementScript
number_components()
```

These parts already contain important Finnish-language logic.

In particular preserve:

```text
11–19 → single teen asset
20–90 → tens + optional unit
100–900 → hundreds + remainder
```

The current test suite contains explicit regression tests for this.

---

# 20. Tests

Update/add tests for the actual playback architecture.

At minimum test:

### Number composition

```text
57  → 50 + 7
519 → 500 + 19
523 → 500 + 20 + 3
```

### Phrase grouping

Verify that:

```text
20 + 2
```

belongs to the same phrase and does not receive a pause between the two clips.

Verify:

```text
19
```

is a single clip.

### Playback sequencing

Simulate:

```text
arrival clip
→ next clip
→ next clip
→ pause
→ next phrase
```

and verify that only one clip is active at a time.

### Queueing

Verify:

```text
arrival
departure
```

results in:

```text
arrival fully plays
departure starts afterwards
```

### Stale queue entries

Verify announcements older than:

```python
MAX_WAIT_S
```

are discarded while the current announcement is unaffected.

### Cache

Verify the same asset does not repeatedly create/load new `pygame.mixer.Sound` objects.

### Spatial volume

Verify each newly-started clip receives the current spatial volume for the station position.

---

# 21. Manual test

After implementing the fix, run the game and test a real station announcement.

Use a train with a known announcement type, such as an InterCity train.

Verify an example equivalent to:

```text
Hyvät matkustajat.
InterCity viisikymmentäseitsemän
Helsingistä
saapuu
raiteelle kolme.
```

Listen specifically for:

* no clipped first/last syllables
* no stuttering
* no repeated clips
* no unexpected pauses inside numbers
* natural short pauses between phrases
* correct order
* correct track number
* correct place form
* announcement continues while the player moves
* volume follows distance from the station
* no impact on music or other effects

Also test a departure announcement.

---

# 22. Performance requirements

This system must have negligible frame-time impact.

Never:

* decode/reload every clip every frame
* construct large audio buffers
* block the game loop
* sleep while waiting for audio
* run TTS
* perform expensive filesystem operations during every `update()`

The first access to an asset may load it.

After that, use the cache.

The normal per-frame work should be approximately:

```text
check channel state
possibly start one cached Sound
possibly calculate spatial volume
```

---

# 23. Scope restrictions

Do NOT:

* regenerate audio
* modify Chatterbox
* modify `ai-audio-studio`
* modify the asset collection
* change manifest semantics unnecessarily
* redesign train simulation
* redesign the global audio system
* rewrite unrelated audio effects
* change station data
* change timetable logic
* add runtime TTS
* add a new audio dependency
* concatenate raw audio buffers
* use `time.sleep()`
* introduce arbitrary mixer-buffer hacks

Make the smallest clean change that fixes the existing railway announcement playback.

---

# 24. Final validation

Run the relevant test suite, especially:

```text
tests/test_station_announcer.py
```

and the broader audio/train-related tests if present.

Report:

1. What caused the stuttering/broken speech.
2. How announcement playback now works.
3. How individual OGG clips are queued.
4. How phrase boundaries are handled.
5. How numbers remain correctly composed.
6. How the Sound cache works.
7. How spatial volume is applied.
8. How duplicate announcements are prevented.
9. Which tests were added/changed.
10. Manual test result.
11. Any remaining limitations.

Do not claim success without actually testing the implementation.
