"""Native editing session; persistence and search belong to the shared project."""
import copy

from multispecies.catalog import require
from multispecies.records import revise
from source_catalog import media
from workflow import ProjectContext
from PIL import Image


class WorkbenchSession:
    def __init__(self, project, library=None, *, context=None):
        self._owns_context = context is None
        self.context = context or ProjectContext(project, library)
        self.project = self.context.project
        self.library, self.sources, self.service = self.context.library, self.context.sources, self.context.service
        self.workflow = self.context.poses
        self.record = self.draft = None
        self.changes = {}
        self.historical = False
        state = self.workflow.current()
        self.query_id = state.get('query_id')
        self.last_results = self.workflow.result(state['run_id']) if state.get('run_id') else None

    @property
    def dirty(self):
        return bool(self.changes)

    def load(self, oid, revision=None):
        require(not self.dirty, '有未保存修改，请先保存或放弃修改。')
        self.record = self.library.read(oid, revision)
        self.draft = copy.deepcopy(self.record)
        self.historical = self.library.head_id(oid) != self.record['annotation']['id']
        return self.draft

    def discard(self):
        self.changes = {}
        self.draft = copy.deepcopy(self.record)

    def edit(self, patch, actor):
        require(self.record is not None and not self.historical, '请先载入当前版本；历史版本只供查看。')
        changes = copy.deepcopy(self.changes)
        for slot, value in patch.get('parts', {}).items():
            if 'presence' in value and value['presence'] != self.draft['annotation']['parts'][slot]['presence']:
                for key in list(changes.get('directions', {})):
                    if key.startswith(slot+'.'):
                        del changes['directions'][key]
        for field, value in patch.items():
            if field == 'keypoints':
                changes.setdefault('keypoints', {}).setdefault('points', {}).update(copy.deepcopy(value.get('points', {})))
                if 'schema_ref' in value:
                    changes['keypoints']['schema_ref'] = value['schema_ref']
            elif field in {'parts', 'directions'}:
                for key, item in value.items():
                    previous = changes.setdefault(field, {}).setdefault(key, {})
                    if field == 'directions' and 'value' in item and 'reference_points' not in item:
                        previous.pop('reference_points', None)
                    previous.update(copy.deepcopy(item))
            else:
                changes[field] = copy.deepcopy(value)
        draft = revise(self.record, self.library.catalog, changes, actor=actor)
        self.changes, self.draft = changes, draft
        return draft

    def save(self, actor, review=None):
        require(self.record is not None and not self.historical, '历史版本只供查看。')
        require(self.dirty or review, '没有待保存修改。')
        updated = self.library.edit(self.record['observation_id'], self.record['annotation']['id'],
                                    self.changes, actor=actor, review=review)
        self.changes = {}
        self.record = updated
        self.draft = copy.deepcopy(updated)
        return updated

    def save_suggestion(self, suggestion, actor, review=None):
        targets=review.get('targets') if review else None
        if targets:
            targets=[t for t in targets if not t.startswith('parts.')]
        decision='rejected' if review and review['status']=='rejected' else 'corrected'
        result=self.context.models.review(suggestion['id'],suggestion['revision'],decision,actor=actor,
            changes=copy.deepcopy(self.changes) if decision=='corrected' else None,targets=targets)
        old_changes=copy.deepcopy(self.changes)
        self.discard();self.load(suggestion['target_id'])
        if result['status']=='pending':
            remaining=self.context.models.targets(result['changes'])
            patch=self.context.models.scoped(old_changes,remaining)
            self.edit(patch,actor)
        return result

    def prepare_query(self, contract, options, filters):
        require(self.record is not None and not self.historical, '请先载入一份当前姿态作为查询。')
        require(not self.dirty, '请先保存姿态，再搜索。')
        require(self.library.head_id(self.record['observation_id']) == self.record['annotation']['id'],
                '标注已有新修订，请重新载入后再保存查询。')
        spec = self.workflow.prepare_query(self.record['observation_id'], revision=self.record['annotation']['id'],
                                           contract_ref=contract, options=options, source_filters=filters)
        self.query_id = spec['id']
        return spec

    def search_saved_query(self, query_id=None):
        require(not self.dirty, '请先保存姿态，再搜索。')
        self.query_id = query_id or self.workflow.current().get('query_id')
        require(self.query_id, '请先在 M07 保存查询条件。')
        self.last_results = self.workflow.search(self.query_id)
        return self.last_results

    def find(self, contract, options, filters):
        spec = self.prepare_query(contract, options, filters)
        return self.search_saved_query(spec['id'])

    def export_results(self):
        require(self.last_results is not None, '请先搜索。')
        paths = self.workflow.export(self.last_results['run_id'])
        return paths['csv'], paths['json']

    def export_html(self):
        require(self.last_results is not None, '请先搜索。')
        return self.workflow.export(self.last_results['run_id'], include_html=True)['html']

    def export_training(self, *, allow_draft=False, include_ungrouped=False):
        result = self.context.training.freeze('directions', allow_draft=allow_draft, include_ungrouped=include_ungrouped)
        return self.context.training.root/'snapshots'/(result['id']+'.json')

    def preview_frames(self, proxy):
        """Short, silent native preview. It never changes the exact selected frame."""
        path=media.within(self.sources.cache/proxy['cache_name'],self.sources.cache)
        start=max(0,(proxy.get('seconds') or 0)-1)
        raw=media.run('ffmpeg',['-v','error','-ss',str(start),'-i',path,'-t','6','-an',
                               '-vf','fps=10,scale=480:270:force_original_aspect_ratio=decrease,pad=480:270:(ow-iw)/2:(oh-ih)/2',
                               '-pix_fmt','rgb24','-f','rawvideo','pipe:1'],timeout=60)
        size=480*270*3
        require(raw and len(raw)%size==0,'预览片段解码不完整。')
        return [Image.frombytes('RGB',(480,270),raw[i:i+size]) for i in range(0,len(raw),size)]

    def close(self):
        if self._owns_context:
            self.context.close()
