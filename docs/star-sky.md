# Catalog star sky

The star sky uses 5,092 SAO catalogue rows with finite J2000/FK5 coordinates and inclusive native visual magnitude <=6.0. It is a celestial-coordinate atlas, oriented by actual player location and authoritative UTC game time. Catalogue work is offline; runtime work is one cached observer basis and seven magnitude-band weights.

## Source, rights and reproduction

The pinned source is [NASA HEASARC SAO I/131A](https://heasarc.gsfc.nasa.gov/W3Browse/star-catalog/sao.html), downloaded from `https://heasarc.gsfc.nasa.gov/FTP/heasarc/dbase/tdat_files/heasarc_sao.tdat.gz`, SHA-256 `8ad1b253efc0b5386b4e3b8e5150eab4c54b61c090cd3eae6a88eed833702a67`. HEASARC already removed 53 duplicate entries. Of its 258,944 rows, the filter retains 5,092 unique SAO IDs, rejects 252,382 fainter rows and 1,470 rows with missing/invalid required fields. Missing spectral type does not remove a star; photographic magnitudes are not misrepresented as B−V. All retained stars have FK5 proper motions. Resolved component entries retain their source positions/magnitudes; combined source entries remain combined. Sol and non-SAO records are rejected.

NASA NTRS labels both the [original 1966 catalogue](https://ntrs.nasa.gov/citations/19660017606) and [1984 machine-readable documentation](https://ntrs.nasa.gov/citations/19840015351) **Work of the US Gov. Public Use Permitted.** [NASA's source-specific open-data entry](https://data.nasa.gov/dataset/smithsonian-astrophysical-observatory-star-catalog) links to government-work terms. `godot/assets/sky/NOTICE.txt` retains the public-use statement, 17 USC 105 text, original institutions, modifications and source links. Finnish, English and German displayed credits name SAO/USNO/NASA HEASARC. No endorsement is implied.

```sh
.venv/bin/python tools/build_star_sky.py --source /path/to/heasarc_sao.tdat.gz
# Rebuild byte-identical textures from the bundled subset, without a download:
.venv/bin/python tools/build_star_sky.py
```

`source.json` pins the original source and generated file hashes, schema, precision and epoch. The large source archive is not shipped. HYG, Hipparcos and their derived records are not included; those catalogues were reviewed locally as alternative/validation sources only.

## Photometric limits

SAO visual magnitudes are mixed historical visual/photovisual estimates rounded to 0.1 mag, not uniformly modern Johnson V. A local HD cross-check against HYG has median absolute difference 0.11 mag and 95th percentile 0.30 mag; variables, combined components and occasional old photometry have larger differences. 319 HYG rows at modern V<=6 have SAO values >6.0. The native SAO cutoff therefore represents a historical visual-magnitude-six sample, not exact modern Johnson-V completeness. Its major bright stars include Sirius, Canopus, Vega, Arcturus, Capella, Polaris and Alpha Centauri. This is explicitly a source/photometry limit, not a silent G-to-V substitution or a random replacement sample.

## Atlas and astrometry

Two shared 4096x2048 RGBA PNG maps encode seven independent magnitude bands (<=0, 0..1, ..., 5..6). RA increases along u and declination runs +90 to -90 along v. Source positions use a 0.55-texel sigma angular Gaussian footprint with RA width corrected by cos(dec), wrapping the RA seam. The amplitude encoding and band weights use the same 0.2 logarithmic slope, so source brightness ordering remains continuous across band boundaries. This compresses visual brightness range for the display while retaining magnitude ordering. Textures use lossless import, linear sampling and no mipmaps; alpha-border processing is disabled because alpha is a data band. Neutral white is used consistently because the source has no calibrated B−V. Decoding seven bands permits smooth suppression of faint stars separately from bright stars; band transitions span one magnitude. The two uncompressed RGBA maps total 64 MiB GPU memory.

FK5 dRA/dt is seconds of time/year and dDec/dt is arcseconds/year. The builder advances source directions to 2026 in the J2000 equatorial frame. The server applies IAU 1976 date precession, mean sidereal time, observer latitude/east-positive longitude and existing EPSG:3067 grid convergence. The observer is the car or on-foot player rather than the city's centre. A 10-second UTC/0.0001-degree cache bounds runtime work and orientation age; Finnish DST/fold is handled by the existing calendar conversion. Godot +X is grid east, +Y up and -Z grid north.

The tested date range is 2020–2040. Within it, residual proper motion from the fixed 2026 bake plus omitted nutation, annual aberration, FK5/ICRS difference and UT1 corrections stay below the 0.1-degree directional target; `tests/data/star_sky_reference.json` records independent ERFA atco13 airless geometric references. Refraction/extinction near the horizon are approximated by an 0–5-degree horizon fade. Unsupported years disable the star layer rather than claim unvalidated positions.

## Visibility and cost

Clear rural astronomical night reveals the complete selected atlas above the horizon. Stars fade smoothly between solar altitudes -18 and -6 degrees and vanish by daylight. Working lamp counts and building context in at most nine neighbouring 500 m chunks provide a cached light-pollution heuristic, combined with local light/floodlight exposure. An unlit street amid buildings therefore remains polluted. Inputs update every 0.5 seconds and move gradually between values. This is not a measured Bortle map and does not include distant cities beyond streamed context. A bright high Moon reduces the limiting magnitude by up to two. Existing cloud density occludes stars; full overcast suppresses the entire star layer. Terrain/buildings occlude the normal sky. Stars are excluded from the radiance-cubemap pass.

The implementation follows local `game-mechanics-optimizations/04_dirty_flags.md` and `41_2d_sprite_batching.md`: no catalogue rasterization/network fetches in gameplay, no per-star nodes/lights, shared textures, and compact cached input changes. Native GPU scenario evidence and measured limits are recorded locally under `visual-test-results/`; source/atlas rebuild and astrometry tests run independently of those captures.

## Native validation on 26 November 2026

The five named scenarios passed on native Windows Godot 4.7.2, Vulkan Forward+, RTX 5060 at 1280×720; every final screenshot was inspected. The accepted rural source is Kajaanintie 477846.8/7172649.5. All nine surrounding context-chunk corners fall inside the pinned real OSM extract 64.62702,26.43507,64.68649,26.57399; source placement gives zero lamps/buildings there. This coverage is checked by the scenario contract test. The cached raw OSM source was reused with `OSM_CACHE_TTL=999999999`; no unsupported old binary cache or fabricated map placements were used.

Rural midnight reports pollution 0 / limiting magnitude 6 with 108 known projected stars contributing rendered pixels, including 82 at magnitudes 5–6. Three hours later, the observer basis and visible sky rotate with sidereal time; 120 known sources (82 faint) contribute. The Helsinki city control reports pollution 1 / limiting magnitude 2, one bright source and no faint ones. Fully overcast and daytime controls both report zero catalogue-star pixel contribution. Readiness compares source-direction pixels in paired star-on/off renders before timing, then restores normal rendering before capture. The 11 independent ERFA fixtures have maximum directional error 0.00748 degrees.

Before/after profiles use the same source, pose, date, weather, resolution and eight-second measurement, a 30-second minimum warmup and all streamed builds/uploads finished. Baseline is commit `cefa76a0`, with only identical verification-camera/warmup hooks. Values below are frame times in milliseconds:

| View | Version | p50 | p95 | p99 | Worst | Draw calls | VRAM MiB |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Rural | Before | 3.333 | 3.704 | 5.000 | 7.764 | 133 | 2912.12 |
| Rural | Star sky | 2.793 | 3.333 | 3.923 | 6.180 | 127 | 2976.12 |
| City | Before | 10.606 | 12.183 | 16.667 | 46.382 | 443 | 4158.58 |
| City | Star sky | 11.400 | 15.000 | 19.375 | 49.361 | 445 | 4223.16 |

The two maps cost 64 MiB of resident texture memory. Rural population is identical at 78,515 forest rows/228 GLBs; city population is identical at 825 forest rows. A few moving wildlife/traffic objects differ across runs, so draw counts and improved rural frame time are not evidence of an intrinsic speed gain. City average frame time rose 9.6% and p95 rose 23.1%; this remains a measured quality/performance tradeoff. Long-frame investigation found zero chunk work and zero pipeline compilations in both city captures, with roughly 2.2 ms main work during their 38–49 ms tails. Frames above 33 ms decreased 3→2; frames above the 60 Hz budget increased 4→12. Last-sample city 3D GPU time was 1.881→2.429 ms. Low-end GPU behavior has not been measured. The existing moving cloud uniforms continue to trigger the same sky/radiance updates; the star texture is excluded from cubemap rendering and adds no star nodes, lights or geometry batches.

Local evidence is under `visual-test-results/star_sky_final_comparison.json` and the five scenario directories. Early polluted-site, incomplete-extract, external-fetch and interrupted baseline trials are diagnostic failures and are not accepted evidence. Screenshots, source-comparison data and research notes remain local.
