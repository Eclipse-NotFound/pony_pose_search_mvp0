"""Runtime receipts and retries in isolated data; Popen is always intercepted.

Fake PNGs exercise admission only. No test launches Animate or claims rendering.
"""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import zipfile

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/common'))
from multispecies.catalog import DataError, load_json
from workflow import ProjectContext
from workflow import character_fla as module


@pytest.fixture(autouse=True)
def never_launch_an_application(monkeypatch):
    monkeypatch.setattr(module.subprocess, 'Popen',
        lambda *a, **k: pytest.fail('Native process launch is forbidden in offline tests'))


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    renderer = module.AnimateRenderer(tmp_path)
    monkeypatch.setattr(renderer, 'status', lambda: {'available':True, 'executable':'offline-double.exe', 'reason':'offline'})
    directory = tmp_path/'private bundle'; directory.mkdir()
    bundle = {'export_id':'export_original', 'script_path':str(directory/'export.jsfl'),
              'result_path':str(directory/'result.json'), 'request':{'request_sha256':'frozen_hash'}}
    clock = SimpleNamespace(value=0)
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock.value)
    def sleep(seconds):
        clock.value += seconds
    monkeypatch.setattr(module.time, 'sleep', sleep)
    return SimpleNamespace(renderer=renderer, bundle=bundle, clock=clock,
                           marker=renderer.state_root/'pending.json')


def write_terminal(bundle, state='done'):
    result = {'export_id':bundle['export_id'], 'request_sha256':bundle['request']['request_sha256'], 'state':state}
    Path(bundle['result_path']).write_text(json.dumps(result), encoding='utf-8')
    return result


def test_timeout_then_late_receipt_waits_for_same_request_without_second_launch(runtime, monkeypatch):
    t = runtime; launches = []
    monkeypatch.setattr(module.subprocess, 'Popen', lambda args, **kwargs: launches.append(args))
    with pytest.raises(ValueError, match='继续等待同一请求'):
        t.renderer.run(t.bundle, timeout=.3)
    assert len(launches) == 1 and t.marker.is_file()
    def sleep(seconds):
        t.clock.value += seconds
        write_terminal(t.bundle)
    monkeypatch.setattr(module.time, 'sleep', sleep)
    assert t.renderer.run(t.bundle, timeout=1)['state'] == 'done'
    assert len(launches) == 1 and not t.marker.exists()


def test_interruption_preserves_pending_and_resume_accepts_without_executable(runtime, monkeypatch):
    t = runtime; launches = []; calls = []
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *a, **k: launches.append(a))
    def checkpoint():
        calls.append(1)
        if len(calls) == 2:
            raise InterruptedError('stop this worker')
    with pytest.raises(InterruptedError):
        t.renderer.run(t.bundle, checkpoint)
    assert len(launches) == 1 and t.marker.is_file()
    expected = write_terminal(t.bundle)
    monkeypatch.setattr(t.renderer, 'status', lambda: {'available':False, 'reason':'not installed'})
    assert t.renderer.run(t.bundle) == expected
    assert len(launches) == 1 and not t.marker.exists()


def test_other_pending_request_is_refused_with_its_receipt_path(runtime, monkeypatch):
    t = runtime
    t.renderer.state_root.mkdir(parents=True)
    previous_path = t.renderer.state_root/'unfinished-result.json'
    t.marker.write_text(json.dumps({'export_id':'export_other', 'result_path':str(previous_path)}), encoding='utf-8')
    with pytest.raises(DataError, match='另一个 Animate') as exc:
        t.renderer.run(t.bundle)
    assert str(previous_path) in str(exc.value)
    assert t.marker.is_file()


def test_partly_written_receipt_is_waited_for_not_replayed(runtime, monkeypatch):
    t = runtime; launches = []
    def launch(*args, **kwargs):
        launches.append(args)
        Path(t.bundle['result_path']).write_text('{"export_id":', encoding='utf-8')
    def sleep(seconds):
        t.clock.value += seconds
        write_terminal(t.bundle)
    monkeypatch.setattr(module.subprocess, 'Popen', launch)
    monkeypatch.setattr(module.time, 'sleep', sleep)
    assert t.renderer.run(t.bundle, timeout=1)['state'] == 'done'
    assert len(launches) == 1


def test_process_creation_failure_releases_marker(runtime, monkeypatch):
    def failed(*args, **kwargs):
        raise OSError('test process could not start')
    monkeypatch.setattr(module.subprocess, 'Popen', failed)
    with pytest.raises(OSError):
        runtime.renderer.run(runtime.bundle)
    assert not runtime.marker.exists()


