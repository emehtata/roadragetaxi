# 80 m DEM terrain (experimental)

Brief: [dem-finland-80m.md](dem-finland-80m.md). Spec: [specs/dem-terrain-80m-prototype.md](specs/dem-terrain-80m-prototype.md).

The game shows ground heights from an 80 m height raster, for display only.
The Python server samples the raster into each chunk's `ground_heights`, and
Godot draws it. Collision and the simulation do not change.

## Source and licence

This prototype uses **Copernicus WorldDEM-30 (GLO-30 Public)**, a **surface
model (DSM)**. It is not a bare-ground model: its heights include buildings,
trees and other objects. See "DSM excess" below.

Attribution (adapted data). It is also shown in the in-game credits, i18n key
`credits_terrain`:

> produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved

- Citation: ESA, Copernicus DEM, https://doi.org/10.5270/ESA-c5d3d65.
- Licence: GLO-30 Public is free to use for the general public under the
  Copernicus DEM licence. The notice above was checked on the COP-DEM
  collection page on dataspace.copernicus.eu on 2026-11-14.
- The 10 m European tiles (EEA-10) are not used, because only eligible users
  may use them.

**MML KM10 is not used in this prototype.** It is a ground model (DTM), so it
is the better source once an MML API key exists. `tools/dem80.py download`
(the MML default) and `convert` remain for that. Its attribution would then
replace the one above.

## Switch

Off by default. To turn it on, set `game.terrain_dem80 = true` in the
settings file; Godot then passes `--terrain-dem80` or `--no-terrain-dem80` to
the server. You can also pass the server flag directly. When the switch is off
or there is no `<cache>/dem80/`, the game uses the old `<city>.dem.json` if it
exists, else flat ground.

The top-down 3D camera keeps its height above the ground under the taxi
(`Buildings3D.ground_elevation`, from `map_layer.deck_height`). With DEM ground,
each chunk's base ground and road meshes are split into triangles no longer
than 20 m before they are lifted onto the terrain (`Buildings3D.subdivide`).
Their mm layer gaps are widened ×20, so the roads stay above the landuse
layers. These changes apply to rendering only.

## Copernicus download and conversion (no key)

    .venv/bin/python tools/dem80.py download --source copernicus --out ~/.cache/copernicus-dem30
    .venv/bin/python tools/dem80.py convert --source copernicus ~/.cache/copernicus-dem30/*.tif --out ~/.cache/RoadRageTrip/dem80

The tool picks the 1x1 degree tiles by bbox from the public bucket
`copernicus-dem-30m.s3.amazonaws.com`. The tiles are COGs in EPSG:4326 with
EGM2008 heights. Each tile's CRS geokey and its bounds are checked against
the file name. Copernicus tiles have no NoData tag. The sea has no tiles,
and the coast reads 0 m.

For each EPSG:3067 10 m cell, the tool takes the nearest Copernicus cell. Each
80 m sample is then the mean of its 8×8 cells, NoData skipped. The default
bbox is Oulu (EPSG:3067 400000,7180000 to 460000,7240000).

## MML KM10 (later; needs a free MML API key)

    export MML_API_KEY=...   # never commit or print it
    .venv/bin/python tools/dem80.py download --out km10/
    .venv/bin/python tools/dem80.py convert km10/*.tif --out <cache>/dem80 --source-date MM/YYYY

- Without the key, `download` stops and fetches nothing.
- With the key, it only lists the OGC API processes. The process id, the
  sheet tiling and the NoData tag must be checked before a download job is
  added.
- `convert` stitches the sheets on the 10 m grid before taking the means, and
  reads each file's own `GDAL_NODATA` tag.

## Format

**Tiles.** `dem80_<i>_<j>.bin` covers x from `i*20480` and y from `j*20480`
(EPSG:3067). Sample `(c, r)` is centred at `x0 + 40 + 80c`, `y0 + 40 + 80r`.

- Header (little-endian `<4sHiiHffhI`): magic `RRD1`, version 1, i, j, size
  256, step 80, scale 0.1, nodata -32768, and the crc32 of the raw data.
- Data: zlib-compressed int16[256*256], rows along +y.
- Height in metres = value × 0.1. NoData never becomes 0 m.

**Index.** `dem80.json` holds the CRS, vertical datum, step, tile size, scale,
nodata, the tile list with bounds, the source files, the source date and the
attribution.

**Loader.** `osm/elevation.py` `load_dem80` / `Dem80.height_m`: bilinear,
`None` for NoData.

## Oulu measurements (2026-11-14)

- Copernicus tiles: N64 and N65, each with E024, E025 and E026.
- Download: 113,366,598 bytes in 5.4 s.
- Output: 16 tiles (`dem80_19_350` to `dem80_22_353`), 545,036 bytes plus a 3 kB index.
- Raw int16: 2,097,792 bytes, so the compression ratio is 3.85.
- Conversion: 8.1 s, 468 MB peak RSS.
- A rerun gives byte-identical output.

## DSM excess

The table compares terrain height at 20 m sample points, by OSM class, with
the median of the open-ground samples within 200 m. The areas are 2 km
squares.

| spot | class | samples | mean excess | max excess |
|---|---|---|---|---|
| East hill (453249, 7201078) | buildings | 3 | 0.33 m | 1.91 m |
| East hill | forest | 3810 | 0.69 m | 7.66 m |
| City centre (427804, 7210711) | buildings | 1365 | 0.96 m | 9.00 m |
| City centre | forest | 394 | 1.35 m | 5.26 m |

The 80 m mean has already smoothed most of the objects out: the mean excess
is about 1 m or less. The measure also includes the natural slope within
200 m.

**Choice: (a)** use the DSM as ground and record the excess as a known
limitation. Lowering the terrain under OSM footprints, option (b), needs a
polygon test per ground sample. That belongs in `map_chunks` on the server,
or in a per-vertex polygon test on the client. Neither is a simple
render-only rule. KM10 removes the excess.

## Reproduce

Run the same sources with the same command: the output files are
byte-identical. Check with `sha256sum <cache>/dem80/*`.

- Tests: `tests/test_dem80.py`, `tests/test_elevation.py` and
  `godot/tests/dem_terrain.gd`.
- Visual scenarios: `terrain_oulu_dem80` (terrain on, readiness check
  `dem_ground`) and `terrain_oulu_dem80_off`, both from the same pose.

## Pending

- The MML KM10 download (needs the key).
- Load ms, FPS and vertex counts for the terrain on and off.
