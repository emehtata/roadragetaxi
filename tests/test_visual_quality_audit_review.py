"""Review atlases must retain every source panel at its original pixel size."""
import importlib.util
from pathlib import Path

from PIL import Image


def reviewer():
    spec = importlib.util.spec_from_file_location('vqa_review', Path(__file__).parents[1] / 'tools/visual_quality_audit_review.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_atlases_preserve_every_panel_once_with_source_mapping(tmp_path):
    source = Image.new('RGB', (3200, 370))
    for column in range(8):
        source.paste((column * 30, 45, 100), (column * 400, 0, (column + 1) * 400, 370))
    source.save(tmp_path / 'vehicles_01_day_eight-angles.png')
    evidence = {'file': 'vehicles_01_day_eight-angles.png', 'row': 1, 'angles': ['front', 'rear', 'left', 'right', 'front_three_quarter', 'rear_three_quarter', 'top', 'elevated'], 'ready': True}
    data = {'assets': [{'id': 'A-001', 'name': 'car', 'category': 'Vehicles', 'status': 'partially inspected', 'evidence': [evidence, dict(evidence)]}]}
    module = reviewer()
    index = module.build(data, tmp_path)
    assert len(index['panels']) == 8
    assert {p['view'] for p in index['panels']} == set(evidence['angles'])
    assert all(p['asset'] == 'A-001' for p in index['panels'])
    for panel in index['panels']:
        with Image.open(tmp_path / panel['atlas']) as atlas:
            assert atlas.width <= 2048 and atlas.height <= 2048
            assert atlas.crop(panel['atlas_box']).tobytes() == source.crop(panel['source_box']).tobytes()
    assert module.validate(index, tmp_path) == []


def test_review_validation_rejects_changed_source_pixels(tmp_path):
    source = Image.new('RGB', (1600, 630), (10, 20, 30))
    source.save(tmp_path / 'context_A-001_normal-close.png')
    data = {'assets': [{'id': 'A-001', 'name': 'bed', 'category': 'Interior furniture', 'status': 'partially inspected', 'evidence': [{'file': 'context_A-001_normal-close.png', 'row': 1, 'angles': ['normal', 'close']}]}]}
    module = reviewer()
    index = module.build(data, tmp_path)
    source.putpixel((20, 20), (200, 100, 50))
    source.save(tmp_path / 'context_A-001_normal-close.png')
    assert any('source pixels' in error for error in module.validate(index, tmp_path))


def test_runtime_frames_keep_manifest_identity_in_review_atlases(tmp_path):
    (tmp_path / 'runtime').mkdir()
    Image.new('RGB', (640, 480), (10, 20, 30)).save(tmp_path / 'runtime/forest_399.png')
    import json
    (tmp_path / 'runtime-manifest.json').write_text(json.dumps({'captures': [
        {'file': 'runtime/forest_399.png', 'asset': 'A-070', 'family': 'runtime-lod',
         'angle': '399 m before visibility boundary', 'ready': True}]}))
    index = reviewer().build({'assets': []}, tmp_path)
    assert len(index['panels']) == 1
    assert index['panels'][0]['asset'] == 'A-070'
    assert index['panels'][0]['view'] == '399 m before visibility boundary'
    assert index['panels'][0]['family'] == 'runtime-lod'


def test_rebuild_preserves_review_of_unchanged_panels_without_crediting_new_images(tmp_path):
    import json
    source = tmp_path / 'context_A-002_normal-close.png'
    Image.new('RGB', (1600, 630), (1, 2, 3)).save(source)
    module = reviewer()
    data = {'assets': []}
    old = module.build(data, tmp_path)
    for panel in old['panels']: panel['review_status'] = 'independently inspected'
    (tmp_path / 'review/index.json').write_text(json.dumps(old))
    Image.new('RGB', (1600, 630), (4, 5, 6)).save(tmp_path / 'context_A-001_normal-close.png')
    new = module.build(data, tmp_path)
    retained = [p for p in new['panels'] if p['source'] == source.name]
    added = [p for p in new['panels'] if p['source'] != source.name]
    assert [p['id'] for p in retained] == [p['id'] for p in old['panels']]
    assert all(p['review_status'] == 'independently inspected' for p in retained)
    assert all(p['review_status'] == 'pending' for p in added)


def test_temporal_gameplay_capture_is_included_in_independent_review(tmp_path):
    import json
    run = tmp_path / 'gameplay_strict' / 'snow_animation' / 'run'
    run.mkdir(parents=True)
    for filename in ['screenshot.png', 'screenshot_2.png']:
        Image.new('RGB', (1280, 720), (1, 2, 3)).save(run / filename)
    (run / 'result.json').write_text(json.dumps({'status': 'passed'}))
    index = reviewer().build({'assets': []}, tmp_path)
    assert {Path(p['source']).name for p in index['panels']} == {'screenshot.png', 'screenshot_2.png'}


def test_rebuild_keeps_unchanged_atlas_file_when_adding_another_family(tmp_path):
    Image.new('RGB', (1600, 630), (1, 2, 3)).save(tmp_path / 'canvas_01_normal-close.png')
    module = reviewer()
    old = module.build({'assets': []}, tmp_path)
    page = tmp_path / old['pages'][0]['file']
    timestamp = page.stat().st_mtime_ns
    Image.new('RGB', (1600, 630), (4, 5, 6)).save(tmp_path / 'context_A-001_normal-close.png')
    module.build({'assets': []}, tmp_path)
    assert page.stat().st_mtime_ns == timestamp


def test_rebuild_repairs_an_interrupted_atlas_write(tmp_path):
    Image.new('RGB', (1600, 630), (1, 2, 3)).save(tmp_path / 'canvas_01_normal-close.png')
    module = reviewer()
    old = module.build({'assets': []}, tmp_path)
    page = tmp_path / old['pages'][0]['file']
    page.write_bytes(page.read_bytes()[:100])
    new = module.build({'assets': []}, tmp_path)
    assert module.validate(new, tmp_path) == []


def test_panel_ids_survive_metadata_array_reordering(tmp_path):
    import json
    Image.new('RGB', (1600, 630), (1, 2, 3)).save(tmp_path / 'canvas_01_normal-close.png')
    module = reviewer()
    old = module.build({'assets': []}, tmp_path)
    expected = {tuple(p['source_box']): p['id'] for p in old['panels']}
    old['panels'].reverse()
    (tmp_path / 'review/index.json').write_text(json.dumps(old))
    new = module.build({'assets': []}, tmp_path)
    assert {tuple(p['source_box']): p['id'] for p in new['panels']} == expected
