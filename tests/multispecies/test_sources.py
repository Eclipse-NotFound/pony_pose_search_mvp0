"""Source identity, exact decoding, crash recovery and real loopback endpoints.

All annotations, media and exported results live in pytest's isolated directory.
"""
import copy
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import threading
import time
import zipfile
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'scripts/common'), str(ROOT/'scripts/m11')]
from multispecies import Library, DataError, validate_observation
from multispecies.records import new_observation
from multispecies.matching import search
from source_catalog import SourceCatalog, SourceService
from source_catalog import media


def image(path):
    im = Image.new('RGB',(80,60),'white')
    for x in range(80):
        for y in range(60):
            im.putpixel((x,y),(x*3,y*4,(x+y)%255))
    path.parent.mkdir(parents=True,exist_ok=True); im.save(path)
    return im


def drain(c):
    for _ in range(200):
        if not c.run_next(): return
    raise AssertionError('queue did not finish')


@pytest.fixture
def setup(tmp_path):
    lib = Library(tmp_path/'library',default_catalog=ROOT/'data/meta/body_catalog_v2.json')
    c = SourceCatalog(lib.root/'sources')
    folder = tmp_path/'originals'; folder.mkdir(); image(folder/'scene.png')
    added = c.add_inputs([str(folder)]); drain(c)
    f = c.list_files()['items'][0]
    return lib,c,SourceService(c,lib),folder,added['root_ids'][0],f


def imported(setup, request='request_first', roi=None):
    lib,c,s,folder,rid,f = setup
    p = c.create_position(f['id'])
    return s.import_observation(position_id=p['id'],roi=roi or [10,10,40,30],form_ref='twilight.unicorn@1',request_id=request,actor='test fixture')['record']


def approve(lib,r,angle=(1,0)):
    return lib.edit(r['observation_id'],r['annotation']['id'],{'parts':{'core':{'presence':'present'}},
                'directions':{'core.head':{'value':list(angle),'visibility':'visible'}}},actor='test fixture',
                review={'status':'approved','targets':['parts.core','directions.core.head']})


def test_mixed_scan_individual_errors_repeat_and_candidates(setup):
    lib,c,s,folder,rid,original = setup
    with zipfile.ZipFile(folder/'scene.fla','w') as z:
        z.writestr('DOMDocument.xml','<DOMDocument frameRate="24"><timelines><DOMTimeline name="Scene 1"><layers><DOMLayer name="pony"><frames><DOMFrame index="0" duration="106"/></frames></DOMLayer></layers></DOMTimeline></timelines></DOMDocument>')
    (folder/'old.fla').write_bytes(bytes.fromhex('d0cf11e0a1b11ae1')+b'fixture')
    (folder/'scene.swf').write_bytes(b'FWS\x09'+(8).to_bytes(4,'little'))
    (folder/'bad.png').write_bytes(b'broken image')
    (folder/'notes.bin').write_bytes(b'opaque')
    xfl=folder/'scene_xfl';xfl.mkdir();(xfl/'DOMDocument.xml').write_text('<DOMDocument/>');(xfl/'LIBRARY').mkdir();(xfl/'LIBRARY'/'part.xml').write_text('part')
    c.scan(rid);drain(c)
    files=c.list_files()['items'];assert len(files)==7
    bad=next(x for x in files if x['name']=='bad.png');assert bad['state']=='error' and bad['version_id']
    assert c.verified_path(bad['id'])[0]==folder/'bad.png'
    modern=next(x for x in files if x['name']=='scene.fla');assert modern['metadata']['container']=='zip_xml'
    assert c.file(modern['id'])['metadata']['scenes'][0]['frames']==106
    assert len(c.related(original['id']))==2
    assert all(x['status']=='candidate' for x in c.related(original['id']))
    vcount=len(c.export()['versions']);c.scan(rid);drain(c);assert len(c.export()['versions'])==vcount
    assert len(c.list_files()['items'])==7
    with pytest.raises(DataError): c.create_position(modern['id'])


def test_selected_files_do_not_import_siblings_and_exclusions(setup):
    lib,c,s,folder,rid,f=setup
    elsewhere=folder.parent/'selected';elsewhere.mkdir();image(elsewhere/'keep.png');image(elsewhere/'ignore.png')
    rr=c.add_inputs([str(elsewhere/'keep.png')])['root_ids'][0];drain(c)
    assert [x['name'] for x in c.list_files(root_id=rr)['items']]==['keep.png']
    nested=folder/'skip';nested.mkdir();image(nested/'hidden.png')
    c.add_inputs([str(folder)],excludes=['skip']);drain(c)
    assert len(c.list_files(root_id=rid)['items'])==1


