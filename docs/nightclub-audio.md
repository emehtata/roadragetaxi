# Nightclub music

Dance music leaks out of nightclubs into the streets around them, at night.

## Where the venues come from

- **Points:** OSM `amenity=nightclub` nodes, which is how Oulu's are mapped
  (Kaarlenholvi, Ilona, Club Labra, Yölento and others). Overpass fetches them
  and `osm/build.py` makes `SceneryObject(kind="nightclub", opening_hours=...)`.
- **Buildings:** a building tagged `amenity=nightclub` (`venue_type`) counts
  too. Bars and pubs don't.
- **To the client:** each map chunk carries `nightclubs: [[x, y, schedule], ...]`
  (`map_chunks.py`). They load and unload with their chunk;
  `MapLayer.nightclubs()` reads the loaded chunks, so nothing is kept in step
  and nothing is duplicated.
- **Schedule:** weekly open intervals in minutes, 0 = Monday 00:00
  (`nightlife.py`). The OSM `opening_hours` is used when it's a simple form
  (`Fr-Su 22:00-04:30`, `We-Th 00:00-04:30; Fr,Sa 23:00-05:00`, `Mo off`).
  Anything else, or none, gets the default **Th–Sa 22:00–04:00**, an estimate
  of Finnish nightlife.
- **Adding a venue:** map it in OpenStreetMap. There are no development
  fixtures: Oulu's real data covers it.

Nothing in the simulation reads these: it's sound only.

## How it sounds (`godot/nightclub_audio.gd`)

Three factors are kept apart and multiplied:

| Factor | Function | What it does |
| --- | --- | --- |
| Open | `open_level` | 0 to 1, fading over `FADE_MIN` (20 game minutes) after opening and before closing. Venues open past midnight, and Sunday night wraps into Monday. Driven by the server's game clock (`calendar.date` + `game_time_seconds`) |
| Distance | `gain` | 1 within `DOOR_M` (12 m), falling smoothly to 0 at `RANGE_M` (160 m, world metres = the server's EPSG:3067 metres). Steep near the door, a long quiet tail |
| Walls | `cutoff_hz` | A low-pass at `CUTOFF_DOOR_HZ` (2.6 kHz) right outside, closing to `CUTOFF_FAR_HZ` (280 Hz) at the edge: the bass carries, the highs go |

- **Muffling is an approximation:** the player is always outside, so the music
  always comes through the venue's walls. No ray tests are made against other
  buildings.
- **Players:** a fixed pool of `PLAYERS` (3) `AudioStreamPlayer2D`s, each on
  its own bus (`Nightclub0`–`2`, sending to Environment) with one
  `AudioEffectLowPassFilter`. All are made once.
- **Which venues play:** the loudest three. A venue keeps its player while it
  stays among them, so the track never restarts on a chunk crossing, a volume
  change or the clock.
- **Smoothing:** volume and cutoff ease toward their targets over `SMOOTH_S`
  (0.6 s). A player stops once faded out.
- **Mix:** door-level music is boosted 6 dB over the original mix. City day/night
  ambience follows the loudest playing club's smoothed gain, dropping to 20% of
  its usual level at the door and recovering with distance or closing fades.
  Weather, traffic and other sounds are unchanged; the Environment bus is not ducked.
- **Panning:** the 2D player only pans; its own attenuation is off.
- **Tracks:** every `.ogg` in `assets/music/nightclub/` (`tracks_in`, read at start), one picked per venue by its position, started at a
  random point so neighbouring clubs aren't in step. A missing file logs a
  warning and the music is silent.
- **Tuning:** the constants at the top of `nightclub_audio.gd` set loudness
  (`LOUDNESS_DB`), range, muffling and fades.

## Assets

`src/theroadragetrip/assets/music/nightclub/nightclub_dance_{1,2}.ogg`: the
project owner's two tracks (2026-10-19), converted from MP3 to Ogg Vorbis at
q1 (about 3 MB each; heard muffled anyway). They are listed in
`tools/license_inventory.json`; how they were made is still to be recorded.
To add a track, drop an `.ogg` into the folder; it plays from the next start.

## Checks

- `tests/test_nightlife.py`: opening hours parsing and the fallback, a node
  keeping its hours, a bar not being a nightclub, and chunks carrying venues
  from points and buildings.
- `godot/tests/run_tests.gd` `test_nightclub_audio`:
  - closed by day and fading in when opening;
  - open after midnight and faded out after closing;
  - Sunday wrapping into Monday;
  - quieter and more muffled with distance, without steps;
  - recognisable just outside and inaudible beyond the range;
  - three players for the nearest venues, a duplicate counted once;
  - no restart while moving, everything stopped far away;
  - silent and safe without tracks.
- Selftest report: `nightclubs_loaded`, `nightclubs_playing`,
  `nightclub_nearest_m`. Central Oulu on a Friday at 23:30: 4 loaded, the 2
  within range playing. On a Monday night: none.
