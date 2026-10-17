"""Keep the game, Python package and Windows installer on the same release."""
import re
import tomllib
from pathlib import Path


def test_release_versions_match():
    root = Path(__file__).resolve().parents[1]
    package = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    match = re.fullmatch(r"(\d+\.\d+\.\d+)a0", package)
    assert match is not None
    base = match[1]
    assert f'config/version="{base}alpha"' in (root / "godot/project.godot").read_text()
    assert f'#define AppVersion "{base}alpha"' in (root / "installer/RoadRageTrip.iss").read_text()
    exports = (root / "godot/export_presets.cfg").read_text()
    for field in ("file_version", "product_version"):
        assert f'application/{field}="{base}.0"' in exports
