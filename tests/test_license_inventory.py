"""The licensing inventory covers everything shipped (LICENSE_AUDIT.md)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import check_license_inventory as check  # noqa: E402
import collect_licenses  # noqa: E402


def test_every_shipped_file_and_package_has_a_licensing_entry():
    assert check.main() == 0


def test_a_new_unlisted_asset_or_package_is_reported():
    inventory = json.loads(check.INVENTORY.read_text(encoding="utf-8"))
    found = check.problems(inventory, ["src/theroadragetrip/fonts/new_font.ttf"], ["brand-new-package"])
    assert any("new_font.ttf" in problem for problem in found)
    assert any("brand-new-package" in problem for problem in found)


def test_the_bundled_packages_licences_are_collected(tmp_path):
    rows = collect_licenses.collect(tmp_path)
    assert any(row.startswith("shapely ") for row in rows) and any(row.startswith("certifi ") for row in rows)
    assert (tmp_path / "shapely" / "licenses" / "LICENSE_GEOS").is_file()  # GEOS, LGPL-2.1
    assert (tmp_path / "PACKAGES.txt").read_text(encoding="utf-8").count("\n") == len(rows)
