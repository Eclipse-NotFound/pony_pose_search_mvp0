"""Real Tk controls and an isolated source library; never modify production labels."""
import os
from pathlib import Path
import subprocess
import sys
import time
import tkinter as tk

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'scripts/m10'), str(ROOT/'scripts/common')]


@pytest.mark.skipif(os.name != 'nt', reason='Windows launcher')
def test_launcher_finds_installed_python_without_path():
    env = dict(os.environ, PATH=str(Path(os.environ['SystemRoot'])/'System32'))
    result = subprocess.run([os.environ['COMSPEC'], '/d', '/c', str(ROOT/'run_m10.bat'), '--help'],
                            cwd=ROOT.parent, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
    assert result.returncode == 0, result.stdout.decode(errors='replace')
    assert b'--project-root' in result.stdout


@pytest.mark.skipif(os.name != 'nt', reason='Windows launcher')
def test_batch_launches_real_native_ui_and_forwards_unicode_paths(tmp_path):
    target=tmp_path/'独立 资料库'
    env=dict(os.environ,PATH=str(Path(os.environ['SystemRoot'])/'System32'))
    result=subprocess.run([os.environ['COMSPEC'],'/d','/c',str(ROOT/'run_m10.bat'),
                           '--check-ui','--project-root',str(ROOT),'--workbench-library',str(target)],cwd=ROOT.parent,env=env,
                          stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60)
    assert result.returncode==0,result.stdout.decode(errors='replace')
    assert b'"m10_native_ui": "ready"' in result.stdout
    assert (target/'catalog.json').exists()


def wait(root, predicate, timeout=12):
    until=time.monotonic()+timeout
    while time.monotonic()<until:
        root.update()
        if predicate():return
        time.sleep(.03)
    raise AssertionError('native UI did not complete')


@pytest.fixture(scope='session')
def tk_root():
    root=tk.Tk();root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def ui(tmp_path, monkeypatch, tk_root):
    # Tk variables from destroyed fixtures must be finalized on the UI thread,
    # before the next background worker can trigger cyclic garbage collection.
    import gc
    gc.collect()
    from native_workbench import NativeWorkbench
    from tkinter import messagebox
    errors=[]
    monkeypatch.setattr(messagebox,'showerror',lambda *a,**k:errors.append(a))
    root=tk_root
    app=NativeWorkbench(root,ROOT,library=tmp_path/'library')
    app.pack(fill='both',expand=True)
    root.update()
    yield root,app,errors
    app.close();app.destroy();root.update()
    assert errors == []


def add_picture(app, tmp_path, name='scene'):
    path=tmp_path/(name+'.png')
    im=Image.new('RGB',(120,90),'white');im.putpixel((1,1),(30,60,90));im.save(path)
    app.session.sources.add_inputs([str(path)])
    return path


def test_native_import_draw_review_search_source_and_history(ui,tmp_path):
    from multispecies import DataError, ConflictError
    root,app,errors=ui
    path=add_picture(app,tmp_path)
    wait(root,lambda:app.session.sources.list_files()['items'] and app.session.sources.list_files()['items'][0]['state']=='ready')
    app.refresh_sources();fid=app.session.sources.list_files()['items'][0]['id']
    app.files.selection_set(fid);wait(root,lambda:app.position_id is not None)
    app.set_region([10,10],[110,80]);app.confirm_region.set(True)
    app.import_button.invoke();wait(root,lambda:app.session.record is not None and not app.busy)
    oid=app.session.record['observation_id'];original=app.session.record['annotation']['id']
    assert app.session.record['source']['roi']==[10,10,100,70]
    app.part.choose('core');app.update_part();app.presence.choose('present');app.set_presence()
    app.direction.choose('core.head');app.update_direction();app.visibility.choose('visible')
    app.draw_direction([20,30],[80,30])
    assert app.session.draft['annotation']['directions']['core.head']['value']==[1,0]
    with pytest.raises(DataError,match='未保存'):app.load_record(oid)
    app.review('approved',True);wait(root,lambda:not app.busy)
    assert app.session.record['annotation']['directions']['core.head']['review_status']=='approved'
    first_revision=app.session.record['annotation']['id']
    assert app.session.record['source']['locator_ref']==app.position_id
    # Another record from the same actual image. Only this isolated library is changed.
    other=app.session.service.import_observation(position_id=app.position_id,roi=[0,0,120,90],form_ref='twilight.unicorn@1',request_id='second_fixture')['record']
    app.session.library.edit(other['observation_id'],other['annotation']['id'],
        {'parts':{'core':{'presence':'present'}},'directions':{'core.head':{'value':[1,0],'visibility':'visible'}}},
        actor='fixture',review={'status':'approved','targets':['parts.core','directions.core.head']})
    app.contract.choose('pony.body14@1');app.search_button.invoke();wait(root,lambda:not app.busy)
    assert len(app.session.last_results['results'])==1
    # The visible summary must name the frozen query even after another record loads.
    saved_description=app.query_description(app.session.last_results['query_spec'])
    assert 'scene' in saved_description
    wait(root,lambda:bool(app.results.selection()))
    app.select_result();app.open_result_source()
    assert str(path)==app.session.service.describe_position(app.position_id)['path']
    assert app.source_picture.image.size==(120,90)
    assert not app.mirror.get() and app.exchange.get()
    csv_path,json_path=app.session.export_results()
    assert csv_path.exists() and 'second_fixture' not in csv_path.read_text(encoding='utf-8-sig')
    assert str(path) in __import__('json').loads(json_path.read_text(encoding='utf-8'))['results'][0]['position_text']
    # Old revisions cannot be edited or approved; current HEAD remains untouched.
    app.load_record(oid,original)
    with pytest.raises(DataError,match='历史'):app.session.edit({'parts':{'core':{'presence':'present'}}},'test')
    assert app.session.library.head_id(oid)==first_revision
    app.load_record(oid)
    app.draw_direction([20,30],[20,60])
    concurrent=app.session.library.edit(oid,first_revision,{'directions':{'core.head':{'value':[0,-1]}}},actor='other window')
    with pytest.raises(ConflictError):app.session.save('test')
    assert app.session.dirty and app.session.library.head_id(oid)==concurrent['annotation']['id']


def test_native_controller_contains_workbench_without_browser(tmp_path,monkeypatch,tk_root):
    import control_center
    import webbrowser
    from tkinter import messagebox
    errors=[]
    monkeypatch.setattr(messagebox,'showerror',lambda *a,**k:errors.append(a))
    monkeypatch.setattr(webbrowser,'open',lambda *a,**k:pytest.fail('must not open browser'))
    root=tk.Toplevel(tk_root);root.withdraw()
    app=control_center.ControlCenter(root,workbench_library=tmp_path/'library')
    try:
        root.update()
        assert not errors
        assert app.native_workbench is not None
        assert not hasattr(app,'_main_notebook')
        assert len(app.native_workbench.module_buttons)==9
        assert app.native_workbench.session.library.root==tmp_path/'library'
        assert not app.native_workbench.session.dirty
    finally:
        if app.native_workbench:app.native_workbench.close()
        root.destroy()


def test_m10_module_buttons_share_saved_annotations_query_and_results(tmp_path,monkeypatch,tk_root):
    import control_center
    from multispecies import new_observation
    from tkinter import messagebox, ttk
    errors=[]
    monkeypatch.setattr(messagebox,'showerror',lambda *a,**k:errors.append(a))
    root=tk.Toplevel(tk_root);root.withdraw()
    app=control_center.ControlCenter(root,workbench_library=tmp_path/'shared library')
    view=app.native_workbench
    try:
        im=Image.new('RGB',(80,60),'white');im.putpixel((2,2),(20,30,40));path=tmp_path/'fixture.png';im.save(path)
        asset=app.project_context.library.upload_image(path.read_bytes())
        records=[]
        for _ in range(2):
            r=new_observation(view.catalog,profile_ref='pony.quadruped@2draft1',image_ref=asset['id'],image_size=asset['size'])
            view.session.library.save(r)
            r=view.session.library.edit(r['observation_id'],r['annotation']['id'],
                {'parts':{'core':{'presence':'present'}},'directions':{'core.head':{'value':[1,0],'visibility':'visible'}}},
                actor='fixture',review={'status':'approved','targets':['parts.core','directions.core.head']})
            records.append(r)
        view.refresh_records();view.load_record(records[0]['observation_id'])
        assert not hasattr(control_center,'build_module_command')
        def run(mid):
            view.module_buttons[mid].invoke()
            root.update()
        run('M05');assert view.tabs.select()==str(view.editor_tab)
        view.part.choose('core');view.update_part();view.direction.choose('core.head');view.update_direction()
        view.draw_direction([10,10],[10,40]);view.review('approved',True);wait(root,lambda:not view.busy)
        changed=view.session.record['annotation']['id']
        run('M07');assert view.tabs.select()==str(view.editor_tab)
        run('M08');assert view.tabs.select()==str(view.search_tab)
        view.query_save_button.invoke();wait(root,lambda:not view.busy)
        assert app.project_context.poses.query(view.session.query_id)['annotation_id']==changed
        view.saved_search_button.invoke();wait(root,lambda:not view.busy)
        assert view.session.last_results['query_revision']==changed
        assert view.session.last_results['results'][0]['score']==pytest.approx(.5)
        run('M09');assert view.tabs.select()==str(view.results_tab)
        # A global refresh must not replace shared-library facts with old CSV status.
        app._refresh_all_status()
        assert app.module_status_vars['M05'].get()=='可标注'
        assert app.module_status_vars['M07'].get()=='已保存'
        assert app.module_status_vars['M08'].get()=='已完成'
        assert app.module_status_vars['M09'].get()=='可查看'
        assert Path(view.session.export_html()).is_file()
        assert not errors
    finally:
        view.close();app.project_context.close();root.destroy();tk_root.update()


def test_direction_click_coordinates_and_close_guard(ui,tmp_path,monkeypatch):
    from types import SimpleNamespace
    root,app,errors=ui
    add_picture(app,tmp_path)
    wait(root,lambda:bool(app.session.sources.list_files()['items']) and app.session.sources.list_files()['items'][0]['state']=='ready')
    fid=app.session.sources.list_files()['items'][0]['id']
    position=app.session.sources.create_position(fid)
    result=app.session.service.import_observation(position_id=position['id'],roi=[0,0,120,90],form_ref='twilight.unicorn@1',request_id='click_fixture')
    app.load_record(result['record']['observation_id']);app.part.choose('core');app.update_part()
    app.annotation_mode.choose('directions');app.update_annotation_mode()
    app.presence.choose('present');app.set_presence()
    picture=app.pose_picture
    picture.scale=2;picture.offset=(10,20)
    assert picture.point(SimpleNamespace(x=50,y=80))==[20,30]
    # Actual canvas event handlers, with redraw preserving the test coordinate transform.
    monkeypatch.setattr(picture,'redraw',lambda:None)
    picture.press(SimpleNamespace(x=50,y=80));picture.release(SimpleNamespace(x=170,y=80))
    pair=app.session.draft['annotation']['reference_points']['core.head']
    assert pair=={'start':[20,30],'end':[80,30]}
    monkeypatch.setattr('native_workbench.messagebox.askyesno',lambda *a,**k:False)
    assert not app.can_close()
    app.session.discard()
    assert app.can_close()


def test_failed_media_job_and_retry_are_visible(ui,tmp_path):
    root,app,errors=ui
    broken=tmp_path/'broken.png';broken.write_bytes(b'broken')
    app.enqueue_sources([str(broken)])
    wait(root,lambda:not app.busy and any(j['state']=='failed' for j in app.session.sources.status()['jobs']))
    job=next(j for j in app.session.sources.status()['jobs'] if j['state']=='failed')
    assert job['error']
    Image.new('RGB',(20,20),'blue').save(broken)
    app.session.sources.retry(job['id'])
    wait(root,lambda:app.session.sources.job(job['id'])['state']=='done')
    app.refresh_sources()
    assert '失败 0' in app.jobs_status.get()


def test_draft_changes_do_not_keep_stale_reference_points(ui,tmp_path):
    root,app,errors=ui
    add_picture(app,tmp_path)
    wait(root,lambda:bool(app.session.sources.list_files()['items']) and app.session.sources.list_files()['items'][0]['state']=='ready')
    file=app.session.sources.list_files()['items'][0]
    p=app.session.sources.create_position(file['id'])
    r=app.session.service.import_observation(position_id=p['id'],roi=[0,0,120,90],form_ref='twilight.unicorn@1',request_id='direct_vector_fixture')['record']
    app.load_record(r['observation_id']);app.presence.choose('present');app.set_presence()
    app.draw_direction([1,1],[10,10])
    app.patch_direction({'value':[0,-1]})
    assert 'core.head' not in app.session.draft['annotation']['reference_points']
    assert app.session.draft['annotation']['directions']['core.head']['value']==[0,-1]
    app.presence.choose('absent');app.set_presence()
    assert 'core.head' not in app.session.draft['annotation']['directions']


def test_native_advanced_exports_filters_and_exclusions(ui,tmp_path):
    import json
    root,app,errors=ui
    path=add_picture(app,tmp_path)
    wait(root,lambda:bool(app.session.sources.list_files()['items']) and app.session.sources.list_files()['items'][0]['state']=='ready')
    source=app.session.sources
    file=source.list_files()['items'][0];rid=file['root_id']
    selections=source.get_root(rid)['selections']
    source.set_excludes(rid,['skip']);assert json.loads(source.get_root(rid)['excludes'])==['skip']
    source.set_excludes(rid,[])
    assert json.loads(source.get_root(rid)['excludes'])==[]
    assert source.get_root(rid)['selections']==selections
    position=source.create_position(file['id'])
    r=app.session.service.import_observation(position_id=position['id'],roi=[0,0,120,90],form_ref='twilight.unicorn@1',request_id='advanced_fixture')['record']
    app.load_record(r['observation_id'])
    assert app.session.service.filter_records([r],{'format':'PNG','root_id':rid})==[r]
    assert app.session.service.filter_records([r],{'format':'MP4'})==[]
    snapshot=app.session.export_training(allow_draft=True,include_ungrouped=True)
    assert json.loads(snapshot.read_text(encoding='utf-8'))['options']['allow_draft'] is True
    # Native dialogs construct successfully; their checkboxes default to off.
    for action in (app.import_options,app.source_filter_options,app.training_options):
        action();root.update()
        dialogs=[w for w in app.winfo_children() if isinstance(w,tk.Toplevel)]
        assert dialogs
        for dialog in dialogs:dialog.destroy()


def test_native_points_suggestion_partial_review_and_all_module_pages(ui,tmp_path):
    from multispecies.keypoints import ORDER
    root,app,errors=ui
    add_picture(app,tmp_path)
    wait(root,lambda:bool(app.session.sources.list_files()['items']) and app.session.sources.list_files()['items'][0]['state']=='ready')
    file=app.session.sources.list_files()['items'][0];p=app.session.sources.create_position(file['id'])
    r=app.session.context.dataset.import_region(position_id=p['id'],roi=[0,0,120,90],form_ref='twilight.unicorn@1',request_id='point_review_fixture')['record']
    app.load_record(r['observation_id']);app.annotation_mode.choose('keypoints');app.update_annotation_mode()
    app.draw_annotation([10,20],[10,20]);app.point_key.choose(ORDER[0]);app.review_point();wait(root,lambda:not app.busy)
    assert app.session.record['annotation']['keypoints']['points'][ORDER[0]]['value']==[10,20]
    cap={'id':'fixture','profiles':[r['profile_ref']],'point_order':ORDER,'model_sha256':'0'*64}
    changes={'keypoints':{'points':{ORDER[0]:{'value':[25,25],'visibility':'visible'},ORDER[1]:{'value':[50,25],'visibility':'visible'}}}}
    suggestion=app.session.context.models.suggest(app.session.record,changes,cap)
    app.lifecycle.refresh_models();app.lifecycle.suggestions.selection_set(suggestion['id'])
    app.lifecycle.review_dialog();root.update()
    from tkinter import ttk
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)
    next(b for b in descendants(app) if isinstance(b,ttk.Button) and b.cget('text')=='载入标注草稿修改').invoke()
    assert app.point_key.key()==ORDER[0] and app.annotation_mode.key()=='keypoints'
    app.pose_picture.scale=3
    app.draw_annotation([30,30],[30,30]);app.review_point();wait(root,lambda:not app.busy)
    current=app.session.library.read(r['observation_id'])
    assert current['annotation']['keypoints']['points'][ORDER[0]]['value']==[30,30]
    assert current['annotation']['keypoints']['points'][ORDER[1]]['value'] is None
    assert app.active_suggestion and app.session.dirty
    app.next_point();app.review_point();wait(root,lambda:not app.busy)
    assert not app.active_suggestion and not app.session.dirty
    assert app.session.record['annotation']['keypoints']['points'][ORDER[1]]['value']==[50,25]
    for module in ['M01','M02','M03','M04','M05','M06','AI','TASKS']:
        app.open_module(module);root.update()
    assert not errors


