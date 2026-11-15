"""The audit must reject evidence that cannot support a visual pass."""
import importlib.util
from pathlib import Path


TOOL = Path(__file__).parents[1] / "tools/visual_quality_audit.py"


def validator():
    spec = importlib.util.spec_from_file_location("vqa", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate


def test_pass_requires_multiple_views_and_existing_evidence(tmp_path):
    data = {"assets": [{"id": "A-001", "name": "car", "category": "Vehicles", "source": "car.gd",
                        "status": "passed", "evidence": [{"file": "missing.png", "angles": ["front"]}]}],
            "defects": []}
    errors = validator()(data, tmp_path)
    assert any("multiple" in error for error in errors)
    assert any("missing.png" in error for error in errors)


def test_duplicate_ids_and_unsubstantiated_defects_are_rejected(tmp_path):
    asset = {"id": "A-001", "name": "car", "category": "Vehicles", "source": "car.gd",
             "status": "uninspected", "reason": "capture failed", "evidence": []}
    data = {"assets": [asset, dict(asset)], "defects": [{"id": "VQA-001", "asset": "unknown"}]}
    errors = validator()(data, tmp_path)
    assert any("duplicate" in error for error in errors)
    assert any("unknown" in error for error in errors)


def test_inventory_summary_reconciles(tmp_path):
    data = {"assets": [{"id": "A-001", "name": "car", "category": "Vehicles", "source": "car.gd",
                        "status": "uninspected", "reason": "capture failed", "evidence": []}],
            "defects": [], "summary": {"discovered": 99}}
    assert any("summary" in error for error in validator()(data, tmp_path))


def test_context_capture_requires_identified_target(tmp_path):
    (tmp_path / 'panel.png').write_bytes(b'fixture')
    data = {'assets': [{'id': 'A-001', 'name': 'chair', 'category': 'Interior furniture',
                       'source': 'home_interior.gd', 'status': 'partially inspected', 'reason': 'distance pending',
                       'evidence': [{'file': 'panel.png', 'angles': ['normal', 'close'], 'ready': True,
                                     'capture_kind': 'targeted context', 'target_confirmed': False}]}], 'defects': []}
    assert any('target' in error for error in validator()(data, tmp_path))


def test_gameplay_cli_propagates_failed_readiness(monkeypatch):
    spec = importlib.util.spec_from_file_location('vqa', TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'capture_gameplay', lambda ids: 1)
    monkeypatch.setattr('sys.argv', ['visual_quality_audit.py', '--gameplay', 'audit_night_settled'])
    assert module.main() == 1


def test_runtime_manifest_rejects_unfinished_room_traversal_and_missing_frames(tmp_path):
    spec = importlib.util.spec_from_file_location('vqa', TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = {'captures': [{'file': 'runtime/missing.png', 'ready': False}],
                'homes': [{'asset': 'A-173', 'rooms_expected': 7, 'rooms_visited': [0],
                           'doors_expected': 6, 'doors_crossed': []}]}
    errors = module.validate_runtime(manifest, tmp_path)
    assert any('missing.png' in error for error in errors)
    assert any('readiness' in error for error in errors)
    assert any('rooms' in error for error in errors)
    assert any('doors' in error for error in errors)


def test_runtime_manifest_rejects_missing_requested_lod_variant(tmp_path):
    spec = importlib.util.spec_from_file_location('vqa', TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = {'captures': [], 'lod': [], 'lod_expected': [
        {'asset': 'A-002', 'system': 'generated imported mesh LOD'}]}
    assert any('LOD not sampled' in error for error in module.validate_runtime(manifest, tmp_path))


def test_gap_matrix_does_not_complete_ui_family_without_capture_evidence(tmp_path):
    spec = importlib.util.spec_from_file_location('vqa', TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    matrix = {'families': [{'id': 'HUD', 'source': 'hud.gd', 'status': 'completed', 'evidence': []}]}
    assert any('completed' in error for error in module.validate_gap_matrix(matrix, tmp_path))


def test_gap_matrix_rejects_unrendered_finite_state(tmp_path):
    spec = importlib.util.spec_from_file_location('vqa', TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / 'panel.png').write_bytes(b'fixture')
    matrix = {'families': [{'id': 'HUD', 'source': 'hud.gd', 'status': 'completed',
                            'evidence': ['panel.png'], 'expected_states': ['notice', 'summary'],
                            'captured_states': ['notice']}]}
    assert any('summary' in error for error in module.validate_gap_matrix(matrix, tmp_path))


def test_map_context_requires_motion_and_observed_chunk_change():
    spec = importlib.util.spec_from_file_location('vqa', TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = {'audit_context': {'samples': 4, 'travel_m': 60, 'added_chunk_ids': [], 'removed_chunk_ids': []}}
    assert module.validate_map_context(result, 50)
    result['audit_context']['added_chunk_ids'] = ['956_14339']
    assert module.validate_map_context(result, 50) == []
    result['audit_context']['travel_m'] = 0
    assert module.validate_map_context(result, 50)


def test_chunk_revisit_requires_same_chunk_to_be_removed_then_readded():
    spec = importlib.util.spec_from_file_location('vqa', TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = {'audit_context': {'samples': 4, 'travel_m': 1000,
                               'added_chunk_ids': ['a'], 'removed_chunk_ids': ['b'],
                               'reloaded_chunk_ids': []}}
    assert module.validate_map_context(result, 50, require_reload=True)
    result['audit_context']['reloaded_chunk_ids'] = ['b']
    assert module.validate_map_context(result, 50, require_reload=True)
    result['audit_context']['added_chunk_ids'].append('b')
    assert module.validate_map_context(result, 50, require_reload=True) == []


def test_chunk_round_trip_uses_maximum_excursion_not_net_displacement():
    spec = importlib.util.spec_from_file_location('vqa', TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = {'audit_context': {'samples': 3, 'travel_m': 0,
                               'added_chunk_ids': ['a'], 'removed_chunk_ids': ['a'],
                               'reloaded_chunk_ids': ['a'],
                               'timeline': [{'position': [0, 0]}, {'position': [1000, 0]},
                                            {'position': [0, 0]}]}}
    assert module.validate_map_context(result, 50, require_reload=True) == []