def test_fla_nonstandard_directory_local_crc_and_bounded_document(tmp_path):
    path=tmp_path/'local.fla'
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('DOMDocument.xml','<DOMDocument width="1920"/>')
    data=path.read_bytes();cut=data.index(b'PK\x01\x02')
    path.write_bytes(data[:cut]+b'nonstandard central directory')
    raw,container=media.fla_document(path);assert container=='zip_local_records' and b'1920' in raw
    corrupted=bytearray(path.read_bytes());corrupted[14]^=1;path.write_bytes(corrupted)
    with pytest.raises(DataError,match='CRC'):media.fla_document(path)


def test_unicode_xml_does_not_bypass_declaration_rejection():
    document='<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE DOMDocument [<!ENTITY value "1920">]><DOMDocument width="&value;"/>'
    with pytest.raises(DataError,match='外部声明'):media._xml(document.encode('utf-16'))


def test_roi_unknown_parts_idempotency_and_recovery(setup,monkeypatch):
    lib,c,s,folder,rid,f=setup
    r=imported(setup);assert r['annotation']['directions']=={}
    assert all(x['presence']=='unknown' for x in r['annotation']['parts'].values())
    assert r['source']['source_to_image']==[1,0,0,1,-10,-10]
    full=Image.open(folder/'scene.png').crop((10,10,50,40)).convert('RGBA')
    raw,_=lib.image_bytes(r['image_ref']);assert Image.open(io.BytesIO(raw)).convert('RGBA').tobytes()==full.tobytes()
    edited=approve(lib,r)
    again=imported(setup);assert again['annotation']['id']==edited['annotation']['id']
    with pytest.raises(DataError,match='同一导入'): imported(setup,roi=[0,0,10,10])
    second=imported(setup,'request_second',[30,5,25,45]);assert second['observation_id']!=r['observation_id']
    original_commit=s._commit_import
    monkeypatch.setattr(s,'_commit_import',lambda *args: (_ for _ in ()).throw(OSError('interrupted at commit')))
    with pytest.raises(OSError): imported(setup,'request_recovery')
    assert len(s.records())==2 and len(lib.records())==3
    monkeypatch.setattr(s,'_commit_import',original_commit);s.recover()
    assert len(s.records())==3
    recovered=imported(setup,'request_recovery');assert recovered['source']['import_ref']=='request_recovery'
    assert len(s.records())==3


@pytest.mark.parametrize('region',[[0,0,0,5],[-1,0,5,5],[70,0,20,5],[1.5,0,5,5],[True,0,5,5]])
def test_invalid_roi_does_not_create_observation(setup,region):
    with pytest.raises(DataError): imported(setup,roi=region)
    assert setup[0].records()==[]


def test_source_crop_validation(setup):
    r=imported(setup);r['source']['source_to_image']=[1,0,0,1,0,0]
    with pytest.raises(DataError): validate_observation(r,setup[0].catalog)


def test_source_replacement_preserves_old_picture_and_blocks_mislocation(setup):
    lib,c,s,folder,rid,f=setup;r=imported(setup);pid=r['source']['locator_ref'];before=c.cached_image(pid).read_bytes()
    im=Image.open(folder/'scene.png').convert('RGB');im.putpixel((20,20),(0,0,0));im.save(folder/'scene.png')
    assert s.describe(r)['availability']=='changed'
    with pytest.raises(DataError,match='内容已改变'): c.verified_path(f['id'],f['version_id'])
    c.scan(rid);drain(c);assert c.file(f['id'])['version_id']!=f['version_id']
    assert c.cached_image(pid).read_bytes()==before and s.describe(r)['availability']=='changed'
    with pytest.raises(DataError): c.create_position(f['id'],version_id=f['version_id'])
    assert c.create_position(f['id'])['id']!=pid


def test_hash_check_catches_same_size_same_mtime_replacement(setup):
    lib,c,s,folder,rid,f=setup
    opaque=folder/'raw.bin';opaque.write_bytes(b'old bytes');c.scan(rid);drain(c)
    f=next(x for x in c.list_files()['items'] if x['name']=='raw.bin');st=opaque.stat();opaque.write_bytes(b'new bytes');os.utime(opaque,ns=(st.st_atime_ns,st.st_mtime_ns))
    with pytest.raises(DataError,match='内容已改变'): c.verified_path(f['id'])


