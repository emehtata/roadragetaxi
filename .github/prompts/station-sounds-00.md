# Railway Announcement Audio Asset System

We are building Finnish railway station announcements for the game **Road Rage Trip**.

The project already has a local **Chatterbox TTS** installation integrated into `ai-audio-studio`. The user has a reference voice recording that will be used as the voice reference for generating all announcement assets.

The goal of this task is to design and implement the **audio asset generation and organization system** inside `ai-audio-studio`.

Do not implement the in-game announcement playback system yet. This phase is only about producing, organizing, validating, and describing the audio assets.

---

## 1. First inspect the existing project

Before changing anything:

1. Inspect the existing `ai-audio-studio` backend and frontend.
2. Find the existing Chatterbox TTS integration.
3. Find how reference audio is currently selected/uploaded.
4. Find the existing audio generation API.
5. Find the existing audio preview/download functionality.
6. Reuse the existing Chatterbox implementation instead of creating a second TTS pipeline.
7. Preserve all existing functionality.

Do not invent environment variables, API endpoints, configuration names, or Chatterbox interfaces. Use the existing implementation discovered in the repository.

---

# 2. Railway announcement asset directory

Create a dedicated railway announcement asset directory.

Use this structure:

```text
assets/
└── railway_announcements/
    ├── numbers/
    │   ├── 0.ogg
    │   ├── 1.ogg
    │   ├── 2.ogg
    │   ├── ...
    │   ├── 10.ogg
    │   ├── 20.ogg
    │   ├── 30.ogg
    │   ├── ...
    │   ├── 100.ogg
    │   ├── 200.ogg
    │   ├── ...
    │   ├── 500.ogg
    │   ├── 1000.ogg
    │   └── ...
    │
    ├── places/
    │   ├── oulu.ogg
    │   ├── helsinki.ogg
    │   ├── tampere.ogg
    │   ├── rovaniemi.ogg
    │   └── ...
    │
    ├── train_types/
    │   ├── intercity.ogg
    │   ├── pendolino.ogg
    │   ├── regional.ogg
    │   ├── night_train.ogg
    │   └── ...
    │
    ├── platforms/
    │   ├── raide.ogg
    │   ├── raiteelle.ogg
    │   ├── raiteelta.ogg
    │   └── ...
    │
    ├── phrases/
    │   ├── attention.ogg
    │   ├── arriving.ogg
    │   ├── departing.ogg
    │   ├── next_train.ogg
    │   ├── delayed.ogg
    │   └── ...
    │
    ├── connectors/
    │   ├── pause_short.ogg
    │   ├── pause_medium.ogg
    │   └── pause_long.ogg
    │
    └── manifest.json
```

Do not blindly create every possible file. The actual asset list must be data-driven.

---

# 3. Finnish number system

Finnish railway announcements should assemble numbers from reusable number components.

Do NOT generate every possible number as an individual TTS file.

For example:

```text
523
→ 500.ogg + 20.ogg + 3.ogg
```

Similarly:

```text
47
→ 40.ogg + 7.ogg

108
→ 100.ogg + 8.ogg

523
→ 500.ogg + 20.ogg + 3.ogg

1008
→ 1000.ogg + 8.ogg
```

The actual pronunciation stored in the files must be the natural Finnish word:

```text
3.ogg       = "kolme"
7.ogg       = "seitsemän"
20.ogg      = "kaksikymmentä"
40.ogg      = "neljäkymmentä"
100.ogg     = "sata"
200.ogg     = "kaksisataa"
500.ogg     = "viisisataa"
1000.ogg    = "tuhat"
```

The number system must be implemented as metadata rather than hard-coded into individual announcement files.

The manifest should contain enough information for the game to determine how a numeric value is composed.

For example:

```json
{
  "numbers": {
    "3": {
      "file": "numbers/3.ogg",
      "value": 3,
      "text": "kolme"
    },
    "20": {
      "file": "numbers/20.ogg",
      "value": 20,
      "text": "kaksikymmentä"
    },
    "500": {
      "file": "numbers/500.ogg",
      "value": 500,
      "text": "viisisataa"
    }
  }
}
```

