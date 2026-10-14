"""M02 candidate decisions, M03 character occurrences, M04 repeatable samples."""
from multispecies.catalog import fingerprint, require
from multispecies.records import new_id
from source_catalog.schema import RevisionStore


class DatasetWorkflow:
    def __init__(self, library, sources, service):
        self.library, self.sources, self.service = library, sources, service
        self.store = RevisionStore(sources)

    def candidate_set(self, label='待整理素材', *, set_id='set_inbox', actor='本机用户'):
        require(isinstance(label, str) and label.strip(), '候选集合需要名称')
        found = self.store.get(set_id)
        return found or self.store.save('candidate_set', set_id, {'label': label.strip()}, actor=actor)

    def decide(self, position_id, decision, *, set_id='set_inbox', expected=None,
               actor='本机用户', evidence=None, complete_regions=False):
        require(decision in {'selected', 'excluded', 'undecided'}, '请选择保留、排除或待判断')
        require(isinstance(complete_regions, bool), '完整框选标记须为开关')
        self.sources.position(position_id)
        self.candidate_set(set_id=set_id, actor=actor)
        key = 'candidate_'+fingerprint([set_id, position_id])[:32]
        return self.store.save('candidate', key, {
            'set_id': set_id, 'position_id': position_id, 'decision': decision,
            'region_revisions': sorted(r['revision'] for r in self.regions(key)) if complete_regions else [],
            'complete_regions': complete_regions, 'evidence': evidence or {'kind': 'manual'}},
            expected=expected, parent=set_id, actor=actor)

    def candidate(self, position_id, set_id='set_inbox'):
        key = 'candidate_'+fingerprint([set_id, position_id])[:32]
        return self.store.get(key)

    def candidates(self, set_id=None):
        return self.store.list('candidate', set_id)

    def region(self, candidate_id, roi, form_ref, *, region_id=None, expected=None,
               actor='本机用户', review_status='unreviewed', quality='keep', is_query=False, evidence=None):
        candidate = self.store.read(candidate_id)
        require(candidate['kind'] == 'candidate' and candidate['decision'] == 'selected', '角色框只能保存到保留的候选画面')
        require(quality in {'keep', 'reject'}, '区域质量无效')
        require(review_status in {'unreviewed', 'approved', 'corrected', 'rejected', 'legacy_official'}, '区域审核状态无效')
        require(review_status != 'legacy_official' or evidence and evidence.get('kind') == 'legacy', '原正式审核需要迁移证据')
        require(isinstance(is_query, bool), '查询标记必须是开关')
        self.library.catalog.get('forms', form_ref)
        position = self.sources.position(candidate['position_id'])
        width, height = position['payload']['image_size']
        require(isinstance(roi, list) and len(roi) == 4 and all(type(v) is int for v in roi), '角色框需要四个整数：左、上、宽、高')
        x, y, w, h = roi
        require(x >= 0 and y >= 0 and w > 0 and h > 0 and x+w <= width and y+h <= height, '角色框超出画面')
        key = region_id or new_id('region')
        result = self.store.save('region', key, {'candidate_id': candidate_id, 'position_id': candidate['position_id'],
            'roi': roi, 'form_ref': form_ref, 'quality': quality, 'is_query': is_query,
            'review_status': review_status, 'evidence': evidence or {'kind': 'manual'}},
            expected=expected, parent=candidate_id, actor=actor)
        # Completeness is invalidated by a region edit; it is a separate human judgement.
        if candidate.get('complete_regions'):
            self.decide(candidate['position_id'], candidate['decision'], set_id=candidate['set_id'],
                        expected=candidate['revision'], actor=actor)
        return result

    def regions(self, candidate_id=None):
        return self.store.list('region', candidate_id)

    def generate(self, region_id, revision, *, actor='本机用户'):
        region = self.store.read(region_id, revision)
        require(region['kind'] == 'region', '需要角色区域')
        current = self.store.read(region_id)
        require(current['revision'] == revision, '角色框已有新版本，请重新选择后生成样本')
        candidate = self.store.read(region['candidate_id'])
        require(candidate['decision'] == 'selected' and region['quality'] == 'keep' and
                region['review_status'] in {'approved', 'corrected', 'legacy_official'}, '请先确认保留画面并审核角色框')
        with self.sources.db() as db:
            linked=db.execute('SELECT observation_id FROM generated_samples WHERE region_revision=?',(revision,)).fetchone()
        if linked:
            record=self.library.read(linked[0])
            return {'record':record,'asset':self.library.assets[record['image_ref']],'location':self.service.describe(record)}
        occurrence=region_id
        with self.sources.db() as db:
            previous=db.execute('SELECT s.observation_id FROM generated_samples s JOIN workflow_revisions r ON r.id=s.region_revision WHERE r.item_id=? ORDER BY r.created LIMIT 1',(region_id,)).fetchone()
        if previous:occurrence=self.library.read(previous[0])['occurrence_id']
        # Stable request identity survives a crash between the import commit and the sample link.
        request_id = 'region_sample_'+fingerprint(revision)[:32]
        result = self.service.import_observation(position_id=region['position_id'], roi=region['roi'],
            form_ref=region['form_ref'], request_id=request_id, actor=region['actor'],
            is_query=region['is_query'], occurrence_id=occurrence,
            region_ref={'id': region_id, 'revision': revision, 'candidate_id': region['candidate_id']})
        with self.sources.db() as db:
            db.execute('INSERT OR IGNORE INTO generated_samples VALUES(?,?,?)',
                       (revision, result['record']['observation_id'], request_id))
        return result

    def samples(self):
        with self.sources.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM generated_samples')]

    def queue_generate(self, region_id, revision):
        return self.sources.queue('sample', {'region_id': region_id, 'revision': revision}, 'sample:'+revision)

    def import_region(self, *, position_id, roi, form_ref, request_id, actor='本机用户', is_query=False):
        """The one-click UI path still persists the same candidate/region lifecycle."""
        key = 'region_'+fingerprint(request_id)[:32]
        region = next((r for r in self.regions() if r['id'] == key), None)
        if region:
            require([position_id, roi, form_ref, is_query] == [region['position_id'], region['roi'], region['form_ref'], region['is_query']],
                    '同一操作不能对应不同区域')
        else:
            candidate = self.candidate(position_id)
            if not candidate or candidate['decision'] != 'selected':
                candidate = self.decide(position_id, 'selected', actor=actor,
                                        expected=candidate['revision'] if candidate else None)
            region = self.region(candidate['id'], roi, form_ref, region_id=key, actor=actor,
                                 review_status='approved', is_query=is_query)
        return self.generate(region['id'], region['revision'], actor=actor)

    def queue_frames(self, file_id, start=1, stop=1, step=1, *, set_id='set_inbox', actor='本机用户'):
        require(all(type(v) is int for v in (start,stop,step)) and 1<=start<=stop and step>0,'帧范围使用从 1 开始的正整数')
        require((stop-start)//step+1<=10000,'一次最多选择 10000 帧，请分段处理')
        _,version=self.sources.verified_path(file_id)
        require(version['kind'] in {'image','video'},'该格式目前只能编目，不能取帧')
        require(version['kind']!='image' or (start==stop==1),'静态图片只有第 1 帧')
        args={'file_id':file_id,'version_id':version['id'],'start':start,'stop':stop,'step':step,'set_id':set_id,'actor':actor}
        return self.sources.queue('sample_frames',args,'sample_frames:'+fingerprint(args))

    def sample_frames(self, file_id, version_id, start, stop, step, set_id, actor, jid=None):
        output=[];frames=range(start,stop+1,step)
        for index,number in enumerate(frames):
            self.sources._checkpoint()
            p=self.sources.create_position(file_id,ordinal0=number-1,version_id=version_id)
            old=self.candidate(p['id'],set_id)
            c=old or self.decide(p['id'],'undecided',set_id=set_id,actor=actor)
            output.append(c['id'])
            if jid:self.sources._progress(jid,index+1,len(frames))
        return {'candidate_ids':output}
