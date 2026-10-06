# Godot Parity Phase 7 — Speech and Stations

## Objective

Implement the next recommended phase from
`docs/architecture/godot-pygame-rendering-parity.md`:

1. driver and passenger speech events, audio, and subtitles
2. railway station announcements
3. station crowd and luggage ambience
4. the `J` next-train panel

The Python simulation remains authoritative for when somebody speaks, which
line is chosen, train arrival/departure facts, station passenger counts, and
timetable results. Godot owns playback, subtitle lifetime, local panel
visibility, and spatial ambience presentation.

This is one low-risk speech/station phase. Do not combine it with the later
settings-menu phase, historical weather, rendering polish, train popups, or
unrelated controls.

---

## 1. Read and trace the current implementation first

Before changing code, trace:

* driver/passenger speech selection, cooldowns, comment-channel exclusion,
  subtitle fields, and four-second comment lifetime in `audio.py`
* every `play_driver_line`, `play_passenger_line_for_situation`,
  `play_passenger_line`, `update_passenger_speech`, and `update_comments` call
  in `simulation.py`
* `passenger_chatter.json`, `driver_chatter.json`, and the gender/language/hash
  filename convention under `sounds/passenger_chatter` and `sounds/driver_chatter`
* `NullAudio`, `EventAudio`, rail-event conversion, state broadcasting, and
  the game calendar in `server/__init__.py`
* state/event construction and interpolation in `protocol.py`
* `AnnouncementScript`, `StationAnnouncer`, its clip ordering/pauses, platform
  source rules, 20-second stale queue, and tests in `station_announcer.py`
* `_play_rail_sounds`, station ambience selection, the first-use timetable
  hint, `J` toggle, and next-train board construction in `main/__init__.py`
* `RailwayManager.stations`, station waiting counts, `next_arrivals`, and
  `next_departures`
* `draw_next_train` and speech subtitle styling in `render/hud.py`
* Godot's due-event path, `audio_manager.gd`, `audio_events.json`, HUD, input,
  map coordinates, and existing train audio
* current Python protocol/server/audio/rail tests and Godot unit/self-tests

Use the repository as the source of truth. Reuse the existing text catalogs,
recorded speech, announcement manifest/clips, timetable objects, translations,
audio buses, spatial ranges, and UI patterns.

---

## 2. Keep decisions on the server and presentation on the client

`EventAudio` currently discards the speech-specific methods inherited from
`NullAudio`. Replace those no-ops with a small pygame-free speech event path.
The server must decide:

* whether speech is eligible and not already busy
* cooldowns and random interval timing
* the selected catalog entry
* requested-language text and existing fallback behaviour
* gender, speaker kind, optional passenger name, and audio hash/key

Godot must not independently choose a line, mood, language, or random speech
interval. Two clients observing the same simulation event must receive the
same speech decision.

Share/extract the smallest pure selection/state helper needed by both
`AudioManager` and `EventAudio`; do not duplicate the chatter catalogs and
selection rules. The helper must not import pygame. Preserve Pygame behaviour
and public calls.

Use simulation delta for server speech timing. Preserve the existing
three-second per-situation driver cooldown, random passenger chatter interval,
one-at-a-time speech exclusion, and four-second subtitle lifetime. If exact
clip duration is needed for exclusion, derive it once from existing asset
metadata/files without initializing an audio device; do not add a dependency.

Do not move audio mixing, subtitle drawing, or asset decoding to Python's
headless server.

---

## 3. Add one explicit speech event contract

Emit one event for each accepted line, containing only stable presentation
facts, for example:

```text
{
  type: "speech",
  speaker: "driver" | "passenger",
  speaker_name: string | null,
  gender: "woman" | "man",
  language: "fi" | "en",
  hash: string,
  text: string,
  duration_s: 4.0
}
```

Use the repository's actual accepted language/gender values and stable hash
keys if they differ. The event must contain enough information for Godot to
resolve exactly one existing chatter file without accepting an arbitrary
filesystem path from the wire.