The generation tool should be able to calculate which number components are needed.

---

# 4. Do not assume all numbers need to exist

The tool must support a configurable number range.

For example:

```text
Minimum number: 0
Maximum number: 999
```

The tool should calculate the required Finnish number components and show them to the user before generation.

For 0–999, the expected reusable components are approximately:

```text
0–9
10–19
20, 30, 40, ..., 90
100, 200, 300, ..., 900
```

However, do not hard-code this list blindly.

Build the number-component generator so that it can correctly determine the required components for the configured range.

Support larger values such as:

```text
1000
2000
...
```

if the configured range requires them.

---

# 5. Important Finnish grammar rule

Do not assume that every announcement can be assembled by simply concatenating dictionary forms.

For example, these are grammatically different:

```text
raide kolme
raiteelle kolme
raiteelta kolme
```

Therefore create separate reusable phrase assets where necessary.

For example:

```text
platforms/
├── raide.ogg
├── raiteelle.ogg
└── raiteelta.ogg
```

The numeric component remains reusable:

```text
raiteelle + kolme
```

rather than generating a separate `raiteelle_3.ogg`.

Keep the asset system composable.

---

# 6. Place names

Place names must be individual assets.

Example:

```text
places/
├── oulu.ogg
├── helsinki.ogg
├── tampere.ogg
├── rovaniemi.ogg
├── kemi.ogg
└── ...
```

The filename must be a stable machine-readable identifier.

The manifest must store the actual spoken text separately.

Example:

```json
"places": {
  "oulu": {
    "file": "places/oulu.ogg",
    "text": "Oulu"
  }
}
```

Do not assume that the filename is always the spoken text.

This is important for names containing spaces, punctuation, abbreviations, or special pronunciation requirements.

---

# 7. Train types

Create reusable train type assets.

Examples:

```text
train_types/
├── intercity.ogg
├── pendolino.ogg
├── regional.ogg
└── night_train.ogg
```

The exact list must be based on the train types already used by Road Rage Trip where possible.

Do not invent train types that are not required by the game without marking them as examples.

Each asset must contain natural Finnish pronunciation suitable for a railway announcement.

---

# 8. Announcement phrases

Create reusable phrase assets for the common announcement vocabulary.

Examples:

```text
phrases/
├── attention.ogg
├── arriving.ogg
├── departing.ogg
├── next_train.ogg
├── delayed.ogg
├── destination.ogg
└── platform.ogg
```

The actual phrase list should be determined from the announcement templates required by the game.

The goal is to construct announcements from reusable parts.

For example:

```text
"Seuraavaksi saapuu Oulun asemalle juna numero 523."
```

could conceptually be constructed from:

```text
next_train
+
place
+
train_number
```

Do not generate an entire announcement for every train.

---

# 9. Reference voice

The generation interface must support a reference audio file.

All assets belonging to the same announcement voice should be generated using the same reference recording and compatible Chatterbox settings.

The UI should clearly show:

* selected reference voice
* asset category
* asset identifier
* Finnish text to synthesize
* output filename
* generation status
* preview
* regenerate
* accept/reject state

Do not modify the reference audio automatically unless the existing Chatterbox pipeline already requires such processing.

---

# 10. Generation manifest

Create:

```text
assets/railway_announcements/manifest.json
```

The manifest must describe every generated asset.

Use a structure similar to:

```json
{
  "version": 1,
  "language": "fi",
  "voice": {
    "id": "station_announcer_01",
    "reference": "reference/station_announcer_01.wav"
  },
  "numbers": {},
  "places": {},
  "train_types": {},
  "platforms": {},
  "phrases": {}
}
```

Each asset entry should contain at minimum:

```json
{
  "file": "places/oulu.ogg",
  "text": "Oulu"
}
```

Where useful, include:

```json
{
  "file": "numbers/500.ogg",
  "text": "viisisataa",
  "value": 500,
  "category": "number",
  "language": "fi"
}
```

