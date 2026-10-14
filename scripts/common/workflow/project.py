"""Versioned queries and frozen search runs, independent of Tk and HTTP."""
import base64
import copy
import csv
import html
import io
import json
from pathlib import Path

from multispecies import Library
from multispecies.catalog import fingerprint, load_json, require
from multispecies.library import _atomic_json, _safe_id
from multispecies.matching import search
from multispecies.records import new_id, now, usable
from source_catalog import SourceCatalog, SourceService


MODULES = {
    'M01': {'name': '素材登记与画面获取', 'integration': 'shared'},
    'M02': {'name': '候选筛选', 'integration': 'shared'},
    'M03': {'name': '角色与框选', 'integration': 'shared'},
    'M04': {'name': '样本生成', 'integration': 'shared'},
    'M05': {'name': '姿态标注与审核', 'integration': 'shared'},
    'M06': {'name': '姿态资料准备', 'integration': 'shared'},
    'M07': {'name': '查询设置', 'integration': 'shared'},
    'M08': {'name': '相似姿态搜索', 'integration': 'shared'},
    'M09': {'name': '结果与素材定位', 'integration': 'shared'},
}

DEFAULT_OPTIONS = {
    'allow_mirror': False, 'allow_whole_limb_exchange': True, 'strict_identity': False,
    'include_unreviewed': False, 'allow_draft': False, 'minimum_coverage': 0.,
    'top_n': 15, 'character_ref': None, 'species_ref': None,
    'collections': ['official', 'manual'], 'group_weights': {},
    'view_weight': .10, 'layout_weight': .05,
}


class ProjectContext:
    """One project/library selection and one owner for the source worker."""
    def __init__(self, project, library=None):
        self.project = Path(project).resolve()
        root = Path(library).resolve() if library else self.project/'data/pose_library_v2'
        require(not (root/'INCOMPLETE.json').exists(), '此副本尚未完成，不能作为工作资料库打开')
        self.library = Library(root,
                               default_catalog=self.project/'data/meta/body_catalog_v2.json')
        self.sources = SourceCatalog(self.library.root/'sources')
        self.service = SourceService(self.sources, self.library)
        self.service.recover()
        from .dataset import DatasetWorkflow
        self.dataset = DatasetWorkflow(self.library, self.sources, self.service)
        from .character_fla import CharacterFlaWorkflow
        self.characters = CharacterFlaWorkflow(self)
        self.sources.handlers['character_fla'] = lambda p,jid: self.characters.execute(jid=jid, **p)
        self.sources.handlers['sample_frames'] = lambda p,jid: self.dataset.sample_frames(jid=jid,**p)
        self.sources.handlers['sample'] = lambda p, jid: self.dataset.generate(**p)
        from .training import TrainingWorkflow
        from .models import ModelWorkflow
        from .migration import migrate
        self.training = TrainingWorkflow(self)
        self.models = ModelWorkflow(self)
        self.sources.handlers.update(train=self.models.execute, predict=self.models.execute,
            migration=lambda p,jid:migrate(self,jid=jid,**p),
            snapshot=lambda p,jid:self.training.freeze(**p),
            dataset_export=lambda p,jid:self.training.materialize(**p),
            derive=lambda p,jid:self.derive(**p))
        self.poses = PoseWorkflow(self.library, self.service)

    def derive(self, observation_id, revision, *, actor='本机用户', replace=False):
        from multispecies.keypoints import derive
        record=self.library.read(observation_id,revision)
        updated=derive(record,self.library.catalog,actor=actor,replace=replace)
        return self.library.save(updated,expected_revision=revision)

    def statuses(self):
        counts=self.sources.status();candidates=self.dataset.candidates();regions=self.dataset.regions()
        return {**self.poses.statuses(),
                'M01':(str(sum(counts['files'].values()))+' 个素材',''),
                'M02':(str(len(candidates))+' 个候选',''),
                'M03':(str(len(regions))+' 个角色框',''),
                'M04':(str(len(self.dataset.samples()))+' 个样本关系',''),
                'M06':(str(len(self.training.snapshots()))+' 份训练快照','')}

    def close(self):
        self.sources.stop()


