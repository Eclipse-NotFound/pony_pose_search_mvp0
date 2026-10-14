"""User workflows across candidates, regions, reviewed points, suggestions and training."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

import pytest
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/common'))
from workflow import ProjectContext
from multispecies.catalog import DataError, load_json
from multispecies.library import ConflictError
from multispecies.keypoints import SCHEMA, ORDER, proposals
from multispecies.records import usable


@pytest.fixture
def ctx(tmp_path):
    context=ProjectContext(ROOT,tmp_path/'library')
    yield context
    context.close()


def frame(ctx, tmp_path, name='frame'):
    path=tmp_path/(name+'.png');im=Image.new('RGB',(100,80),'white');im.putpixel((5,5),(20,80,190));im.save(path)
    rid=ctx.sources.add_inputs([str(path)])['root_ids'][0]
    ctx.sources.scan(rid)
    file=next(x for x in ctx.sources.list_files(limit=200)['items'] if x['path']==str(path))
    ctx.sources.probe(file['id'])
    return ctx.sources.create_position(file['id'])['id']


def sample(ctx,tmp_path):
    pid=frame(ctx,tmp_path)
    return ctx.dataset.import_region(position_id=pid,roi=[0,0,100,80],form_ref='twilight.unicorn@1',request_id='sample_fixture')['record']


def test_candidates_multiple_occurrences_recrop_and_restart(ctx,tmp_path):
    pid=frame(ctx,tmp_path)
    c=ctx.dataset.decide(pid,'undecided')
    c=ctx.dataset.decide(pid,'selected',expected=c['revision'])
    a=ctx.dataset.region(c['id'],[0,0,40,60],'twilight.unicorn@1',review_status='approved')
    b=ctx.dataset.region(c['id'],[50,10,40,60],'twilight.unicorn@1',review_status='approved')
    first=ctx.dataset.generate(a['id'],a['revision'])['record']
    assert ctx.dataset.generate(a['id'],a['revision'])['record']==first
    other=ctx.dataset.generate(b['id'],b['revision'])['record']
    assert first['occurrence_id']!=other['occurrence_id']
    revised=ctx.dataset.region(c['id'],[0,0,45,65],'twilight.unicorn@1',region_id=a['id'],expected=a['revision'],review_status='approved')
    with pytest.raises(DataError,match='新版本'):ctx.dataset.generate(a['id'],a['revision'])
    recrop=ctx.dataset.generate(a['id'],revised['revision'])['record']
    assert recrop['occurrence_id']==first['occurrence_id'] and recrop['observation_id']!=first['observation_id']
    assert recrop['image_ref']!=first['image_ref'] and not recrop['annotation']['directions']
    assert ctx.library.read(first['observation_id'])==first
    reopened=ProjectContext(ROOT,ctx.library.root)
    try:
        assert len(reopened.dataset.regions())==2 and len(reopened.dataset.samples())==3
        assert reopened.dataset.generate(a['id'],revised['revision'])['record']==recrop
        assert len(reopened.dataset.store.history(a['id']))==2
    finally:reopened.close()


def test_stale_candidate_and_region_changes_cannot_overwrite(ctx,tmp_path):
    pid=frame(ctx,tmp_path);c=ctx.dataset.decide(pid,'selected')
    c2=ctx.dataset.decide(pid,'excluded',expected=c['revision'])
    with pytest.raises(ConflictError):ctx.dataset.decide(pid,'selected',expected=c['revision'])
    with pytest.raises(DataError,match='保留'):ctx.dataset.region(c['id'],[0,0,20,20],'twilight.unicorn@1')
    assert ctx.dataset.candidate(pid)['revision']==c2['revision']


def test_schema_points_are_separate_and_derivations_become_stale(ctx,tmp_path):
    r=sample(ctx,tmp_path);oid=r['observation_id']
    points={'head.center':{'value':[20,20],'visibility':'visible'},'head.forward_reference':{'value':[40,20],'visibility':'visible'}}
    r=ctx.library.edit(oid,r['annotation']['id'],{'keypoints':{'points':points}},actor='person',
        review={'status':'approved','targets':['keypoints.'+key for key in points]})
    assert not r['annotation']['directions'] and len(r['annotation']['keypoints']['points'])==21
    d=ctx.derive(oid,r['annotation']['id'])
    assert d['annotation']['directions']['core.head']['value']==[1,0]
    assert d['annotation']['directions']['core.head']['review_status']=='unreviewed'
    changed=ctx.library.edit(oid,d['annotation']['id'],{'keypoints':{'points':{'head.forward_reference':{'value':[20,50]}}}},actor='person')
    assert not usable(changed,'core.head')
    assert changed['annotation']['keypoints']['points']['head.center']['review_status']=='approved'
    assert proposals(changed)['conflicts']==['core.head']
    with pytest.raises(DataError,match='不同'):ctx.derive(oid,changed['annotation']['id'])
    applied=ctx.derive(oid,changed['annotation']['id'],replace=True)
    assert applied['annotation']['directions']['core.head']['value']==[0,1]
    manual=ctx.library.edit(oid,applied['annotation']['id'],{'directions':{'core.head':{'value':[-1,0]}}},actor='manual')
    assert 'derived_from' not in manual['annotation']['directions']['core.head']
    assert manual['annotation']['keypoints']==applied['annotation']['keypoints']


def test_direction_reference_arrows_cannot_become_training_keypoints(ctx,tmp_path):
    r=sample(ctx,tmp_path)
    ctx.library.edit(r['observation_id'],r['annotation']['id'],{'parts':{'core':{'presence':'present'}},
       'directions':{'core.head':{'reference_points':{'start':[20,20],'end':[40,20]},'visibility':'visible'}}},actor='person',
       review={'status':'approved','targets':['parts.core','directions.core.head']})
    point=ctx.training.freeze('keypoints')
    direction=ctx.training.freeze('directions')
    assert not point['records'] and point['excluded'][0]['reason']=='no_schema_points'
    assert len(direction['records'])==1


def test_suggestion_review_is_persisted_scoped_and_stale_safe(ctx,tmp_path):
    r=sample(ctx,tmp_path)
    cap={'id':'fixture_model','profiles':[r['profile_ref']],'point_order':ORDER,'model_sha256':'0'*64}
    changes={'keypoints':{'points':{'head.center':{'value':[10,20],'visibility':'visible'}}}}
    s=ctx.models.suggest(r,changes,cap)
    assert ctx.library.head_id(r['observation_id'])==r['annotation']['id']
    accepted=ctx.models.review(s['id'],s['revision'],'accepted',actor='reviewer')
    current=ctx.library.read(r['observation_id'])
    assert current['annotation']['keypoints']['points']['head.center']['review_status']=='approved'
    assert current['annotation']['keypoints']['points']['head.forward_reference']['review_status']=='unreviewed'
    assert accepted['output_ref']==current['annotation']['id']
    stale=ctx.models.suggest(current,changes,cap)
    ctx.library.edit(r['observation_id'],current['annotation']['id'],{'view':{}},actor='other')
    with pytest.raises(DataError,match='新版本'):ctx.models.review(stale['id'],stale['revision'],'accepted')
    assert next(s for s in ctx.models.suggestions() if s['id']==stale['id'])['stale']
    assert ctx.models.review(stale['id'],stale['revision'],'rejected')['status']=='rejected'


def test_detection_requires_complete_reviewed_frame_and_groups_recrops(ctx,tmp_path):
    r=sample(ctx,tmp_path);pid=r['source']['locator_ref'];c=ctx.dataset.candidate(pid)
    assert not ctx.training.freeze('detection')['records']
    c=ctx.dataset.decide(pid,'selected',expected=c['revision'],complete_regions=True)
    snapshot=ctx.training.freeze('detection')
    assert len(snapshot['records'])==1
    region=ctx.dataset.regions(c['id'])[0]
    ctx.dataset.region(c['id'],[1,1,90,70],region['form_ref'],region_id=region['id'],expected=region['revision'],review_status='approved')
    assert not ctx.training.freeze('detection')['records']
    assert ctx.training.read(snapshot['id'])['records'][0]['regions'][0]['roi']==[0,0,100,80]


def test_snapshot_preserves_points_and_materialized_package_detects_changes(ctx,tmp_path):
    r=sample(ctx,tmp_path)
    points={'head.center':{'value':[20,20],'visibility':'visible'}}
    r=ctx.library.edit(r['observation_id'],r['annotation']['id'],{'keypoints':{'points':points}},actor='reviewer',
        review={'status':'approved','targets':['keypoints.head.center']})
    snapshot=ctx.training.freeze('keypoints')
    assert snapshot['records'][0]['point_order']==ORDER
    ctx.library.edit(r['observation_id'],r['annotation']['id'],{'keypoints':{'points':{'head.center':{'value':[30,30]}}}},actor='later')
    package=ctx.training.materialize(snapshot['id'])
    assert package['records'][0]['points'][0]==[20,20]
    labels=list((ctx.training.root/'datasets'/snapshot['id']/'labels').rglob('*.txt'))
    assert labels and len(labels[0].read_text().split())==5+21*3
    assert ctx.training.materialize(snapshot['id'])==package
    labels[0].write_text('tampered')
    with pytest.raises(DataError,match='变化'):ctx.training.materialize(snapshot['id'])


def test_source_schema_upgrade_keeps_pre_upgrade_backup_and_is_repeatable(tmp_path):
    path=tmp_path/'library/sources';path.mkdir(parents=True)
    with sqlite3.connect(path/'catalog.sqlite3') as db:
        db.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        db.execute("INSERT INTO settings VALUES('schema','1')")
    ctx=ProjectContext(ROOT,tmp_path/'library')
    try:
        with ctx.sources.db() as db:
            assert db.execute("SELECT value FROM settings WHERE key='schema'").fetchone()[0]=='2'
            backup=Path(db.execute("SELECT value FROM settings WHERE key='schema_v1_backup'").fetchone()[0])
        with sqlite3.connect(backup) as db:
            assert db.execute("SELECT value FROM settings WHERE key='schema'").fetchone()[0]=='1'
        second=ProjectContext(ROOT,tmp_path/'library');second.close()
        assert len(list(path.glob('schema-v1-before-v2-*.sqlite3')))==1
    finally:ctx.close()


def test_partial_suggestion_accept_correct_reject_and_retry(ctx,tmp_path,monkeypatch):
    r=sample(ctx,tmp_path);oid=r['observation_id']
    cap={'id':'fixture_model','profiles':[r['profile_ref']],'point_order':ORDER,'model_sha256':'0'*64}
    changes={'keypoints':{'points':{k:{'value':[10+i*10,20],'visibility':'visible'} for i,k in enumerate(ORDER[:3])}}}
    s=ctx.models.suggest(r,changes,cap)
    first=ctx.models.review(s['id'],s['revision'],'accepted',targets=['keypoints.'+ORDER[0]])
    record=ctx.library.read(oid)
    assert record['annotation']['keypoints']['points'][ORDER[0]]['review_status']=='approved'
    assert record['annotation']['keypoints']['points'][ORDER[1]]['value'] is None
    assert first['status']=='pending' and not next(x for x in ctx.models.suggestions() if x['id']==s['id'])['stale']
    assert ctx.models.review(s['id'],s['revision'],'accepted',targets=['keypoints.'+ORDER[0]])==first
    patch={'keypoints':{'points':{ORDER[1]:{'value':[75,20],'visibility':'visible'}}}}
    original=ctx.models.store.save
    def interrupt(kind,*args,**kwargs):
        if kind=='suggestion':raise OSError('simulated interruption after annotation commit')
        return original(kind,*args,**kwargs)
    monkeypatch.setattr(ctx.models.store,'save',interrupt)
    with pytest.raises(OSError):ctx.models.review(s['id'],first['revision'],'corrected',changes=patch,targets=['keypoints.'+ORDER[1]])
    committed=ctx.library.head_id(oid)
    monkeypatch.setattr(ctx.models.store,'save',original)
    second=ctx.models.review(s['id'],first['revision'],'corrected',changes=patch,targets=['keypoints.'+ORDER[1]])
    assert ctx.library.head_id(oid)==committed
    final=ctx.models.review(s['id'],second['revision'],'rejected',targets=['keypoints.'+ORDER[2]])
    assert final['status']=='mixed' and len(final['decisions'])==3
    current=ctx.library.read(oid)
    assert current['annotation']['keypoints']['points'][ORDER[1]]['value']==[75,20]
    assert current['annotation']['keypoints']['points'][ORDER[2]]['value'] is None
    assert len(ctx.models.store.history(s['id']))==4


def test_sampling_and_generation_jobs_are_repeatable(ctx,tmp_path):
    pid=frame(ctx,tmp_path);position=ctx.sources.position(pid)
    file_id=position['file_id']
    job=ctx.dataset.queue_frames(file_id)
    assert ctx.dataset.queue_frames(file_id)==job
    while ctx.sources.run_next():pass
    assert ctx.sources.job(job)['state']=='done'
    c=ctx.dataset.candidate(pid);assert c['decision']=='undecided'
    c=ctx.dataset.decide(pid,'selected',expected=c['revision'])
    r=ctx.dataset.region(c['id'],[0,0,60,50],'twilight.unicorn@1',review_status='approved')
    job=ctx.dataset.queue_generate(r['id'],r['revision'])
    while ctx.sources.run_next():pass
    assert ctx.sources.job(job)['state']=='done' and len(ctx.dataset.samples())==1
    assert ctx.dataset.queue_generate(r['id'],r['revision'])==job


def test_model_job_cancel_and_restart_do_not_claim_resume(ctx,tmp_path):
    jid=ctx.sources.queue('train',{'runtime':'missing'},'test cancellation')
    ctx.sources.cancel(jid)
    assert ctx.sources.job(jid)['state']=='cancelled'
    jid=ctx.sources.queue('train',{'runtime':'missing'},'test interrupted')
    with ctx.sources.db() as db:db.execute("UPDATE jobs SET state='running' WHERE id=?",(jid,))
    ctx.sources.start()
    import time
    deadline=time.monotonic()+5
    while ctx.sources.job(jid)['state']=='running' and time.monotonic()<deadline:time.sleep(.05)
    ctx.sources.stop()
    assert ctx.sources.job(jid)['state']=='failed'
    assert '重新' in ctx.sources.job(jid)['error']


def test_verified_legacy_crop_binding_keeps_annotation_and_recrop_occurrence(ctx,tmp_path):
    from multispecies import new_observation
    import io
    pid=frame(ctx,tmp_path)
    with Image.open(ctx.sources.cached_image(pid)) as image:
        out=io.BytesIO();image.crop((5,5,75,65)).save(out,'PNG')
    asset=ctx.library.upload_image(out.getvalue())
    old=new_observation(ctx.library.catalog,profile_ref='pony.quadruped@2draft1',image_ref=asset['id'],image_size=asset['size'])
    ctx.library.save(old)
    c=ctx.dataset.decide(pid,'selected');region=ctx.dataset.region(c['id'],[5,5,70,60],'twilight.unicorn@1',review_status='approved')
    updated=ctx.service.bind_legacy_region(region,old)
    assert updated['observation_id']==old['observation_id'] and updated['image_ref']==old['image_ref']
    assert updated['annotation']['directions']==old['annotation']['directions'] and updated['source']['precision']=='image_exact'
    with ctx.sources.db() as db:db.execute('INSERT INTO generated_samples VALUES(?,?,?)',(region['revision'],old['observation_id'],updated['source']['import_ref']))
    assert ctx.dataset.generate(region['id'],region['revision'])['record']==updated
    changed=ctx.dataset.region(c['id'],[6,5,69,60],'twilight.unicorn@1',region_id=region['id'],expected=region['revision'],review_status='approved')
    recrop=ctx.dataset.generate(changed['id'],changed['revision'])['record']
    assert recrop['occurrence_id']==old['occurrence_id'] and recrop['image_ref']!=old['image_ref']
    bad=new_observation(ctx.library.catalog,profile_ref=old['profile_ref'],image_ref=asset['id'],image_size=asset['size']);ctx.library.save(bad)
    with pytest.raises(DataError,match='像素'):ctx.service.bind_legacy_region(changed,bad)


def test_pair_snapshot_same_images_and_groups_without_promoting_points(ctx,tmp_path):
    r=sample(ctx,tmp_path);oid=r['observation_id']
    points={ORDER[0]:{'value':[20,20],'visibility':'visible'}}
    r=ctx.library.edit(oid,r['annotation']['id'],{'keypoints':{'points':points},'parts':{'core':{'presence':'present'}},
        'directions':{'core.head':{'value':[1,0],'visibility':'visible'}}},actor='test',
        review={'status':'approved','targets':['keypoints.'+ORDER[0],'parts.core','directions.core.head']})
    result=ctx.training.freeze_pair()
    first=ctx.training.read(result['snapshots']['keypoints']);second=ctx.training.read(result['snapshots']['directions'])
    assert [(e['observation_id'],e['split']) for e in first['records']]==[(e['observation_id'],e['split']) for e in second['records']]
    assert first['comparison_id']==second['comparison_id']==result['id']


def test_interrupted_annotation_head_commit_recovers_without_rolling_back(ctx,tmp_path,monkeypatch):
    import multispecies.library as module
    r=sample(ctx,tmp_path);original=module._atomic_json
    def fail_head(path,data):
        if path.name=='HEAD.json':raise OSError('interrupt before head')
        return original(path,data)
    from multispecies.records import revise
    newer=revise(r,ctx.library.catalog,{'view':{}},actor='test')
    monkeypatch.setattr(module,'_atomic_json',fail_head)
    with pytest.raises(OSError):ctx.library.save(newer,expected_revision=r['annotation']['id'])
    assert ctx.library.head_id(r['observation_id'])==r['annotation']['id']
    monkeypatch.setattr(module,'_atomic_json',original)
    ctx.library.save(newer,expected_revision=r['annotation']['id'])
    assert ctx.library.head_id(r['observation_id'])==newer['annotation']['id']
    latest=ctx.library.edit(r['observation_id'],newer['annotation']['id'],{'view':{}},actor='later')
    ctx.library.save(newer,expected_revision=r['annotation']['id'])
    assert ctx.library.head_id(r['observation_id'])==latest['annotation']['id']


def test_detection_accepts_pending_candidate_and_keeps_sibling_suggestions_current(ctx,tmp_path):
    pid=frame(ctx,tmp_path);c=ctx.dataset.decide(pid,'undecided')
    import hashlib
    cap={'id':'fixture_detector','forms':{'0':'twilight.unicorn@1'}}
    common={'target_kind':'candidate','target_id':c['id'],'input_revision':c['revision'],
        'image_sha256':hashlib.sha256(ctx.sources.cached_image(pid).read_bytes()).hexdigest(),'capability':cap,'status':'pending','output_ref':None}
    suggestions=[]
    for i in range(2):
        suggestions.append(ctx.models.store.save('suggestion','fixture_box_'+str(i),{**common,'changes':{'roi':[i*40,0,30,60],'form_ref':'twilight.unicorn@1'}},parent=c['id'],actor='fixture'))
    first,second=suggestions
    ctx.models.review(first['id'],first['revision'],'accepted')
    assert ctx.dataset.candidate(pid)['decision']=='selected'
    assert not next(s for s in ctx.models.suggestions() if s['id']==second['id'])['stale']
    ctx.models.review(second['id'],second['revision'],'accepted')
    assert len(ctx.dataset.regions(c['id']))==2


def test_compatibility_m01_to_m06_commands_use_shared_lifecycle(ctx,tmp_path):
    import subprocess,os
    path=tmp_path/'cli.png';im=Image.new('RGB',(100,80),'white');im.putpixel((3,3),(50,90,160));im.save(path)
    scripts={'M01':'extract_frames.py','M02':'select_candidates.py','M03':'annotate_bboxes.py','M04':'crop_characters.py','M06':'generate_pose_vectors.py'}
    def call(mid,action,request=None,wait=False):
        request_path=tmp_path/'request.json';request_path.write_text(json.dumps(request or {}),encoding='utf-8')
        command=[sys.executable,str(ROOT/'scripts'/mid.lower()/scripts[mid]),'--library',str(ctx.library.root),'--action',action,'--request',str(request_path)]
        if wait:command.append('--wait')
        result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',env=dict(os.environ,PYTHONUTF8='1'),timeout=30)
        assert result.returncode==0,result.stdout+result.stderr
        return json.loads(result.stdout)
    call('M01','import',{'paths':[str(path)]},True)
    file=call('M01','list')['items'][0]
    call('M01','frames',{'file_id':file['id']},True)
    c=call('M02','list')[0]
    c=call('M02','decide',{'position_id':c['position_id'],'decision':'selected','expected':c['revision']})
    r=call('M03','region',{'candidate_id':c['id'],'roi':[0,0,100,80],'form_ref':'twilight.unicorn@1','review_status':'approved'})
    jobs=call('M04','generate',{'region_id':r['id'],'revision':r['revision']},True)
    assert jobs[0]['state']=='done' and len(ctx.dataset.samples())==1
    assert call('M06','verify')['records']==1
