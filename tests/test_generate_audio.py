"""tools/generate_audio.py post-processing and job selection (no GPU needed)."""
import numpy as np

from tools.generate_audio import CATALOG, generation_seconds, jobs, make_loop, process, seed_for, trim_silence

SR = 1000


def test_one_shot_is_trimmed_faded_normalised_and_mono():
    quiet = np.zeros((300, 2))
    burst = np.full((200, 2), 0.25)
    clip = process(np.concatenate([quiet, burst, quiet]), SR, loop=False, channels=1)
    assert clip.shape[1] == 1
    assert len(clip) < 300  # the silent ends are gone (a little padding stays)
    assert clip[0, 0] == 0.0 and abs(clip[-1, 0]) < 1e-9  # faded, no click
    assert np.isclose(np.abs(clip).max(), 10 ** (-1 / 20))  # -1 dBFS peak


def test_loop_end_runs_into_its_start():
    t = np.arange(4000) / SR
    audio = np.stack([np.sin(2 * np.pi * 3.3 * t)] * 2, axis=1)  # 3.3 Hz: no natural loop point
    looped = make_loop(audio, SR, crossfade_s=0.5)
    assert len(looped) == 4000 - 500
    # The sample after the last one is the first: its step is like any other.
    assert abs(looped[0, 0] - looped[-1, 0]) < 3 * np.abs(np.diff(looped[:, 0])).max()


def test_silence_stays_silence():
    assert len(trim_silence(np.zeros((100, 1)), SR)) == 100


def test_every_planned_file_is_a_job_with_a_stable_seed():
    import json

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    planned = [e for g in catalog["groups"].values() if "generation" in g for e in g["files"]]
    todo = jobs(catalog, force=True)
    assert len(todo) == len(planned) and planned
    assert len({seed_for(e["id"]) for _, _, e in todo}) == len(todo)
    assert jobs(catalog, groups={"weather.thunder"}, force=True)[0][0] == "weather.thunder"
    assert generation_seconds([3.0, 8.0], loop=False) == 8.5
