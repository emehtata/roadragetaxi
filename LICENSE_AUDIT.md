# Licensing audit for a commercial release

Audited: branch `release/0.18.0alpha` at `fd514d1` (v0.17.1alpha plus 12
commits), 2026-10-17, and the Windows release as `.github/workflows/windows-release.yml`
builds it. Task: `.github/prompts/license-audit.md`.

This is a technical audit of the evidence in the repository, the build and the
tools used. It is not legal advice. Where rights depend on facts not recorded
here, or on interpreting a licence, the item is marked unresolved or flagged
for legal review instead of being assumed permissive.

The machine-readable inventory is `tools/license_inventory.json`.
`tools/check_license_inventory.py` (run by `tests/test_license_inventory.py`)
fails when a shipped file or bundled Python package has no entry. It does not
judge licence compatibility.

## Answers

1. **Is the game's own code still MIT?** Yes. `LICENSE` (© 2026 Esa
   Mehtätalo) is unchanged and excludes the sounds and the listed data. The
   bundled osmium-tool (GPL-3.0) runs as a separate program and does not change
   the game's licence (see Software).
2. **What may be distributed commercially on current evidence?** The
   permissively licensed software, once its notices ship (done in this
   change); OSM, Digitraffic, DVV and FMI data, with attribution (done);
   Wikipedia municipality data, with attribution and the file kept CC BY-SA 4.0;
   GEOS, certifi and the PyInstaller bootloader, with their notices and source
   access (done in the release workflow).
3. **What must be fulfilled before a paid Steam release?** Everything under
   Unresolved, and checking the Windows build's bundled notices (Checklist).
4. **What still needs permission, replacement, source distribution or legal
   review?** The sports fixtures, the cloned announcement voice, the chatter
   voices, the generated sound effects' model licence, the images, the sample
   map and the OSM tile and Nominatim services (Unresolved).
5. **Is the current package ready for commercial distribution?** **No.**
   Material rights are unresolved: the sports fixtures, voice consent, and the
   origin of the sounds and images.

## Scope and method

What the Windows release ships, per `windows-release.yml` (PyInstaller
`--add-data`, the Godot export filter `*.json, *.ico, *.svg` plus resources,
excluding `tests/*`):

- **Game executable:** Godot export (`RoadRageTrip.exe`, `.pck`).
- **Server:** `server/RoadRageServer.exe` and `_internal/`: Python and the
  runtime packages, plus `src/theroadragetrip/{img,sounds,assets}` and
  `sample_osm.json.gz`.
- **osmium-tool:** `server/osmium/`, with its libraries.
- **Not shipped:** world and tile caches, the Finland `.osm.pbf` (the player
  downloads it), the ai-audio-studio project and its reference voices.

Evidence used: licence files in the repository, wheel metadata and licence
files of the installed packages (`tools/collect_licenses.py`), Godot's own
`Engine.get_license_info()`, conda package metadata (osmium), the generators'
configuration (`audio_catalog.json`, `railway_announcements/manifest.json`,
ai-audio-studio), the data importers, and git history. Licence texts not
available locally were not assumed.

## Findings

### Software