def test_same_pending_wrong_hash_is_not_accepted_or_replayed(runtime, monkeypatch):
    t = runtime; launches = []
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *a, **k: launches.append(a))
    with pytest.raises(ValueError):
        t.renderer.run(t.bundle, timeout=0)
    wrong = write_terminal(t.bundle); wrong['request_sha256'] = 'wrong'
    Path(t.bundle['result_path']).write_text(json.dumps(wrong), encoding='utf-8')
    with pytest.raises(ValueError, match='超时'):
        t.renderer.run(t.bundle, timeout=.3)
    assert len(launches) == 1 and t.marker.is_file()


class ReceiptRenderer:
    def __init__(self):
        self.calls = []
        self.states = ['failed', 'done']

    def status(self):
        return {'available':True, 'reason':'offline test double'}

    def run(self, bundle, checkpoint=lambda: None):
        self.calls.append(bundle['export_id'])
        request = bundle['request']; directory = Path(bundle['result_path']).parent
        state = self.states.pop(0)
        if state == 'timeout':
            raise ValueError('offline simulated timeout')
        result = {'schema_version':module.SCHEMA, 'export_id':request['export_id'],
            'request_sha256':request['request_sha256'], 'operation':request['operation'],
            'copy_uri':request['copy_uri'], 'state':state,
            'renderer':{'name':'Adobe Animate','version':'OFFLINE TEST DOUBLE'}, 'frames':[]}
        if state == 'done':
            for index in request['frames0']:
                name = f'frame_{index+1:06d}.png'
                Image.new('RGBA', (8, 8), (index, 100, 200, 255)).save(directory/'frames'/name)
                result['frames'].append({'frame_index0':index, 'file':name, 'timeline_id':request['timeline']['id']})
        else:
            result['error'] = {'code':'EXPORT_FAILED', 'message':'offline temporary failure'}
        Path(bundle['result_path']).write_text(json.dumps(result), encoding='utf-8')
        return result


@pytest.fixture
def workflow(tmp_path):
    source = tmp_path/'角色 空格.fla'
    xml = '<DOMDocument><timelines><DOMTimeline name="舞台"><layers><DOMLayer><frames><DOMFrame index="0" duration="4"/></frames></DOMLayer></layers></DOMTimeline></timelines></DOMDocument>'
    with zipfile.ZipFile(source, 'w') as archive:
        archive.writestr('DOMDocument.xml', xml)
    context = ProjectContext(ROOT, tmp_path/'library')
    try:
        added = context.sources.add_inputs([str(source)])
        context.sources.scan(added['root_ids'][0])
        file = context.sources.list_files()['items'][0]
        context.sources.probe(file['id'])
        renderer = ReceiptRenderer()
        context.characters.renderer = renderer
        bundle = context.characters.prepare_export(file['id'], 'scene:0', start=2, stop=4, step=2, actor='原操作人')
        yield SimpleNamespace(context=context, flow=context.characters, renderer=renderer, bundle=bundle, source=source)
    finally:
        context.close()


def test_failed_retry_creates_frozen_child_preserving_original_then_reuses_success(workflow):
    t = workflow; original_id = t.bundle['export_id']; original_dir = Path(t.bundle['directory'])
    with pytest.raises(DataError, match='导出失败'):
        t.flow.execute(original_id)
    original_result = (original_dir/'result.json').read_bytes()
    original_copy = (original_dir/'source.fla').read_bytes()
    accepted = t.flow.execute(original_id)
    child_id = load_json(original_dir/'retry.json')['export_id']
    _, child = t.flow._request(child_id)
    assert child_id != original_id and accepted['export_id'] == child_id
    for key in ('file_id','version_id','source_sha256','timeline','frames0','actor','set_id'):
        assert child[key] == t.bundle['request'][key]
    assert child['previous_export_id'] == original_id
    assert (original_dir/'result.json').read_bytes() == original_result
    assert (original_dir/'source.fla').read_bytes() == original_copy == t.source.read_bytes()
    assert t.flow.execute(original_id) == accepted
    assert t.renderer.calls == [original_id, child_id]


def test_each_explicit_retry_stops_after_one_new_native_failure(workflow):
    t = workflow; t.renderer.states = ['failed','failed','failed']
    for expected_count in range(1, 4):
        with pytest.raises(DataError, match='导出失败'):
            t.flow.execute(t.bundle['export_id'])
        assert len(t.renderer.calls) == expected_count
    assert len(set(t.renderer.calls)) == 3