def test_save_candidate_focuses_the_correct_page(ui,tmp_path):
    root,app,errors=ui
    add_picture(app,tmp_path)
    wait(root,lambda:bool(app.session.sources.list_files()['items']) and app.session.sources.list_files()['items'][0]['state']=='ready')
    source=app.session.sources;file=source.list_files()['items'][0];position=source.create_position(file['id'])
    data=app.session.context.dataset
    for index in range(101):data.decide(position['id'],'undecided',set_id='paging_fixture_'+str(index))
    target=data.decide(position['id'],'undecided')
    ids=[c['id'] for c in data.candidates()];target_page=ids.index(target['id'])//100*100
    app.lifecycle.candidate_offset=100 if target_page==0 else 0
    app.show_position(position['id'])
    app.save_candidate();root.update()
    assert app.lifecycle.candidates.exists(target['id'])
    assert app.lifecycle.candidates.selection()==(target['id'],)
    assert app.lifecycle.candidate['id']==target['id']
    assert app.lifecycle.region_picture.image.size==(120,90)


def test_import_after_existing_selection_keeps_new_record_loaded(ui,tmp_path):
    root,app,errors=ui
    add_picture(app,tmp_path)
    wait(root,lambda:bool(app.session.sources.list_files()['items']) and app.session.sources.list_files()['items'][0]['state']=='ready')
    source=app.session.sources;file=source.list_files()['items'][0];position=source.create_position(file['id'])
    first=app.session.context.dataset.import_region(position_id=position['id'],roi=[0,0,120,90],form_ref='twilight.unicorn@1',request_id='previous_selected_fixture')['record']
    app.refresh_records();app.load_record(first['observation_id']);app.records.selection_set(first['observation_id']);root.update()
    app.show_position(position['id']);app.full_region();app.confirm_region.set(True)
    app.import_button.invoke();wait(root,lambda:not app.busy)
    assert len(app.session.library.records())==2
    assert app.session.record['observation_id']!=first['observation_id']
    assert app.records.selection()==(app.session.record['observation_id'],)