Do not store generated audio as base64 in the manifest.

---

# 11. Audio format

Use a consistent format for all final game assets.

Preferred:

```text
OGG Vorbis
```

Keep the sample rate, channel configuration, and quality consistent across generated assets.

If the current Chatterbox pipeline generates WAV, add a deterministic conversion step to the final OGG format rather than requiring the user to convert files manually.

Never silently overwrite an accepted asset.

If an asset already exists, require an explicit regenerate/replace operation.

---

# 12. Asset generation workflow

Implement the following workflow:

### Step 1 — Select reference voice

User selects/uploads the reference voice.

### Step 2 — Select asset category

Examples:

```text
Numbers
Places
Train types
Platforms
Phrases
```

### Step 3 — Generate asset list

The tool shows all required assets.

For numbers, calculate the required reusable components from the configured number range.

### Step 4 — Review text

The user must be able to edit the exact Finnish text before generation.

This is important because pronunciation occasionally needs manual correction.

### Step 5 — Generate

Generate each asset with Chatterbox using the selected reference voice.

Generation must happen through the existing asynchronous/background generation mechanism if one already exists.

Do not block the Flask request while generating a large batch.

### Step 6 — Preview

Allow immediate playback of the generated file.

### Step 7 — Accept / regenerate

The user can:

* accept
* regenerate
* edit text and regenerate
* discard

### Step 8 — Export

Accepted files are stored in the correct directory and `manifest.json` is updated.

---

# 13. Deterministic filenames

Filenames must be stable.

Examples:

```text
numbers/3.ogg
numbers/20.ogg
numbers/500.ogg

places/oulu.ogg
places/helsinki.ogg

train_types/intercity.ogg

platforms/raiteelle.ogg
phrases/attention.ogg
```

Do not generate filenames based on timestamps or random IDs.

If the spoken text contains characters unsuitable for filenames, use a stable identifier and store the actual text in the manifest.

---

# 14. Validation

Add validation for the generated asset collection.

The validator should detect:

* missing files
* manifest entries pointing to missing files
* files existing without manifest entries
* duplicate identifiers
* duplicate filenames
* invalid JSON
* unsupported audio format
* inconsistent audio properties
* empty audio files
* obviously corrupted files

For number assets, validate that the manifest contains enough components to construct all numbers in the configured range.

The validator should produce a clear report.

Example:

```text
Railway announcement asset validation

Numbers:
  0–999: OK
  Missing components: none

Places:
  27 defined
  27 files present

Train types:
  4 defined
  4 files present

Platforms:
  3 defined
  3 files present

Missing files: 0
Orphan files: 0
Invalid files: 0

Result: PASS
```

---

# 15. Do not implement announcement playback yet

This phase must NOT implement:

* in-game announcement scheduling
* station detection
* train arrival detection
* announcement playback in Pygame
* dynamic audio mixing
* train timetable integration
* NPC interaction

Those will be separate tasks.

This phase produces the clean audio asset library and manifest that those systems can consume later.

---

# 16. Tests

Add automated tests for:

1. Number component calculation.

Examples:

```text
3 → [3]
23 → [20, 3]
47 → [40, 7]
108 → [100, 8]
523 → [500, 20, 3]
999 → [900, 90, 9]
1008 → [1000, 8]
```

2. Manifest generation.

3. Manifest validation.

4. Stable filename generation.

5. Missing-file detection.

6. Orphan-file detection.

7. JSON round-trip.

8. Number-range validation.

Do not require actual Chatterbox inference in unit tests. Mock the TTS generation layer.

---

# 17. Documentation

Add a short documentation file:

```text
assets/railway_announcements/README.md
```

Document:

* directory structure
* reference voice requirements
* how to generate assets
* how number composition works
* how to add a new place
* how to add a new train type
* how to add a new phrase
* how to regenerate one asset
* how to validate the collection
* manifest format

Include concrete examples.

---

# 18. Important implementation principles

Follow these principles throughout the implementation:

