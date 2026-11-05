# Missing licence entries and texts

## Goal
`python tools/check_license_inventory.py` currently fails (1 problem). Close every
item that has no licensing entry or whose licence text/notice is missing, using
only texts already in the repo or in installed packages (no network).

## Findings (2026-11-05, measured)
1. `src/theroadragetrip/assets/borders.json.gz`: no entry in
   `tools/license_inventory.json`. This is the only check failure. Its notice is already in
   `src/theroadragetrip/assets/DATA_LICENSES.txt` (lines 71-76: OSM relation
   54224 ODbL-1.0 + Natural Earth 1:50m v5.1.2 public domain, built by
   `tools/osm/build_borders.py`).
2. `opening_hours_py` 2.1.4: it has an inventory entry and ships its texts
   (`dist-info/licenses/LICENSE-APACHE`, `LICENSE-MIT`, collected by
   `tools/collect_licenses.py`), but it is not in the Python table in
   `THIRD_PARTY_LICENSES.md` or the package table in `LICENSE_AUDIT.md`.
3. All other runtime packages (`runtime_closure` + `pyinstaller`) already ship a
   licence file from their dist-info. None is flagged `[NO LICENCE FILE SHIPPED]`.
4. The ODbL-1.0 and CC BY / BY-SA 4.0 full texts are not available offline
   (missing from repo, packages and /usr/share/common-licenses). Both licences
   allow a URI reference (ODbL 4.3, CC BY 3(a)(1)(C)), and DATA_LICENSES.txt
   already gives the URIs. Do not add the full texts.

## Files to change
- `tools/license_inventory.json`: add an `assets` entry "Country borders"
  with paths `["src/theroadragetrip/assets/borders.json.gz"]`, all FIELDS
  (name, paths, purpose, shipped=true, origin, licence
  "ODbL-1.0 AND LicenseRef-PublicDomain (Natural Earth)", evidence
  "https://www.openstreetmap.org/copyright; https://www.naturalearthdata.com/about/terms-of-use/; DATA_LICENSES.txt",
  obligations, commercial "yes, under ODbL", status "conditional",
  remediation). Copy the field style from the "OpenStreetMap places database"
  entry.
- `THIRD_PARTY_LICENSES.md`: add a row to the Python table:
  `opening_hours_py | MIT OR Apache-2.0 | Both licence files ship`.
- `LICENSE_AUDIT.md`: add the matching `opening_hours_py` row to the
  package table (status Verified). Under the phased-docs rule, append the row
  and leave the existing rows unchanged.

## Acceptance criteria
1. `python tools/check_license_inventory.py` exits 0 and prints `0 problem(s)`.
2. Every name in `inventory["python_packages"]` appears in the
   `THIRD_PARTY_LICENSES.md` Python table.
3. The new borders entry's `licence` names both ODbL-1.0 and Natural Earth
   public domain, matching DATA_LICENSES.txt.
4. No file gets licence text fetched from the network.

## Tests to add
- `tests/test_license_inventory.py::test_inventory_has_no_problems`: runs
  `problems(inventory, shipped_files(), packages)` from
  `tools/check_license_inventory.py` and asserts the list is empty. It fails
  today on borders.json.gz.
- `tests/test_license_inventory.py::test_every_package_listed_in_third_party_md`:
  every `python_packages` key (case-insensitive, `-`/`_` treated as the same) is
  in THIRD_PARTY_LICENSES.md. It fails today on opening_hours_py.

## Out of scope
- Items marked Unresolved in LICENSE_AUDIT.md (sound/voice provenance, images,
  sample_osm.json.gz, sports fixtures, tile/Nominatim policies). They need facts
  that are not recorded, not licence texts.
- Bundling the full ODbL or CC texts (offline copies are unavailable, and a URI is enough).
- Checking the Windows build's Python `LICENSE.txt` and numpy bundled notices (a release checklist item).