def test_responsive_pages_keep_controls_and_query_options(tmp_path,monkeypatch,tk_root):
    """Exercise mapped controls at the supported minimum, including visible settings."""
    from tkinter import ttk, messagebox
    from control_center import ControlCenter
    from ui_components import Toolbar
    errors=[]
    monkeypatch.setattr(messagebox,'showerror',lambda *a,**k:errors.append(a))
    root=tk.Toplevel(tk_root)
    app=ControlCenter(root,workbench_library=tmp_path/'layout-library')
    view=app.native_workbench
    root.geometry('1100x720+0+0')
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)
    def settle():
        until=time.monotonic()+.12
        while time.monotonic()<until:root.update();time.sleep(.01)
    try:
        for module in ('M01','M03','M05','M07','M08','M09','M06','AI','TASKS'):
            view.open_module(module);settle()
            assert view.active_module==module
            for toolbar in [w for w in descendants(view) if isinstance(w,Toolbar) and w.winfo_ismapped()]:
                for action in toolbar.winfo_children():
                    assert action.winfo_ismapped(), (module,action)
                    assert action.winfo_x()+action.winfo_width()<=toolbar.winfo_width()+1
                    assert action.winfo_y()+action.winfo_height()<=toolbar.winfo_height()+1
        view.open_module('M01');settle()
        assert view.source_picture.canvas.winfo_height()>=160
        # Basic controls stay visible; changing pages preserves the entered options.
        view.query_only.set(True);settle()
        assert view.import_button.winfo_ismapped()
        view.open_module('M09');view.unreviewed.set(True)
        view.top_n.delete(0,'end');view.top_n.insert(0,'37')
        view.open_module('M05');view.open_module('M09');settle()
        assert view.unreviewed.get() and view.top_n.get()=='37'
        assert not view.mirror.get() and view.exchange.get()
        # Panel wheel must scroll without changing the selected comparison options.
        from types import SimpleNamespace
        view.search_settings._wheel(SimpleNamespace(delta=-120));settle()
        assert view.unreviewed.get() and view.top_n.get()=='37'
        assert not errors
    finally:
        view.close();app.project_context.close();root.destroy();tk_root.update()


