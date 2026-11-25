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


def test_reported_forest_scenario_requires_target_geometry():
    registry = json.loads((RESULTS.parents[1] / 'tools' / 'visual_scenarios.json').read_text(encoding='utf-8'))
    scenario = next((s for s in registry['scenarios'] if s['id'] == 'oulu_screenshot_forest_day'), None)
    assert scenario is not None, 'latest screenshot forest needs a real-map regression scenario'
    assert scenario['city'] == 'Oulu'
    assert scenario['pose'] == pytest.approx([425360.4558, 7216744.0155, -3.31216944])
    assert scenario['camera'] == 'third'
    assert scenario['requires']['dem_ground'] is True
    target = scenario['requires']['forest_target']
    assert target['bounds'] == [425309.37, 7216772.75, 425329.37, 7216792.75]
    assert target['min_crowns'] >= 5
    assert target['require_glb'] is True
    assert target['min_height_px'] >= 20
    assert 'Helmikkäkuja' in scenario['why']
