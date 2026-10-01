# Railway announcement assets

Finnish station announcement clips for Road Rage Trip, built from small
reusable parts: numbers, place names, train types, platform words and
phrases. Generated in `ai-audio-studio` (page **Railway announcements**,
`/announcements`) with Chatterbox; the logic lives in
`ai-audio-studio/announcements.py`. The game does not play them yet.

## Directory structure

```text
railway_announcements/
├── manifest.json            what every file is and says
├── numbers/
│   ├── units/0.ogg … 9.ogg
│   ├── teens/11.ogg … 19.ogg      own words: yksitoista … yhdeksäntoista
│   ├── tens/10.ogg … 90.ogg       kymmenen, kaksikymmentä, …
│   ├── hundreds/100.ogg … 900.ogg sata, kaksisataa, …
│   └── thousands/1000.ogg …       only if the number range needs them
├── place_forms.json         hand-written "to"/"from" forms of each place
├── places/<id>.ogg          Oulu, Tornio-Itäinen, …   (oulu.ogg, tornio_itainen.ogg)
├── places/to/<id>.ogg       Ouluun, Helsinkiin, Tampereelle, …
├── places/from/<id>.ogg     Oulusta, Helsingistä, Tampereelta, …
├── train_types/<id>.ogg     intercity.ogg, pendolino.ogg, …
├── platforms/<id>.ogg       raide.ogg, raiteelle.ogg, raiteelta.ogg
├── phrases/<id>.ogg         attention.ogg, arriving.ogg, …
└── connectors/<id>.ogg      pause_short/medium/long.ogg (silence)
```

All files are mono OGG Vorbis at Chatterbox's sample rate (24 kHz), with
silence trimmed from both ends so parts can be played back to back.

## Reference voice

Default `voices/female/eeva.wav` (in ai-audio-studio): a clean recording
of one speaker. Use the same voice for the whole set; the manifest records
it (`voice`) and each entry's `voice`. The recording is never copied here.

## Number composition

Numbers are said with components, never one file per number:

| Number | Components | Files |
|---|---|---|
| 3 | 3 | `units/3` |
| 14 | 14 | `teens/14` |
| 47 | 40 + 7 | `tens/40`, `units/7` |
| 115 | 100 + 15 | `hundreds/100`, `teens/15` |
| 519 | 500 + 19 | `hundreds/500`, `teens/19` (never 500 + 10 + 9) |
| 523 | 500 + 20 + 3 | `hundreds/500`, `tens/20`, `units/3` |
| 1008 | 1000 + 8 | `thousands/1000`, `units/8` |

`announcements.compose_number(519)` returns those files in order. For
0–999 the set needs 37 components: 0–19, 20–90 by tens, 100–900 by
hundreds. The page computes the list for any range up to 9999.

## Place forms

Announcements say where a train goes and where it comes from, so each
place has three clips: the name ("Oulu"), the "to" form ("Ouluun") and the
"from" form ("Oulusta"). Finnish picks the ending per place - inner
-Vn/-sta ("Helsinkiin", "Helsingistä", with a stem change) or outer
-lle/-lta ("Tampereelle", "Seinäjoelta") - so the forms are written by hand
in `place_forms.json`, keyed by place id:

```json
"helsinki": {"name": "Helsinki", "to": "Helsinkiin", "from": "Helsingistä"}
```

## Announcement templates

```text
[attention] [train type] [number] [place to] [arriving] [raiteelle] [number]
"Hyvät matkustajat. InterCity viisikymmentäseitsemän Ouluun saapuu raiteelle kolme."

[train type] [number] [place from] [arriving] [raiteelle] [number]
"Pendolino neljäsataa yksitoista Helsingistä saapuu raiteelle kaksi."

[destination] [place]
"määränpää Oulu"

[next_train] [departing] [raiteelta] [number]
"Seuraava juna lähtee raiteelta kaksi."

[train type] [number] [delayed] [number] [minutes]
"Pendolino neljäsataa yksitoista on myöhässä noin kymmenen minuuttia."
```

## Generating

1. Start ai-audio-studio (`make run`) and open http://127.0.0.1:8420/announcements.
2. Pick the reference voice and the number range, press **Update list**.
3. Choose a category. Edit any Finnish text first if needed.
4. **Generate** one asset or **Generate all missing** (queued, one at a time on the GPU).
5. Listen; **Accept**, **Regenerate**, edit and regenerate, or **Discard**.

Accepting converts the WAV to OGG here and writes `manifest.json`. An
accepted file is only replaced after you confirm it.

### Regenerate one asset

Find its row, edit the text if needed, **Regenerate**, listen, **Accept**
and confirm the replacement.

### A pronunciation fix

Edit the text in the row (e.g. a spelling that Chatterbox says better). The
manifest keeps your text as `text` and the original as `default_text`.

## Adding things

- **A place**: places come from the game's timetable (every station where a
  long-distance train stops). For another one, add it to the timetable data
  or to `long_distance_places()` in `announcements.py`. Its id is the name in
  ASCII (`slug("Tornio-Itäinen")` → `tornio_itainen`). Add its "to" and
  "from" forms to `place_forms.json`; until then its rows in "Places: to" and
  "Places: from" have empty text (type the form there to generate it).
- **A train type**: add `id: (timetable type code, Finnish name)` to
  `TRAIN_TYPES` in `announcements.py`.
- **A phrase**: add `id: "Finnish text"` to `PHRASES` (or `PLATFORMS`).

Then reload the page: the new rows show as missing.

## Validating

Press **Validate collection** on the page, or:

```bash
cd ai-audio-studio
.venv/bin/python -c "import announcements as a; print(a.validate(0, 999)[1])"
```

It reports missing files, files without a manifest entry, duplicate ids or
files, invalid JSON, non-OGG/empty/unreadable files, mixed sample rates or
channel counts, and whether every number in the range can be said.

## manifest.json

```json
{
  "version": 1,
  "language": "fi",
  "voice": {"id": "eeva", "reference": "female/eeva.wav"},
  "sample_rate": 24000,
  "numbers": {
    "units": {"3": {"file": "numbers/units/3.ogg", "text": "kolme", "value": 3,
                    "category": "numbers", "language": "fi", "duration_s": 0.41,
                    "voice": "female/eeva.wav", "accepted_at": "2026-10-01T12:00:00"}},
    "teens": {}, "tens": {}, "hundreds": {}, "thousands": {}
  },
  "places": {"oulu": {"file": "places/oulu.ogg", "text": "Oulu", "…": "…"}},
  "places_to": {"oulu": {"file": "places/to/oulu.ogg", "text": "Ouluun", "…": "…"}},
  "places_from": {"oulu": {"file": "places/from/oulu.ogg", "text": "Oulusta", "…": "…"}},
  "train_types": {"intercity": {"file": "train_types/intercity.ogg", "text": "InterCity", "train_type": "IC"}},
  "platforms": {}, "phrases": {}, "connectors": {}
}
```