Requirements:

* driver lines use the current Finnish-audio fallback when appropriate while
  retaining the requested-language subtitle text, matching current Pygame
* specific Finnish passenger lines still resolve to their catalog entry
* situation-based mood filtering remains unchanged
* a missing catalog entry or missing file fails quietly and emits no unusable
  event
* events remain edge-like and pass through the existing state-buffer due-event
  mechanism exactly once
* reconnecting or interpolating state never replays old speech
* malformed/unknown speech events are ignored safely

Do not put transient speech in continuously repeated state and do not send raw
audio bytes.

---

## 4. Play speech and show subtitles in Godot

Extend the existing audio manager with the minimum direct-file support needed
for the existing PCM WAV chatter files. Cache decoded streams by resolved
stable asset key, use the `Game` bus, and play speech non-positionally as the
taxi's current conversation. Do not copy, transcode, regenerate, or add audio
files.

Maintain one speech player/channel:

* do not overlap driver and passenger lines
* a new event that arrives while the channel is busy follows the server's
  decision; do not invent a second random choice or an unbounded client queue
* free/stop it cleanly on disconnect
* volume follows the existing Game/Master bus controls

Add one reusable subtitle label to the HUD, not one node per event. Match the
Pygame presentation closely:

* `speaker name: text`
* passenger name when supplied, otherwise the localized/default speaker label
* white text on a translucent black background
* horizontally centred near the bottom, above conflicting HUD controls
* visible for the event's bounded duration, using real time
* later accepted speech replaces/refreshes the single subtitle
* resizing remains correct and long lines wrap within the viewport

Subtitles should be enabled by default for this phase. Do not implement or
persist comments/subtitles settings; that belongs to the later settings phase.

---

## 5. Emit complete station-announcement events

When a timetable train arrives or departs, preserve the existing
`train_arrived`/`train_departed` event and also build an announcement from the
existing `AnnouncementScript` and manifest.

The server event should describe one complete announcement, not one protocol
event per audio clip. It must contain:

```text
{
  type: "station_announcement",
  clips: [stable manifest-relative clip keys in playback order],
  at: [world_x, world_y],
  text: assembled Finnish sentence
}
```

The example is illustrative; keep naming consistent with the current event
schema. Reuse `AnnouncementScript.phrases`, `StationAnnouncer.clips`, and their
pause selection through a shared pygame-free helper rather than reimplementing
Finnish train names, numbers, tracks, places, or connector pauses.

Requirements:

* arrival/departure wording, train category special cases, number components,
  origin/destination, track, attention phrase, and pauses match Pygame
* resolve only manifest-owned relative paths beneath the announcement asset
  root; malformed traversal/absolute keys are rejected
* locate sound at the applicable station/platform source available to the
  headless world, falling back to the train stop point as Pygame does
* do not suppress server events based on a Pygame listener/audio-device check
* absent service/stop/manifest data emits no announcement but keeps ordinary
  train sound events

Godot owns one FIFO announcement player. Play the clip list strictly in order,
including pause clips, without gaps introduced by frame polling. Queue complete
announcements, drop an announcement still waiting after the existing 20 real
seconds, and keep the currently playing announcement intact. Use the `Game`
bus and the existing railway announcement spatial range `(60 m, 300 m)`.

Do not flatten an announcement into a newly generated file and do not add a
node/player per clip.

---

## 6. Add compact authoritative railway/timetable state

Add one optional `state.railway` object built from the current
`RailwayManager` and server calendar. It should carry only the station facts
needed for this phase:

```text
stations: [{name, x, y, waiting}]
nearest_station: string | null
arrivals: [{time, train_type, number, origin, track}]
departures: [{time, train_type, number, destination, track}]
```

Use the exact current data types where sensible. Requirements:

* nearest station and the next five arrivals/departures are computed by the
  existing `RailwayManager` queries relative to the taxi, not reimplemented
  in Godot
