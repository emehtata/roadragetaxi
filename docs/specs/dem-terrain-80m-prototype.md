# DEM terrain 80 m prototype (Phase 1 spec)

## Status
- Prototype scope: done with Copernicus WorldDEM-30 (GLO-30) as the test source, because the MML KM10 download is blocked on the MML key. The MML route in this spec is still the target; the MML download and full-area measurements are Pending in docs/dem-terrain-80m.md.
- Copernicus is a surface model (DSM): heights include buildings and trees.
- Copernicus tiles hold the sea as 0 m (a known limit, recorded in docs/dem-terrain-80m.md).

## Goal
Convert MML KM10 GeoTIFFs for the Oulu area into 80 m, 256x256 int16 tiles and feed
them into the existing render-only ground path, so the 3D view shows real terrain. Brief: docs/dem-finland-80m.md.

## Audit findings (section 1)
- World metres are absolute EPSG:3067 (x east, y north): `world_loader.latlon_to_world_metres`, `world_cache.COORDINATE_SYSTEM`, `osm/build.py`. KM10 is EPSG:3067 too, so **no reprojection**.
- A DEM path already exists and is the integration point: `osm/elevation.py` (`Dem`, JSON raster, bilinear `height_m`) is loaded in `server/__init__.py:299` from `<cache>/<city>.dem.json` into `world.dem`; `map_chunks.ChunkIndex._ground_heights` sends a 20 m grid per 500 m chunk (`CHUNK_SIZE_M`, `GROUND_STEP_M`, shared edge samples) as `ground_heights`; `godot/map_chunk.gd` passes it to `buildings_3d.gd ground_height()` (ground mesh, decks, trees, forest). No DEM: key omitted, flat ground.
- Godot does no coordinate conversion of its own for terrain; it uses the server's chunk origin. Simulation stays 2D on the server; ground is render-only.
- `tools/make_dem.py` builds the JSON from an ESRI ASCII grid and maps NoData to 0.0 (violates brief 3.8).
- `Dem.base = height_m(0,0)`: with absolute coords (0,0) is far outside, so it clamps to a raster corner; the "relative to origin" base is effectively arbitrary.
- Water/coast: water polygons are drawn flat; with real heights sea (~0 m N2000) sits near ground level, lakes may be above/below surrounding rendered ground. Risk, checked visually.
- Installed: numpy, pyproj, pillow. No rasterio/GDAL.

## Verified source facts (section 2)
- Product page: https://www.maanmittauslaitos.fi/en/maps-and-spatial-data/datasets-and-interfaces/product-descriptions/elevation-model-10-m
  EPSG:3067, heights N2000 (EPSG:3900), 10 m pixels, GeoTIFF float metres (3 significant decimals) or ASCII grid; negative below sea level; accuracy 1.4 m; updated monthly.
