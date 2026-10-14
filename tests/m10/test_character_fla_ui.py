"""FLA entry points reuse M01/M02 and never submit video-frame extraction jobs."""
import gc
from pathlib import Path
import sys
import threading
import time
import tkinter as tk
from types import SimpleNamespace

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'scripts/m10'), str(ROOT/'scripts/common')]


def wait(root, predicate):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(.02)
    raise AssertionError('FLA UI did not complete')


@pytest.fixture(scope='module')
def fla_tk_root():
    root = tk.Tk(); root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def fla_ui(tmp_path, monkeypatch, fla_tk_root):
    gc.collect()
    from native_workbench import NativeWorkbench
    from tkinter import messagebox
    errors = []
    monkeypatch.setattr(messagebox, 'showerror', lambda *args, **kwargs: errors.append(args))
    root = fla_tk_root
    app = NativeWorkbench(root, ROOT, library=tmp_path/'isolated-library')
    app.pack(fill='both', expand=True)
    app.session.sources.pause(True)
    file = dict(id='fla_fixture', name='角色.fla', format='FLA', kind='fla', state='ready',
                metadata={}, path=str(tmp_path/'角色.fla'), version_id='version_fixture')
    original_file = app.session.sources.file
    monkeypatch.setattr(app.session.sources, 'file', lambda fid: file if fid==file['id'] else original_file(fid))
    app.files.insert('', 'end', iid=file['id'], values=(file['name'], 'FLA', '可用'))
    app.files.selection_set(file['id']); app.select_file()
    manifest = dict(file_id=file['id'], version_id=file['version_id'], warnings=[],
        renderer=dict(available=True, reason=''), timelines=[
            dict(id='scene_a', kind='scene', name='场景一', frame_count=3, suggested=False, reason='舞台'),
            dict(id='body_a', kind='symbol', name='完整角色／侧面', frame_count=7, suggested=True, reason='完整身体'),
            dict(id='leg_a', kind='symbol', name='前腿', frame_count=2, suggested=False, reason='零件')])
    calls = []
    inspections = []
    rows = []
    def inspect(fid):
        inspections.append((fid, threading.get_ident()))
        return manifest
    def positions(fid, timeline_id=None):
        return [r for r in rows if r['file_id']==fid and (timeline_id is None or r['payload']['timeline_id']==timeline_id)]
    def queue_export(fid, tid, **kwargs):
        calls.append((fid, tid, kwargs)); return 'fla_job'
    app.session.context.characters = SimpleNamespace(inspect=inspect, positions=positions, queue_export=queue_export)
    root.update()
    yield SimpleNamespace(root=root, app=app, manifest=manifest, file=file, calls=calls, rows=rows,
                          inspections=inspections, errors=errors, tmp_path=tmp_path)
    app.close(); app.destroy(); root.update()
    gc.collect()
    assert errors == []


def test_character_window_checks_in_background_and_queues_selected_range(fla_ui):
    t = fla_ui; app = t.app
    assert str(app.character_fla_button.cget('state')) == 'normal'
    window = app.open_character_fla()
    wait(t.root, lambda: window.manifest is not None and not app.busy)
    assert t.inspections == [(t.file['id'], t.inspections[0][1])]
    assert t.inspections[0][1] != threading.get_ident()
    assert window.timeline_tree.get_children() == ('body_a',)
    assert (window.start.get(), window.stop.get(), window.step.get()) == ('1', '7', '1')
    window.show_all.set(True); window.refresh_timelines()
    assert set(window.timeline_tree.get_children()) == {'scene_a', 'body_a', 'leg_a'}
    window.timeline_tree.selection_set('scene_a'); window.select_timeline()
    window.start.set('2'); window.stop.set('3')
    window.export_button.invoke()
    wait(t.root, lambda: bool(t.calls) and not app.busy)
    assert t.calls == [('fla_fixture', 'scene_a', dict(start=2, stop=3, step=1, actor='本机用户'))]
    assert '排队' in window.notice.get()


