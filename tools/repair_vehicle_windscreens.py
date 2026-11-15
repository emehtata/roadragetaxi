#!/usr/bin/env python3
"""Subtract the existing front-glass footprint from residual painted windscreen faces.

Run once on the five original GLBs (or rerun: an already repaired model is unchanged).
Only the main painted primitive gains clipped boundary vertices/indices. Glass and
all other primitives/materials retain their original bytes. Requires project Shapely.
"""
from __future__ import annotations
import argparse
import copy
import json
import math
from pathlib import Path
import struct

from shapely import constrained_delaunay_triangles
from shapely.geometry import Polygon
from shapely.ops import unary_union

KINDS = ('hatchback', 'estate', 'suv', 'pickup', 'panel_van')
ROOT = Path(__file__).resolve().parents[1]


def read_glb(path):
    raw = path.read_bytes()
    length, tag = struct.unpack_from('<I4s', raw, 12)
    assert tag == b'JSON'
    document = json.loads(raw[20:20 + length])
    binary_length, tag = struct.unpack_from('<I4s', raw, 20 + length)
    assert tag == b'BIN\x00'
    return document, raw[28 + length:28 + length + binary_length]


def accessor(document, binary, index):
    a = document['accessors'][index]
    view = document['bufferViews'][a['bufferView']]
    code = {5121: 'B', 5123: 'H', 5125: 'I', 5126: 'f'}[a['componentType']]
    count = {'SCALAR': 1, 'VEC3': 3}[a['type']]
    size = struct.calcsize('<' + code * count)
    return [struct.unpack_from('<' + code * count, binary, view.get('byteOffset', 0) + a.get('byteOffset', 0) + i * view.get('byteStride', size)) for i in range(a['count'])]


def world_vertices(document, binary, node):
    assert 'rotation' not in node and 'matrix' not in node
    primitive = document['meshes'][node['mesh']]['primitives'][0]
    scale = node.get('scale', [1, 1, 1])
    position = node.get('translation', [0, 0, 0])
    return primitive, [tuple(v[i] * scale[i] + position[i] for i in range(3)) for v in accessor(document, binary, primitive['attributes']['POSITION'])]


def barycentric(point, triangle):
    a, b, c = triangle
    den = (b[0]-a[0])*(c[1]-a[1])-(c[0]-a[0])*(b[1]-a[1])
    if abs(den) < 1e-12:
        return None
    s = ((point[0]-a[0])*(c[1]-a[1])-(point[1]-a[1])*(c[0]-a[0]))/den
    t = ((b[0]-a[0])*(point[1]-a[1])-(b[1]-a[1])*(point[0]-a[0]))/den
    return (1-s-t, s, t)


def interpolate(weights, values):
    return tuple(sum(weights[j]*values[j][i] for j in range(3)) for i in range(3))


