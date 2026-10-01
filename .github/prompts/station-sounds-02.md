You are working on the Road Rage Trip repository.

Current branch:

`release/0.15.0alpha`

## Objective

Complete the railway station announcement audio asset set.

The existing railway announcement audio files were generated with Chatterbox using the reference voice:

`voices/female/eeva.wav`

Some train-type audio assets may already exist, but the set must be audited against the actual timetable abbreviations used by the game.

**If a required audio asset is missing, create it.**

Do not merely add code mappings for missing audio. The goal is to ensure that every required timetable train type / line identifier has a correct Finnish spoken audio asset.

---

# 1. First inspect the existing repository

Before making changes, inspect:

* `src/theroadragetrip/assets/railway_announcements/`
* `src/theroadragetrip/assets/railway_announcements/README.md`
* `src/theroadragetrip/assets/railway_announcements/manifest.json`
* `src/theroadragetrip/assets/railway_announcements/train_types/`
* `src/theroadragetrip/station_announcer.py`
* the timetable/train model
* the code that populates `train_type`
* existing railway announcement tests
* the local `ai-audio-studio` setup and its Chatterbox generation workflow, if available in the repository/documentation

Do not assume that the current `train_types/` directory is complete.

Build an inventory of:

1. existing train-type audio files;
2. their manifest entries;
3. their spoken Finnish meaning;
4. timetable abbreviations currently produced by the game.

---

# 2. Authoritative timetable abbreviations

The following meanings are authoritative:

| Abbreviation | Spoken meaning                         |
| ------------ | -------------------------------------- |
| `SP`         | Pendolino Plus                         |
| `S`          | Pendolino                              |
| `IC`         | InterCity                              |
| `PYO`        | Yöjuna                                 |
| `HDM`        | Kiskobussi                             |
| `H`          | Taajamajuna Iisalmi–Ylivieska-reitillä |
| `D`          | lähijunan linjatunnus D                |
| `G`          | lähijunan linjatunnus G                |
| `H`          | lähijunan linjatunnus H                |
| `M`          | lähijunan linjatunnus M                |
| `O`          | lähijunan linjatunnus O                |
| `R`          | lähijunan linjatunnus R                |
| `T`          | lähijunan linjatunnus T                |
| `Z`          | lähijunan linjatunnus Z                |

The duplicate `H` is intentional.

It represents two different possible timetable meanings:

* Taajamajuna Iisalmi–Ylivieska
* lähijunan H-linja

---

# 3. Resolve the H ambiguity from actual timetable data

Do not blindly create one generic `H.ogg` and use it for every `H`.

Inspect the timetable data model and determine whether there is enough information to distinguish:

```text
H = Taajamajuna Iisalmi–Ylivieska
```

from:

```text
H = lähijunan H-linja
```

Look at all relevant available fields, such as:

* train category/type;
* line identifier;
* route;
* origin;
* destination;
* train number;
* service name;
* operator;
* any other existing classification.

Do not invent a new classification if the repository already contains the necessary information.

If the current timetable representation can distinguish the two cases, introduce the smallest clean internal distinction required by the announcement system.

If it cannot distinguish them, document exactly what information is missing and do not silently generate an incorrect mapping.

---

# 4. Audit the existing audio assets

For each required spoken concept, determine whether a suitable existing audio file already exists.

The required concepts are:

### Long-form train types

```text
Pendolino Plus
Pendolino
InterCity
Yöjuna
Kiskobussi
Taajamajuna
```

### Commuter train line identifiers

```text
D
G
H
M
O
R
T
Z
```

Do not assume that a filename such as `H.ogg` tells you its semantic meaning.

Inspect the actual manifest and generation metadata.

For each asset, verify:

* filename;
* manifest key;
* spoken Finnish content;
* sample rate;
* format;
* channel count;
* whether silence is already trimmed;
* whether the asset uses `female/eeva.wav` as the reference voice.

---

# 5. Generate missing audio files

If a required concept is missing, generate it using the existing local Chatterbox workflow.

Use:

```text
female/eeva.wav
```

as the reference voice.

The spoken content must be natural Finnish.

Required long-form clips should correspond to:

```text
Pendolino Plus
Pendolino
InterCity
Yöjuna
Kiskobussi
Taajamajuna
```

For commuter lines, create individual spoken clips for:

```text
D
G
H
M
O
R
T
Z
```

The line clips must be appropriate for Finnish station announcements.

Do not create clips containing additional words unless that is explicitly required by the existing announcement design.

For example, a line identifier asset should not unexpectedly say:

```text
"linja R"
```

if the intended announcement is simply the spoken identifier.

First inspect the existing assets and conventions and match them.

---

# 6. Important: do not duplicate H incorrectly

If two different audio concepts are required for `H`, they must have distinct internal asset identities.

For example, conceptually:

```text
H commuter line
H taajamajuna
```

must not both point to one arbitrary `H.ogg`.

Choose clear filenames/manifest keys according to the existing asset naming convention.

The exact filenames must be based on the repository's current conventions, not invented independently.

If the timetable model cannot distinguish the two meanings, do not pretend that it can.

---

# 7. Update manifest.json

Every newly generated audio file must be registered in:

`src/theroadragetrip/assets/railway_announcements/manifest.json`