* Reuse the existing Chatterbox integration.
* Do not create a second TTS backend.
* Do not invent configuration variables.
* Do not invent game train types if they can be discovered from the existing project.
* Keep the audio asset system independent from Pygame.
* Keep the manifest machine-readable.
* Keep filenames deterministic.
* Never silently overwrite accepted audio.
* Keep generation asynchronous for batches.
* Make individual asset regeneration easy.
* Preserve exact Finnish text in the manifest.
* Treat pronunciation corrections as intentional text variants rather than modifying the canonical display name.
* Do not generate thousands of unnecessary audio files.
* Use reusable Finnish number components.
* Do not assume simple string concatenation is grammatically valid for every announcement.
* Do not implement announcement playback in this phase.

---

# 19. Final deliverables

At the end of the implementation, provide:

1. The new railway announcement asset directory.
2. `manifest.json`.
3. `README.md`.
4. Number-component generation logic.
5. Asset generation UI integrated into the existing `ai-audio-studio`.
6. Batch generation support.
7. Preview/regenerate/accept workflow.
8. Asset validation.
9. Automated tests.
10. A short implementation report listing:

* files changed
* new API endpoints, if any
* new frontend components
* manifest format
* tests executed
* anything intentionally deferred

Do not make unrelated changes to `ai-audio-studio`.

## Important correction: Finnish numbers 11–19

The railway announcement audio system must handle Finnish number morphology correctly.

The numbers **11–19 are special cases**.

They cannot be constructed by concatenating:

```text
10 + 1
10 + 2
...
10 + 9
```

because Finnish uses the `-toista` forms:

```text
11 = yksitoista
12 = kaksitoista
13 = kolmetoista
14 = neljätoista
15 = viisitoista
16 = kuusitoista
17 = seitsemäntoista
18 = kahdeksantoista
19 = yhdeksäntoista
```

Therefore, **11–19 must each have their own generated audio asset**.

### Number asset categories

Treat Finnish number components as three distinct categories:

```text
numbers/
├── units/
│   ├── 0.ogg
│   ├── 1.ogg
│   ├── 2.ogg
│   └── ...
│
├── teens/
│   ├── 11.ogg
│   ├── 12.ogg
│   ├── 13.ogg
│   ├── 14.ogg
│   ├── 15.ogg
│   ├── 16.ogg
│   ├── 17.ogg
│   ├── 18.ogg
│   └── 19.ogg
│
├── tens/
│   ├── 20.ogg
│   ├── 30.ogg
│   ├── 40.ogg
│   ├── 50.ogg
│   ├── 60.ogg
│   ├── 70.ogg
│   ├── 80.ogg
│   └── 90.ogg
│
└── hundreds/
    ├── 100.ogg
    ├── 200.ogg
    ├── 300.ogg
    ├── ...
    └── 900.ogg
```

If thousands are required, add:

```text
thousands/
├── 1000.ogg
├── 2000.ogg
├── 3000.ogg
└── ...
```

Do not generate unnecessary files.

---

## Number composition rules

The number composer must explicitly handle the Finnish teen range.

Examples:

```text
3
→ numbers/units/3.ogg

11
→ numbers/teens/11.ogg

19
→ numbers/teens/19.ogg

20
→ numbers/tens/20.ogg

23
→ numbers/tens/20.ogg
 + numbers/units/3.ogg

47
→ numbers/tens/40.ogg
 + numbers/units/7.ogg

100
→ numbers/hundreds/100.ogg

108
→ numbers/hundreds/100.ogg
 + numbers/units/8.ogg

115
→ numbers/hundreds/100.ogg
 + numbers/teens/15.ogg

523
→ numbers/hundreds/500.ogg
 + numbers/tens/20.ogg
 + numbers/units/3.ogg

519
→ numbers/hundreds/500.ogg
 + numbers/teens/19.ogg
```

This is the required decomposition model.

In particular:

```text
519 != 500 + 10 + 9
```

It must be:

```text
519 = 500 + 19
```

where `19.ogg` contains the complete spoken word:

```text
yhdeksäntoista
```

Likewise:

