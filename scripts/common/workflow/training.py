"""M06 reviewed snapshots and exact, versioned inputs for model workers."""
import copy
import hashlib
import json
from pathlib import Path

from multispecies.catalog import fingerprint, load_json, require
from multispecies.library import _atomic_json, _safe_id
from multispecies.records import ACCEPTED, new_id, now
from multispecies.training import assign_splits, training_snapshot
from multispecies.keypoints import SCHEMA, ORDER


class TrainingWorkflow:
    def __init__(self, context):
        self.context = context
        self.library, self.dataset = context.library, context.dataset
        self.root = self.library.root/'training'

    def snapshots(self):
        return [load_json(p) for p in sorted((self.root/'snapshots').glob('*.json'))]

    def read(self, key):
        result = load_json(self.root/'snapshots'/(_safe_id(key)+'.json'))
        require(result['snapshot_sha256'] == fingerprint({k:v for k,v in result.items() if k != 'snapshot_sha256'}), '训练快照内容已变化')
        return result

    def freeze(self, task='directions', *, allow_draft=False, include_ungrouped=False, seed='pose-v2'):
        require(task in {'directions', 'keypoints', 'detection'}, '未知监督任务')
        require(type(allow_draft) is bool and type(include_ungrouped) is bool, '训练选项必须为开关')
        require(isinstance(seed, str) and seed, '分组种子不能为空')
        if task == 'directions':
            content = training_snapshot(self.library, allow_draft=allow_draft, include_ungrouped=include_ungrouped, seed=seed)
            entries, excluded = content['records'], content['excluded']
        elif task == 'keypoints':
            entries, excluded = self._keypoints(include_ungrouped)
        else:
            entries, excluded = self._detection()
        assign_splits(entries, seed)
        result = {'schema_version': 'workflow_training_snapshot_v1', 'id': new_id('snapshot'),
            'task': task, 'created_at': now(), 'seed': seed,
            'catalog': self.library.catalog.data, 'catalog_sha256': self.library.catalog.sha256,
            'options': {'allow_draft': allow_draft, 'include_ungrouped': include_ungrouped},
            'records': entries, 'excluded': excluded}
        if task == 'keypoints':
            result.update(schema_ref=SCHEMA, point_order=ORDER)
        result['snapshot_sha256'] = fingerprint(result)
        _atomic_json(self.root/'snapshots'/(result['id']+'.json'), result)
        return result

    def freeze_pair(self, **options):
        """Comparable supervision on identical observations and linked split groups."""
        left=self.freeze('directions',**options);right=self.freeze('keypoints',**options)
        common={e['observation_id'] for e in left['records']} & {e['observation_id'] for e in right['records']}
        require(common,'没有同时具备已审核方向和已审核点位的共同图片')
        cid=new_id('comparison');paired=[]
        for original in (left,right):
            result=copy.deepcopy(original)
            result['excluded'] += [{'observation_id':e['observation_id'],'reason':'paired_supervision_unavailable'} for e in result['records'] if e['observation_id'] not in common]
            result['records']=[e for e in result['records'] if e['observation_id'] in common]
            result.update(id=new_id('snapshot'),comparison_id=cid,input_snapshots=[left['id'],right['id']])
            paired.append(result)
        assign_splits(paired[0]['records']+paired[1]['records'],left['seed'])
        for result in paired:
            result.pop('snapshot_sha256',None);result['snapshot_sha256']=fingerprint(result)
            _atomic_json(self.root/'snapshots'/(result['id']+'.json'),result)
        report={'id':cid,'snapshots':{s['task']:s['id'] for s in paired},'observations':sorted(common),
                'policy':'same images and connected groups; choose the same seed, epochs and size when training'}
        _atomic_json(self.root/'comparisons'/(cid+'.json'),report)
        return report

    def _keypoints(self, include_ungrouped):
        entries, excluded = [], []
        assets = self.library.assets
        for r in self.library.records(['official', 'manual']):
            oid = r['observation_id']; kp = r['annotation'].get('keypoints')
            reason = None
            if r.get('example_only') or r.get('test_only'):
                reason = 'synthetic_or_test'
            if not kp:
                reason = reason or 'no_schema_points'
            asset = assets[r['image_ref']]
            try:
                self.library.image_bytes(r['image_ref'])
            except (OSError, ValueError):
                reason = reason or 'image_changed_or_missing'
            if asset['issues']:
                reason = reason or 'image_issue'
            groups = ['shot:'+r['split_groups']['shot_ref']] if r['split_groups'].get('shot_ref') else []
            if r['split_groups'].get('asset_family_ref'):
                groups.append('asset:'+r['split_groups']['asset_family_ref'])
            if not groups and not include_ungrouped:
                reason = reason or 'group_not_confirmed'
            points = kp['points'] if kp else {}
            mask = [points.get(k,{}).get('value') is not None and points[k]['review_status'] in ACCEPTED and
                    points[k]['visibility'] not in {'occluded','out_of_frame'} for k in ORDER]
            if not any(mask): reason = reason or 'no_approved_points'
            if reason:
                excluded.append({'observation_id': oid, 'reason': reason}); continue
            entries.append({'observation_id': oid, 'annotation_id': r['annotation']['id'],
                'image_ref': r['image_ref'], 'image_path': asset['path'], 'image_sha256': asset['sha256'],
                'image_size': asset['size'], 'profile_ref': r['profile_ref'], 'schema_ref': SCHEMA,
                'point_order': ORDER, 'points': [copy.deepcopy(points[k]['value']) if flag else None for k,flag in zip(ORDER,mask)],
                'mask': mask, 'observation': copy.deepcopy(r), 'group_confirmed': bool(groups),
                'links': groups+['image:'+r['image_ref'], 'occurrence:'+r['occurrence_id']]})
        return entries, excluded

    def _detection(self):
        entries, excluded = [], []
        for c in self.dataset.candidates():
            regions = self.dataset.regions(c['id'])
            reason = None
            if c['decision'] != 'selected': reason = 'candidate_not_selected'
            elif not c['complete_regions'] or c.get('region_revisions') != sorted(r['revision'] for r in regions):
                reason = 'all_characters_not_confirmed'
            elif not regions or any(r['review_status'] not in ACCEPTED or r['quality'] != 'keep' or r['is_query'] for r in regions):
                reason = 'unreviewed_or_query_region'
            if reason:
                excluded.append({'candidate_id': c['id'], 'reason': reason}); continue
            try:
                position = self.context.sources.position(c['position_id'])
                path = self.context.sources.cached_image(c['position_id'])
                asset = self.library.upload_image(path.read_bytes())
                if asset['issues']: raise ValueError('image_issue')
            except (OSError, ValueError) as exc:
                excluded.append({'candidate_id': c['id'], 'reason': str(exc)}); continue
            location = self.context.service.describe_position(c['position_id'])
            entries.append({'candidate_id': c['id'], 'candidate_revision': c['revision'],
                'position_id': c['position_id'], 'image_ref': asset['id'], 'image_path': asset['path'],
                'image_sha256': asset['sha256'], 'image_size': asset['size'],
                'regions': [{**r, 'character_ref': self.library.catalog.get('forms',r['form_ref']).get('character_ref')} for r in regions],
                'group_confirmed': True, 'links': ['source:'+location['file_id'], 'content:'+location['sha256'], 'image:'+asset['id']]})
        return entries, excluded

    def materialize(self, snapshot_id):
        with self.library._locked():
            return self._materialize(snapshot_id)

    def _materialize(self, snapshot_id):
        snapshot = self.read(snapshot_id)
        from multispecies.catalog import Catalog
        catalog = Catalog(snapshot['catalog'])
        target = self.root/'datasets'/snapshot_id
        manifest = target/'manifest.json'
        if manifest.exists():
            result = load_json(manifest)
            require(result['snapshot_sha256'] == snapshot['snapshot_sha256'], '训练目录与快照不符')
            self.verify_package(result)
            return result
        target.mkdir(parents=True, exist_ok=True)
        _atomic_json(target/'INCOMPLETE.json', {'snapshot_id': snapshot_id})
        task = snapshot['task']
        classes = sorted({r['form_ref']
                          for e in snapshot['records'] for r in e.get('regions', [])}) if task == 'detection' else ['character']
        files, usable = [], []
        for i, entry in enumerate(snapshot['records']):
            split = entry['split']
            if split == 'unassigned': continue
            raw = Path(entry['image_path']).read_bytes()
            require(hashlib.sha256(raw).hexdigest() == entry['image_sha256'], '训练图片内容与快照不符')
            suffix = Path(entry['image_path']).suffix.lower()
            path = target/'images'/split/(f'{i:06d}'+suffix)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            files.append({'path': str(path), 'sha256': entry['image_sha256']})
            item = {**entry, 'image_path': str(path)}
            usable.append(item)
            if task != 'directions':
                w, h = entry['image_size']
                if task == 'keypoints':
                    values = ['0','0.5','0.5','1','1']
                    for p, mask in zip(entry['points'], entry['mask']):
                        values.extend([str(p[0]/w),str(p[1]/h),'2'] if mask else ['0','0','0'])
                    rows = [' '.join(values)]
                else:
                    rows = []
                    for region in entry['regions']:
                        form = catalog.get('forms', region['form_ref'])
                        cls = classes.index(region['form_ref'])
                        x,y,rw,rh = region['roi']
                        rows.append(f'{cls} {(x+rw/2)/w} {(y+rh/2)/h} {rw/w} {rh/h}')
                label = target/'labels'/split/(f'{i:06d}'+'.txt')
                label.parent.mkdir(parents=True, exist_ok=True)
                label.write_text('\n'.join(rows)+'\n', encoding='utf-8')
                files.append({'path':str(label), 'sha256':hashlib.sha256(label.read_bytes()).hexdigest()})
        data = {'path': str(target), 'train': 'images/train', 'val': 'images/validation',
                'test': 'images/test', 'names': dict(enumerate(classes))}
        if task == 'keypoints': data['kpt_shape'] = [len(ORDER), 3]
        _atomic_json(target/'data.yaml', data)  # JSON is a YAML subset.
        files.append({'path':str(target/'data.yaml'), 'sha256':hashlib.sha256((target/'data.yaml').read_bytes()).hexdigest()})
        result = {'schema_version':'workflow_training_package_v1', 'snapshot_id':snapshot_id,
                  'snapshot_sha256':snapshot['snapshot_sha256'], 'task':task, 'records':usable,
                  'data_yaml':str(target/'data.yaml'), 'point_order':snapshot.get('point_order'), 'files':files}
        result['package_sha256'] = fingerprint(result)
        _atomic_json(manifest, result)
        (target/'INCOMPLETE.json').unlink()
        return result

    @staticmethod
    def verify_package(package):
        require(package['package_sha256'] == fingerprint({k:v for k,v in package.items() if k != 'package_sha256'}), '训练清单已变化')
        for item in package['files']:
            require(Path(item['path']).is_file() and hashlib.sha256(Path(item['path']).read_bytes()).hexdigest() == item['sha256'], '训练文件已变化：'+item['path'])
        return package
