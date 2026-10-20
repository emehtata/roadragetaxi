# Animal calls

For any sound effect, run `./ai-audio.sh "A crow cawing twice"` from the
repository root. The wrapper uses the sibling ai-audio-studio virtualenv and
saves a uniquely named Ogg file plus prompt/seed metadata in its `outputs/`
directory. It prints the output path when finished. Optional arguments:
`--seconds 4`, `--seed 123`, `--output-dir /tmp/sounds`. Set `AUDIO_STUDIO` if
the studio lives elsewhere. The installed model and a CUDA GPU are required.

Wildlife and owned dogs play short mono Ogg Vorbis calls through the Environment
volume channel. The existing ai-audio-studio Stable Audio Open installation
generates the clips with `generate_game_animals.py` (preserved in this repository
as `tools/generate_animal_audio.py`); `assets/audio/animals/generation.json`
records prompts, seeds, model and durations. Listening review is recorded separately
from successful generation and decoding.

Regenerate one rejected call with the studio virtualenv and
`tools/generate_animal_audio.py src/theroadragetrip/assets/audio/animals --only crow --force --seed-base 82400`.

Eight wildlife species have distinct clips: squirrel, small bird, pigeon, crow,
hare, fox, moose and roe deer. Pedestrians' owned dogs use a dog bark. Calls follow
interpolated source positions and pan in stereo like car stereos. Species-specific
audible ranges run from 30 to 120 metres, with quadratic distance falloff.
Four reusable players bound simultaneous playback. Calls repeat occasionally,
with randomized cooldowns: birds are more frequent than large mammals. Hares
only vocalize when fleeing. These are approximate ambience policies, not a
biological simulation.

Despawned and out-of-range sources stop immediately and release cooldown records.
Underground views and disconnected sessions clear playback. No additional animal
simulation, network messages or collision objects are introduced.

Run `godot --headless --path godot --script res://tests/animal_audio.gd` to check
asset loading, distance falloff, moving sources, bounded players and cleanup.