```text
514 = 500 + 14
515 = 500 + 15
516 = 500 + 16
...
519 = 500 + 19
```

---

## Reference voice

Use the existing Chatterbox TTS integration with this reference voice:

```text
female/eeva.wav
```

This is the canonical reference voice for the railway announcement asset set.

The generator should default to:

```text
Reference voice:
female/eeva.wav
```

Do not duplicate or copy the reference recording into every asset directory.

The manifest should identify the reference voice:

```json
{
  "version": 1,
  "language": "fi",
  "voice": {
    "id": "eeva",
    "reference": "female/eeva.wav"
  }
}
```

All railway announcement assets generated for this voice should use the same reference recording unless the user explicitly chooses another voice.

---

## Recommended manifest structure

Use explicit number categories in the manifest:

```json
{
  "version": 1,
  "language": "fi",

  "voice": {
    "id": "eeva",
    "reference": "female/eeva.wav"
  },

  "numbers": {
    "units": {
      "3": {
        "file": "numbers/units/3.ogg",
        "text": "kolme",
        "value": 3
      }
    },

    "teens": {
      "11": {
        "file": "numbers/teens/11.ogg",
        "text": "yksitoista",
        "value": 11
      },
      "12": {
        "file": "numbers/teens/12.ogg",
        "text": "kaksitoista",
        "value": 12
      }
    },

    "tens": {
      "20": {
        "file": "numbers/tens/20.ogg",
        "text": "kaksikymmentä",
        "value": 20
      }
    },

    "hundreds": {
      "500": {
        "file": "numbers/hundreds/500.ogg",
        "text": "viisisataa",
        "value": 500
      }
    }
  }
}
```

The manifest must make the distinction between `units`, `teens`, `tens`, and `hundreds` explicit.

---

## Number composer API

Implement a pure, easily testable function such as:

```python
compose_number(523)
```

returning:

```python
[
    "numbers/hundreds/500.ogg",
    "numbers/tens/20.ogg",
    "numbers/units/3.ogg",
]
```

For:

```python
compose_number(519)
```

return:

```python
[
    "numbers/hundreds/500.ogg",
    "numbers/teens/19.ogg",
]
```

For:

```python
compose_number(14)
```

return:

```python
[
    "numbers/teens/14.ogg",
]
```

For:

```python
compose_number(47)
```

return:

```python
[
    "numbers/tens/40.ogg",
    "numbers/units/7.ogg",
]
```

The composer must never attempt to synthesize `11–19` from `10 + unit`.

---

## Required tests

Add explicit tests for every Finnish teen number:

```text
11
12
13
14
15
16
17
18
19
```

Also test:

```text
20
21
29
30
47
99
100
101
110
111
115
119
120
123
500
511
519
523
999
```

The important expected results include:

```text
11  → [11]
19  → [19]

111 → [100, 11]
119 → [100, 19]

511 → [500, 11]
519 → [500, 19]

523 → [500, 20, 3]
```

where the values represent the corresponding manifest asset components.

---

## TTS generation list

The generation UI should display the exact Finnish text that Chatterbox will synthesize.

For the teen numbers:

```text
11  → yksitoista
12  → kaksitoista
13  → kolmetoista
14  → neljätoista
15  → viisitoista
16  → kuusitoista
17  → seitsemäntoista
18  → kahdeksantoista
19  → yhdeksäntoista
```

The user must be able to preview and regenerate these individually.

Do not generate `11–19` automatically from smaller audio files.

They are individual TTS assets.

---

## Final required number asset set

For a basic 0–999 Finnish number system, the generator should produce only the reusable components needed to construct every number:

```text
0–9
11–19
20, 30, 40, ..., 90
100, 200, 300, ..., 900
```

There is no need for separate assets for:

```text
21
22
23
...
98
```

because these can be composed from tens + units.

Likewise there is no need for:

```text
101
102
...
999
```

as individual files.

The resulting system should therefore remain small while still being able to construct every number from 0–999.

Use `female/eeva.wav` as the default reference voice throughout the generation workflow.
