"""Generate the game's sound effects from the audio catalog with Stable Audio Open.

Reads src/theroadragetrip/assets/audio/audio_catalog.json, generates every
file whose status is "planned", post-processes it (trim silence, fades,
peak normalisation, seamless loop crossfade, mono for one-shots), writes it
as OGG Vorbis and records the result back into the catalog after each file,
so an interrupted run resumes where it stopped.

Run with the ai-audio-studio virtualenv (it has torch, diffusers and the
downloaded model):

    /home/ubuntu/work/ai-audio-studio/.venv/bin/python tools/generate_audio.py
    ... --dry-run                      # list what would be generated
    ... --group weather.thunder        # one group (repeatable)
    ... --priority required            # only these priorities (repeatable)
    ... --force                        # regenerate files already generated
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import zlib
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "src" / "theroadragetrip" / "assets" / "audio" / "audio_catalog.json"
MODEL_ID = "stabilityai/stable-audio-open-1.0"
STEPS = 100
PEAK_DBFS = -1.0
SILENCE_DB = -45.0  # below the peak: trimmed from the ends of one-shots
LOOP_CROSSFADE_S = 1.0
CLIP_LEVEL = 0.999


# -- post-processing (pure numpy, tested in tests/test_generate_audio.py) ---

def trim_silence(audio: np.ndarray, sample_rate: int, threshold_db: float = SILENCE_DB, pad_s: float = 0.02) -> np.ndarray:
    """Cut leading/trailing parts quieter than threshold_db below the peak.
    audio is (samples, channels)."""
    level = np.abs(audio).max(axis=1)
    peak = level.max()
    if peak <= 0.0:
        return audio
    loud = np.flatnonzero(level >= peak * 10 ** (threshold_db / 20.0))
    pad = int(pad_s * sample_rate)
    return audio[max(0, loud[0] - pad):min(len(audio), loud[-1] + pad + 1)]


def fade(audio: np.ndarray, sample_rate: int, fade_in_s: float = 0.005, fade_out_s: float = 0.05) -> np.ndarray:
    audio = audio.copy()
    fade_in = min(len(audio), int(fade_in_s * sample_rate))
    fade_out = min(len(audio), int(fade_out_s * sample_rate))
    if fade_in:
        audio[:fade_in] *= np.linspace(0.0, 1.0, fade_in)[:, None]
    if fade_out:
        audio[-fade_out:] *= np.linspace(1.0, 0.0, fade_out)[:, None]
    return audio


def make_loop(audio: np.ndarray, sample_rate: int, crossfade_s: float = LOOP_CROSSFADE_S) -> np.ndarray:
    """Seamless loop: the tail is crossfaded into the head and dropped, so
    the last sample runs straight into the first (equal-power fade)."""
    n = min(int(crossfade_s * sample_rate), len(audio) // 3)
    if n <= 0:
        return audio
    t = np.linspace(0.0, np.pi / 2.0, n)[:, None]
    looped = audio[:-n].copy()
    looped[:n] = audio[:n] * np.sin(t) + audio[-n:] * np.cos(t)
    return looped


def normalize(audio: np.ndarray, peak_dbfs: float = PEAK_DBFS) -> np.ndarray:
    peak = np.abs(audio).max()
    return audio if peak <= 0.0 else audio * (10 ** (peak_dbfs / 20.0) / peak)


def process(audio: np.ndarray, sample_rate: int, loop: bool, channels: int) -> np.ndarray:
    """(samples, channels) float from the model -> finished clip."""
    if channels == 1:
        audio = audio.mean(axis=1, keepdims=True)
    if loop:
        audio = make_loop(audio, sample_rate)
    else:
        audio = fade(trim_silence(audio, sample_rate), sample_rate)
    return normalize(audio)


def metrics(raw: np.ndarray, audio: np.ndarray, sample_rate: int) -> dict:
    """Checks for the catalog: clipping in the raw generation, how much was
    near-silent, loudness of the result."""
    rms = float(np.sqrt(np.mean(audio ** 2)))
    raw_level = np.abs(raw).max(axis=1)
    return {
        "duration_s": round(len(audio) / sample_rate, 3),
        "raw_clipped_samples": int(np.count_nonzero(np.abs(raw) >= CLIP_LEVEL)),
        "raw_silent_fraction": round(float(np.mean(raw_level < raw_level.max() * 10 ** (SILENCE_DB / 20.0))), 3)
        if raw_level.max() > 0 else 1.0,
        "rms_dbfs": round(20.0 * np.log10(rms), 1) if rms > 0 else None,
    }


def seed_for(file_id: str) -> int:
    """Stable per file, so a regeneration of one file is reproducible."""
    return zlib.crc32(file_id.encode())


def generation_seconds(duration_s: list, loop: bool) -> float:
    """Generate a little longer than the longest wanted length: one-shots
    lose their silent ends, loops lose the crossfade."""
    longest = max(duration_s)
    return min(47.0, longest + (LOOP_CROSSFADE_S + 0.5 if loop else 0.5))


def jobs(catalog: dict, groups=None, priorities=None, force: bool = False) -> list:
    """(group id, group, file entry) for every file to generate."""
    selected = []
    for group_id, group in catalog["groups"].items():
        if groups and group_id not in groups:
            continue
        if priorities and group["priority"] not in priorities:
            continue
        if "generation" not in group:
            continue  # existing asset only
        for entry in group["files"]:
            if force or entry["status"] != "generated":
                selected.append((group_id, group, entry))
    return selected


def save_catalog(catalog: dict) -> None:
    tmp = CATALOG.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(CATALOG)  # never a half-written catalog


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--group", action="append", help="only this group id (repeatable)")
    parser.add_argument("--priority", action="append", help="only these priorities (repeatable)")
    parser.add_argument("--force", action="store_true", help="regenerate files already generated")
    parser.add_argument("--dry-run", action="store_true", help="list the files and exit")
    parser.add_argument("--steps", type=int, default=STEPS, help=f"diffusion steps (default {STEPS})")
    args = parser.parse_args()

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    todo = jobs(catalog, args.group, args.priority, args.force)
    if args.group:
        unknown = set(args.group) - set(catalog["groups"])
        if unknown:
            parser.error(f"unknown group(s): {', '.join(sorted(unknown))}")
    print(f"{len(todo)} file(s) to generate")
    if args.dry_run or not todo:
        for group_id, group, entry in todo:
            print(f"  {entry['file']:<48} {entry['variant']}")
        return 0

    import soundfile as sf
    import torch
    from diffusers import StableAudioPipeline

    if not torch.cuda.is_available():
        print("CUDA is not available - refusing to run Stable Audio on the CPU.", file=sys.stderr)
        return 1
    print(f"Loading {MODEL_ID} on {torch.cuda.get_device_name(0)} ...", flush=True)
    pipe = StableAudioPipeline.from_pretrained(MODEL_ID, torch_dtype=torch.float16).to("cuda")
    pipe.enable_attention_slicing()
    sample_rate = pipe.vae.sampling_rate
    audio_root = CATALOG.parent

    started = time.monotonic()
    failed = []
    for done, (group_id, group, entry) in enumerate(todo):
        elapsed = time.monotonic() - started
        eta = f" ETA {_duration(elapsed / done * (len(todo) - done))}" if done else ""
        print(f"\n[{done + 1}/{len(todo)}] {entry['file']} - {entry['variant']}"
              f"  (elapsed {_duration(elapsed)}{eta})", flush=True)
        prompt = f"{entry['variant']}. {group['generation']['prompt']}"
        seed = seed_for(entry["id"])
        loop = group["loop"]
        channels = catalog["format"]["channels"]["loop" if loop else "one_shot"]
        try:
            with torch.inference_mode():
                raw = pipe(
                    prompt=prompt,
                    negative_prompt=group["generation"]["negative_prompt"],
                    num_inference_steps=args.steps,
                    audio_end_in_s=generation_seconds(group["duration_s"], loop),
                    num_waveforms_per_prompt=1,
                    generator=torch.Generator(device="cuda").manual_seed(seed),
                ).audios[0].T.float().cpu().numpy()
            audio = process(raw, sample_rate, loop, channels)
            path = audio_root / entry["file"]
            path.parent.mkdir(parents=True, exist_ok=True)
            sf.write(path, audio, sample_rate, format="OGG", subtype="VORBIS")
        except Exception as exc:  # one bad file must not lose the whole run
            print(f"  FAILED: {exc}", flush=True)
            failed.append(entry["file"])
            continue
        checks = metrics(raw, audio, sample_rate)
        entry.update({
            "status": "generated",
            "review": "pending",  # speech/music/artifacts need a listen
            "prompt": prompt,
            "seed": seed,
            "steps": args.steps,
            "sample_rate": sample_rate,
            "channels": channels,
            "generated": date.today().isoformat(),
            **checks,
        })
        save_catalog(catalog)
        warn = []
        if checks["raw_clipped_samples"]:
            warn.append(f"{checks['raw_clipped_samples']} clipped samples")
        if checks["raw_silent_fraction"] > 0.5:
            warn.append(f"{checks['raw_silent_fraction']:.0%} near-silent")
        print(f"  ok {checks['duration_s']:.2f}s rms {checks['rms_dbfs']} dBFS"
              + (f"  WARNING: {', '.join(warn)}" if warn else ""), flush=True)

    print(f"\nDone in {_duration(time.monotonic() - started)}: "
          f"{len(todo) - len(failed)} generated, {len(failed)} failed")
    for file in failed:
        print(f"  failed: {file}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
