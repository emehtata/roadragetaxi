"""Every export preset packs every GLB model under godot/assets and the animal palette textures."""
import configparser
from fnmatch import fnmatch
from pathlib import Path

PRESETS = Path(__file__).resolve().parents[1] / "godot" / "export_presets.cfg"


def test_presets_pack_animals():
    cfg = configparser.ConfigParser(interpolation=None, strict=False)
    cfg.read(PRESETS, encoding="utf-8")
    presets = [s for s in cfg.sections() if s.startswith("preset.") and "." not in s[len("preset."):]]
    assert len(presets) == 3
    for section in presets:
        include = [p.strip() for p in cfg[section]["include_filter"].strip('"').split(",") if p.strip()]
        exclude = [p.strip() for p in cfg[section]["exclude_filter"].strip('"').split(",") if p.strip()]
        models = [str(p.relative_to(PRESETS.parent)) for p in (PRESETS.parent / "assets").rglob("*.glb")]
        assert len(models) >= 25
        for path in models + [str(p.relative_to(PRESETS.parent)) for p in (PRESETS.parent / "assets/animals").glob("*.png")]:
            assert any(fnmatch(path, p) for p in include), (section, path)
            assert not any(fnmatch(path, p) for p in exclude), (section, path)