def test_rebind_requires_all_matching_content_and_old_roi_survives(setup):
    lib,c,s,folder,rid,f=setup;r=imported(setup)
    wrong=folder.parent/'wrong';wrong.mkdir();image(wrong/'scene.png');im=Image.open(wrong/'scene.png');im.putpixel((2,2),(0,0,0));im.save(wrong/'scene.png')
    with pytest.raises(DataError,match='同名不同内容'): c.rebind_root(rid,str(wrong))
    assert c.get_root(rid)['path']==str(folder)
    moved=folder.parent/'moved';folder.rename(moved)
    assert s.describe(r)['availability']=='offline'
    c.rebind_root(rid,str(moved));assert s.describe(r)['availability']=='available'
    assert c.verified_path(f['id'])[0]==moved/'scene.png'
    assert s.describe(r)['roi']==[10,10,40,30]


def test_pause_restart_worker_recovers_claimed_tasks(setup):
    lib,c,s,folder,rid,f=setup
    c.pause(True);job=c.queue('scan',{'root_id':rid});assert not c.run_next()
    replacement=SourceCatalog(c.root);assert replacement.paused
    with c.db() as db:db.execute("UPDATE jobs SET state='running' WHERE id=?",(job,))
    replacement.pause(False);replacement.start()
    try:
        for _ in range(100):
            if replacement.job(job)['state']=='done':break
            time.sleep(.05)
        assert replacement.job(job)['state']=='done'
    finally: replacement.stop()


def test_interactive_frame_is_not_stuck_behind_batch_probes(setup):
    lib,c,s,folder,rid,f=setup
    background=c.queue('probe',{'file_id':f['id']})
    requested=c.queue('position',{'fid':f['id']})
    c.run_next()
    assert c.job(requested)['state']=='done' and c.job(background)['state']=='queued'


def test_same_name_different_bytes_and_same_bytes_different_paths(setup):
    lib,c,s,folder,rid,f=setup
    def fla(path,width):
        path.parent.mkdir()
        with zipfile.ZipFile(path,'w') as z:z.writestr('DOMDocument.xml',f'<DOMDocument width="{width}"/>')
    a,b=folder/'a'/'same.fla',folder/'b'/'same.fla';fla(a,1920);fla(b,1280)
    same=folder/'c'/'same.fla';same.parent.mkdir();shutil.copyfile(a,same)
    c.scan(rid);drain(c)
    files={f['rel_path']:f for f in c.list_files()['items']}
    assert files['a/same.fla']['version_id']!=files['b/same.fla']['version_id']
    assert files['a/same.fla']['version_id']==files['c/same.fla']['version_id']
    assert files['a/same.fla']['id']!=files['c/same.fla']['id']
    assert c.verified_path(files['c/same.fla']['id'])[0]==same
    assert all(x['status']=='candidate' for x in c.related(files['a/same.fla']['id']))


def test_exif_orientation_before_roi(setup):
    lib,c,s,folder,rid,f=setup
    im=image(folder/'rotate.jpg');exif=im.getexif();exif[274]=6;im.save(folder/'rotate.jpg',exif=exif)
    c.scan(rid);drain(c);f=next(x for x in c.list_files()['items'] if x['name']=='rotate.jpg')
    p=c.create_position(f['id']);assert p['payload']['image_size']==[60,80]
    assert p['payload']['exif_orientation']==6


@pytest.mark.parametrize('ordinal',[-1,3,True,1.5])
def test_decoded_index_bounds(ordinal):
    index={'frame_count':3}
    with pytest.raises(DataError):media.frame_position(index,ordinal)


def test_missing_and_repeated_timestamps_are_not_frame_identity():
    index={'frame_count':3,'stream_index':2,'time_base':[1,1000],'start_pts':5000,'decoder':{},
           'frames':[{'pts':5000,'timestamp_basis':'pts'},{'pts':5000,'timestamp_basis':'pts'},{'pts':None,'timestamp_basis':'missing'}]}
    a,b,c=[media.frame_position(index,i) for i in range(3)]
    assert a['seconds']==b['seconds']==0 and a['presentation_ordinal0']!=b['presentation_ordinal0']
    assert c['seconds'] is None and c['presentation_ordinal0']==2


