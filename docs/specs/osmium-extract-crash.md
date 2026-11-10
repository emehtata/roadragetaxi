# Osmium extract must never crash the game

## Goal
With osm_source=pbf, any osmium or extract failure (missing binary, bad output, OOM, kill) must surface as `PbfUnavailable` (Overpass fallback plus HUD notice, per e58d3924), never an unhandled exception or a dead server. Not reproduced here (no Finland PBF in the checkout); the causes below come from code reading, so confirm each with its test first.

## Observed symptom / likely root causes
1. `src/theroadragetrip/osm/pbf_source.py:189` catches only `RuntimeError`. Other failures escape `fetch_osm_ways_from_pbf` and `world_loader._use_pbf` (`world_loader.py:80`, catches only `PbfUnavailable`). They kill the fetch or tile stream and can wedge `_wait_for_active_tile_fetch`:
   - `OSError` / `FileNotFoundError` / `PermissionError` from `subprocess.run` (`pbf_source.py:236`) when osmium vanishes or is not executable after the `osmium_command()` check.
   - `xml.etree.ElementTree.ParseError` from `_parse_osm_xml` (`pbf_source.py:244`) on truncated output, for example when osmium is killed by the OOM killer while writing. The extract goes to a tmpdir.
   - `MemoryError` from building the whole element list (`pbf_source.py:199-206`).
2. `pbf_source.py:112-117` and `101-122`: the background cell cut (`build_cells_for` -> `_extract_cell`, `pbf_index.py:194-210`) has no timeout. It runs concurrently with the foreground whole-file `osmium extract` (`pbf_source.py:197-198`). The comment at lines 101-104 says two smart cuts need several GB of RAM, but the single-cut guard only serialises cuts against each other, not against the foreground extract. Together they can trigger the OOM killer, which takes the game or server down on small machines and WSL.
3. `pbf_index.py:95-110` (`_source_bbox`): `check=True` and `json.loads` raise `CalledProcessError` / `KeyError`. This is safe only because it runs in the cut thread. Any future synchronous caller would crash.
4. Makefile `index-pbf` (line ~84) hardcodes `src/theroadragetrip/assets/osm/finland-latest.osm.pbf`. That directory does not exist in a fresh checkout, so the target fails with an osmium or Python traceback instead of an actionable message. `install-osmium` (line ~87) is Linux apt/Darwin brew only.

## Files to change
- `src/theroadragetrip/osm/pbf_source.py`: widen the handler at 189 to map `OSError`, `ET.ParseError` and `MemoryError` to `PbfUnavailable("osmium_failed", ...)` with a short detail. Give the background cut a memory guard: skip or defer it while a foreground extract runs.
- `src/theroadragetrip/utils/pbf_index.py`: add a timeout to the `subprocess.run` calls at 95, 104 and 205. Wrap `_source_bbox` failures in `RuntimeError`. Clean temp files on any exit.
- `Makefile`: `index-pbf` checks the file exists and prints how to download it (or takes `PBF=`).
- `tests/test_pbf_source.py`, `tests/test_pbf_index.py`: new tests below.

## Acceptance criteria
1. A missing or non-executable osmium at run time (`subprocess.run` raises `OSError`) gives `PbfUnavailable(reason="osmium_failed")`, and the Overpass fallback runs with `data_source_notice` set.
2. Truncated or invalid osmium output (`ET.ParseError`) gives the same `PbfUnavailable`; the tmpdir is removed.
3. A killed osmium (return code -9 or 137) gives `PbfUnavailable` with the exit code in the detail.
4. The background cell cut and a foreground whole-file extract never run at the same time. The cut is retried on a later fetch.
5. `_extract_cell` and `_source_bbox` time out after a bounded wait and never leave `.tmp` files in the index dir.
6. `make index-pbf` with no PBF exits non-zero with one actionable line and no traceback.
7. The server process stays alive and keeps ticking through every case above (traffic decisions stay on the Python server).

## Tests to add
- `tests/test_pbf_source.py::test_oserror_from_osmium_falls_back` - monkeypatch `subprocess.run` to raise `FileNotFoundError`. Today the error propagates uncaught.
- `tests/test_pbf_source.py::test_truncated_osm_xml_falls_back` - fake osmium writes `<osm><node`. Today `ParseError` propagates.
- `tests/test_pbf_source.py::test_sigkilled_osmium_reports_exit_code` - return code -9 with an empty file.
- `tests/test_pbf_source.py::test_cell_cut_deferred_during_foreground_extract` - the cut is not started while an extract holds the guard. Today both run.
- `tests/test_pbf_index.py::test_extract_cell_timeout_cleans_tmp` - `TimeoutExpired` gives `RuntimeError` and no `.tmp` file. Today it raises raw `TimeoutExpired`.
- `tests/test_pbf_index.py::test_source_bbox_bad_json_is_runtimeerror`.
- Run `pytest tests/test_pbf_source.py tests/test_pbf_index.py` (the osmium-gated tests need `make install-osmium`).

## Out of scope
- Changing the grid size, the smart strategy or the index format.
- A streaming parser to replace the in-memory element list (separate memory work).
- Godot HUD changes (the notice from e58d3924 is reused as is).
- Windows bundling of osmium and the `install-osmium` Windows branch.
