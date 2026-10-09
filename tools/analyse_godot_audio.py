"""Measure the Godot client's sound output, phase by phase, from its
--audiotest run (godot/audio_test.gd records each phase's Master-bus mix
to its own WAV and logs it as an "AUDIOTEST phase {...}" line).

    python tools/analyse_godot_audio.py <godot log>

Per phase: RMS dBFS per channel (after the first 0.4 s: fades, onsets),
left-right balance (panning), peak, and spectral centroid (rises with pitch).

An OS-level recording (WSLg: ffmpeg -f pulse -i RDPSink.monitor) proves the
sound reaches the system, but can't be cut into phases: the WSLg sink drops
idle stretches and its latency varies by seconds.
"""

import json
import sys
import wave

import numpy as np


def levels(path: str):
    with wave.open(path) as recording:
        rate, channels = recording.getframerate(), recording.getnchannels()
        samples = np.frombuffer(recording.readframes(recording.getnframes()), dtype=np.int16)
    return rate, samples.reshape(-1, channels).astype(np.float64) / 32768.0


def dbfs(block) -> float:
    rms = float(np.sqrt(np.mean(block ** 2))) if len(block) else 0.0
    return 20.0 * np.log10(rms) if rms > 1e-6 else -120.0


def centroid_hz(block, rate: int) -> float:
    """Spectral centroid of the mono mix - rises with the engine's pitch."""
    mono = block.mean(axis=1)
    if len(mono) < 2 or not np.any(mono):
        return 0.0
    spectrum = np.abs(np.fft.rfft(mono))
    return float((np.fft.rfftfreq(len(mono), 1.0 / rate) * spectrum).sum() / spectrum.sum())


def main() -> None:
    phases = [json.loads(line.split("AUDIOTEST phase ", 1)[1]) for line in open(sys.argv[1]) if "AUDIOTEST phase " in line]
    print(f"{'phase':20s} {'seconds':>7s} {'left dBFS':>10s} {'right dBFS':>11s}  {'L-R dB':>6s}  peak  centroid Hz")
    for phase in phases:
        try:
            rate, audio = levels(phase["file"])
        except FileNotFoundError:
            print(f"{phase['phase']:20s} (no recording)")
            continue
        block = audio[int(0.4 * rate):]
        left, right = dbfs(block[:, 0]), dbfs(block[:, -1])
        print(f"{phase['phase']:20s} {len(audio) / rate:7.1f} {left:10.1f} {right:11.1f}  {left - right:6.1f}"
              f"  {np.abs(block).max() if len(block) else 0:.2f}  {centroid_hz(block, rate):8.0f}")


if __name__ == "__main__":
    main()
