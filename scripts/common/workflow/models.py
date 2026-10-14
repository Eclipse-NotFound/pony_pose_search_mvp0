"""Persisted model capabilities, frozen input jobs, and explicit suggestion review."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from multispecies.catalog import fingerprint, load_json, require
from multispecies.library import _atomic_json
from multispecies.records import new_id, now, revise, validate_observation
from multispecies.keypoints import SCHEMA, ORDER, PROFILES
from source_catalog.schema import RevisionStore


class ModelWorkflow:
    def __init__(self, context):
        self.context = context
        self.library, self.sources = context.library, context.sources
        self.store = RevisionStore(self.sources)
        self.root = self.library.root/'models'

    def runtimes(self):
        project = self.context.project
        choices = [os.environ.get('POSE_AI_PYTHON'),
                   str(project/'experiments/direction_expanded_20261009/.yolo-venv/Scripts/python.exe'),
                   str(project/'experiments/direction_expanded_20261009/.venv/Scripts/python.exe'), sys.executable]
        return list(dict.fromkeys(str(Path(p).resolve()) for p in choices if p and Path(p).is_file()))

    def register(self, path, backend, *, profiles=None, point_order=None, directions=None, forms=None, actor='本机用户'):
        path=Path(path).resolve()
        require(path.is_file(), '找不到模型文件')
        require(backend in {'yolo_pose','yolo_detection','body14_resnet'}, '未实现此模型后端')
        if backend == 'yolo_pose':
            require(point_order == ORDER and profiles and set(profiles) <= PROFILES, '点位模型必须明确声明相同的 21 点顺序和适用身体')
        elif backend == 'body14_resnet':
            from multispecies.importers import LEGACY_MAPPING
            require(directions == list(LEGACY_MAPPING.values()) and profiles and set(profiles) <= PROFILES, '方向模型必须声明 body14 语义顺序和适用身体')
        else:
            require(isinstance(forms, dict) and forms, '检测模型必须声明类别编号对应的角色形态')
            for key, value in forms.items():
                require(str(key).isdigit(), '类别编号须为非负整数')
                self.library.catalog.get('forms',value)
        sha=hashlib.sha256(path.read_bytes()).hexdigest()
        spec={'path':str(path),'model_sha256':sha,'backend':backend,'profiles':profiles or [],
              'point_order':point_order,'directions':directions,'forms':forms or {},'schema_ref':SCHEMA if point_order else None,
              'actor':actor,'created_at':now()}
        spec['id']='model_'+fingerprint([sha,backend,profiles,point_order,directions,forms])[:32]
        destination=self.root/(spec['id']+'.json')
        if destination.exists():return load_json(destination)
        _atomic_json(destination,spec)
        return spec

    def models(self):
        return [load_json(p) for p in sorted(self.root.glob('model_*.json'))]

    def model(self, key):
        from multispecies.library import _safe_id
        spec=load_json(self.root/(_safe_id(key)+'.json'))
        require(Path(spec['path']).is_file() and hashlib.sha256(Path(spec['path']).read_bytes()).hexdigest()==spec['model_sha256'], '模型内容已经变化，请重新登记')
        return spec

    def suggest(self, record, changes, capability, *, suggestion_id=None):
        # Validate the complete prospective record before exposing a suggestion.
        require(record['profile_ref'] in capability['profiles'], '模型未声明支持此身体结构')
        require(isinstance(changes,dict) and set(changes) <= {'keypoints','directions'}, '模型建议只能修改明确支持的姿态字段')
        if 'keypoints' in changes:
            require(capability.get('point_order')==ORDER, '点位模型的语义顺序不匹配')
        if 'directions' in changes:
            require(set(changes['directions']) <= set(capability.get('directions') or []), '方向输出超出模型能力')
        revise(record,self.library.catalog,changes,actor=capability['id'])
        sid=suggestion_id or new_id('suggestion')
        existing=next((s for s in self.suggestions() if s['id']==sid),None)
        if existing:return existing
        return self.store.save('suggestion',sid,{'target_kind':'observation','target_id':record['observation_id'],
            'input_revision':record['annotation']['id'],'image_ref':record['image_ref'],
            'image_sha256':self.library.assets[record['image_ref']]['sha256'],'capability':capability,
            'changes':changes,'status':'pending','output_ref':None},parent=record['observation_id'],actor=capability['id'])

    @staticmethod
    def candidate_matches(suggestion, candidate):
        evidence=candidate.get('evidence',{})
        return candidate['revision']==suggestion['input_revision'] or (candidate['decision']=='selected' and
            evidence.get('kind')=='model_candidate_review' and evidence.get('input_revision')==suggestion['input_revision'] and
            evidence.get('model_id')==suggestion['capability']['id'])

    def suggestions(self):
        result=self.store.list('suggestion')
        for row in result:
            if row['target_kind']=='observation':current=self.library.head_id(row['target_id'])
            else:
                candidate=self.store.read(row['target_id'])
                current=row['input_revision'] if self.candidate_matches(row,candidate) else candidate['revision']
            row['stale']=row['input_revision'] != current and row['status']=='pending'
        return result

    @staticmethod
    def targets(patch):
        return ['keypoints.'+k for k in patch.get('keypoints',{}).get('points',{})]+['directions.'+k for k in patch.get('directions',{})]

    @staticmethod
    def scoped(patch, targets):
        result={}
        for target in targets:
            kind,key=target.split('.',1)
            if kind=='keypoints':
                result.setdefault(kind,{'schema_ref':SCHEMA,'points':{}})['points'][key]=copy.deepcopy(patch[kind]['points'][key])
            elif kind=='directions':result.setdefault(kind,{})[key]=copy.deepcopy(patch[kind][key])
        return result

    def review(self, sid, revision, decision, *, actor='本机用户', changes=None, targets=None):
        require(decision in {'accepted','corrected','rejected'}, '请选择接受、修改后接受或拒绝')
        suggestion=self.store.read(sid)
        if suggestion['revision']!=revision:
            # An identical repeated submission returns the durable decision.
            event=next((e for e in suggestion.get('decisions',[]) if e['suggestion_revision']==revision),None)
            require(event and event['decision']==decision and event.get('requested_targets')==targets
                    and event.get('requested_changes')==changes,'建议已经处理，请刷新')
            return suggestion
        require(suggestion['status']=='pending','这份建议已处理，不可改写历史结论')
        output=None;remaining={};selected=[]
        patch=changes if decision=='corrected' else suggestion['changes']
        if suggestion['target_kind']=='observation':
            available=self.targets(suggestion['changes'])
            selected=targets if targets is not None else available
            require(selected and len(selected)==len(set(selected)) and set(selected)<=set(available),'只能审核本建议覆盖的点位或方向')
            if decision!='rejected':
                require(isinstance(patch,dict) and set(patch)<= {'keypoints','directions'},'修改内容只能包含本模型建议的姿态字段')
                require(set(self.targets(patch))<=set(available) and set(selected)<=set(self.targets(patch)),'修改内容超出本建议范围')
                patch=self.scoped(patch,selected)
            remaining=self.scoped(suggestion['changes'],[t for t in available if t not in selected])
        token=fingerprint([sid,revision,decision,targets,changes])
        if decision!='rejected':
            if suggestion['target_kind']=='observation':
                oid=suggestion['target_id'];current=self.library.read(oid)
                applied=next((e for e in current['evidence'] if e.get('decision_ref')==token),None)
                if applied:output=current['annotation']['id']
                else:
                    require(current['annotation']['id']==suggestion['input_revision'], '输入标注已有新版本，旧建议不能覆盖；请重新预测')
                    self.library.image_bytes(suggestion['image_ref'])
                    require(self.library.assets[suggestion['image_ref']]['sha256']==suggestion['image_sha256'],'建议对应图片已变化')
                    updated=revise(current,self.library.catalog,patch,actor=actor,
                        review={'status':'corrected' if decision=='corrected' else 'approved','targets':selected})
                    updated['evidence'][-1].update(kind='model',capability=suggestion['capability'],suggestion_ref=sid,
                        decision_ref=token,decision=decision,input_revision=suggestion['input_revision'],reviewed_by=actor)
                    validate_observation(updated,self.library.catalog)
                    self.library.save(updated,expected_revision=suggestion['input_revision'])
                    output=updated['annotation']['id']
            else:
                require(targets is None,'角色框整体审核')
                c=self.store.read(suggestion['target_id'])
                rid='region_suggestion_'+fingerprint(sid)[:24]
                old=next((r for r in self.context.dataset.regions(c['id']) if r['id']==rid),None)
                if old:
                    require(old.get('evidence',{}).get('decision_ref')==token,'角色框已存在其他审核结论')
                else:
                    require(self.candidate_matches(suggestion,c), '候选判断已有新版本，请重新预测')
                    path=self.sources.cached_image(c['position_id'])
                    require(hashlib.sha256(path.read_bytes()).hexdigest()==suggestion['image_sha256'],'建议对应画面已变化')
                if c['decision']=='undecided':
                    c=self.context.dataset.decide(c['position_id'],'selected',set_id=c['set_id'],expected=c['revision'],actor=actor,
                        evidence={'kind':'model_candidate_review','input_revision':suggestion['input_revision'],'model_id':suggestion['capability']['id']})
                region=old or self.context.dataset.region(c['id'],patch['roi'],patch['form_ref'],region_id=rid,
                    actor=actor,review_status='corrected' if decision=='corrected' else 'approved',
                    evidence={'kind':'model','suggestion_ref':sid,'decision_ref':token,'capability':suggestion['capability']})
                output=region['revision']
        pending=bool(self.targets(remaining))
        event={'suggestion_revision':revision,'decision':decision,'targets':selected,'requested_targets':targets,
               'requested_changes':changes,'output_ref':output,'reviewed_by':actor,'reviewed_at':now()}
        return self.store.save('suggestion',sid,{**suggestion,'status':'pending' if pending else ('mixed' if len({e['decision'] for e in suggestion.get('decisions',[])}|{decision})>1 else decision),
            'original_input_revision':suggestion.get('original_input_revision',suggestion['input_revision']),
            'input_revision':output if pending and output else suggestion['input_revision'],
            'changes':remaining if pending else suggestion['changes'],'output_ref':output,'reviewed_by':actor,
            'reviewed_at':event['reviewed_at'],'decisions':suggestion.get('decisions',[])+[event]},
            expected=revision,parent=suggestion['target_id'],actor=actor)

    def queue_predict(self, model_id, *, observations=None, candidates=None, runtime=None):
        spec=self.model(model_id); inputs=[]
        require(bool(observations) != bool(candidates), '请选择姿态或候选画面中的一种')
        if observations:
            require(spec['backend']!='yolo_detection','检测器需要完整候选画面')
            for oid in observations:
                r=self.library.read(oid)
                require(r['profile_ref'] in spec['profiles'],'模型不支持所选身体')
                self.library.image_bytes(r['image_ref'])
                asset=self.library.assets[r['image_ref']]
                inputs.append({'id':oid,'revision':r['annotation']['id'],'record':r,'path':asset['path'],'sha256':asset['sha256']})
        else:
            require(spec['backend']=='yolo_detection','此模型需要角色裁剪图')
            for cid in candidates:
                c=self.store.read(cid)
                require(c['decision']!='excluded','已排除画面不参与检测，请先改为待判断或保留')
                p=self.sources.cached_image(c['position_id'])
                inputs.append({'id':cid,'revision':c['revision'],'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
        request={'operation':'predict','model':spec,'inputs':inputs,'runtime':runtime or self.runtimes()[0]}
        return self.sources.queue('predict',request,'predict:'+fingerprint(request))

    def queue_train(self, snapshot_id, *, runtime=None, epochs=20, image_size=224, batch=4, device='cpu', seed=17):
        require(type(epochs) is int and 1<=epochs<=10000,'训练轮数须为 1—10000')
        require(type(batch) is int and 1<=batch<=1024,'批量须为 1—1024')
        require(type(image_size) is int and 64<=image_size<=2048,'训练尺寸须为 64—2048')
        package=self.context.training.materialize(snapshot_id)
        require(any(e['split']=='train' for e in package['records']) and any(e['split']=='validation' for e in package['records']),
                '需要分组独立的训练和验证图片；不能把训练集自动当验证集')
        request={'operation':'train','package':package,'runtime':runtime or self.runtimes()[0],
                 'epochs':epochs,'image_size':image_size,'batch':batch,'device':device,'seed':seed}
        return self.sources.queue('train',request,'train:'+fingerprint(request))

    def execute(self, request, jid):
        runtime=Path(request['runtime'])
        require(runtime.is_file(),'所选训练解释器不存在')
        out=self.library.root/'jobs'/jid;out.mkdir(parents=True,exist_ok=True)
        payload={**request,'output_dir':str(out),'project':str(self.context.project)}
        _atomic_json(out/'request.json',payload)
        script=self.context.project/'scripts/ai/workflow_worker.py'
        log=out/'worker.log'
        with log.open('w',encoding='utf-8') as stream:
            proc=subprocess.Popen([str(runtime),'-X','utf8','-B',str(script),'--request',str(out/'request.json')],
                stdout=stream,stderr=subprocess.STDOUT,cwd=out,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            try:
                while proc.poll() is None:
                    if self.sources._stop.is_set() or self.sources.job(jid)['state']=='cancel_requested':
                        proc.terminate()
                        try:proc.wait(timeout=3)
                        except subprocess.TimeoutExpired:proc.kill();proc.wait()
                        raise ValueError('任务已停止；训练不承诺断点续训，重试会重新开始')
                    time.sleep(.2)
            finally:
                if proc.poll() is None:proc.kill();proc.wait()
        require(proc.returncode==0,'模型任务失败，日志：'+str(log)+'\n'+log.read_text(encoding='utf-8')[-1800:])
        result=load_json(out/'result.json')
        if request['operation']=='predict':
            ids=[];spec=request['model']
            for entry in result['predictions']:
                source=next(x for x in request['inputs'] if x['id']==entry['id'])
                if spec['backend']=='yolo_detection':
                    for index,box in enumerate(entry['boxes']):
                        sid='suggestion_'+fingerprint([jid,entry['id'],index])[:32]
                        existing=next((s for s in self.store.list('suggestion') if s['id']==sid),None)
                        row=existing or self.store.save('suggestion',sid,{'target_kind':'candidate','target_id':entry['id'],
                            'input_revision':source['revision'],'image_sha256':source['sha256'],'capability':spec,
                            'changes':box,'status':'pending','output_ref':None},parent=entry['id'],actor=spec['id'])
                        ids.append(row['id'])
                else:
                    row=self.suggest(source['record'],entry['changes'],spec,
                        suggestion_id='suggestion_'+fingerprint([jid,entry['id']])[:32])
                    ids.append(row['id'])
            return {'suggestions':ids,'log':str(log)}
        spec=self.register(result['model_path'],result['backend'],profiles=result.get('profiles'),
            point_order=result.get('point_order'),directions=result.get('directions'),forms=result.get('forms'),actor='训练任务 '+jid)
        return {**result,'model_id':spec['id'],'log':str(log)}
