# Task: Prototype Finland-wide 80m elevation terrain for Road Rage Trip

## Objective

Implement an experimental terrain elevation pipeline using the Finnish National Land Survey (Maanmittauslaitos, MML) KM10 elevation dataset.

The initial target is to create a Finland-wide elevation dataset with an effective resolution of 80 metres and integrate a selected test area into the existing Godot 3D renderer.

This is a prototype, not a complete terrain-system rewrite.

The purpose is to establish:
- Whether 80m elevation data is sufficient for large-scale terrain representation.
- Whether the dataset can be converted into a compact format suitable for the game.
- Whether terrain tiles can be loaded efficiently into Godot.
- Whether the terrain aligns correctly with the existing OSM-based world.

## 1. Repository and architecture audit

Before implementation:

1. Inspect the current repository architecture and identify:
   - Godot rendering architecture.
   - Existing coordinate reference systems.
   - World-coordinate conversion.
   - Map chunk dimensions and positioning.
   - Existing terrain, ground and water rendering.
   - Python server and Godot client responsibilities.

2. Identify where terrain rendering can be integrated without disrupting existing functionality.

3. Do not replace the existing map or road rendering system.

4. Do not move simulation responsibilities from the Python server to Godot.

5. Keep the terrain system modular and independently testable.

Write down the findings before implementation.

## 2. Source elevation data

Use Maanmittauslaitos (MML) KM10 elevation data.

Official source:
https://www.maanmittauslaitos.fi/

Find the current official download mechanism and documentation.

Requirements:
- Use the official source.
- Verify the dataset's coordinate reference system.
- Verify elevation units and NoData representation.
- Verify licensing and required attribution.
- Do not assume that all downloadable files use identical metadata.
- Do not invent download URLs.

The tool must support downloading the necessary source tiles automatically where the official service permits it.

For the initial experiment, download enough data to cover the Oulu metropolitan area and its surroundings.

The tool should also support processing additional areas later.

## 3. Conversion pipeline

Implement a reproducible offline conversion tool.

Input:
- MML KM10 GeoTIFF tiles.

Output:
- 80m elevation raster.
- Compact binary tile files suitable for runtime loading.
- Metadata describing geographic coverage, resolution, dimensions and coordinate reference system.

Requirements:

1. Reproject only if necessary. Avoid unnecessary coordinate transformations.
2. Resample from 10m to 80m.
3. Use an appropriate resampling method for terrain elevation. Evaluate average aggregation versus bilinear interpolation and document the choice.
4. Handle missing data and tile boundaries correctly.
5. Avoid introducing artificial elevation discontinuities between neighbouring source tiles.
6. Store elevations as signed 16-bit integers if the vertical range and encoding permit it.
7. Use a documented elevation encoding with a 0.1m quantization step.
8. Preserve NoData separately. Never interpret missing elevation as zero metres.
9. Compress individual output tiles independently.

Do not assume that 16-bit storage automatically saves a particular amount of disk space. Measure actual output sizes.

## 4. Tile format

For the prototype, use tiles containing 256 × 256 elevation samples.

At 80m resolution, each tile covers approximately 20.48 × 20.48 kilometres.

Each tile must:
- Have a stable geographic identity.
- Have clearly defined bounds.
- Include sufficient metadata for positioning.
- Support neighbouring tile loading.
- Avoid visible seams at tile boundaries.

Use a simple, documented binary format. Do not introduce unnecessary dependencies or a complicated asset database.

## 5. Godot integration

Integrate the prototype into the existing Godot 3D renderer.

Requirements:

- Generate terrain geometry from elevation tiles.
- Position terrain using the existing world-coordinate conversion.
- Ensure terrain aligns with existing OSM roads and buildings.
- Support neighbouring tiles.
- Avoid loading the entire country into GPU memory.
- Keep terrain geometry and collision handling separate.
- Avoid unnecessary high-density geometry.
- Use LOD or another suitable approach if needed.

The Python server remains authoritative for simulation and collision decisions.

Godot terrain is initially a visual representation. Do not introduce client-side vehicle physics or collision authority.

Do not break existing rendering when elevation data is missing.

Provide a way to disable the experimental terrain renderer.

## 6. Test area

Use Oulu and surrounding areas as the first test region.