def test_read_frame_keeps_target_when_an_old_source_selection_is_queued(ui,tmp_path):
    root,app,errors=ui
    add_picture(app,tmp_path,'first');add_picture(app,tmp_path,'second')
    wait(root,lambda:len(app.session.sources.list_files()['items'])==2 and all(f['state']=='ready' for f in app.session.sources.list_files()['items']))
    app.refresh_sources()
    files=app.session.sources.list_files()['items']
    app.file_id=files[0]['id']
    app.files.selection_set(files[0]['id'])  # event has not yet been processed
    app.file_id=files[1]['id']
    app.read_frame()
    wait(root,lambda:app.position_id is not None and not app.watched)
    assert app.file_id==files[1]['id']
    assert app.session.sources.position(app.position_id)['file_id']==files[1]['id']
    assert app.files.selection()==(files[1]['id'],)


def test_classic_point_sequence_select_missing_keyboard_and_save_on_navigation(ui,tmp_path,monkeypatch):
    from types import SimpleNamespace
    from multispecies import new_observation
    from multispecies.keypoints import ORDER
    root,app,errors=ui
    path=tmp_path/'points.png';Image.new('RGB',(400,300),'white').save(path)
    asset=app.session.library.upload_image(path.read_bytes())
    records=[]
    for _ in range(2):
        record=new_observation(app.catalog,profile_ref='pony.quadruped@2draft1',image_ref=asset['id'],image_size=asset['size'])
        app.session.library.save(record);records.append(record)
    app.refresh_records();app.load_record(records[0]['observation_id']);app.open_module('M05')
    assert app.annotation_mode.key()=='keypoints' and len(app.point_key.keys)==21
    app.pose_picture.scale=1
    app.draw_annotation([30,30],[30,30])
    assert app.point_key.key()==ORDER[1]
    assert app.session.draft['annotation']['keypoints']['points'][ORDER[0]]['value']==[30,30]
    # Clicking an existing point selects it without editing/advancing another point.
    app.pose_picture.scale=1;app.draw_annotation([30,30],[30,30])
    assert app.point_key.key()==ORDER[0]
    app.pose_picture.scale=1;app.draw_annotation([80,30],[80,30])
    assert app.point_key.key()==ORDER[1]
    assert app.session.draft['annotation']['keypoints']['points'][ORDER[0]]['value']==[80,30]
    app.clear_point();assert app.point_key.key()==ORDER[2]
    assert app.session.draft['annotation']['keypoints']['points'][ORDER[1]]['missing_reason']=='not_discernible'
    # Actual keyboard events have the old selection semantics, but text fields keep arrows.
    app._editor_shortcut('<Up>',SimpleNamespace(widget=app.pose_picture.canvas));assert app.point_key.key()==ORDER[1]
    assert app._editor_shortcut('<Down>',SimpleNamespace(widget=app.record_filter)) is None
    app.point_key.current(20);app.next_point();assert app.point_key.key()==ORDER[-1]
    first=app.session.record['observation_id']
    app.navigate_record(records[1]['observation_id']);wait(root,lambda:not app.busy)
    assert app.session.record['observation_id']==records[1]['observation_id']
    saved=app.session.library.read(first)['annotation']['keypoints']['points'][ORDER[0]]
    assert saved['value']==[80,30] and saved['review_status']=='unreviewed'
    app.navigate_record(first);app.jump_unannotated();wait(root,lambda:not app.busy)
    assert app.session.record['observation_id']==records[1]['observation_id']