def test_retry_after_child_timeout_keeps_same_child_request(workflow):
    t = workflow; t.renderer.states = ['failed','timeout','done']
    with pytest.raises(DataError):
        t.flow.execute(t.bundle['export_id'])
    with pytest.raises(ValueError, match='timeout'):
        t.flow.execute(t.bundle['export_id'])
    child_id = t.renderer.calls[-1]
    result = t.flow.execute(t.bundle['export_id'])
    assert result['export_id'] == child_id
    assert t.renderer.calls == [t.bundle['export_id'],child_id,child_id]


def test_unmatched_failure_receipt_does_not_authorize_retry(workflow):
    t = workflow
    with pytest.raises(DataError):
        t.flow.execute(t.bundle['export_id'])
    path = Path(t.bundle['result_path']); result = load_json(path); result['request_sha256'] = 'wrong'
    path.write_text(json.dumps(result), encoding='utf-8')
    with pytest.raises(DataError, match='失败回执与原请求不匹配'):
        t.flow.execute(t.bundle['export_id'])
    assert len(t.renderer.calls) == 1
    assert not (Path(t.bundle['directory'])/'retry.json').exists()


def test_source_catalog_job_retry_uses_new_attempt_without_new_job(workflow):
    t = workflow; sources = t.context.sources
    # Ignore old scan/probe queue entries; those were explicitly executed above.
    with sources.db() as db:
        db.execute("UPDATE jobs SET state='done' WHERE state='queued'")
    jid = sources.queue('character_fla', {'export_id':t.bundle['export_id']}, 'offline-fla-runtime')
    sources.pause(False)
    sources.run_next()
    assert sources.job(jid)['state'] == 'failed'
    sources.retry(jid); sources.run_next()
    job = sources.job(jid)
    assert job['state'] == 'done'
    assert job['result']['export_id'] != t.bundle['export_id']
    assert len(t.renderer.calls) == 2


@pytest.mark.parametrize('mode', ['RGB', 'RGBA', 'P'])
def test_complete_png_passes_integrity_verification(tmp_path, mode):
    from PIL.PngImagePlugin import PngInfo
    path = tmp_path/'complete.png'
    metadata = PngInfo(); metadata.add_text('Description', 'native export integrity fixture')
    Image.new(mode, (16, 16)).save(path, pnginfo=metadata)
    module._verify_png(path)


@pytest.mark.parametrize('removed', [1, 8, 12, 16, 20])
def test_truncated_png_end_is_rejected(tmp_path, removed):
    path = tmp_path/'truncated.png'
    Image.new('RGBA', (8, 8), (100, 20, 200, 255)).save(path)
    path.write_bytes(path.read_bytes()[:-removed])
    with pytest.raises(DataError, match='PNG'):
        module._verify_png(path)


def test_corrupt_png_idat_crc_is_rejected_even_when_pixels_can_load(tmp_path):
    path = tmp_path/'bad_crc.png'
    Image.new('RGBA', (8, 8), (100, 20, 200, 255)).save(path)
    raw = bytearray(path.read_bytes())
    tag = raw.index(b'IDAT')
    length = int.from_bytes(raw[tag-4:tag], 'big')
    raw[tag+4+length] ^= 1  # Only the CRC changes, not the compressed pixels.
    path.write_bytes(raw)
    with Image.open(path) as image:
        image.load()  # This used to be the only integrity check.
    with pytest.raises(DataError, match='校验值损坏'):
        module._verify_png(path)


def test_png_with_trailing_data_is_rejected(tmp_path):
    path = tmp_path/'extra_data.png'
    Image.new('RGB', (8, 8), 'red').save(path)
    path.write_bytes(path.read_bytes()+b'extra data')
    with pytest.raises(DataError, match='尾随数据'):
        module._verify_png(path)


def test_truncated_last_png_rejects_batch_before_publishing_any_position(workflow):
    t = workflow; t.renderer.states = ['done']
    result = t.renderer.run(t.bundle)
    path = Path(t.bundle['directory'])/'frames'/result['frames'][-1]['file']
    path.write_bytes(path.read_bytes()[:-12])
    with pytest.raises(DataError, match='结束块'):
        t.flow.accept_export(t.bundle['export_id'])
    assert t.flow.positions(t.bundle['request']['file_id']) == []
    assert t.context.dataset.candidates() == []
