"""FLA export admission, provenance and the existing pose workflow in isolation.

The tiny PNG receipt is a test double for Animate. These tests never launch a
native application and do not claim to verify Adobe's rendering fidelity.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import zipfile

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/common'))

from multispecies import DataError
from multispecies.catalog import fingerprint
from workflow import ProjectContext
from workflow.character_fla import CharacterFlaWorkflow, SCHEMA


class NoLaunchRenderer:
    def status(self):
        return {'available': True, 'reason': '测试回执；不启动 Animate'}

    def run(self, *args, **kwargs):
        pytest.fail('This test must not launch a renderer')


@pytest.fixture
def engineering(tmp_path):
    source = tmp_path/'角色源素材'/'角色 空格.fla'; source.parent.mkdir()
    document = '''<DOMDocument width="120" height="90" frameRate="24">
      <symbols><Include href="whole.xml"/></symbols>
      <timelines><DOMTimeline name="舞台"><layers><DOMLayer name="角色"><frames>
        <DOMFrame index="0" duration="3"><elements><DOMSymbolInstance libraryItemName="角色/侧面"/></elements></DOMFrame>
      </frames></DOMLayer></layers></DOMTimeline></timelines></DOMDocument>'''
    symbol = '''<DOMSymbolItem name="角色/侧面"><timeline><DOMTimeline name="侧面"><layers><DOMLayer name="形体"><frames>
       <DOMFrame index="0" duration="3"><elements/></DOMFrame>
       </frames></DOMLayer></layers></DOMTimeline></timeline></DOMSymbolItem>'''
    with zipfile.ZipFile(source, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('DOMDocument.xml', document)
        archive.writestr('LIBRARY/whole.xml', symbol)
    ctx = ProjectContext(ROOT, tmp_path/'isolated library')
    added = ctx.sources.add_inputs([str(source)])
    ctx.sources.scan(added['root_ids'][0])
    file = ctx.sources.list_files()['items'][0]
    ctx.sources.probe(file['id']); file = ctx.sources.file(file['id'])
    flow = CharacterFlaWorkflow(ctx, renderer=NoLaunchRenderer())
    ctx.characters = flow
    manifest = flow.inspect(file['id'])
    yield SimpleNamespace(ctx=ctx, flow=flow, source=source, file=file, manifest=manifest,
                          tmp_path=tmp_path, original=source.read_bytes())
    ctx.close()


def export_request(t, timeline='symbol:角色/侧面', **kwargs):
    return t.flow.prepare_export(t.file['id'], timeline, **kwargs)


def receipt(bundle, *, color=(140, 40, 200, 255)):
    directory = Path(bundle['directory']); request = bundle['request']
    frames = []
    for ordinal in request['frames0']:
        name = f'frame_{ordinal:05d}.png'
        image = Image.new('RGBA', (120, 90), color)
        image.putpixel((ordinal+1, 1), (10, 240, 70, 255))
        image.save(directory/'frames'/name)
        frames.append(dict(file=name, frame_index0=ordinal, timeline_id=request['timeline']['id']))
    result = dict(schema_version=SCHEMA, export_id=request['export_id'], operation=request['operation'],
                  request_sha256=request['request_sha256'], copy_uri=request['copy_uri'], state='done',
                  renderer=dict(name='Adobe Animate', version='24.0.4 test double'),
                  frames=frames, exported_count=len(frames))
    write_receipt(bundle, result)
    return result


def write_receipt(bundle, result):
    Path(bundle['result_path']).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')


def legacy_source(t):
    source = t.source.parent/'旧版角色.fla'
    source.write_bytes(bytes.fromhex('d0cf11e0a1b11ae1') + b'isolated OLE fixture')
    added = t.ctx.sources.add_inputs([str(source)])
    t.ctx.sources.scan(added['root_ids'][0])
    file = next(f for f in t.ctx.sources.list_files()['items'] if f['path']==str(source))
    t.ctx.sources.probe(file['id'])
    return source, t.ctx.sources.file(file['id'])


def inspection_receipt(bundle):
    request = bundle['request']
    result = dict(schema_version=SCHEMA, export_id=request['export_id'], operation=request['operation'],
        request_sha256=request['request_sha256'], copy_uri=request['copy_uri'], state='done',
        renderer=dict(name='Adobe Animate', version='24.0.4 test double'), frames=[],
        timelines=[dict(id='scene:0', kind='scene', name='场景一', index0=0, frame_count=3,
                        suggested=True, reason='主场景'),
                   dict(id='symbol:角色/侧面', kind='symbol', name='角色/侧面', index0=None,
                        frame_count=3, suggested=True, reason='复合元件')])
    write_receipt(bundle, result)
    return result


def assert_empty(t):
    assert t.flow.positions(t.file['id']) == []
    assert t.ctx.dataset.candidates() == []
    assert t.ctx.library.records() == []


def test_prepare_makes_fingerprinted_private_copy_and_never_changes_original(engineering):
    t = engineering
    bundle = export_request(t, start=1, stop=3, step=2)
    request = bundle['request']; directory = Path(bundle['directory'])
    assert request['frames0'] == [0, 2]
    assert request['timeline']['id'] == 'symbol:角色/侧面'
    assert request['request_sha256'] == fingerprint({k:v for k,v in request.items() if k!='request_sha256'})
    assert request['source_sha256'] == hashlib.sha256(t.original).hexdigest()
    assert (directory/'source.fla').read_bytes() == t.original == t.source.read_bytes()
    assert directory.resolve().is_relative_to(t.ctx.library.root.resolve())
    assert request['copy_uri'] == (directory/'source.fla').as_uri()
    script = Path(bundle['script_path']).read_text(encoding='utf-8')
    assert '__PONY_CHARACTER_REQUEST__' not in script and request['export_id'] in script
    assert not Path(bundle['result_path']).exists()
    assert_empty(t)


def test_inspect_reuses_verified_version_cache_but_refresh_rechecks_and_status_is_live(engineering, monkeypatch):
    from source_catalog import fla_structure
    t = engineering; original = fla_structure.inspect_structure
    calls = []
    def inspect(path):
        calls.append(path)
        return original(path)
    monkeypatch.setattr(fla_structure, 'inspect_structure', inspect)
    monkeypatch.setattr(t.flow.renderer, 'status', lambda: {'available':False, 'reason':'测试中移除了渲染程序'})
    cached = t.flow.inspect(t.file['id'])
    assert calls == []
    assert cached['timelines'] == t.manifest['timelines']
    assert cached['renderer']['available'] is False
    fresh = t.flow.inspect(t.file['id'], refresh=True)
    assert calls == [t.source]
    assert fresh['version_id'] == t.file['version_id']
    t.source.write_bytes(t.original+b'changed after inspection')
    with pytest.raises(DataError):
        t.flow.inspect(t.file['id'])


def test_accept_inspection_binds_old_source_and_can_prepare_exact_symbol_from_cache(engineering, monkeypatch):
    t = engineering; source, file = legacy_source(t)
    original = source.read_bytes()
    bundle = t.flow.prepare_export(file['id'], operation='inspect')
    native = inspection_receipt(bundle)
    accepted = t.flow.accept_inspection(bundle['export_id'])
    assert accepted['file_id'] == file['id']
    assert accepted['version_id'] == file['version_id']
    assert accepted['container'] == 'ole'
    assert accepted['timelines'] == native['timelines']
    assert accepted['inspection_export_ref'] == bundle['export_id']
    assert t.flow.inspect(file['id']) == accepted  # NoLaunchRenderer.run must never be reached.
    render = t.flow.prepare_export(file['id'], 'symbol:角色/侧面', start=2, stop=2)
    assert render['request']['frames0'] == [1]
    assert render['request']['timeline']['name'] == '角色/侧面'
    assert source.read_bytes() == original
    assert t.flow.positions(file['id']) == []
    assert t.ctx.dataset.candidates() == []


@pytest.mark.parametrize('damage', ['wrong_source_version', 'source_changed', 'wrong_copy', 'wrong_operation',
                                  'duplicate_id', 'empty_id', 'empty_name', 'symbol_identity',
                                  'scene_identity', 'scene_bool_index', 'bool_count'])
def test_accept_inspection_rejects_bad_binding_and_ambiguous_timelines(engineering, damage):
    t = engineering; source, file = legacy_source(t)
    if damage == 'wrong_operation':
        bundle = export_request(t, stop=1)
    else:
        bundle = t.flow.prepare_export(file['id'], operation='inspect')
    native = inspection_receipt(bundle)
    if damage == 'wrong_source_version': native['request_sha256'] = '0'*64
    elif damage == 'source_changed': source.write_bytes(source.read_bytes()+b'changed')
    elif damage == 'wrong_copy': native['copy_uri'] = source.as_uri()
    elif damage == 'duplicate_id': native['timelines'].append(dict(native['timelines'][1]))
    elif damage == 'empty_id': native['timelines'][1]['id'] = ''
    elif damage == 'empty_name': native['timelines'][1]['name'] = ''
    elif damage == 'symbol_identity': native['timelines'][1]['id'] = 'symbol:另一个角色'
    elif damage == 'scene_identity': native['timelines'][0]['id'] = 'scene:1'
    elif damage == 'scene_bool_index': native['timelines'][0]['index0'] = False
    elif damage == 'bool_count': native['timelines'][1]['frame_count'] = True
    write_receipt(bundle, native)
    with pytest.raises(DataError):
        t.flow.accept_inspection(bundle['export_id'])
    assert not (t.ctx.sources.cache/('character_structure_'+file['version_id']+'.json')).exists()
    assert t.ctx.dataset.candidates() == []


def test_ole_refresh_rechecks_completed_inspection(engineering, monkeypatch):
    t = engineering; _, file = legacy_source(t)
    calls = []
    def run(bundle, checkpoint):
        calls.append(bundle['export_id'])
        result = inspection_receipt(bundle)
        return result
    monkeypatch.setattr(t.flow.renderer, 'run', run)
    first = t.flow.inspect(file['id'])
    assert len(calls) == 1
    assert t.flow.inspect(file['id']) == first
    assert len(calls) == 1
    refreshed = t.flow.inspect(file['id'], refresh=True)
    assert len(calls) == 2
    assert calls[0] != calls[1]
    assert first['inspection_export_ref'] != refreshed['inspection_export_ref']


def test_ole_inspection_timeout_reuses_unfinished_request_even_when_refreshing(engineering, monkeypatch):
    t = engineering; _, file = legacy_source(t)
    calls = []
    def run(bundle, checkpoint):
        calls.append(bundle['export_id'])
        if len(calls) == 1:
            raise ValueError('simulated host dialog timeout')
        return inspection_receipt(bundle)
    monkeypatch.setattr(t.flow.renderer, 'run', run)
    with pytest.raises(ValueError, match='timeout'):
        t.flow.inspect(file['id'])
    assert t.ctx.dataset.candidates() == []
    accepted = t.flow.inspect(file['id'], refresh=True)
    assert len(calls) == 2 and calls[0] == calls[1]
    assert accepted['inspection_export_ref'] == calls[0]
    assert len(list(t.flow.root.iterdir())) == 1


def test_admitted_frames_follow_candidates_regions_samples_query_and_source_location(engineering):
    t = engineering; bundle = export_request(t, start=2, stop=3); receipt(bundle)
    accepted = t.flow.accept_export(bundle['export_id'])
    assert len(accepted['position_ids']) == len(accepted['candidate_ids']) == 2
    records = []
    for pid in accepted['position_ids']:
        candidate = t.ctx.dataset.candidate(pid)
        assert candidate['decision'] == 'undecided'
        selected = t.ctx.dataset.decide(pid, 'selected', expected=candidate['revision'])
        region = t.ctx.dataset.region(selected['id'], [10, 10, 90, 60], 'twilight.unicorn@1', review_status='approved')
        record = t.ctx.dataset.generate(region['id'], region['revision'])['record']
        assert record['source']['locator_ref'] == pid
        assert record['source']['precision'] == 'timeline_exact'
        assert record['source']['source_to_image'] == [1, 0, 0, 1, -10, -10]
        assert record['annotation']['directions'] == {}
        records.append(t.ctx.library.edit(record['observation_id'], record['annotation']['id'],
            {'parts': {'core': {'presence': 'present'}},
             'directions': {'core.head': {'value': [1, 0], 'visibility': 'visible'}}},
            actor='人工审核', review={'status': 'approved', 'targets': ['parts.core', 'directions.core.head']}))
    query = t.ctx.poses.prepare_query(records[0]['observation_id'], source_filters={'exact': True, 'format': 'FLA'})
    results = t.ctx.poses.search(query['id'])
    assert len(results['results']) == 1
    hit = results['results'][0]
    assert hit['observation_id'] == records[1]['observation_id']
    assert hit['score'] == pytest.approx(1)
    assert hit['location']['path'] == str(t.source)
    assert hit['location']['position']['timeline_id'] == 'symbol:角色/侧面'
    assert hit['location']['position']['frame_index0'] == 2
    assert hit['location']['precision'] == 'timeline_exact'
    assert '角色/侧面' in hit['position_text'] and '3' in hit['position_text']
    assert '视频帧' not in hit['position_text']
    assert t.ctx.poses.result(results['run_id']) == results
    assert t.source.read_bytes() == t.original


def test_repeated_accept_and_new_identical_export_keep_manual_exclusion(engineering):
    t = engineering; bundle = export_request(t, stop=1); receipt(bundle)
    first = t.flow.accept_export(bundle['export_id']); pid = first['position_ids'][0]
    candidate = t.ctx.dataset.candidate(pid)
    excluded = t.ctx.dataset.decide(pid, 'excluded', expected=candidate['revision'])
    assert t.flow.accept_export(bundle['export_id']) == first
    another = export_request(t, stop=1); receipt(another)
    again = t.flow.accept_export(another['export_id'])
    assert again['position_ids'] == first['position_ids']
    assert again['candidate_ids'] == first['candidate_ids']
    assert t.ctx.dataset.candidate(pid) == excluded
    assert len(t.ctx.dataset.candidates()) == 1


def test_same_frame_in_scene_and_symbol_stays_separate(engineering):
    t = engineering
    symbol = export_request(t, stop=1); receipt(symbol)
    scene = export_request(t, timeline='scene:0', stop=1); receipt(scene)
    a = t.flow.accept_export(symbol['export_id'])['position_ids'][0]
    b = t.flow.accept_export(scene['export_id'])['position_ids'][0]
    assert a != b
    assert [p['id'] for p in t.flow.positions(t.file['id'], 'symbol:角色/侧面')] == [a]
    assert [p['id'] for p in t.flow.positions(t.file['id'], 'scene:0')] == [b]
    assert t.ctx.sources.position(a)['payload']['coordinates'] == 'symbol_export_pixels'
    assert t.ctx.sources.position(b)['payload']['coordinates'] == 'stage_export_pixels'


def test_shared_queue_honors_pause_cancels_unstarted_job_and_reuses_receipt(engineering):
    t = engineering
    cancelled = t.flow.queue_export(t.file['id'], 'scene:0', stop=1)
    t.ctx.sources.cancel(cancelled)
    assert t.ctx.sources.job(cancelled)['state'] == 'cancelled'
    jid = t.flow.queue_export(t.file['id'], 'symbol:角色/侧面', start=2, stop=2)
    job = t.ctx.sources.job(jid)
    export_id = job['parameters']['export_id']; directory = t.flow.root/export_id
    bundle = dict(export_id=export_id, directory=str(directory), result_path=str(directory/'result.json'),
                  request=json.loads((directory/'request.json').read_text(encoding='utf-8')))
    receipt(bundle)
    t.ctx.sources.pause(True)
    assert t.ctx.sources.run_next() is False
    assert t.ctx.sources.job(jid)['state'] == 'queued'
    assert_empty(t)
    t.ctx.sources.pause(False)
    for _ in range(20):
        if not t.ctx.sources.run_next(): break
    assert t.ctx.sources.job(jid)['state'] == 'done'
    assert t.ctx.sources.job(cancelled)['state'] == 'cancelled'
    assert len(t.flow.positions(t.file['id'])) == 1
    assert t.flow.positions(t.file['id'])[0]['payload']['frame_index0'] == 1


def test_interrupted_accept_resumes_from_receipt_without_overwriting_review(engineering, monkeypatch):
    from source_catalog.store import Interrupted
    t = engineering; bundle = export_request(t); receipt(bundle)
    original = t.ctx.dataset.decide
    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise Interrupted()
    monkeypatch.setattr(t.ctx.dataset, 'decide', interrupted)
    with pytest.raises(Interrupted):
        t.flow.execute(bundle['export_id'])
    existing = t.flow.positions(t.file['id'])
    assert len(existing) == 1
    monkeypatch.setattr(t.ctx.dataset, 'decide', original)
    pid = existing[0]['id']; candidate = t.ctx.dataset.candidate(pid)
    reviewed = t.ctx.dataset.decide(pid, 'excluded', expected=candidate['revision'])
    resumed = t.flow.execute(bundle['export_id'])
    assert len(resumed['position_ids']) == len(t.ctx.dataset.candidates()) == 3
    assert t.ctx.dataset.candidate(pid) == reviewed


@pytest.mark.parametrize('damage', ['source', 'copy', 'request', 'script'])
def test_changed_inputs_are_rejected_before_any_position_is_published(engineering, damage):
    t = engineering; bundle = export_request(t, stop=1); receipt(bundle)
    directory = Path(bundle['directory'])
    if damage == 'source':
        t.source.write_bytes(t.original + b'changed')
    elif damage == 'copy':
        (directory/'source.fla').write_bytes(t.original + b'changed')
    elif damage == 'script':
        Path(bundle['script_path']).write_text('// changed export implementation', encoding='utf-8')
    else:
        path = directory/'request.json'; request = json.loads(path.read_text(encoding='utf-8'))
        request['frames0'] = [1]; path.write_text(json.dumps(request), encoding='utf-8')
    with pytest.raises(DataError):
        t.flow.accept_export(bundle['export_id'])
    assert_empty(t)


@pytest.mark.parametrize('damage', ['export_id', 'request_hash', 'copy_uri', 'failed', 'renderer',
                                  'missing', 'timeline', 'path', 'duplicate_file', 'bool_frame', 'float_frame'])
def test_wrong_receipt_is_rejected_before_any_position_is_published(engineering, damage):
    t = engineering; bundle = export_request(t, stop=2); result = receipt(bundle)
    if damage == 'export_id': result['export_id'] = 'other_export'
    elif damage == 'request_hash': result['request_sha256'] = '0'*64
    elif damage == 'copy_uri': result['copy_uri'] = t.source.as_uri()
    elif damage == 'failed': result['state'] = 'failed'
    elif damage == 'renderer': result['renderer']['name'] = 'Other Renderer'
    elif damage == 'missing': result['frames'].pop()
    elif damage == 'timeline': result['frames'][1]['timeline_id'] = 'scene:0'
    elif damage == 'path': result['frames'][1]['file'] = '../outside.png'
    elif damage == 'duplicate_file': result['frames'][1]['file'] = result['frames'][0]['file']
    elif damage == 'bool_frame': result['frames'][1]['frame_index0'] = True
    elif damage == 'float_frame': result['frames'][1]['frame_index0'] = 1.0
    write_receipt(bundle, result)
    with pytest.raises(DataError):
        t.flow.accept_export(bundle['export_id'])
    assert_empty(t)


def test_missing_last_image_rejects_entire_batch(engineering):
    t = engineering; bundle = export_request(t, stop=2); result = receipt(bundle)
    (Path(bundle['directory'])/'frames'/result['frames'][1]['file']).unlink()
    with pytest.raises((DataError, FileNotFoundError)):
        t.flow.accept_export(bundle['export_id'])
    assert_empty(t)


def test_junction_marked_output_directory_is_refused_before_admission(engineering, monkeypatch):
    t = engineering; bundle = export_request(t, stop=1); receipt(bundle)
    frames = Path(bundle['directory'])/'frames'
    original = Path.is_junction
    monkeypatch.setattr(Path, 'is_junction', lambda path: path==frames or original(path))
    with pytest.raises(DataError):
        t.flow.accept_export(bundle['export_id'])
    assert_empty(t)


@pytest.mark.skipif(os.name != 'nt', reason='Windows junction containment')
def test_frames_directory_junction_cannot_admit_external_pictures(engineering):
    import _winapi
    t = engineering; bundle = export_request(t, stop=1); result = receipt(bundle)
    frames = Path(bundle['directory'])/'frames'
    external = t.tmp_path/'external pictures'; external.mkdir()
    name = result['frames'][0]['file']
    (external/name).write_bytes((frames/name).read_bytes())
    (frames/name).unlink(); frames.rmdir()
    try:
        _winapi.CreateJunction(str(external), str(frames))
    except PermissionError:
        pytest.skip('Current sandbox does not permit creating a directory junction')
    try:
        assert frames.is_junction()
        with pytest.raises(DataError):
            t.flow.accept_export(bundle['export_id'])
        assert_empty(t)
    finally:
        # Remove only the empty directory link, never its target's contents.
        os.rmdir(frames)
    assert (external/name).is_file()
