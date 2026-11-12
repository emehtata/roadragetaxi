import json
from pathlib import Path

ANIMALS = Path(__file__).resolve().parents[1] / "godot" / "assets" / "animals"


def test_every_animal_glb_has_cc0_manifest():
    glbs = sorted(ANIMALS.glob("*.glb"))
    assert glbs
    for glb in glbs:
        manifest = glb.with_suffix(".manifest.json")
        assert manifest.exists(), f"{glb.name} has no manifest"
        assert json.loads(manifest.read_text())["extras"]["license"] == "CC0-1.0", glb.name


def test_sources_lists_every_glb():
    sources = (ANIMALS / "SOURCES.md").read_text()
    for glb in ANIMALS.glob("*.glb"):
        line = next((row for row in sources.splitlines() if f"`{glb.name}`" in row), "")
        assert "CC0-1.0" in line, f"{glb.name} not listed as CC0-1.0 in SOURCES.md"
