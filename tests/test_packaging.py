"""An installed package must carry every runtime asset: pyproject's
package-data globs (resolved like setuptools does, relative to the package)
must cover every sound the audio catalog names, the catalog itself and the
railway announcements. `assets/*` once matched none of them (godot-03/04);
a real wheel build was checked by hand - too slow for a unit test."""
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "theroadragetrip"


def _packaged() -> set[Path]:
    patterns = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"]["package-data"]["theroadragetrip"]
    return {path for pattern in patterns for path in PACKAGE.glob(pattern) if path.is_file()}


def test_every_runtime_audio_asset_is_package_data():
    packaged = _packaged()
    audio = PACKAGE / "assets" / "audio"
    catalog = json.loads((audio / "audio_catalog.json").read_text(encoding="utf-8"))
    needed = {audio / "audio_catalog.json"} | {
        audio / entry["file"] for group in catalog["groups"].values() for entry in group["files"]
        if entry.get("status") == "generated"
    }
    needed |= {p for p in (PACKAGE / "assets" / "railway_announcements").rglob("*") if p.is_file()}
    assert len(needed) > 500
    assert sorted(str(p.relative_to(PACKAGE)) for p in needed - packaged) == []
