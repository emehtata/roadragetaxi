"""Asset preservation for VQA-001–005; geometric coverage runs in Godot."""
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('repair_vehicle_windscreens', ROOT/'tools/repair_vehicle_windscreens.py')
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)
BASELINE = json.loads((ROOT/'godot/tests/data/vehicle_windscreens.json').read_text())


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, separators=(',', ':'), sort_keys=True).encode()).hexdigest()


def test_only_windscreen_body_indices_and_boundary_vertices_changed():
    for kind, baseline in BASELINE.items():
        path = ROOT/f'godot/assets/vehicles/{kind}.glb'
        document, binary = repair.read_glb(path)
        assert fingerprint(document['nodes']) == baseline['nodes'], kind
        assert fingerprint(document['materials']) == baseline['materials'], kind
        body = document['meshes'][document['nodes'][1]['mesh']]['primitives'][0]
        for key, expected in baseline['body_attributes'].items():
            values = repair.accessor(document, binary, body['attributes'][key])
            assert fingerprint(values[:expected['count']]) == expected['sha256'], (kind, key)
        others = []
        for mesh in document['meshes']:
            for primitive in mesh['primitives']:
                if primitive is body:
                    continue
                others.append({'attributes': {key: fingerprint(repair.accessor(document, binary, index)) for key, index in primitive['attributes'].items()},
                               'indices': fingerprint(repair.accessor(document, binary, primitive['indices']))})
        assert others == baseline['others'], kind
    assert hashlib.sha256((ROOT/'godot/assets/vehicles/saloon.glb').read_bytes()).hexdigest() == BASELINE['saloon']['sha256']


def test_repair_is_idempotent(tmp_path):
    for kind in repair.KINDS:
        path = tmp_path/f'{kind}.glb'
        original = (ROOT/f'godot/assets/vehicles/{kind}.glb').read_bytes()
        path.write_bytes(original)
        assert repair.repair(path) == 0, kind
        assert path.read_bytes() == original, kind