Include:
- Urban terrain.
- Coastal areas.
- Rivers and water.
- Forested terrain.
- Areas with noticeable elevation changes.

Check:
- Terrain alignment with OSM data.
- Coastline and water compatibility.
- Road positioning.
- Building positioning.
- Tile boundaries.
- Elevation accuracy against the original KM10 source.

Do not invent artificial test scenarios. Use actual geographic locations and existing game data.

## 7. Performance measurements

Measure and document:

- Downloaded source data size.
- Converted dataset size.
- Compression ratio.
- Conversion time.
- Tile loading time.
- Memory consumption.
- GPU memory usage if measurable.
- FPS with terrain disabled and enabled.
- Geometry count.

Run repeatable tests using the same camera position, resolution and scene.

Do not optimize blindly. Identify actual bottlenecks.

## 8. Testing and validation

Create automated tests for:

- Elevation encoding and decoding.
- NoData handling.
- Tile coordinate calculations.
- Tile boundary continuity.
- Geographic positioning.
- Metadata validation.
- Reproducibility of conversion.

Include a visual test scene or a suitable existing game scene.

Verify that neighbouring tiles do not produce cracks or elevation jumps.

## 9. Documentation

Create documentation covering:

- Data source and licensing.
- Download procedure.
- Conversion procedure.
- Binary tile format.
- Coordinate system.
- Elevation encoding.
- Godot integration.
- Performance measurements.
- Known limitations.
- Instructions for reproducing the experiment.

Include the required MML attribution.

## 10. Agent workflow

Use the existing spec-writer, implementer and tester workflow.

Spec-writer:
- Inspect the architecture.
- Identify technical risks.
- Define the implementation specification.
- Explicitly identify integration points.

Implementer:
- Implement the conversion pipeline.
- Implement tile storage.
- Integrate terrain into Godot.
- Preserve existing functionality.

Tester:
- Independently verify conversion accuracy.
- Test geographic alignment.
- Test tile boundaries.
- Measure performance.
- Check that the implementation does not introduce regressions.

The tester must not merely confirm that the implementation works. It must actively look for incorrect coordinate transformations, elevation offsets, missing-data artifacts and rendering problems.

## 11. Scope restrictions

- Do not download the complete 2m dataset.
- Do not implement the entire Finland-wide runtime terrain streaming system yet.
- Do not redesign the existing map architecture.
- Do not change Python simulation responsibilities.
- Do not introduce BIN technology as a map-data architecture.
- Do not remove existing rendering features.
- Do not introduce unrelated visual improvements.

Keep the implementation focused on proving the 80m elevation pipeline.

Use atomic commits. Pushing the working branch is permitted.

Do not create Git tags.

## 12. Definition of done

The experiment is successful when:

1. Real MML KM10 data has been downloaded.
2. Oulu test-area data has been converted to 80m resolution.
3. The converted data is stored in a compact, documented format.
4. Godot displays actual terrain elevation.
5. Terrain aligns with the existing OSM world.
6. Missing data and tile boundaries are handled correctly.
7. Performance measurements are available.
8. The experiment can be reproduced from documented instructions.

At completion, provide a concise technical report with actual measurements, screenshots and a recommendation on whether 80m resolution should become the baseline for the Finland-wide terrain system.

Do not claim success based solely on a terrain mesh appearing on screen. Geographic accuracy and reproducibility are essential.
## Measured: whole Finland in the package (2026-11-14)

- Source: 155 Copernicus GLO-30 tiles N59..N70 x E019..E031 (N61E019 is 404, open sea),
  2,722,507,959 bytes in `~/.cache/copernicus-dem30` (not committed).
- `tools/dem80.py convert --source copernicus --bbox finland`: 58 min 43 s wall clock,
  4.0 GB peak RSS (WSL, 15 GB RAM).
- Output `src/theroadragetrip/assets/dem80/`: 1807 tiles + dem80.json, 124,008,031 bytes
  (about 69 KB per tile; ratio about 22:1 against the source). Plain git, no LFS.
- Lookup order: `<cache>/dem80`, `$THEROADRAGETRIP_DEM80_DIR`, then the packaged folder.
- Oulu city centre (65.0121 N, 25.4682 E): 13.9 m; the 1 km ring spans 0.0 to 20.4 m.