def test_unavailable_renderer_explains_reason_and_never_queues_video_job(fla_ui, monkeypatch):
    t = fla_ui; app = t.app
    t.manifest['renderer'] = dict(available=False, reason='未配置 Animate 渲染程序')
    monkeypatch.setattr(app.session.sources, 'queue', lambda *a, **kw: pytest.fail('FLA must not queue a video position'))
    app.read_frame()
    window = app._character_fla_window
    wait(t.root, lambda: window.manifest is not None and not app.busy)
    assert '未配置 Animate' in window.notice.get()
    assert str(window.export_button.cget('state')) == 'disabled'
    window.export_button.invoke()
    assert t.calls == []
    assert app.sample_frames_dialog() is window


def test_engineering_frame_navigation_is_scoped_to_timeline_and_reopens_from_result(fla_ui, monkeypatch):
    t = fla_ui; app = t.app
    image = t.tmp_path/'render.png'; Image.new('RGBA', (100, 80), 'red').save(image)
    for pid, tid, ordinal in [('body_1', 'body_a', 0), ('scene_1', 'scene_a', 0), ('scene_2', 'scene_a', 1)]:
        t.rows.append(dict(id=pid, file_id=t.file['id'], version_id=t.file['version_id'], payload=dict(
            kind='fla_frame', precision='timeline_exact', timeline_id=tid,
            timeline_kind='symbol' if tid=='body_a' else 'scene', timeline_name=tid,
            frame_index0=ordinal, image_size=[100, 80])))
    def describe(pid):
        row = next(r for r in t.rows if r['id']==pid)
        return dict(file_id=row['file_id'], position_id=pid, position=row['payload'])
    monkeypatch.setattr(app.session.service, 'describe_position', describe)
    monkeypatch.setattr(app.session.service, 'position_text', lambda info: '定位精度：timeline_exact')
    monkeypatch.setattr(app.session.sources, 'cached_image', lambda pid: image)
    monkeypatch.setattr(app.session.sources, 'queue', lambda *a, **kw: pytest.fail('FLA must not queue a video position'))
    app.open_location(dict(position_id='scene_1'))
    assert app.timeline_id == 'scene_a'
    assert app.frame_number.get() == '1'
    app.read_frame(1)
    assert app.position_id == 'scene_2'
    assert app.frame_number.get() == '2'
    assert '第 2 工程帧' in app.source_caption.cget('text')
    assert '视频' not in app.source_caption.cget('text')
    assert '精确到工程时间轴帧' in app.source_detail.get('1.0', 'end')
    app.read_frame(-1)
    assert app.position_id == 'scene_1'  # Same ordinal in body_a must never win.
    t.manifest['renderer'] = dict(available=False, reason='本机暂无渲染程序')
    window = app.open_character_fla()
    wait(t.root, lambda: window.manifest is not None and not app.busy)
    assert set(window.positions_tree.get_children()) == {'scene_1', 'scene_2'}
    assert str(window.export_button.cget('state')) == 'disabled'
    window.positions_tree.selection_set('scene_2'); window.open_position()
    assert app.position_id == 'scene_2'
    assert app.active_module == 'M01'
    app.open_location(dict(position_id='body_1'))
    assert app.open_character_fla() is window
    assert window.selected_timeline == 'body_a'
    assert window.positions_tree.get_children() == ('body_1',)
    window.open_candidates()
    assert app.active_module == 'M02'
    assert window.state() == 'withdrawn'


def test_source_caption_distinguishes_engineering_video_and_image():
    from ui_components import position_caption
    assert position_caption(dict(kind='fla_frame', timeline_kind='symbol', timeline_name='侧面', frame_index0=8)) == '元件：侧面 · 第 9 工程帧'
    assert position_caption(dict(kind='video_frame', presentation_ordinal0=8)) == '第 9 视频帧'
    assert position_caption(dict(kind='image', precision='image_exact')) == '原图'
