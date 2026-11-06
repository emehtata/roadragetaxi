# Licence entry for borders.json.gz

## Goal
`tools/license_inventory.json` has an `assets` entry for
`src/theroadragetrip/assets/borders.json.gz`. The file is not only OSM: Finland's
outline is OSM (ODbL), the neighbours' outlines are Natural Earth (public domain).

## Status (2026-11-06)
Already done in commit 8753e6e ("Licences: add borders.json.gz inventory entry ..."),
on release/v0.21.0beta. `python tools/check_license_inventory.py` prints
`0 problem(s)`. The failure the task quotes predates that commit. Nothing is left
to edit unless the checks below fail.

## Evidence (facts from the repo, none guessed)
- `tools/osm/build_borders.py` docstring: Finland from OSM relation 54224 (ODbL),
  neighbours from Natural Earth 1:50m admin 0 countries v5.1.2 (public domain),
  EPSG:3067, built from Geofabrik finland-latest.osm.pbf via osmium.
- `src/theroadragetrip/assets/DATA_LICENSES.txt` lines 71-76 carry the notice.
- Missing fact: the date of the PBF used for the build is not recorded
  (places.json.gz records 2026-09-09). Do not invent one.

## Entry (matches the "OpenStreetMap places database" style)
- name "Country borders"; paths `["src/theroadragetrip/assets/borders.json.gz"]`; shipped true
- origin "OpenStreetMap relation 54224 and Natural Earth 1:50m v5.1.2, tools/osm/build_borders.py"
- copyright "OpenStreetMap contributors; Natural Earth (public domain)"
- licence "ODbL-1.0 AND LicenseRef-PublicDomain (Natural Earth)"
- evidence "https://www.openstreetmap.org/copyright; https://www.naturalearthdata.com/about/terms-of-use/; DATA_LICENSES.txt"
- obligations: attribution "© OpenStreetMap contributors" where used; the derived
  database stays under ODbL with a notice; offer it (ships in the release)
- commercial "yes, under ODbL"; status "conditional"
- remediation "in-game attribution (Credits, map views: done); ODbL and Natural Earth notice in DATA_LICENSES.txt (present)"

## Acceptance criteria
1. `python tools/check_license_inventory.py` exits 0, `0 problem(s)`.
2. `pytest tests/test_license_inventory.py` passes.
3. The entry has every field in `FIELDS` and the same field order/style as the places entry.
4. `licence` names both ODbL-1.0 and Natural Earth public domain.

## Tests to add
None new. `test_every_shipped_file_and_package_has_a_licensing_entry` and
`test_inventory_has_no_problems` already fail without the entry
("no licensing entry for shipped file ...borders.json.gz").

## Out of scope
- Unresolved items (sample_osm.json.gz, sounds, images).
- Bundling the full ODbL text (a URI suffices).