- Licence: CC BY 4.0 (https://www.maanmittauslaitos.fi/en/opendata-licence-cc40). Attribution: licensor, dataset name, delivery time, e.g. "Contains data from the National Land Survey of Finland Elevation model 10 m MM/YYYY".
- Download: MapSite "Download geospatial data", and OGC API Processes https://avoin-paikkatieto.maanmittauslaitos.fi/tiedostopalvelu/ogcproc/v1/ (listed on the product page).
- curl from this machine 2026-11-14: internet works; the OGC endpoint returns `401 WWW-Authenticate: Basic realm="API-key required"`, a bogus `api-key` gives 403. A free MML API key is required (env var `MML_API_KEY`, never committed).
- NOT verified (needs the key): the process id, the sheet tiling of KM10 and the GeoTIFF NoData tag. The implementer reads them from `/processes` and each file's tags; the downloader must read NoData per file (brief: metadata may differ). The Oulu bbox (EPSG:3067, about x 400000-460000, y 7180000-7240000) is mapped to whatever sheets the service returns; the tile grid below is ours, independent of sheets.

## Format decision
One binary file per 256x256 tile, zlib-compressed per tile, read by a ~30-line numpy loader. Not a database, asset system or map-data architecture (brief 11 forbids BIN map data); it is the minimum to store a raster.
- Grid: tile (i, j) covers x0 = i*20480, y0 = j*20480 in EPSG:3067; sample (c, r) centre at x0 + 40 + 80c, rows along +y. Name `dem80_<i>_<j>.bin`.
- Header (little-endian): magic `RRD1`, u16 version, i32 i, i32 j, u16 size=256, f32 step=80, f32 scale=0.1, i16 nodata=-32768, u32 crc32 of raw data; then zlib(int16[256*256]). Height = value*0.1 m (range -3276.7..3276.7, Finland max ~1324 m).
- `dem80.json` index: CRS, step, tile size, list of tiles with bounds, source files, source dates, attribution.
- Resampling: block **mean** of the 8x8 10 m cells (NoData excluded; cell NoData if all 64 missing). Mean, not bilinear: it uses every source sample, no aliasing; bilinear samples 4 of 64. Blocks align to the 10 m grid so no sub-pixel shift. Mosaic source sheets before aggregating so blocks never straddle a seam.

## Files
- `tools/dem80.py` (new): `download(bbox, out_dir, api_key)`, `convert(src_tifs, out_dir, bbox)`; GeoTIFF read with pillow (float32, tags 33550/33922/42113) - no GDAL dependency unless pillow fails, then add `tifffile`.
- `src/theroadragetrip/osm/elevation.py`: `Dem80` with `height_m(x, y) -> float | None`, `load_dem80(dir) -> Dem80 | None` (lazily opens tiles, LRU of a few); keep `Dem` and JSON. Fix `base` to 0 for absolute N2000 (render offset handled by chunk origin).
- `server/__init__.py:299`: prefer `<cache>/dem80/` when present and setting `terrain_dem80` (default on, `--no-terrain` / settings toggle) allows it; else existing JSON; else flat.
- `map_chunks._ground_heights`: NoData sample -> nearest valid neighbour in the chunk, or omit the grid if all missing (never 0 m).
- `tools/visual_scenarios.json`: `terrain_oulu_dem80` on real Oulu coordinates (river mouth + a ridge).
- `docs/dem-terrain-80m.md`: source, licence + attribution, download, conversion, format, measurements, limits, repro steps.

## Acceptance (maps to brief DoD 1-8)
1. `tools/dem80.py download` fetches real KM10 sheets for the Oulu bbox with `MML_API_KEY`; sizes logged. (DoD1)
2. `convert` writes tiles + index covering the bbox; rerun gives byte-identical files. (DoD2, 8)
3. Format documented in the doc above; measured raw vs compressed size and ratio recorded. (DoD3, 7)
4. Godot 3D view in `terrain_oulu_dem80` shows ground matching KM10 (sampled points within 0.5 m of source 80 m mean). (DoD4)
5. Roads/buildings sit on the ground; no offset vs OSM at chosen landmarks. (DoD5)
6. NoData never becomes 0 m; tile and chunk edges share samples, no cracks. (DoD6)
7. Measurements: download size, output size, conversion time, tile load ms, RSS, FPS on/off, vertex count at a fixed camera. (DoD7)
8. Missing `dem80/` or toggle off: rendering identical to today. 

## Tests
- `tests/test_dem80.py`: `test_encode_decode_roundtrip_0p1m` (quantization), `test_nodata_preserved_not_zero`, `test_tile_index_of_point_and_bounds` (incl. negative/edge coords), `test_mean_block_aggregation_excludes_nodata`, `test_boundary_continuity_across_sheets` (two synthetic sheets mosaicked = one sheet converted), `test_header_and_index_metadata_valid` (magic, crc, CRS), `test_conversion_reproducible_bytes`, `test_height_m_matches_tile_sample_at_centres`.
- `tests/test_elevation.py`: `test_ground_heights_no_zero_for_nodata`, `test_server_falls_back_to_flat_without_dem80`.
- Visual: `terrain_oulu_dem80` with readiness checks (docs/visual-testing.md), screenshot inspected, toggled off vs on.

## Risks
- API key required; sheet tiling and NoData tag unverified until a key exists.
- Pillow float32 GeoTIFF reading may fail on compressed/tiled TIFFs -> `tifffile` fallback.
- 80 m ground under 20 m chunk grid flattens embankments; roads may clip into slopes; water polygons flat vs terrain.
- Absolute N2000 heights change camera/deck baseline vs current relative heights.

## Out of scope
Finland-wide streaming, LOD, collision/physics, 2 m data, map architecture changes, water-level rework.
