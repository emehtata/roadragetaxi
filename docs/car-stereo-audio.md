# Car stereos

Some NPC cars boom bass-heavy electro pop. This is client-side sound only: the
simulation, protocol and collisions are unchanged.
Code: `godot/car_audio.gd`.

## Which cars

- **Eligible:** `vehicle_type == "car"`, not a taxi and not police (from the
  state's NPC rows). Vans, trucks, buses, tractors and two-wheelers never are.
- **Has a stereo:** `draw(vehicle id) < share(game minute of the week)`. The
  draw is a fixed multiplicative hash of the server's vehicle id, so the same car
  always draws the same.
- **Kept for life:** it is decided when the car is first seen and kept while the
  car exists. A car unseen for `FORGET_S` (10 s) is forgotten, which is what
  despawning looks like from the client. Streaming and the clock never reroll it.
- **Share** (estimates; time from the server's calendar and game clock):

| When | Share |
| --- | --- |
| Friday and Saturday nights, 18:00–05:00 | `SHARE_WEEKEND_NIGHT` 10 % |
| Other evenings and nights | `SHARE_EVENING` 3 % |
| Daytime, 05:00–18:00 | `SHARE_DAY` 1 % |

## How it sounds

The levels, smoothing and ambience ducking are the nightclub music's
(`nightclub_audio.gd`: `LOUDNESS_DB`, `SMOOTH_S`, `CITY_AMBIENCE_MIN`). The city
ambience follows whichever is louder, a club or a car.

- **Distance:** full loudness within `NEAR_M` (6 m), smoothly to silence at
  `RANGE_M` (120 m, world metres).
- **Through the body:** a low-pass at `CUTOFF_NEAR_HZ` (9 kHz, synths and
  percussion still there) up close, closing to `CUTOFF_FAR_HZ` (250 Hz, only
  the 808s) at the edge.
- **Players:** `PLAYERS` (3) `AudioStreamPlayer2D`s on their own low-pass buses
  (`CarMusic0`–`2`, sending to Environment), all made once. They play the
  loudest stereo cars. A car keeps its player while it stays among them, so
  turns, lanes and chunks never restart the track.
- **Position:** the car's interpolated position each frame
  (`EntityLayer.npc_cars()`, the same blend the car is drawn with), so the music
  moves with it and doesn't jump.
- **Tracks:** every `.ogg` in `assets/music/cars/` (read at start: drop a new one in), e.g. the owner's two tracks
  converted from MP3 to Ogg Vorbis q1. One is picked per car, started at a
  random point. Missing files leave the stereos silent.

## Checks

`godot/tests/run_tests.gd` `test_car_audio`:

- the shares by weekday and hour, including after midnight;
- only ordinary cars, the same draw for the same car, and about the share over
  4,000 ids;
- distance and filter curves that fall without steps;
- one player for a duplicated car;
- the music following a moving car and surviving a clock change;
- a despawned car releasing its player;
- silent and safe without tracks.

The selftest report includes `car_stereos_playing`.
