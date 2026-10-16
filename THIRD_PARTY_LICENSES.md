# Third-party software in the Windows release

The Windows release of Road Rage Trip includes the programs and libraries below
in `server/osmium/`, which reads local `.osm.pbf` map files. The game's own code
is under the MIT licence in `LICENSE`. The game runs osmium-tool as a separate
program; the components below keep their own licences.

The full licence text of every package is in `server/osmium/licenses/`.
`server/osmium/licenses/PACKAGES.txt` lists each package's exact version and
licence. The binaries are conda-forge's builds (https://conda-forge.org/).

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

## osmium-tool source code (GPL-3.0)

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
