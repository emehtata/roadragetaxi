#!/usr/bin/env python3
"""Losslessly repack existing audit sheets into ordered, native-size review atlases.

.venv/bin/python tools/visual_quality_audit_review.py
.venv/bin/python tools/visual_quality_audit_review.py --check
No rendering, new captures, or automatic visual approval is performed.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import html
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1] / 'docs/visual-quality-audit'
ANGLE_NAMES = ['front', 'rear', 'left', 'right', 'front_three_quarter', 'rear_three_quarter', 'top', 'elevated']


def digest(image):
    return hashlib.sha256(image.convert('RGB').tobytes()).hexdigest()


def layout(path, size):
    name = path.name
    if name.endswith('_eight-angles.png'):
        condition = name.rsplit('_eight-angles.png', 1)[0].rsplit('_', 1)[1]
        return 'initial-3d-' + condition, 400, 370, ANGLE_NAMES
    if name.startswith('canvas_'):
        return 'supplemental-canvas', 800, 630, ['normal', 'close']
    if name.startswith('context_'):
        return 'targeted-context', 800, 630, ['normal', 'close']
    if name.startswith('distance_'):
        return 'perspective-distances', 640, 510, ['close', 'normal', 'far']
    if name.startswith('indoor_'):
        return 'indoor-first-person', 640, 510, ['entry_forward', 'entry_left', 'entry_back', 'entry_right']
    return 'other-retained-evidence', size[0], size[1], ['whole image']


def build(data, root):
    directory = root / 'review'
    directory.mkdir(exist_ok=True)
    previous_path = directory / 'index.json'
    previous = json.loads(previous_path.read_text()) if previous_path.exists() else {'panels': []}
    def identity(panel):
        return panel['source'], tuple(panel['source_box']), panel['pixel_sha256']
    reviewed = {identity(panel): (int(panel['id'].split('-')[1]), panel['review_status']) for panel in previous['panels']}
    previous_panels = {panel['id']: panel for panel in previous['panels']}
    previous_pages = {page['file']: page for page in previous.get('pages', [])}
    by_source = defaultdict(dict)
    for asset in data['assets']:
        for evidence in asset.get('evidence', []):
            by_source[evidence['file']][evidence.get('row', 1)] = (asset, evidence)
    context = {}
    manifest = root / 'context-manifest.json'
    if manifest.exists():
        for record in json.loads(manifest.read_text())['captures']:
            if record.get('sheet'):
                context[(record['sheet'], record['panel'])] = record
    panels, sources = [], []
    for path in sorted(root.glob('*.png')):
        with Image.open(path) as image:
            family, width, height, defaults = layout(path, image.size)
            if image.width % width or image.height % height:
                raise ValueError(f'{path.name}: sheet does not fit expected panel dimensions')
            sources.append({'file': path.name, 'size': list(image.size)})
            for row in range(image.height // height):
                owner, evidence = by_source[path.name].get(row + 1, ({}, {}))
                views = evidence.get('angles', defaults)
                for column in range(image.width // width):
                    view = views[column] if column < len(views) else 'empty or unaccepted view slot'
                    limit = ''
                    if column >= len(views): limit = 'Empty or unavailable view slot; no inspection credit'
                    if family == 'supplemental-canvas' and owner.get('category') == 'Interior furniture':
                        limit = 'Initial room labels obscure the furniture target; use its targeted-context replacement. No furniture inspection credit.'
                    capture = context.get((path.name, column + 1)) if family == 'targeted-context' else None
                    if capture:
                        view = capture['angle']
                        if not capture['ready']: limit = capture.get('reason', 'Capture not accepted')
                    box = (column * width, row * height, (column + 1) * width, (row + 1) * height)
                    panels.append({'family': family, 'asset': owner.get('id'), 'name': owner.get('name', ''),
                                   'category': owner.get('category', ''), 'source': path.name, 'source_box': list(box),
                                   'view': view, 'condition': evidence.get('condition', family), 'limitation': limit,
                                   'pixel_sha256': digest(image.crop(box)), 'review_status': 'pending'})
    # Retain accepted and rejected gameplay images in separate review families.
    for path in sorted(root.glob('gameplay*/*/*/screenshot*.png')):
        result = json.loads((path.parent / 'result.json').read_text())
        review_path = path.parent / 'visual-review.json'
        review = json.loads(review_path.read_text()) if review_path.exists() else {}
        rejected = result.get('status') != 'passed' or review.get('accepted') is False or path.parent.parent.name == 'metallic_vehicle_paint_night'
        family = 'gameplay-rejected' if rejected else 'gameplay-accepted'
        if result.get('audit_temporal') and not rejected: family = 'gameplay-live-weather'
        relative = str(path.relative_to(root))
        with Image.open(path) as image:
            sources.append({'file': relative, 'size': list(image.size)})
            panels.append({'family': family, 'asset': None, 'name': path.parent.parent.name, 'category': 'Gameplay',
                           'source': relative, 'source_box': [0, 0, image.width, image.height], 'view': 'whole gameplay view',
                           'condition': str(result.get('game_time', 'named scenario')), 'limitation': 'Rejected as settled/visible gameplay evidence' if rejected else 'Representative context only',
                           'pixel_sha256': digest(image), 'review_status': 'pending'})
    runtime = root / 'runtime-manifest.json'
    if runtime.exists():
        assets = {a['id']: a for a in data['assets']}
        for record in json.loads(runtime.read_text())['captures']:
            path = root / record['file']
            with Image.open(path) as image:
                sources.append({'file': record['file'], 'size': list(image.size)})
                owner = assets.get(record['asset'], {})
                panels.append({'family': record['family'], 'asset': record['asset'],
                               'name': owner.get('name', record['asset']), 'category': owner.get('category', ''),
                               'source': record['file'], 'source_box': [0, 0, image.width, image.height],
                               'view': record['angle'], 'condition': record.get('condition', 'audit runtime'),
                               'limitation': record.get('limitation', '') if record['ready'] else 'Readiness failed; rejected',
                               'pixel_sha256': digest(image), 'review_status': 'pending'})
    groups = defaultdict(list)
    for panel in panels:
        if identity(panel) in reviewed:
            panel['review_status'] = reviewed[identity(panel)][1]
        box = panel['source_box']
        groups[(panel['family'], box[2] - box[0], box[3] - box[1])].append(panel)
    pages = []
    cached_source = None
    cached_image = None
    for (family, width, height), entries in sorted(groups.items()):
        print(f'Review atlas family {family}: {len(entries)} panels', flush=True)
        columns, rows = 2048 // width, 2048 // height
        if not columns or not rows:
            raise ValueError(f'{family}: {width}x{height} cannot fit a native-size 2048 atlas')
        # Append new evidence after previously indexed panels: reviewed page pixels and IDs stay stable.
        entries.sort(key=lambda p: (0, reviewed[identity(p)][0]) if identity(p) in reviewed else
                     (1, p['asset'] or p['name'], p['source'], p['source_box'][1], p['source_box'][0]))
        capacity = columns * rows
        for start in range(0, len(entries), capacity):
            selected = entries[start:start + capacity]
            filename = f'review/{family}_{start // capacity + 1:03}.png'
            size = [width * min(columns, len(selected)), height * ((len(selected) + columns - 1) // columns)]
            old = previous_pages.get(filename, {})
            reuse = (root / filename).is_file() and old.get('size') == size and len(old.get('panels', [])) == len(selected) and all(
                identity(panel) == identity(previous_panels[id_]) for panel, id_ in zip(selected, old.get('panels', [])))
            if reuse:
                try:
                    with Image.open(root / filename) as existing: existing.load()
                except OSError:
                    reuse = False  # Interrupted earlier composition: rebuild from intact source pixels.
            atlas = None if reuse else Image.new('RGB', tuple(size), '#16212c')
            ids = []
            for position, panel in enumerate(selected):
                x, y = position % columns * width, position // columns * height
                if not reuse:
                    if cached_source != panel['source']:
                        with Image.open(root / panel['source']) as source:
                            cached_image = source.convert('RGB')
                        cached_source = panel['source']
                    tile = cached_image.crop(panel['source_box'])
                    atlas.paste(tile, (x, y))
                panel.update(id=f'RP-{len(ids) + start + 1:05}-{family}', atlas=filename, atlas_box=[x, y, x + width, y + height])
                ids.append(panel['id'])
            if not reuse:
                destination = root / filename
                temporary = destination.with_suffix('.tmp.png')
                atlas.save(temporary, optimize=True)
                temporary.replace(destination)
            pages.append({'file': filename, 'family': family, 'size': size, 'panels': ids,
                          'assets': sorted({p['asset'] for p in selected if p['asset']})})
    referenced = {p['asset'] for p in panels if p['asset']}
    index = {'format': 1, 'pixel_policy': 'RGB source pixels copied without resizing; original label strips retained',
             'review_status': 'independent review complete' if all(p['review_status'] == 'independently inspected' for p in panels) else 'pending independent review of new or changed panels', 'sources': sources, 'pages': pages, 'panels': panels,
             'assets_without_panels': [{'id': a['id'], 'status': a['status'], 'reason': a.get('reason', '')} for a in data['assets'] if a['id'] not in referenced],
             'counts': {'source_images': len(sources), 'atlas_pages': len(pages), 'panels': len(panels), 'target_records': len(referenced)}}
    (directory / 'index.json').write_text(json.dumps(index, indent=2) + '\n')
    write_indexes(index, root)
    return index


def write_indexes(index, root):
    groups = defaultdict(list)
    for page in index['pages']: groups[page['family']].append(page)
    lines = ['# Full-resolution review atlas index', '',
             'No new captures. Original panel pixels and label strips are copied without resizing. Every atlas is at most 2048×2048 pixels. Open at 100% scale; a reduced overview does not count as full-resolution review.', '',
             f"{index['counts']['source_images']} source images → {index['counts']['atlas_pages']} ordered atlas pages; {index['counts']['panels']} panels; {index['counts']['target_records']} inventory records. {sum(p['review_status'] == 'independently inspected' for p in index['panels'])} panels independently reviewed; other panels remain pending. Rejected/empty slots are retained explicitly, not promoted to evidence.", '',
             '[Browser index (native pixels)](index.html) · [Exact panel/source rectangles and checklist](index.json)', '',
             'Review pending panels in each listed atlas in order. Unchanged source pixels retain prior independent review; new or changed pixels begin pending. Record atlas filenames/panel IDs and findings in the tester report; opening this index gives no review credit. Assets without panels are listed in index.json with their unused/uninspected reasons.', '']
    links = []
    for family, pages in groups.items():
        lines += ['## ' + family, '']
        section = ['<!doctype html><meta charset="utf-8"><title>' + html.escape(family) + '</title>',
                   '<style>body{background:#16212c;color:#eef;font:16px sans-serif}img{display:block;max-width:none;height:auto}figure{margin:24px 0}figcaption{position:sticky;top:0;background:#16212c;padding:8px}</style>',
                   '<h1>' + html.escape(family) + '</h1><p>Native source pixels. Scroll horizontally if necessary; use browser zoom 100%. Review each panel, including rejected/empty slots. Opening this page does not mark review complete.</p><p><a href="index.html">All families</a></p>']
        for page in pages:
            name = Path(page['file']).name
            complete = all(panel['review_status'] == 'independently inspected' for panel in index['panels'] if panel['atlas'] == page['file'])
            label = f"{name} · {len(page['panels'])} panels · {', '.join(page['assets']) or 'gameplay'}"
            lines.append(f'- [{"x" if complete else " "}] [{name}]({name}) — {len(page["panels"])} panels, {page["size"][0]}×{page["size"][1]}; {", ".join(page["assets"]) or "gameplay"}')
            section += [f'<figure><figcaption>{html.escape(label)}</figcaption><a href="{name}"><img loading="lazy" src="{name}" width="{page["size"][0]}" height="{page["size"][1]}" alt="{html.escape(label)}"></a></figure>']
        (root / 'review' / f'{family}.html').write_text('\n'.join(section))
        links.append(f'<li><a href="{family}.html">{family}: {len(pages)} atlas pages</a></li>')
        lines.append('')
    (root / 'review/README.md').write_text('\n'.join(lines))
    (root / 'review/index.html').write_text('<!doctype html><meta charset="utf-8"><title>Audit review index</title><h1>Full-resolution audit review</h1><p>Unscaled, lossless atlas panels; review is pending. Each family is one scrollable page. Use 100% browser zoom and inspect every panel. Rejected evidence remains separate.</p><ul>' + ''.join(links) + '</ul><p><a href="index.json">Panel/source mapping and pending review checklist</a></p>')


def validate(index, root):
    errors = []
    expected = set()
    for source in index['sources']:
        expected.add(source['file'])
    found = {p['source'] for p in index['panels']}
    if found != expected: errors.append('source image coverage mismatch')
    ids = [p['id'] for p in index['panels']]
    if len(ids) != len(set(ids)): errors.append('duplicate review panel IDs')
    for page in index['pages']:
        with Image.open(root / page['file']) as image:
            if max(image.size) > 2048 or list(image.size) != page['size']: errors.append(f"{page['file']}: invalid atlas size")
            for panel in [p for p in index['panels'] if p['atlas'] == page['file']]:
                if digest(image.crop(panel['atlas_box'])) != panel['pixel_sha256']: errors.append(f"{panel['id']}: atlas pixels changed")
    by_source = defaultdict(list)
    for panel in index['panels']: by_source[panel['source']].append(panel)
    for source, panels in by_source.items():
        with Image.open(root / source) as image:
            area = 0
            for panel in panels:
                x0, y0, x1, y1 = panel['source_box']
                area += (x1-x0)*(y1-y0)
                if digest(image.crop(panel['source_box'])) != panel['pixel_sha256']: errors.append(f"{panel['id']}: source pixels changed")
            if area != image.width*image.height: errors.append(f'{source}: incomplete panel coverage')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    index = json.loads((ROOT / 'review/index.json').read_text()) if args.check else build(json.loads((ROOT / 'inventory.json').read_text()), ROOT)
    print('Validating atlas/source pixels', flush=True)
    errors = validate(index, ROOT)
    print('\n'.join(errors) if errors else json.dumps(index['counts'], indent=2))
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
