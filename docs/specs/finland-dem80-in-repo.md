# Finland dem80 in the repo

## Goal
Ship the whole of Finland as 80 m Copernicus dem80 tiles inside the package. The game loads
them first. A missing or corrupt tile leaves that area flat and logs one error.

## Tiles (checked 2026-11-14 with HTTP HEAD on copernicus-dem-30m.s3.amazonaws.com)
- Finland is about 59.8-70.1 N and 19-31.6 E, so the tiles are N59..N70 x E019..E031:
  12 x 13 = 156 names, `Copernicus_DSM_COG_10_N{lat}_00_E0{lon}_00_DEM`.
- 155 return 200. Missing: N61E019 (404, open sea in the Bothnian Sea). Other sea-only tiles
  may also be missing in later releases; `fetch_copernicus` already skips 403 and 404 as sea.
- Download size (sum of Content-Length): 2,722,507,959 bytes (about 2.7 GB). The download stays
  in the cache (`~/.cache/copernicus-dem30`) and is never committed.
- Output estimate: the EPSG:3067 bbox `50000,6600000,740000,7800000` holds about 34 x 59 dem80
  tiles. The Oulu set is 16 tiles and 548 KB (about 34 KB per tile), so the full set is at most
  about 70 MB, and less because all-NoData sea tiles are smaller or skipped. This fits plain git
  without LFS. The implementer measures the real output bytes and the conversion time
  (`/usr/bin/time -v`) and writes both into docs/dem-finland-80m.md.

## Files to change
- `tools/dem80.py`: add `FINLAND_BBOX = (50000, 6600000, 740000, 7800000)` and the
  `--bbox finland` alias. Reuse `fetch_copernicus` and `convert_copernicus`. Convert in
  latitude strips if memory needs it. `index_for` already writes COP_ATTRIBUTION into dem80.json.
- `src/theroadragetrip/assets/dem80/`: the committed `dem80.json` and `dem80_<i>_<j>.bin` files.
  `[tool.setuptools.package-data]` `"assets/**/*"` in pyproject.toml already ships them, so
  pyproject needs no change.
- `src/theroadragetrip/osm/elevation.py`:
  - `dem80_dirs()` appends the packaged `Path(__file__).parent.parent / "assets" / "dem80"` last,
    after the cache dir and $THEROADRAGETRIP_DEM80_DIR, so a local override still wins.
  - `Dem80._load` catches ValueError/OSError from `decode_tile` (a corrupt tile) and returns None.
    It logs one `logging.error` per tile, at most once per process (a set of reported tiles).
  - Keep `missing_ground_message` for a missing or invalid index: flat ground everywhere.
- `Makefile`: `dem80-windows` stays as it is. The packaged copy makes it optional.

## Behaviour / acceptance
1. With an empty XDG_DATA_HOME and no env var, `load_ground(..., dem80_enabled=True)` returns
   the packaged Dem80.
2. The packaged dem80.json passes `validate_index` and contains COP_ATTRIBUTION.
3. The height at Oulu city centre (65.0121 N, 25.4682 E, projected to EPSG:3067) is not None,
   and the 1 km ring around it is not flat (max - min > 1 m).
4. A missing tile gives `height_m` None for that area, which renders flat ground. There is no exception.
5. A corrupt tile (bad crc) gives None for that area, one ERROR log line naming the file, and no
   repeat on the next sample. Godot shows the server log error in its console the same way the
   existing no-DEM error does.
6. A missing or corrupt dem80.json makes the ground flat everywhere and logs the existing
   missing-ground error once.

## Tests to add (tests/test_elevation.py)
- `test_packaged_dem80_loads_and_validates`: fails while the assets are absent or dem80_dirs lacks the packaged path.
- `test_packaged_dem80_oulu_centre_not_flat`: fails if the tiles are flat, empty or misplaced.
- `test_dem80_missing_tile_is_flat`: uses a tmp copy with one tile deleted and expects None.
- `test_dem80_corrupt_tile_logs_once_and_is_flat`: uses a tmp copy with one tile's bytes flipped. It
  fails today, because `decode_tile` raises ValueError out of `height_m`.

## Commands
    .venv/bin/python tools/dem80.py download --source copernicus --bbox finland --out ~/.cache/copernicus-dem30
    /usr/bin/time -v .venv/bin/python tools/dem80.py convert --source copernicus --bbox finland \
        ~/.cache/copernicus-dem30/*.tif --out src/theroadragetrip/assets/dem80
    du -sb src/theroadragetrip/assets/dem80
    make check
    XDG_DATA_HOME=$(mktemp -d) make godot-test

## Out of scope
- Git LFS, MML KM10 data, physics use of the heights, and changes to make dem80-windows.
- Sea-only tiles are not filled in. NoData stays flat.

## Status
- Done: 155 land tiles packaged under `src/theroadragetrip/assets/dem80/` (124 MB of plain git files,
  no LFS). Regenerating the set would add another 124 MB to git history.
- Cold-tile first decode costs about 47 ms per 20 km tile. This is a one-time hitch on first load.
- Packaged DEM is looked up last; a missing or corrupt tile is flat with one logged error.
- Per-tile lookup (ddc846fa): each dem80 tile comes from the first folder that has it (cache, env,
  then packaged). Sysmä gets terrain (80.78 m) where only the packaged set covers it. The cache
  still wins for tiles it holds. A corrupt cache tile gives flat ground, not the packaged tile (by design).
- Tester verdict: PASS, with the follow-up fixes (tests, licence notice, credits line).
