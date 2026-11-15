#!/usr/bin/env python3
"""Lower the existing coach HVAC assembly 0.32 m onto its roof (VQA-012)."""
import argparse
import json
from pathlib import Path
import struct

from repair_vehicle_windscreens import accessor, read_glb


def repair(path: Path) -> int:
    document, data = read_glb(path)
    binary = bytearray(data)
    paint = document['meshes'][2]['primitives'][0]
    cap = accessor(document, binary, paint['attributes']['POSITION'])
    # The painted HVAC box is separate from the roof at 3.57 m. Already lowered: no change.
    cap_bottom = min(v[1] for v in cap if abs(v[0]) < 1.3 and v[1] > 3.6)
    if cap_bottom < 3.8:
        return 0
    assert abs(cap_bottom - 3.96) < 1e-5, 'unexpected coach HVAC geometry'
    changed = 0
    for mesh in document['meshes']:
        for primitive in mesh['primitives']:
            position = document['accessors'][primitive['attributes']['POSITION']]
            view = document['bufferViews'][position['bufferView']]
            vertices = accessor(document, binary, primitive['attributes']['POSITION'])
            for index, v in enumerate(vertices):
                if v[1] <= 3.8:
                    continue
                assert abs(v[0]) < 1.3 and abs(v[2]) < .64, 'unexpected non-HVAC vertex above roof'
                offset = view.get('byteOffset', 0) + position.get('byteOffset', 0) + index * view.get('byteStride', 12)
                struct.pack_into('<f', binary, offset + 4, v[1] - .32)
                changed += 1
            updated = accessor(document, binary, primitive['attributes']['POSITION'])
            position['min'] = [min(v[j] for v in updated) for j in range(3)]
            position['max'] = [max(v[j] for v in updated) for j in range(3)]
    assert changed == 914, f'unexpected HVAC vertex count: {changed}'
    encoded = json.dumps(document, separators=(',', ':')).encode()
    encoded += b' ' * (-len(encoded) % 4)
    path.write_bytes(struct.pack('<4sII', b'glTF', 2, 28 + len(encoded) + len(binary)) + struct.pack('<I4s', len(encoded), b'JSON') + encoded + struct.pack('<I4s', len(binary), b'BIN\0') + binary)
    return changed


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', nargs='?', type=Path, default=Path(__file__).resolve().parents[1] / 'godot/assets/vehicles/train_coach.glb')
    print(repair(parser.parse_args().path), 'HVAC vertices lowered')
