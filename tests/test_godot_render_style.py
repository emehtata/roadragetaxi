"""The Godot client draws trains with Pygame's palette: render_style.gd's
TRAIN_PROFILES must match train_compositions.PROFILES."""
import re
from pathlib import Path

from theroadragetrip.train_compositions import PROFILES

STYLE = Path(__file__).resolve().parents[1] / "godot" / "render_style.gd"


def test_godot_train_palette_matches_the_simulation_profiles():
    text = STYLE.read_text(encoding="utf-8")
    block = text[text.index("const TRAIN_PROFILES"):text.index("}", text.index("const TRAIN_PROFILES"))]
    godot = {}
    for name, body, pattern in re.findall(r'"(\w+)": \[Color8\(([\d, ]+)\), (?:null|Color8\(([\d, ]+)\))\]', block):
        rgb = lambda s: tuple(int(v) for v in s.split(","))
        godot[name] = (rgb(body), rgb(pattern) if pattern else None)
    assert godot == PROFILES