def test_query_image_points_derive_search_and_query_identity(ui,tmp_path):
    from multispecies import new_observation
    from multispecies.keypoints import ORDER
    from tkinter import ttk
    root,app,errors=ui
    path=tmp_path/'查询.bmp';Image.new('RGB',(200,150),'pink').save(path)
    original=path.read_bytes()
    app.import_query_image(path,'twilight.unicorn@1');wait(root,lambda:not app.busy)
    query=app.session.record['observation_id']
    assert app.active_module=='M07' and app.tabs.select()==str(app.editor_tab)
    assert app.session.record['collection']=='query' and path.read_bytes()==original
    app.patch({'keypoints':{'points':{ORDER[0]:{'value':[30,30],'visibility':'visible'},ORDER[1]:{'value':[90,30],'visibility':'visible'}}}})
    app.derive_from_points();wait(root,lambda:not app.busy)
    dialogs=[w for w in app.winfo_children() if isinstance(w,tk.Toplevel) and w.title()=='从点位生成方向']
    assert len(dialogs)==1
    buttons=[w for frame in dialogs[0].winfo_children() for w in frame.winfo_children() if isinstance(w,ttk.Button)]
    next(b for b in buttons if b.cget('text')=='生成方向').invoke();wait(root,lambda:not app.busy)
    assert app.session.record['annotation']['directions']['core.head']['value']==[1,0]
    app.direction.choose('core.head');app.update_direction();app.review('approved',True);wait(root,lambda:not app.busy)
    candidate=new_observation(app.catalog,profile_ref='pony.quadruped@2draft1',image_ref=app.session.record['image_ref'],image_size=[200,150])
    app.session.library.save(candidate)
    app.session.library.edit(candidate['observation_id'],candidate['annotation']['id'],
        {'parts':{'core':{'presence':'present'}},'directions':{'core.head':{'value':[1,0],'visibility':'visible'}}},
        actor='fixture',review={'status':'approved','targets':['parts.core','directions.core.head']})
    app.prepare_search();app.group_weight_vars['head'].set('2.5')
    app.search_button.invoke();wait(root,lambda:not app.busy)
    assert app.session.last_results['options']['group_weights']['head']==2.5
    assert app.tabs.select()==str(app.results_tab) and len(app.gallery.photos)>=1
    assert app.current_hit()['observation_id']==candidate['observation_id']
    app.open_result_record();assert app.session.record['observation_id']==candidate['observation_id']
    app.open_module('M07');assert app.session.record['observation_id']==query
    assert app.session.record['collection']=='query'
    frozen=app.session.last_results['query_spec']
    newest=app.session.library.edit(query,app.session.record['annotation']['id'],
        {'directions':{'core.head':{'value':[0,1],'visibility':'visible'}}},actor='fixture')
    app.restore_query(frozen);assert app.session.historical
    app.open_module('M07');assert not app.session.historical
    assert app.session.record['annotation']['id']==newest['annotation']['id']


