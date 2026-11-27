"""Visual-test result schema, checked on the newest real run (the VM has no
graphics: run motorway_through_traffic on the GPU machine)."""
import importlib.util
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


BINOCULAR_IDS = ["binoculars_oulu_moon_2x", "binoculars_oulu_moon_8x", "binoculars_oulu_moon_lowered",
                 "binoculars_oulu_moon_overcast_8x", "binoculars_oulu_moon_8x_640x360", "binoculars_helsinki_street_2x", "binoculars_helsinki_street_8x"]


def _registry():
    spec = importlib.util.spec_from_file_location("visual_test_tool", RESULTS.parents[1] / "tools" / "visual_test.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool.scenarios()  # with `extends` resolved


def test_binocular_scenarios_use_real_controls_and_explicit_renderer():
    scenarios = _registry()
    moon = scenarios['oulu_gibbous_moon']
    for id_ in BINOCULAR_IDS:
        s = scenarios[id_]
        assert s['engine_args'] == ['--rendering-method', 'forward_plus', '--rendering-driver', 'vulkan'], id_
        assert 'eye' not in s, 'a test-only camera must not stand in for the player: ' + id_  # (removed from the inherited fields)
        assert s['walk']['forward'] == 0.0 and 'yaw' in s['walk'] and 'pitch' in s['walk'], id_  # on foot, fixed manual aim
        assert 'fov' not in s['binoculars'], id_  # the FOV comes from the O key and the wheel
    for id_ in BINOCULAR_IDS[:5]:  # the Moon scenarios share the sourced place and date
        s = scenarios[id_]
        assert (s['city'], s['pose'], s['start_time']) == (moon['city'], moon['pose'], moon['start_time'])
        assert s['walk']['pitch'] == scenarios[BINOCULAR_IDS[0]]['walk']['pitch']
    assert scenarios['binoculars_oulu_moon_2x']['binoculars']['steps'] == 0
    assert scenarios['binoculars_oulu_moon_8x']['binoculars']['steps'] == 3
    assert scenarios['binoculars_oulu_moon_lowered']['binoculars']['lower'] is True
    assert scenarios['binoculars_oulu_moon_overcast_8x']['cloud'] == 1.0
    assert scenarios['binoculars_oulu_moon_overcast_8x']['binoculars']['target']['hidden'] is True
    assert scenarios['binoculars_oulu_moon_8x_640x360']['resolution'] == [640, 360]
    for id_ in BINOCULAR_IDS[:2]:
        assert scenarios[id_]['requires']['moon_phase']['surface_texture'] is True
        assert scenarios[id_]['requires']['moon_phase']['inside_view'] is True
    two, eight = scenarios['binoculars_helsinki_street_2x'], scenarios['binoculars_helsinki_street_8x']
    for key in ('city', 'pose', 'start_time', 'walk', 'weather'):
        assert two[key] == eight[key], key  # a matched pair
    assert (two['binoculars']['steps'], eight['binoculars']['steps']) == (0, 3)
    assert two['binoculars']['target'] == eight['binoculars']['target']
    assert 'building_at' in eight['binoculars']['target'] and eight['sun_altitude_deg'][0] >= 20  # a daytime mapped building
