# Environment ambience

The Godot client mixes city, rural day, rural night and beach beds through the
existing **Environment** volume slider. Nearby nightclub and car music ducks all
these beds; weather, wildlife calls, stations, sports crowds, swimming and rides
keep their existing independent layers.

Rural strength blends building density in the four surrounding 500 m chunks
(fully rural at five or fewer buildings, urban at eighteen or more). Mapped
woodland, farmland, meadow, grassland, scrub and wetland override that estimate
inside their polygons. This is an ambience heuristic, not settlement simulation.
Beach waves use mapped beach polygons, with a smooth 80 m falloff that works
across chunk borders. Other untagged shorelines do not play the beach bed.

Location geometry is sampled twice a second from at most nine nearby chunks.
Volumes ease over two seconds. Solar darkness selects the rural day/night mix;
rain reduces the bird bed, winter replaces it with quiet air and suppresses
beach waves. Underground and disconnected sessions clear the outdoor beds.
Missing chunks stay quiet rather than inventing city traffic.

Three 24.5-second stereo Vorbis loops were generated locally with Stable Audio
Open and the existing one-second loop crossfade. The audio catalog records
prompts, deterministic seeds, durations and generation metrics. All clips decode
and have no raw clipped samples. Per-file listening review remains **pending**;
successful generation and loading are not a listening sign-off.

Regenerate with the sibling audio studio virtualenv:

```sh
HF_HUB_OFFLINE=1 ../ai-audio-studio/.venv/bin/python tools/generate_audio.py \
  --group ambient.rural_day --group ambient.rural_night --group ambient.beach --force
```

Client mix, boundary, season, rain, muting and playback checks are in
`godot/tests/run_tests.gd`. Python chunk tests check that the needed landuse tags
survive clipping, and `tools/validate_audio_assets.py` checks catalog references
and decoded assets.

## 0.19 elements (rrt-019.1 sound pass)

Thirteen Stable Audio Open groups for elements added in 0.19, generated with
`tools/generate_audio.sh --group ...` and recorded in the catalog as usual.

| Group | Kind | Trigger |
| --- | --- | --- |
| `pedestrian.front_door` | one-shot at the door | entering or leaving a house (`_home_door_pressed`) |
| `pedestrian.footsteps_indoor` | step | walking a floor plan (`home_walk.gd`), every `FOOTSTEP_M` |
| `vehicle.bicycle_bell` | one-shot at the rider | a cyclist held up by a walker or a stalled vehicle, at most every 6 s per rider (`cycling.BELL_REASONS`); sound only, the ride's decision is unchanged |
| `collision.post_knock` | one-shot at the taxi | a bollard or lamp post bent over (`knocked_posts` rises); touching one keeps the guardrail clang |
| `vehicle.bus_doors` | one-shot at the bus | a line bus stopping at a stop, with its air brake |
| `vehicle.bicycle_freewheel` | positional loop | the nearest moving cyclist |
| `vehicle.motorcycle` | positional loop, pitched by speed | the nearest moving motorcycle |
| `vehicle.reverse_beep` | positional loop | the nearest bus, truck or tractor moving backwards |
| `ambient.protest` | positional loop | the nearest protest group |
| `ambient.playground` | positional loop | the nearest playground equipment, 9-20, not deep winter |
| `ambient.construction` | positional loop | the nearest building site's fence, weekdays 7-16 |
| `ambient.campfire` | positional loop | the nearest fire pit, tent or caravan, 19-01 outside winter |
| `ambient.biergarten` | positional loop | the nearest beer garden, from 15 outside winter |

The site loops (`site_sounds.gd`) look only at the listener's chunk and its eight
neighbours, twice a second. Indoors the Environment bus gets a 500 Hz low-pass
and -8 dB (`audio_manager.set_indoors`): ambience, weather and sport sound
through the walls. Listening review of the new files is **pending**.