class PoseWorkflow:
    """M07 freezes a query, M08 records a run, M09 exports that exact run.

    An annotation is written only through Library.edit/save, including from M05.
    Queries/runs are immutable and live inside the selected library. Neither an
    export nor reopening results consults the latest annotation heads for scores.
    """
    def __init__(self, library, source_service):
        self.library, self.sources = library, source_service
        self.root = library.root/'workflow'

    def _read(self, group, key):
        path = self.root/group/(_safe_id(key)+'.json')
        require(path.is_file(), '找不到已保存的查询或搜索记录')
        data = load_json(path)
        body = {k: v for k, v in data.items() if k != 'content_sha256'}
        require(data.get('content_sha256') == fingerprint(body), '查询或搜索记录内容已变化')
        require(data.get('id') == key, '记录编号与文件不一致')
        return data

    def query(self, query_id):
        return self._read('queries', query_id)

    def result(self, run_id):
        return self._read('runs', run_id)

    def _store(self, group, data, pointer):
        data = copy.deepcopy(data)
        data['content_sha256'] = fingerprint(data)
        path = self.root/group/(data['id']+'.json')
        with self.library._locked():
            require(not path.exists(), '查询或搜索编号已存在，不可覆盖')
            _atomic_json(path, data)
            state_path = self.root/'current.json'
            state = load_json(state_path) if state_path.exists() else {}
            state[pointer] = data['id']
            _atomic_json(state_path, state)
        return data

    def current(self):
        path = self.root/'current.json'
        return load_json(path) if path.exists() else {}

    def prepare_query(self, observation_id, *, revision=None, contract_ref='pony.body14@1',
                      options=None, source_filters=None):
        require(options is None or isinstance(options, dict), '搜索选项必须是对象')
        require(not set(options or {})-set(DEFAULT_OPTIONS), '未知搜索选项')
        opts = copy.deepcopy(DEFAULT_OPTIONS)
        opts.update(copy.deepcopy(options or {}))
        for key in ('allow_mirror', 'allow_whole_limb_exchange', 'strict_identity', 'include_unreviewed', 'allow_draft'):
            require(isinstance(opts[key], bool), '搜索开关必须为布尔值：'+key)
        require(isinstance(opts['collections'], (list, tuple)) and
                all(v in {'official', 'manual', 'experimental'} for v in opts['collections']), '资料集合无效')
        opts['collections'] = list(opts['collections'])
        require(isinstance(opts['group_weights'], dict), '比较权重必须是对象')
        cat = self.library.catalog
        for option, table in (('character_ref', 'characters'), ('species_ref', 'species')):
            if opts[option] is not None:
                cat.get(table, opts[option])
        filters = copy.deepcopy(source_filters if source_filters is not None else {})
        self.sources.filter_records([], filters)  # Validate even with an empty library.
        record = self.library.read(observation_id, revision)
        search(record, [], cat, contract_ref=contract_ref, **opts)
        return self._store('queries', {
            'schema_version': 'pose_query_v1', 'id': new_id('query'), 'created_at': now(),
            'observation_id': observation_id, 'annotation_id': record['annotation']['id'],
            'annotation_sha256': fingerprint(record), 'catalog_sha256': cat.sha256,
            'contract_ref': contract_ref, 'options': opts, 'source_filters': filters,
        }, 'query_id')

    def search(self, query_id):
        spec = self.query(query_id)
        cat = self.library.catalog
        require(cat.sha256 == spec['catalog_sha256'], '身体目录已变化，请重新保存查询条件')
        query = self.library.read(spec['observation_id'], spec['annotation_id'])
        require(fingerprint(query) == spec['annotation_sha256'], '查询标注内容与保存时不一致')
        records = self.sources.records()
        selected = self.sources.filter_records(records, spec['source_filters'])
        result = search(query, selected, cat, contract_ref=spec['contract_ref'], **spec['options'])
        assets = self.library.assets
        by_id = {r['observation_id']: r for r in selected}
        for row in result['results']:
            record = by_id[row['observation_id']]
            info = self.sources.describe(record, assets)
            row['location'] = info
            row['position_text'] = self.sources.position_text(info, mirrored=row['mirrored'])
        # Store the exact input versions, including filtered-by-matcher records.
        # New heads created concurrently cannot alter these immutable revisions.
        candidates = [{'observation_id': r['observation_id'], 'annotation_id': r['annotation']['id'],
                       'annotation_sha256': fingerprint(r), 'image_ref': r['image_ref'],
                       'image_sha256': assets[r['image_ref']]['sha256']} for r in selected]
        run_id = new_id('run')
        result.update(schema_version='pose_search_run_v1', id=run_id, run_id=run_id,
                      query_id=query_id, query_spec=spec, created_at=now(),
                      options=spec['options'], source_filters=spec['source_filters'],
                      source_excluded=len(records)-len(selected), candidate_snapshot=candidates,
                      candidate_snapshot_sha256=fingerprint(candidates), catalog=cat.data)
        return self._store('runs', result, 'run_id')

    def export(self, run_id, *, output_dir=None, include_html=False):
        result = self.result(run_id)
        out = Path(output_dir).resolve() if output_dir else self.library.root/'exports'
        out.mkdir(parents=True, exist_ok=True)
        base = out/run_id
        stream = io.StringIO(newline='')
        writer = csv.writer(stream)
        writer.writerow(['观测编号', '标注版本', '分数', '需翻转', '素材名', '源路径',
                         '位置精度', '视频帧（从1计）', '秒', '原内容SHA256', '完整位置', '工程时间轴', '工程帧（从1计）'])
        for row in result['results']:
            info, pos = row['location'], row['location']['position']
            ordinal = pos.get('presentation_ordinal0')
            values = [row['observation_id'], row['annotation_id'], row['score'], row['mirrored'],
                      info['name'], info['path'], info['precision'], ordinal+1 if ordinal is not None else '',
                      pos.get('seconds'), info.get('sha256'), row['position_text'], pos.get('timeline_name',''),
                      pos['frame_index0']+1 if pos.get('kind') == 'fla_frame' else '']
            writer.writerow(["'"+v if isinstance(v, str) and v.startswith(('=', '+', '-', '@')) else v for v in values])
        paths = {'json': base.with_suffix('.json'), 'csv': base.with_suffix('.csv')}
        _atomic_json(paths['json'], result)
        self._write_text(paths['csv'], stream.getvalue(), encoding='utf-8-sig')
        if include_html:
            paths['html'] = base.with_suffix('.html')
            self._write_text(paths['html'], self._html(result))
        return paths

    @staticmethod
    def _write_text(path, text, encoding='utf-8'):
        import os
        temporary = path.with_name(path.name+'.'+new_id('tmp'))
        try:
            with temporary.open('x', encoding=encoding, newline='') as stream:
                stream.write(text)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _html(self, result):
        cards = []
        for i, row in enumerate(result['results'], 1):
            picture = '<p>图片当前不可用，结果记录仍保留。</p>'
            try:
                raw, mime = self.library.image_bytes(row['image_ref'])
                picture = '<img alt="命中角色" src="data:'+mime+';base64,'+base64.b64encode(raw).decode()+'">'
            except (OSError, ValueError):
                pass
            cards.append('<article><h2>'+str(i)+'. '+html.escape(row['location']['name'])+'</h2>'+picture+
                         '<p>相似分 '+f"{row['score']:.3f}"+' · 覆盖 '+f"{row['candidate_coverage']:.0%}"+
                         (' · 需要左右翻转' if row['mirrored'] else ' · 原始朝向')+'</p><pre>'+
                         html.escape(row['position_text'])+'</pre><small>标注版本：'+html.escape(row['annotation_id'])+'</small></article>')
        return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>姿态搜索结果</title>'
                '<style>body{font:16px/1.65 system-ui;background:#f4f6fa;color:#233044;max-width:1100px;margin:35px auto;padding:20px}'
                'article{background:white;border:1px solid #d6dce5;padding:24px;margin:20px 0;border-radius:12px}'
                'img{max-width:100%;max-height:350px}pre{white-space:pre-wrap;overflow-wrap:anywhere}small{color:#536376}</style>'
                '<h1>姿态搜索结果</h1><p>保存的是当次查询与排序；原文件当前是否可用，需要打开时核验。</p><p>搜索编号：'+
                html.escape(result['run_id'])+'<br>查询修订：'+html.escape(result['query_revision'])+'</p>'+
                (''.join(cards) or '<p>本次没有命中。</p>')+'</html>')

    def statuses(self, observation_id=None):
        records = self.sources.records()
        approved = sum(any(usable(r, k, reviewed_only=True) for k in r['annotation']['directions']) for r in records)
        state = self.current()
        query = self.query(state['query_id']) if state.get('query_id') else None
        run = self.result(state['run_id']) if state.get('run_id') else None
        stale = bool(query and (self.library.head_id(query['observation_id']) != query['annotation_id'] or
                                self.library.catalog.sha256 != query['catalog_sha256']))
        different_selection = bool(query and observation_id and query['observation_id'] != observation_id)
        current_run = bool(run and query and run['query_id'] == query['id'])
        return {
            'M05': ('可标注', f'{len(records)} 份；{approved} 份有已审方向；点位独立审核'),
            'M07': ('需更新' if stale or different_selection else '已保存' if query else '待设置',
                    '固定查询修订；修改后请重新保存'),
            'M08': ('需更新' if stale or different_selection else '已完成' if current_run else '可运行' if query else '待设置',
                    '使用 M07 已保存的条件'),
            'M09': ('可查看' if run else '待搜索',
                    f"当前结果 {len(run['results'])} 条；固定当次版本" if run else '搜索完成后查看来源与导出'),
        }