def test_actual_vfr_nonzero_start_multistream_and_pixel_frame(setup):
    lib,c,s,folder,rid,f=setup
    # Red, green, blue on a stream with unequal PTS gaps; another video stream is distinct.
    src=folder.parent/'frames';src.mkdir()
    for n,col in enumerate(['red','green','blue']):Image.new('RGB',(32,24),col).save(src/f'{n}.png')
    movie=folder/'vfr.mkv'
    media.run('ffmpeg',['-v','error','-y','-framerate','10','-i',src/'%d.png','-f','lavfi','-i','color=yellow:s=32x24:r=1:d=3',
        '-filter_complex',"[0:v]setpts='5/TB+if(eq(N,0),0,if(eq(N,1),0.5/TB,2/TB))'[v]",'-map','[v]','-map','1:v','-fps_mode:v:0','vfr','-c:v','ffv1',movie])
    c.scan(rid);drain(c);f=next(x for x in c.list_files()['items'] if x['name']=='vfr.mkv')
    assert f['state']=='ready',f.get('error')
    p=c.create_position(f['id'],ordinal0=1,stream_index=0);p2=c.create_position(f['id'],ordinal0=1,stream_index=1)
    assert p['payload']['start_pts']>0 and p['payload']['presentation_ordinal0']==1
    pixel=Image.open(c.cached_image(p['id'])).convert('RGB').getpixel((10,10));assert pixel[1]>100 and pixel[0]<10 and pixel[2]<10
    other=Image.open(c.cached_image(p2['id'])).convert('RGB').getpixel((10,10));assert other[0]>200 and other[1]>200
    assert p['id']!=p2['id']
    index=media.frame_index(movie,0,f['metadata']);assert len(set(index['frames'][i+1]['pts']-index['frames'][i]['pts'] for i in range(2)))==2
    proxy=c.create_proxy(p['id']);assert proxy['precision']=='time_approx' and (c.cache/proxy['cache_name']).is_file()
    assert proxy['seconds']==.5
    proxy_probe=json.loads(media.run('ffprobe',['-v','error','-show_streams','-of','json',c.cache/proxy['cache_name']]))
    assert float(proxy_probe['streams'][0]['start_time'])==0
    with pytest.raises(DataError):c.create_position(f['id'],ordinal0=3)


def test_search_scores_unchanged_and_source_filters_apply_before_ranking(setup):
    lib,c,s,folder,rid,f=setup
    a=approve(lib,imported(setup,'request_a'));b=approve(lib,imported(setup,'request_b'))
    before=search(a,lib.records(),lib.catalog,contract_ref='pony.body14@1')
    filtered=s.filter_records(s.records(),{'exact':True,'format':'PNG'})
    after=search(a,filtered,lib.catalog,contract_ref='pony.body14@1')
    assert before==after and before['results'][0]['score']==1
    assert s.filter_records(s.records(),{'format':'FLA'})==[]
    without=copy.deepcopy(a);without['source']={'timestamp_sec':12.5,'frame_index':999,'label':'old fixture'}
    desc=s.describe(without);assert desc['precision']=='time_approx' and 'presentation_ordinal0' not in desc['position']


def test_paths_and_corrupted_cached_frame(setup):
    lib,c,s,folder,rid,f=setup
    with pytest.raises(DataError):media.within(folder/'..'/'escape',folder)
    with pytest.raises(DataError):c.file('../catalog.sqlite3')
    p=c.create_position(f['id']);cached=c.cached_image(p['id']);cached.write_bytes(b'bad cache')
    with pytest.raises(DataError,match='缓存已改变'):c.cached_image(p['id'])
    c.create_position(f['id']);assert c.cached_image(p['id']).read_bytes()!=b'bad cache'


def test_mutation_during_probe_does_not_commit_wrong_version(setup,monkeypatch):
    lib,c,s,folder,rid,f=setup
    old=media.inspect
    def mutate(path,kind,thumb):
        result=old(path,kind,thumb);im=Image.open(path);im.putpixel((4,4),(0,0,0));im.save(path);return result
    monkeypatch.setattr(media,'inspect',mutate)
    with pytest.raises(DataError,match='源文件已变化'):c.probe(f['id'])
    assert c.file(f['id'])['version_id']==f['version_id']


def test_stop_cancels_media_child_process(monkeypatch):
    process_holder=[];original=media.subprocess.Popen
    def capture(*args,**kwargs):
        p=original(*args,**kwargs);process_holder.append(p);return p
    monkeypatch.setattr(media.subprocess,'Popen',capture)
    stop=threading.Event();caught=[]
    def task():
        media._context.stop=stop
        try:media.run('ffmpeg',['-v','error','-re','-f','lavfi','-i','testsrc=size=32x24:rate=1','-f','null','-'])
        except media.Cancelled:caught.append(True)
    t=threading.Thread(target=task);t.start()
    for _ in range(100):
        if process_holder:break
        time.sleep(.01)
    stop.set();t.join(3)
    assert not t.is_alive() and caught and process_holder[0].poll() is not None