| Component | Licence (evidence) | Ships as | Status |
| --- | --- | --- | --- |
| Godot Engine 4.7.2 and its components | MIT plus component licences (`Engine.get_license_info`) | The executable | Conditional: notices now ship (`licenses/godot/LICENSES.txt`) and show in Credits |
| Python 3.12 runtime | PSF-2.0 | `server/_internal` | Conditional: `LICENSE.txt` now ships; verify that the Windows build's copy lists its bundled libraries (OpenSSL, SQLite, ...) |
| PyInstaller bootloader | GPL-2.0-or-later with the bootloader exception (`COPYING.txt`) | Inside `RoadRageServer.exe` | Conditional: the exception permits distributing the built program; the notice now ships |
| requests, urllib3, idna, charset-normalizer, PyEphem, rsplan, pyproj (with PROJ) | Apache-2.0, MIT, BSD-3-Clause, MIT, MIT, MIT, MIT (wheel licence files) | `_internal` | Verified, with notices |
| shapely | BSD-3-Clause | `_internal` | Verified |
| paho-mqtt | EPL-2.0 or EDL-1.0 (chosen: EDL-1.0, BSD-3-Clause) | `_internal` | Verified |
| GEOS 3.13.1 (bundled by shapely) | LGPL-2.1 (`LICENSE_GEOS`) | A separate, replaceable DLL | Conditional: the LGPL text now ships and the GEOS source is attached to each release |
| certifi | MPL-2.0 | `_internal` (unmodified CA bundle) | Conditional: notice and an upstream source pointer |
| numpy | BSD-3-Clause and others; bundles OpenBLAS, LAPACK and GCC runtime parts (wheel `LICENSE.txt`) | `_internal` | Conditional: verify the Windows wheel's bundled-library notices |
| osmium-tool 1.19.1 and libraries | GPL-3.0-only; BSL-1.0, MIT, Zlib, bzip2, BSD-2-Clause, Microsoft runtime (conda metadata) | A separate executable in `server/osmium/` | Conditional: licence texts ship, and the source and build recipe are attached to each release (since 0.17.0alpha) |

GPL note: the game runs osmium-tool as a separate program and passes it files.
That is the arrangement the GPL calls an aggregate. The facts are recorded here;
confirming that no closer coupling exists belongs to legal review.

### Map data (OpenStreetMap, ODbL 1.0)

- `places.json.gz` is a derived database: 244 airports and stations, each keeping
  its OSM id, extracted from Geofabrik's `finland-latest.osm.pbf` of 2026-09-09.
  It stays under ODbL with its notice (in `DATA_LICENSES.txt`) and ships whole,
  so the database itself is what is offered.
- `godot/finland_minimap.svg` is drawn from OSM motorway, trunk and primary
  roads (`tools/osm/build_finland_minimap.py`). That is a produced work: it needs
  attribution, not database share-alike.
- Map data read while playing (Overpass, Geofabrik, world caches) is not shipped.
  The game view shows it with attribution.
- **Attribution (done):** the Credits screen states © OpenStreetMap
  contributors, ODbL 1.0, with a link to https://www.openstreetmap.org/copyright.
  The game view shows "© OpenStreetMap contributors" at all times, and the
  start map credits its tiles.

### Other data

| Data | Licence | Status |
| --- | --- | --- |
| Railway timetable and compositions (Fintraffic / digitraffic.fi) | CC BY 4.0 | Conditional: attribution in Credits (done), changes stated |
| Resident names (DVV) | CC BY 4.0 | Conditional: attribution (done) |
| Municipalities (Wikipedia) | CC BY-SA 4.0 | Conditional: attribution (done). The adapted data file stays CC BY-SA 4.0; legal review of the share-alike scope is advisable |
| FMI weather (runtime only, opt-in) | CC BY 4.0 | Conditional: attribution (done) |
| Liiga and Veikkausliiga fixtures (`sports_fixtures.json.gz`) | None found | **Unresolved** (below) |

### Sounds and images

| Asset | Origin found | Status |
| --- | --- | --- |
| 134 sound effects (`assets/audio/`) | Generated with Stable Audio Open 1.0 (`audio_catalog.json`) | **Unresolved:** the model licence text is not archived. Believed to be the Stability AI Community License, with commercial-use conditions such as a revenue limit, but that is unverified |
| 466 station announcements (`assets/railway_announcements/`) | Chatterbox TTS cloning the reference voice `voices/female/eeva.wav`, from `eeva.mp4` (`manifest.json`) | **Unresolved:** whose voice it is and their consent are not recorded |
| 260 chatter clips (`sounds/`) | Azure Speech (`utils/ttsazure.py`) and/or Chatterbox cloning `voices/female/default.wav` | **Unresolved:** the tool and voice per file are not recorded |
| Images and icons (`img/`, `assets/*.png`, `*.ico`, `*.xpm`) | Not recorded | **Unresolved** |
| Chatter lines (JSON) | Presumably written for the game | Conditional: confirm they are original |
| `sample_osm.json.gz` | Synthetic-looking ids; origin not recorded | **Unresolved** |

