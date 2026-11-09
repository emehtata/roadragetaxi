# PBF download progress: throttle and speed

## Goal
The Finland PBF download screen updates progress at ~1 MiB granularity (not every
frame) and shows a smoothed download speed. Download I/O stays off the per-frame hot path.

## Finding (current behaviour)
`Startup._download_pbf` (godot/startup.gd ~1412) loops `await process_frame` and rewrites
the ProgressBar and Label every frame (not every 0.1 MB). The UI cost is small, but
`HTTPRequest` is created with default `use_threads = false`, so the body is pumped on the
main thread once per frame (`download_chunk_size` default 64 KiB): throughput is bounded
by frame rate and by whatever else runs that frame. Threaded HTTPRequest removes that cap.
Measure before/after (see tests) rather than assume.

## Files to change
- godot/startup.gd: in `_download_pbf` set `request.use_threads = true` (and a larger
  `download_chunk_size`, e.g. 1 MiB, if the bench shows a gain); replace the per-frame
  UI write with a throttled one; show speed in `progress_text`.
- godot/startup.gd: add pure static helpers (testable, no node access):
  `static func download_should_refresh(downloaded: int, last_shown: int, now_ms: int, last_ms: int) -> bool`
  `static func download_speed(prev_bps: float, delta_bytes: int, delta_s: float) -> float`
  `static func download_text(downloaded: int, total: int, bps: float) -> String`
- godot/i18n.gd: only if a localized unit label is needed (fi/en/de); otherwise none.
- godot/tests/run_tests.gd: tests below.

## Behaviour / acceptance criteria
1. The ProgressBar value and label are rewritten only when downloaded bytes crossed a new
   whole MiB since the last write, or >= 1000 ms passed since it (so slow links still
   tick), or on the first sample. `download_should_refresh` encodes this.
2. Label shows `X.Y / Z.Z MiB  -  N.N MiB/s` (total known) or `X.Y MiB  -  N.N MiB/s`
   (total unknown). Granularity of the MiB figure is 1 MiB (no sub-MiB flicker).
3. Speed is an exponential moving average of bytes/s over the sampled intervals
   (alpha ~0.2, seeded by the first interval); `delta_s <= 0` returns `prev_bps` unchanged.
4. Before the first speed sample (or stalled for >3 s) the speed part reads `-- MiB/s`.
5. `get_downloaded_bytes()` / `get_body_size()` are still polled at most once per frame
   (cheap getters), but no Control property is set on frames that do not refresh.
6. The download uses a threaded HTTPRequest; no file I/O or byte copying of the body in
   GDScript (keep `download_file = partial`).
7. Completion, failure, retry, `.part` cleanup and `replace_download` behave as before.
8. Real download of the PBF reaches at least the throughput of the old code on the same
   link (tester: compare wall time or MiB/s over the first 30 s; must not be slower).
9. Screenshot of the download screen inspected, showing bar, MiB count and speed (use a
   local slow HTTP server serving a large file via a temporary URL override if needed).

## Tests to add (godot/tests/run_tests.gd, next to the `download_percent` check ~line 2125)
- `startup download refresh throttle`: false for +0.1 MiB and <1 s; true at +1 MiB; true at
  1 s with +10 KiB; true on first sample. Fails without `download_should_refresh`.
- `startup download speed smoothing`: constant 2 MiB/s input converges to ~2 MiB/s; a one-off
  spike moves the EMA by <= alpha*spike; zero delta_s leaves it unchanged.
- `startup download text`: exact strings for known total, unknown total, and no-speed case.

## Out of scope
- Resume of partial downloads, mirrors, checksum verification.
- The Python-side `progress_callback` for tiles/PBF index (server/map_sync.py).
- Overpass downloads, cancel button, ETA display.
