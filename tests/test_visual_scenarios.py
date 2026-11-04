"""Visual-test result schema, checked on the newest real run (the VM has no
graphics: run motorway_through_traffic on the GPU machine)."""
import json
from pathlib import Path

import pytest

RESULTS = Path(__file__).resolve().parents[1] / "visual-test-results" / "motorway_through_traffic"


def test_motorway_result_has_spawn_rejections():
    runs = sorted(RESULTS.glob("*/result.json"), key=lambda p: p.stat().st_mtime)
    if not runs:
        pytest.skip("no motorway_through_traffic run here (no graphics on this VM)")
    traffic = json.loads(runs[-1].read_text(encoding="utf-8"))["traffic"]
    assert traffic.get("spawn_rejections", {}).get("total", 0) > 0
