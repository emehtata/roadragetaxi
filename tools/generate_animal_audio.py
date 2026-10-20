"""Generate Road Rage Taxi animal calls using the studio's local Stable Audio model.

Run with ai-audio-studio/.venv/bin/python tools/generate_animal_audio.py GAME_AUDIO_DIRECTORY.
Existing clips are reused; metadata records prompts, seeds and signal measurements.
"""
import json
from pathlib import Path
import sys

import numpy as np
import soundfile as sf
import torch
from diffusers import StableAudioPipeline

CALLS = {
    'squirrel': 'A red squirrel giving several short dry chattering squeaks, isolated animal call, close field recording',
    'small_bird': 'A Finnish woodland songbird chirping and twittering a short bright phrase, isolated bird call, close field recording',
    'pigeon': 'A wood pigeon softly cooing twice, isolated bird call, close field recording',
    'hare': 'A hare giving a brief high pitched distressed squeal, isolated animal call, close field recording',
    'fox': 'A red fox giving two short hoarse barking calls, isolated animal call, close field recording',
    'moose': 'A moose giving a short deep nasal grunt and snort, isolated animal call, close field recording',
    'roe_deer': 'A roe deer giving two short rough barking alarm calls, isolated animal call, close field recording',
    'dog': 'A medium sized domestic dog barking twice outdoors, isolated natural dog bark, close field recording',
    'crow': 'A hooded crow cawing three times, rough raspy harsh caw caw bird calls, isolated outdoor field recording',
}


def main():
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=True)
    manifest = output/'generation.json'
    records = json.loads(manifest.read_text()) if manifest.exists() else {}
    pipe = StableAudioPipeline.from_pretrained('stabilityai/stable-audio-open-1.0',
                                              torch_dtype=torch.float16, local_files_only=True).to('cuda')
    pipe.enable_attention_slicing()
    rate = pipe.vae.sampling_rate
    for index, (species, prompt) in enumerate(CALLS.items()):
        path = output/f'{species}.ogg'
        if path.exists() and species in records:
            continue
        seed = 62400 + index
        print(f'Generating {species}', flush=True)
        with torch.inference_mode():
            audio = pipe(prompt=prompt + '. No music, no speech, no background noise.',
                         negative_prompt='music, speech, singing, human voices, traffic, distortion, clipping',
                         num_inference_steps=100, audio_end_in_s=4.0,
                         generator=torch.Generator(device='cuda').manual_seed(seed)).audios[0].float().mean(dim=0).cpu().numpy()
        peak = np.max(np.abs(audio))
        if not np.isfinite(audio).all() or peak < 1e-6:
            raise RuntimeError(f'Invalid or silent generation: {species}')
        loud = np.flatnonzero(np.abs(audio) >= peak * 0.01)
        audio = audio[max(0, loud[0]-int(rate*.02)):min(len(audio), loud[-1]+int(rate*.1))]
        audio *= 0.8 / np.max(np.abs(audio))
        fade = min(int(rate*.015), len(audio)//2)
        audio[:fade] *= np.linspace(0,1,fade)
        audio[-fade:] *= np.linspace(1,0,fade)
        sf.write(path, audio, rate, format='OGG', subtype='VORBIS')
        records[species] = {'file':path.name,'prompt':prompt,'seed':seed,'steps':100,
                            'model':'stabilityai/stable-audio-open-1.0','sample_rate':rate,
                            'channels':1,'duration_s':len(audio)/rate,'review':'listening pending'}
        manifest.write_text(json.dumps(records, indent=2)+'\n')
        print(f'Saved {path.name}: {len(audio)/rate:.2f}s', flush=True)


if __name__ == '__main__':
    main()
