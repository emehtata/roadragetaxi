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
