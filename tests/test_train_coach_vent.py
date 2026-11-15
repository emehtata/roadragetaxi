"""VQA-012: preserve all bytes except the recorded HVAC vertex heights."""
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from repair_train_coach_vent import repair
from repair_vehicle_windscreens import accessor, read_glb


HVAC_RANGES = {0: range(8632, 9482), 1: range(6034, 6074), 2: range(2600, 2624)}


def test_coach_geometry_preserved_and_vent_attached():
    document, binary = read_glb(ROOT / 'godot/assets/vehicles/train_coach.glb')
    masked = bytearray(binary)
    for mesh_id, mesh in enumerate(document['meshes']):
        primitive = mesh['primitives'][0]
        position = document['accessors'][primitive['attributes']['POSITION']]
        view = document['bufferViews'][position['bufferView']]
        vertices = accessor(document, binary, primitive['attributes']['POSITION'])
        selected = [vertices[i] for i in HVAC_RANGES.get(mesh_id, [])]
        if selected:
            assert min(v[1] for v in selected) >= 3.56999
            assert max(v[1] for v in selected) < 3.915
        for index in HVAC_RANGES.get(mesh_id, []):
            offset = view.get('byteOffset', 0) + position.get('byteOffset', 0) + index * view.get('byteStride', 12)
            struct.pack_into('<f', masked, offset + 4, 0)
        position.pop('min', None)
        position.pop('max', None)
    # Baselines recorded before the repair: normals, UVs, indices, textures, other
    # positions, materials and nodes are unchanged byte for byte.
    assert hashlib.sha256(masked).hexdigest() == '3f2444825463ee7b1ebb87858a1710d1cdbe916eb9c1920c94eca05802b5b3eb'
    assert hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest() == 'c74af1d059efb69c559e5f6322e2c89db9943cba5fd5a46cd9071266a51e7b75'
    primitive = document['meshes'][0]['primitives'][0]
    vertices = accessor(document, binary, primitive['attributes']['POSITION'])
    assert abs(min(vertices[i][1] for i in HVAC_RANGES[0]) - 3.57) < .00001
    # The painted box retains its original 25 cm thickness, above the feet.
    vertices = accessor(document, binary, document['meshes'][2]['primitives'][0]['attributes']['POSITION'])
    cap = [vertices[i][1] for i in HVAC_RANGES[2]]
    assert abs(min(cap) - 3.64) < .00001
    assert abs(max(cap) - 3.89) < .00001


def test_repair_is_idempotent(tmp_path):
    source = ROOT / 'godot/assets/vehicles/train_coach.glb'
    path = tmp_path / source.name
    path.write_bytes(source.read_bytes())
    assert repair(path) == 0
    assert path.read_bytes() == source.read_bytes()


def test_repair_lowers_only_the_existing_assembly(tmp_path):
    source = ROOT / 'godot/assets/vehicles/train_coach.glb'
    document, binary = read_glb(source)
    floating = bytearray(binary)
    moved_offsets = []
    for mesh_id, indices in HVAC_RANGES.items():
        primitive = document['meshes'][mesh_id]['primitives'][0]
        position = document['accessors'][primitive['attributes']['POSITION']]
        view = document['bufferViews'][position['bufferView']]
        for index in indices:
            offset = view.get('byteOffset', 0) + position.get('byteOffset', 0) + index * view.get('byteStride', 12) + 4
            struct.pack_into('<f', floating, offset, struct.unpack_from('<f', floating, offset)[0] + .32)
            moved_offsets.append(offset)
    encoded = json.dumps(document, separators=(',', ':')).encode()
    encoded += b' ' * (-len(encoded) % 4)
    path = tmp_path / source.name
    path.write_bytes(struct.pack('<4sII', b'glTF', 2, 28 + len(encoded) + len(floating)) + struct.pack('<I4s', len(encoded), b'JSON') + encoded + struct.pack('<I4s', len(floating), b'BIN\0') + floating)
    assert repair(path) == 914
    _, repaired = read_glb(path)
    for offset in moved_offsets:
        assert abs(struct.unpack_from('<f', repaired, offset)[0] - struct.unpack_from('<f', binary, offset)[0]) < .000001
        floating[offset:offset + 4] = repaired[offset:offset + 4]
    assert repaired == floating
    assert repair(path) == 0