def repair(path):
    assert path.stem in KINDS, "only the five audited source models may be repaired"
    document, binary = read_glb(path)
    original = copy.deepcopy(document)
    body_node, glass_node = document['nodes'][1], document['nodes'][3]
    body, vertices = world_vertices(document, binary, body_node)
    glass, glass_vertices = world_vertices(document, binary, glass_node)
    assert document['materials'][body['material']]['name'].startswith('paint')
    assert document['materials'][glass['material']]['name'] == 'glass'
    assert set(body['attributes']) == {'POSITION', 'NORMAL'}
    glass_ids = [x[0] for x in accessor(document, binary, glass['indices'])]
    panes = []
    for at in range(0, len(glass_ids), 3):
        triangle = [glass_vertices[i] for i in glass_ids[at:at+3]]
        a, b, c = triangle
        u, v = [b[i]-a[i] for i in range(3)], [c[i]-a[i] for i in range(3)]
        normal = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
        size = math.sqrt(sum(x*x for x in normal))
        if size and normal[2]/size > .3 and normal[1]/size > .2 and sum(p[2] for p in triangle) > 0:
            panes.append(triangle)
    assert panes
    # Keep a narrow painted surround at the existing glass boundary.
    opening = unary_union([Polygon([(p[0], p[1]) for p in tri]) for tri in panes]).buffer(-.015, join_style=2)
    ids = [x[0] for x in accessor(document, binary, body['indices'])]
    normals = accessor(document, binary, body['attributes']['NORMAL'])
    new_vertices, new_normals = [], []
    result = []
    changed = 0
    for at in range(0, len(ids), 3):
        face = ids[at:at+3]
        triangle = [vertices[i] for i in face]
        shape = Polygon([(p[0], p[1]) for p in triangle])
        if shape.area < 1e-12 or not shape.intersects(opening):
            result.extend(face)
            continue
        overlap = shape.intersection(opening)
        sample = overlap.representative_point()
        weights = barycentric((sample.x, sample.y), triangle)
        paint_z = interpolate(weights, triangle)[2]
        glass_z = max((interpolate(w, pane)[2] for pane in panes if (w := barycentric((sample.x, sample.y), pane)) is not None and min(w) >= -1e-6), default=-math.inf)
        if abs(paint_z-glass_z) > .10 or overlap.area < 1e-7:
            result.extend(face)
            continue
        remaining = shape.difference(opening)
        changed += 1
        orientation = (triangle[1][0]-triangle[0][0])*(triangle[2][1]-triangle[0][1])-(triangle[2][0]-triangle[0][0])*(triangle[1][1]-triangle[0][1])
        for piece in constrained_delaunay_triangles(remaining).geoms:
            points = list(piece.exterior.coords)[:3]
            if ((points[1][0]-points[0][0])*(points[2][1]-points[0][1])-(points[2][0]-points[0][0])*(points[1][1]-points[0][1])) * orientation < 0:
                points.reverse()
            for point in points:
                weights = barycentric(point, triangle)
                new_vertices.append(interpolate(weights, triangle))
                n = interpolate(weights, [normals[i] for i in face])
                norm = math.sqrt(sum(x*x for x in n))
                new_normals.append(tuple(x/norm for x in n))
                result.append(len(vertices)+len(new_vertices)-1)
    if not changed:
        return 0
    # Preserve every existing buffer view byte; append only new body records and indices.
    buffers = [binary[v.get('byteOffset', 0):v.get('byteOffset', 0)+v['byteLength']] for v in document['bufferViews']]
    pos = document['accessors'][body['attributes']['POSITION']]
    normal = document['accessors'][body['attributes']['NORMAL']]
    view_id = pos['bufferView']
    assert normal['bufferView'] == view_id and document['bufferViews'][view_id]['byteStride'] == 24
    assert pos.get('byteOffset', 0) == 0 and normal.get('byteOffset') == 12
    scale = body_node['scale']; translation = body_node['translation']
    for v, n in zip(new_vertices, new_normals):
        local = tuple((v[i]-translation[i])/scale[i] for i in range(3))
        buffers[view_id] += struct.pack('<6f', *local, *n)
    pos['count'] += len(new_vertices)
    normal['count'] += len(new_vertices)
    # Existing bounds remain unchanged: every new point lies on an original triangle.
    new_view = len(buffers)
    buffers.append(struct.pack('<'+'I'*len(result), *result))
    document['bufferViews'].append({'buffer': 0, 'target': 34963})
    index = copy.deepcopy(document['accessors'][body['indices']])
    index.update(bufferView=new_view, byteOffset=0, componentType=5125, count=len(result), min=[min(result)], max=[max(result)])
    document['accessors'].append(index)
    body['indices'] = len(document['accessors'])-1
    output = bytearray()
    for view, data in zip(document['bufferViews'], buffers):
        output.extend(b'\0' * (-len(output) % 4))
        view.update(byteOffset=len(output), byteLength=len(data))
        output.extend(data)
    document['buffers'][0]['byteLength'] = len(output)
    output.extend(b'\0' * (-len(output) % 4))
    encoded = json.dumps(document, separators=(',', ':')).encode()
    encoded += b' ' * (-len(encoded) % 4)
    path.write_bytes(struct.pack('<4sII', b'glTF', 2, 28+len(encoded)+len(output)) + struct.pack('<I4s',len(encoded),b'JSON') + encoded + struct.pack('<I4s',len(output),b'BIN\0') + output)
    # No material, node transform or non-body primitive may change.
    assert document['materials'] == original['materials'] and document['nodes'] == original['nodes']
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths', nargs='*', type=Path)
    args = parser.parse_args()
    for path in args.paths or [ROOT/'godot/assets/vehicles'/f'{kind}.glb' for kind in KINDS]:
        print(path.name, repair(path), 'paint triangles clipped')

if __name__ == '__main__':
    main()
