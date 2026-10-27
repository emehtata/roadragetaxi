"""Generate a sound from a prompt using ai-audio-studio's local Stable Audio model."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import secrets
import sys
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prompt', help='Describe the sound to generate')
    parser.add_argument('--seconds', type=float, default=5.0, help='Duration, 0.5–47 seconds (default: 5)')
    parser.add_argument('--seed', type=int, default=None, help='Repeatable generation seed')
    parser.add_argument('--output-dir', type=Path, default=Path('output'))
    args = parser.parse_args()
    if not args.prompt.strip():
        parser.error('prompt must not be empty')
    if not 0.5 <= args.seconds <= 47:
        parser.error('--seconds must be between 0.5 and 47')
    if args.seed is not None and not 0 <= args.seed < 2**32:
        parser.error('--seed must be between 0 and 4294967295')

    import torch
    import numpy as np
    import soundfile as sf
    from diffusers import StableAudioPipeline
    from generate_audio import process

    if not torch.cuda.is_available():
        parser.exit(1, 'CUDA is unavailable; this generator requires the local GPU.\n')
    model = 'stabilityai/stable-audio-open-1.0'
    negative = 'music, speech, singing, human voices, distortion, clipping'
    seed = args.seed if args.seed is not None else secrets.randbits(32)
    print(f'Generating {args.seconds:g}s, seed {seed}: {args.prompt}', file=sys.stderr, flush=True)
    pipe = StableAudioPipeline.from_pretrained(model, torch_dtype=torch.float16,
                                              local_files_only=True).to('cuda')
    pipe.enable_attention_slicing()
    with torch.inference_mode():
        raw = pipe(prompt=args.prompt, negative_prompt=negative, num_inference_steps=100,
                   audio_end_in_s=args.seconds,
                   generator=torch.Generator(device='cuda').manual_seed(seed)).audios[0].T.float().cpu().numpy()
    rate = pipe.vae.sampling_rate
    if not np.isfinite(raw).all() or np.max(np.abs(raw)) < 1e-6:
        raise RuntimeError('The model generated invalid or silent audio; try another seed.')
    audio = process(raw, rate, loop=False, channels=1)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir.resolve() / f'{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:12]}.ogg'
    sf.write(path, audio, rate, format='OGG', subtype='VORBIS')
    path.with_suffix('.json').write_text(json.dumps({'prompt':args.prompt,'negative_prompt':negative,
        'model':model,'seed':seed,'steps':100,'duration_s':len(audio)/rate,
        'sample_rate':rate,'channels':1,'file':path.name,'review':'listening pending'},indent=2)+'\n')
    print(path)


if __name__ == '__main__':
    main()