* times come from the authoritative game calendar and are sent in an
  unambiguous compact form sufficient to render `%H:%M`
* station waiting counts come from the authoritative station passenger manager
* all numeric coordinates/counts are finite and bounded/sanitized at the
  protocol boundary
* no railway manager, timetable clock, `StationCall`, or datetime object leaks
  into JSON
* no railway/timetable data yields an empty, safe optional object
* treat this state discretely during interpolation
* keep the extension additive; do not bump the protocol version unless the
  repository's established compatibility rules require it

Do not send station ambience volume, nearest-station distance, formatted panel
text, or per-client UI toggle state.

---

## 7. Add station ambience in Godot

Reproduce `_play_rail_sounds` using `state.railway.stations` and the current
listener position. Of stations with waiting passengers, choose the one whose
sound is loudest under the existing `station.ambience` spatial attenuation.
Drive two positional loops at that station:

```text
base volume = min(1, waiting / 30)
crowd       = base volume * 0.6, station.ambience variation 0
luggage     = base volume * 0.4, station.ambience variation 1
```

Stop both loops when no eligible station exists, on disconnect, or when state
is missing. Reuse the current loop manager and `(15 m, 150 m)` range. Update
position/volume without restarting loops each state. Do not have every station
play simultaneously and do not add station nodes.

---

## 8. Add the `J` next-train panel

`J` is a Godot-local presentation toggle. It must never be sent as a gameplay
command and must not affect simulation/timetable state.

Add one reusable HUD panel that matches `draw_next_train`:

* station name
* `Next trains` arrival section
* `Departing trains` departure section
* up to five rows in each section
* each row shows `HH:MM`, optional localized `track N`, train type/number, and
  origin for arrivals or destination for departures
* top-right placement under the existing speed/road HUD region
* pale blue text, translucent dark background, blue border
* hidden when toggled off or when both lists are empty
* resize-safe and non-modal

Use existing translation keys (`next_trains`, `departing_trains`, `track`, and
the timetable-available hint) where available. Preserve Pygame's one-time
session hint when a map first exposes timetabled stations, without repeatedly
overwriting newer server notifications. If the existing Godot notice ownership
makes the hint conflict with authoritative notices, use a small client-only
hint label/timer instead of mutating simulation state.

Add `J` to the relevant driving hint. Ignore echo/repeat and do not toggle it
while a modal UI owns keyboard input, following existing input conventions.

---

## 9. Scope and protected systems

Do not change:

* taxi, passenger, train, timetable, booking, or station-passenger rules
* speech line text, mood mappings, random interval ranges, or recorded assets
* announcement manifest contents or generated clips
* train movement/rendering or existing arrival/departure sounds
* map/chunk streaming, camera, interpolation, navigation, weather, or physics
* settings/pause menus, saved audio settings, or subtitle toggles
* multiplayer architecture beyond keeping the event/state contracts sane

No new dependency or media asset is needed.

---

## 10. Tests and validation

Add the smallest deterministic checks at the layer that owns each behaviour.

### Python speech/events

Cover at least:

1. each speech API emits the selected stable asset key, matching text, speaker,
   optional passenger name, gender, and language
2. situation mood filtering, specific-line lookup, and Finnish fallback match
   current Pygame behaviour
3. busy exclusion, driver cooldown, passenger random interval, and comment
   expiry use deterministic injected RNG/time or simulation delta
4. missing catalogs/files and disabled/ineligible speech fail quietly
5. `take_events` drains once and no pygame/audio device is imported or opened

### Python announcements/timetable

Cover at least:

1. arrival/departure events include the exact manifest clip order and sentence
2. train types, categories, number decomposition, places, tracks, and pause
   clips remain covered by existing announcement fixtures
3. missing service/stop/manifest data is safe
4. announcement keys cannot escape the asset root
5. railway state contains finite station/waiting data and exactly the next five
   authoritative arrivals/departures nearest the taxi