def test_direct_direction_list_keeps_multispecies_and_does_not_invent_points(ui,tmp_path):
    from multispecies import new_observation
    root,app,errors=ui
    path=tmp_path/'other.png';Image.new('RGB',(200,160),'white').save(path)
    asset=app.session.library.upload_image(path.read_bytes())
    profile=next(p['id'] for p in app.catalog.data['profiles'] if not p['id'].startswith('pony.'))
    record=new_observation(app.catalog,profile_ref=profile,image_ref=asset['id'],image_size=asset['size'])
    app.session.library.save(record);app.load_record(record['observation_id'])
    assert app.annotation_mode.key()=='directions'
    assert set(app.direction.keys)==set(app.catalog.channels(profile))
    key=app.direction.key();app.draw_annotation([30,30],[100,30])
    assert app.session.draft['annotation']['directions'][key]['value']==[1,0]
    assert app.session.draft['annotation']['parts'][key.split('.')[0]]['presence']=='present'
    assert 'keypoints' not in app.session.draft['annotation']


def test_classic_list_keyboard_moves_once_and_does_not_steal_text_keys(ui):
    root,app,errors=ui
    root.deiconify();root.geometry('1100x720');app.open_module('M05');root.update()
    try:
        app.point_key.current(0);app.point_key.focus_force();root.update()
        app.point_key.event_generate('<KeyPress-Down>');root.update()
        assert app.point_key.current()==1  # no second movement from Listbox class binding
        app.point_key.event_generate('<KeyPress-Up>');root.update()
        assert app.point_key.current()==0
        app.record_browser.deiconify();app.record_filter.insert(0,'abc')
        app.record_filter.focus_force();app.record_filter.icursor('end');root.update()
        app.record_filter.event_generate('<KeyPress-Left>');root.update()
        assert app.record_filter.index('insert')==2
        assert app.point_key.current()==0
    finally:
        app.record_browser.withdraw();root.withdraw()
