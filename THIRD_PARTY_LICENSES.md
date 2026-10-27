# Third-party software in the Windows release

Road Rage Trip's own code is under the MIT licence in `LICENSE`. The software
below is not; each component keeps its own licence. Data and other non-code
assets (map data, timetables, names, sounds, images) are listed in
`src/theroadragetrip/assets/DATA_LICENSES.txt` and `src/theroadragetrip/sounds/LICENSE`.
The audit behind this list, with open items, is in `LICENSE_AUDIT.md`.

Where the full texts are in an installed game:

| Folder | What |
| --- | --- |
| `licenses/godot/LICENSES.txt` | Godot Engine's licence, every third-party component in the engine, and their licence texts, written by the engine itself (`tools/godot_licenses.gd`) |
| `server/licenses/python/` | Each bundled Python package's own licence files, the Python runtime's licence, and `PACKAGES.txt` (versions and licences), collected by `tools/collect_licenses.py` |
| `server/osmium/licenses/` | osmium-tool and its libraries (conda-forge packages), with `PACKAGES.txt` |

## The game client: Godot Engine

| Component | Licence | How it ships |
| --- | --- | --- |
| Godot Engine 4.7.2 | MIT, © 2014-present Godot Engine contributors | The game executable (`RoadRageTrip.exe`) |
| Godot's third-party components (FreeType, HarfBuzz, ICU, mbedTLS, the built-in fonts, and so on) | Their own licences (Apache-2.0, BSD, FTL, MPL-2.0, OFL-1.1, Unicode, Zlib, ...) | Built into the executable; listed one by one in `licenses/godot/LICENSES.txt` |

The in-game Credits screen shows the same notices.

## The simulation server: Python and its packages

`server/RoadRageServer.exe` is built with PyInstaller. It contains the Python
runtime and these packages, versions as in `PACKAGES.txt`:

| Component | Licence | Notes |
| --- | --- | --- |
| Python (runtime and standard library) | PSF License 2.0 | The runtime bundles third-party libraries (such as OpenSSL, SQLite, libffi, zlib, bzip2); the Windows build's `LICENSE.txt`, shipped as `python/LICENSE.txt`, is expected to list them. Check it in each release (LICENSE_AUDIT.md) |
| PyInstaller bootloader | GPL-2.0-or-later with the PyInstaller bootloader exception | The exception allows distributing the built program under its own terms |
| requests | Apache-2.0 | Its `NOTICE` file ships with it |
| urllib3 | MIT | |
| idna | BSD-3-Clause | |
| charset-normalizer | MIT | |
| certifi | MPL-2.0 | Its CA bundle (`cacert.pem`) is unmodified; source: https://github.com/certifi/python-certifi |
| PyEphem (`ephem`) | MIT | Self-contained astronomical calculations; no ephemeris download at runtime |
| rsplan | MIT | Reeds-Shepp paths for NPC vehicles' multi-point manoeuvres (manoeuvre.py) |
| pyproj, with PROJ | MIT | PROJ's licence ships as `LICENSE_proj` |
| shapely | BSD-3-Clause | |
| GEOS (bundled by shapely as its own DLL) | LGPL-2.1 | The licence ships as `shapely/licenses/LICENSE_GEOS`. The DLL can be replaced. Its source is attached to every release (`geos-<version>-source.tar.bz2`) and is at https://libgeos.org/ |
| numpy | BSD-3-Clause, with bundled parts under 0BSD, MIT, Zlib and CC0-1.0 | Its wheel bundles libraries such as OpenBLAS and LAPACK (and, in builds that use them, the GCC runtime libraries, GPL-3.0 with the GCC Runtime Library Exception); numpy's own `LICENSE.txt` lists those its build bundles |

## Local .osm.pbf maps: osmium-tool

The release includes in `server/osmium/` the programs and libraries below,
which read local `.osm.pbf` map files. The game runs osmium-tool as a separate
program. `server/osmium/licenses/PACKAGES.txt` lists each package's exact
version and licence. The binaries are conda-forge's builds (https://conda-forge.org/).

| Component | Licence |
| --- | --- |
| osmium-tool 1.19.1 (`osmium.exe`), https://osmcode.org/osmium-tool/ | GNU General Public License v3.0 only |
| libosmium (built into `osmium.exe`) | Boost Software License 1.0 |
| Boost libraries | Boost Software License 1.0 |
| Expat | MIT |
| zlib | zlib licence |
| bzip2 | bzip2 licence (BSD-style) |
| LZ4 | BSD 2-Clause |
| Microsoft Visual C++ runtime, Universal C Runtime | Microsoft redistributable licence terms |

### osmium-tool source code (GPL-3.0)

osmium-tool is free software: you can redistribute it and/or modify it under the
terms of the GNU General Public License version 3, as published by the Free
Software Foundation. It comes with no warranty. The licence text is in
`server/osmium/licenses/osmium-tool/`.

The complete source code for the osmium-tool binary in this release is attached
to the same GitHub release as the installer:
- `osmium-tool-1.19.1-source.tar.gz`: the program's source.
- `osmium-tool-feedstock-recipe.tar.gz`: conda-forge's build recipe and scripts.

Both are at https://github.com/emehtata/roadragetaxi/releases. The project's
home is https://github.com/osmcode/osmium-tool.