Follow the existing manifest schema exactly.

Do not invent a second metadata format.

The manifest must make it possible for the game to resolve the correct spoken asset from the normalized timetable representation.

---

# 8. Update README.md

Update the railway announcement asset documentation so that it explicitly documents the supported train types and line identifiers.

Document:

```text
SP  = Pendolino Plus
S   = Pendolino
IC  = InterCity
PYO = Yöjuna
HDM = Kiskobussi
H   = Taajamajuna / commuter line H depending on timetable context
D   = commuter line D
G   = commuter line G
M   = commuter line M
O   = commuter line O
R   = commuter line R
T   = commuter line T
Z   = commuter line Z
```

Also document how the two meanings of `H` are represented internally.

---

# 9. Update runtime mapping

After the audio assets are complete, update the announcement code so the timetable values resolve to the correct audio assets.

Do not hard-code assumptions based solely on filenames.

Use the manifest and the existing asset architecture.

The runtime must be able to distinguish:

```text
SP → Pendolino Plus
S → Pendolino
IC → InterCity
PYO → Yöjuna
HDM → Kiskobussi
```

and the commuter line identifiers:

```text
D
G
H
M
O
R
T
Z
```

For `H`, use the actual timetable information discovered earlier.

---

# 10. Preserve train-number composition

Train type audio and train number audio are separate.

For example:

```text
IC 519
```

must use:

```text
[InterCity]
[500]
[19]
```

not a generated recording of "InterCity 519".

Likewise:

```text
PYO 273
```

must use:

```text
[Yöjuna]
[200]
[70]
[3]
```

according to the existing number composition rules.

Preserve the existing special Finnish teen-number handling:

```text
11 → yksitoista
12 → kaksitoista
...
19 → yhdeksäntoista
```

and:

```text
519 → 500 + 19
523 → 500 + 20 + 3
```

Never insert an announcement pause inside a number.

---

# 11. Audio generation quality requirements

All newly generated assets must match the existing railway announcement assets.

Inspect the existing assets to determine the established:

* sample rate;
* OGG Vorbis settings;
* mono/stereo format;
* silence trimming;
* loudness/normalization;
* filename convention;
* manifest metadata.

New files must use the same conventions.

Do not arbitrarily choose different audio settings.

Do not commit temporary WAV files unless the existing asset workflow explicitly requires them.

The final repository asset should be the same production format as the existing railway announcement clips.

---

# 12. Do not regenerate existing correct assets

If an existing asset is already correct:

* Finnish pronunciation is correct;
* reference voice is correct;
* recording content is correct;
* audio format matches the asset set;

then keep it.

Do not regenerate it unnecessarily.

Only generate missing or demonstrably incorrect assets.

---

# 13. Tests

Add or update tests for all supported train-type values:

```text
SP
S
IC
PYO
HDM
H
D
G
M
O
R
T
Z
```

Tests must verify the actual `AnnouncementScript` behaviour rather than merely checking that dictionary keys exist.

Test that:

* each abbreviation resolves to the correct spoken concept;
* the corresponding audio file exists;
* the manifest contains the asset;
* train number composition remains correct;
* unsupported values do not silently become another train type;
* `H` is correctly distinguished when the timetable data permits it.

Add explicit regression tests for both meanings of `H`.

---

# 14. Verify the generated assets programmatically

After generating missing audio, run an asset audit.

The audit should verify at least:

* all referenced files exist;
* all files are readable;
* all required manifest entries exist;
* format matches the existing asset set;
* no accidental duplicate filenames exist;
* no temporary generation files were added;
* no manifest entry points to a missing file.

If the project already has an asset validation script, use it rather than creating a duplicate validator.

---

# 15. Manual announcement verification

Manually verify representative announcements for:

```text
SP 123
S 45
IC 519
PYO 273
HDM 403
```

and commuter lines:

```text
D 123
G 123
M 123
O 123
R 123
T 123
Z 123
```

For `H`, verify both:

```text
Taajamajuna H
```

and:

```text
lähijuna H
```

if the timetable data supports both cases.

Listen specifically for:

* correct pronunciation;
* correct Finnish wording;
* correct train type;
* correct line identifier;
* correct number pronunciation;
* no unexpected extra words;
* no missing train-type clip.

---

# 16. Do not redesign unrelated systems

This task is about completing and correctly integrating the railway announcement audio asset set.

Do NOT redesign:

* railway scheduling;
* train movement;
* station simulation;
* OSM streaming;
* parking garages;
* NPC traffic;
* passenger routing;
* general audio architecture.

Do not change unrelated game systems.

---

# 17. Final report

At the end, report:

1. Which train-type/line assets already existed.
2. Which assets were missing.
3. Which new audio files were generated.
4. The exact spoken content of each new file.
5. Which manifest entries were added or changed.
6. How `SP`, `S`, `IC`, `PYO`, `HDM`, `D`, `G`, `M`, `O`, `R`, `T`, and `Z` are mapped.
7. How the two meanings of `H` are distinguished.
8. Any remaining ambiguity in the timetable data.
9. Tests added/updated and their results.
10. Audio asset validation results.
11. Manual listening verification results.

Do not claim an asset is complete merely because a filename exists. Verify the actual audio content and manifest mapping.