6. time advancement and empty/no-railway worlds produce correct JSON-safe state
7. additive railway state does not alter existing train/event fields

### Godot

Cover at least:

1. a speech event resolves the expected existing WAV, plays once, and shows
   one correctly attributed subtitle for the bounded real-time duration
2. malformed/missing speech assets are ignored without crashing or traversal
3. announcement clips play strictly in order on one player; whole
   announcements queue and stale waiting entries expire after 20 seconds
4. announcement audio uses the supplied position and `(60, 300)` range
5. crowd/luggage formulas, variations, loudest-station selection, loop reuse,
   and stop-on-empty/disconnect match Pygame
6. `J` toggles one panel without sending a command; echo/modal input is ignored
7. arrivals/departures format time, optional track, train, and opposite endpoint
   correctly, cap at five, resize safely, and hide on empty/malformed state
8. old servers without speech/announcement/railway additions remain safe
9. existing audio, train events, HUD, phone, navigation, and input tests pass

Run at minimum:

```bash
pytest -q tests/test_audio.py tests/test_station_announcer.py tests/test_trains.py tests/test_protocol.py tests/test_server_headless.py tests/test_client_server_integration.py
make godot-test
make godot-selftest
make audio-check
```

Also run the narrow test files added for the shared speech helper or railway
state. Distinguish unrelated pre-existing failures from regressions.

Manually verify:

1. pickup, dropoff, collision, nausea, recovery, and periodic passenger speech
   use the correct voice and subtitle attribution
2. speech never doubles or replays after interpolation/reconnect
3. arriving and departing trains keep their existing sounds and add a clear,
   ordered Finnish station announcement from the station
4. station ambience grows with waiting passengers and follows only the loudest
   nearby station without loop restarts
5. `J` opens/closes the nearest-station board and game-time rows advance
6. phone/modal input, HUD notices, navigation, driving, and resize still work

---

## 11. Performance acceptance

This phase is expected to be low risk. Required acceptance:

* one reusable speech player and subtitle label
* one reusable announcement player/queue, not one node per clip
* two reusable station ambience loops
* one reusable next-train panel
* decoded streams cached; no file decoding per frame/state
* no timetable recomputation, catalog scan, directory scan, or node churn per
  render frame
* compact bounded state: station rows plus at most five arrivals and five
  departures
* no material regression in the existing Godot benchmark/self-test counters

Record a before/after ordinary drive-through benchmark if the repository's
current parity workflow requires it. At minimum report node/player bounds and
confirm that idle frames allocate no speech/announcement UI or audio nodes.

---

## 12. Documentation

Update only the relevant rows and phase history in
`docs/architecture/godot-pygame-rendering-parity.md`:

* driver/passenger speech audio and subtitles
* station announcements
* station crowd/luggage ambience
* next-train panel and railway protocol state
* `godot-final-07` implementation and validation results

Update protocol/audio documentation if it enumerates event types, state fields,
direct-file playback, spatial ranges, or loops. Do not rewrite or re-audit the
whole parity document.

---

## 13. Git workflow

Work on the current branch:

```text
release/v0.16.0g-alpha
```

Preserve unrelated existing worktree changes. Create clear commits and push
them when implementation and validation are complete. Do not create or push a
Git tag.

---

## Final report

Report:

### Implementation

* shared server speech selection/timing and exact event contract
* Godot speech asset resolution, player ownership, and subtitle lifecycle
* announcement construction, queue/order/staleness, and spatial source
* exact railway state schema and station ambience formulas
* `J` panel behaviour and any current contract that differed from this prompt

### Tests

* exact commands and results
* manual scenarios checked
* any unrelated failures

### Performance

* bounded nodes/players/queues and cached assets
* benchmark/self-test comparison where available

### Git

* commit hash(es)
* confirmation that the branch was pushed
* explicit confirmation that no Git tag was created

Do not start the next parity phase automatically.