### Runtime services

| Service | Use | Status |
| --- | --- | --- |
| tile.openstreetmap.org | Start-map tiles (attributed, identifying User-Agent) | **Unresolved:** the OSMF tile usage policy limits heavy use. Review it for a commercial player base; a commercial or self-hosted tile provider may be needed |
| nominatim.openstreetmap.org | Start-map place names | **Unresolved:** the Nominatim usage policy (1 request/s, no heavy use). Review as above |
| Overpass API servers, Geofabrik, Digitraffic, FMI | Map data, map file, timetable refresh, weather | Conditional: attribution (done); each service's usage terms |

## Unresolved items and the way forward

| Item | Needed | Options |
| --- | --- | --- |
| Sports fixtures | Rights to redistribute the dataset, and the services' terms | Permission from Liiga and Veikkausliiga; a licensed data source; or ship no dataset and fetch bare facts at runtime (subject to the terms). Legal review |
| Announcement voice "eeva" | The speaker's consent to voice cloning and commercial use | Written consent; or regenerate with a voice the project holds rights to |
| Chatter voices | Per-file tool and voice; Azure output terms; consent for cloned voices | Record the provenance; regenerate where it can't be established |
| Sound effects | The Stable Audio Open licence as accepted | Archive the licence text; confirm the commercial terms; legal review |
| Images and icons | Origin and licence per image | Record the origin; if AI-generated, the service's terms; replace any without clear rights |
| `sample_osm.json.gz` | Its origin | Record it (synthetic means project-owned; copied from OSM means ODbL) |
| OSM tiles and Nominatim | Fit with the usage policies at commercial scale | Review the policies; a commercial or self-hosted provider |

## Commercial-release checklist

- [x] Game code stays MIT; `LICENSE` points to the third-party notices.
- [x] OpenStreetMap attribution in the game view, start map and Credits.
- [x] CC BY and BY-SA attribution in Credits (Digitraffic, DVV, FMI, Wikipedia).
- [x] Godot's licence and component notices ship (`licenses/godot/LICENSES.txt`) and show in Credits.
- [x] Python package licences ship (`server/licenses/python/`), with GEOS's LGPL text.
- [x] GEOS and osmium-tool sources attached to every release.
- [x] An inventory check fails on unlisted assets or packages.
- [ ] Inspect a Windows build: Python's `LICENSE.txt` and numpy's notices list the libraries those builds bundle.
- [ ] Sports fixtures: permission, a replacement, or removal from the commercial build.
- [ ] Announcement voice: consent, or regeneration.
- [ ] Chatter voices: provenance per file, terms, consent.
- [ ] Sound effects: archive the model licence and confirm its terms.
- [ ] Images: origin and licence per image.
- [ ] `sample_osm.json.gz`: origin recorded.
- [ ] OSM tile and Nominatim use reviewed for a commercial release.
- [ ] Legal review of the flagged items (GPL aggregate, CC BY-SA scope, generated media, sports data).

## Files changed by this audit

| File | Why |
| --- | --- |
| `LICENSE_AUDIT.md` | This report |
| `THIRD_PARTY_LICENSES.md` | All shipped software, not only osmium, and where its notices are |
| `src/theroadragetrip/assets/DATA_LICENSES.txt` | The minimap, the sample map and the open items |
| `src/theroadragetrip/sounds/LICENSE` | It listed a deleted file; it now records the speech's actual status |
| `README.md` | Its credits claim was wrong; it now points to Credits and to this audit |
| `godot/startup.gd`, `godot/i18n.gd`, `godot/hud.gd` | The Credits screen and the game view's OSM attribution |
| `godot/tests/run_tests.gd` | Checks that the required attributions are present |
| `tools/collect_licenses.py`, `tools/godot_licenses.gd` | Collect the software notices for the release |
| `.github/workflows/windows-release.yml` | Ship the notices, attach GEOS's source, check the notices are installed |
| `tools/license_inventory.json`, `tools/check_license_inventory.py`, `tests/test_license_inventory.py` | The inventory and its check |
