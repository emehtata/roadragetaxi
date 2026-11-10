# Spec: osm_source=pbf falls back to Overpass with a clear player notice

## Goal
Restore the fallback removed in 3e2c6a19, but tell the player in the game UI WHY the
local extract was not used and WHAT to do. A log-only warning is not enough.

## Files to change
- `src/theroadragetrip/osm/pbf_source.py`: add `pbf_unavailable_reason(pbf_path=None) -> Optional[str]`
  returning `"osmium_missing"`, `"pbf_missing"` or None (reuse the checks in
  `fetch_osm_ways_from_pbf`/`local_pbf_available`). Add `class PbfUnavailable(Exception)` carrying `reason`
  and `path`; raise it from the two existing checks (osmium failure = reason `"osmium_failed"`,
  wrap the RuntimeError from `_extract_elements`).
- `src/theroadragetrip/world_loader.py` `resolve_osm_fetch_func`: in `_use_pbf`, catch `PbfUnavailable`,
  `logger.warning`, record the notice once (below), then call the Overpass fetch.
- `src/theroadragetrip/localization.py`: keys `pbf_fallback_osmium_missing`, `_pbf_missing`,
  `_osmium_failed` in fi, en, de (SUPPORTED_LANGUAGES). Text = reason + action + "using Overpass for now".
- `src/theroadragetrip/protocol.py` (state snapshot, near `notification_msg` ~l.691): add
  `data_source_notice` (localized string, "" when none).
- `godot/hud.gd` (+ its scene if a label is needed): show `data_source_notice` as a banner until the
  first map load completes, then ~15 s (see criterion 7; `main.gd` passes `map_ready`); reuse the `notice` label/style path (l.235, 280).
- `src/theroadragetrip/config.py` l.108-114: update comment (fallback + notice, not "map loading fails").
- `tests/test_pbf_source.py`: replace `test_pbf_request_never_silently_falls_back_to_overpass`.
- `tools/visual_scenarios.json`: add `pbf_fallback_notice_day` (server arg forcing `--osm-source pbf`
  with a nonexistent `--osm-pbf-path`; readiness: notice text visible).

## Behaviour / acceptance criteria
1. osm_source=pbf, osmium absent: data is fetched from Overpass (fallback happens) and no exception escapes.
2. osm_source=pbf, extract file missing at the configured/default path: same fallback.
3. osmium present but `osmium extract` fails/times out: same fallback, reason `osmium_failed`.
4. Each reason yields a different notice. Required text content:
   - osmium_missing: says osmium-tool is not installed/not on PATH; `apt/brew/conda install osmium-tool`
     (Windows: bundled osmium missing, reinstall/run tools/run-windows.ps1); or set osm_source to overpass.
   - pbf_missing: includes the resolved path and names the file and its folder ("put finland-latest.osm.pbf into
     the folder <dir>", from osm_pbf_path or the default path), or set `osm_pbf_path`, or use overpass.
   - osmium_failed: says osmium failed (short stderr tail), check the file is a valid .osm.pbf.
5. Notice is localized via `tr()` for fi, en, de (language from the session, same as `notification_msg`).
6. Emitted once per server session per reason (not per tile, not per retry); repeat fallbacks only log.
7. The snapshot carries `data_source_notice` and the HUD renders it readable (not truncated, wraps). It stays
   up while the first map load runs (server `map_loading` not "" or the client's chunk queue not yet empty with
   a chunk loaded), then ~15 s more, so a slow first load cannot hide it. (Changed from a fixed ~15 s from the
   first state: measured in pbf_fallback_notice_day on llvmpipe, the window expired before the scene was ready.)
8. osm_source=overpass and a working pbf: no notice, no fallback, no behaviour change.
9. Scope: startup load AND tile streaming both go through `resolve_osm_fetch_func`, so both are covered;
   the notice is session-scoped so streaming does not re-raise it.

## Tests to add
- `tests/test_pbf_source.py::test_pbf_osmium_missing_falls_back_with_notice` (replaces the 3e2c6a19 test):
  osmium absent -> fake Overpass fetch called, notice reason `osmium_missing`. Fails without the fix (raises).
- `::test_pbf_file_missing_falls_back_with_path_in_notice`: notice contains the path.
- `::test_pbf_osmium_failure_falls_back`: patched `_extract_elements` raises RuntimeError.
- `::test_pbf_fallback_notice_emitted_once`: two fetches, one notice.
- `tests/test_localization.py` (or existing key-parity test): the three keys exist in fi/en/de.
- `tests/test_protocol*.py`: snapshot contains `data_source_notice` after a fallback.
- Visual: run `pbf_fallback_notice_day` via godot-shot per docs/visual-testing.md, inspect the screenshot
  (readiness must pass; text visible, not clipped).

## Out of scope
- Auto-installing osmium or downloading the extract.
- A Settings toggle UI (the text only names the setting).
- Falling back from Overpass to pbf; changing cache behaviour; non-pbf fetch errors.
