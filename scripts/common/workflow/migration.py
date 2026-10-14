"""Explicit, repeatable import of legacy evidence; never overwrite later edits."""
import copy
import csv
from pathlib import Path

from multispecies.catalog import fingerprint, require
from multispecies.library import _atomic_json
from multispecies.records import new_id, now, validate_observation
from multispecies.keypoints import blank, ORDER, PROFILES
from source_catalog.store import dumps
from .inventory import file_hash


def migrate(context, *, include_frames=True, actor='旧资料迁移', jid=None):
    library, dataset, sources = context.library, context.dataset, context.sources
    report = {'schema_version': 'workflow_migration_v1', 'id':new_id('migration'), 'created_at': now(),
              'points':0, 'candidates':0, 'regions':0, 'skipped':0, 'conflicts':[], 'missing':[]}
    hashes, positions, file_ids = {}, {}, {}

    def source_sha(path):
        path=Path(path); path=path if path.is_absolute() else context.project/path
        key=str(path.resolve())
        if key not in hashes: hashes[key]=file_hash(path) if path.is_file() else None
        return hashes[key]

    for old in library.records():
        sources._checkpoint()
        legacy = old.get('legacy', {})
        points = legacy.get('reference_points')
        if not points or not any(p is not None for p in points.values()) or old['profile_ref'] not in PROFILES:
            continue
        oid = old['observation_id']
        if not old['coordinates'].get('image_size'):
            report['conflicts'].append({'observation_id':oid,'reason':'缺少原图尺寸，无法核实点坐标；保留旧参考点，不建立可训练点位'})
            continue
        if old['annotation'].get('keypoints'):
            report['skipped']+=1; continue
        evidence = next((e for e in old['evidence'] if e['kind']=='legacy' and e.get('source_sha256')), None)
        if not evidence or source_sha(evidence['source_path']) != evidence['source_sha256'] or old['annotation']['parent_ids']:
            report['conflicts'].append({'observation_id':oid,'reason':'来源已变化、缺失或已有后续人工修订；保留原记录'}); continue
        r=copy.deepcopy(old); a=r['annotation']; a.update(id=new_id('ann'),parent_ids=[old['annotation']['id']],author=actor,created_at=now())
        a['keypoints']=blank(evidence['id'])
        for key in ORDER:
            value=points.get(key)
            point=a['keypoints']['points'][key]
            point.update(value=copy.deepcopy(value),missing_reason='legacy_unspecified' if value is None else None,
                         visibility='unknown',review_status=evidence.get('review_status') if evidence.get('review_status') in {'legacy_official','query_input'} else 'unreviewed')
        try:
            validate_observation(r,library.catalog)
            library.save(r,expected_revision=old['annotation']['id'])
            report['points']+=1
        except ValueError as exc:
            report['conflicts'].append({'observation_id':oid,'reason':str(exc)})

    def image_position(row):
        path=(context.project/row['image_path']).resolve()
        require(path.is_relative_to(context.project), '旧图片路径超出项目')
        if not path.is_file():
            report['missing'].append(str(path));return None
        key=str(path)
        if key not in positions:
            # Register only this existing image. It remains image-exact, never video-frame-exact.
            file=sources.file(file_ids[key])
            if file['state']!='ready': sources.probe(file['id'])
            positions[key]=sources.create_position(file['id'])['id']
        return positions[key]

    def prior(key, digest):
        with sources.db() as db:
            row=db.execute('SELECT * FROM workflow_migrations WHERE source_key=?',(key,)).fetchone()
        if row:
            if row['source_sha256'] != digest:
                report['conflicts'].append({'source':key,'reason':'旧来源已变化；不覆盖已迁记录'})
            else: report['skipped']+=1
        return row

    def remember(key, digest, result):
        with sources.db() as db:
            db.execute('INSERT OR IGNORE INTO workflow_migrations VALUES(?,?,?)',(key,digest,dumps(result)))

    if include_frames:
        paths=sorted((context.project/'candidates').rglob('*.csv'))+sorted((context.project/'bboxes').rglob('*.csv'))
        tables={}
        for path in paths:
            with path.open(encoding='utf-8-sig',newline='') as stream: tables[path]=list(csv.DictReader(stream))
        image_paths=sorted({str((context.project/r['image_path']).resolve()) for rows in tables.values() for r in rows
                            if r.get('image_path') and (context.project/r['image_path']).is_file()})
        require(all(Path(p).is_relative_to(context.project) for p in image_paths), '旧图片路径超出项目')
        roots=set()
        for start in range(0,len(image_paths),64):
            roots.update(sources.add_inputs(image_paths[start:start+64])['root_ids'])
        for rid in roots: sources.scan(rid)
        with sources.db() as db:
            file_ids={str((Path(r['path'])/r['rel_path']).resolve()):r['id'] for r in db.execute(
                'SELECT f.id,r.path,f.rel_path FROM files f JOIN roots r ON r.id=f.root_id')}
        for path in paths:
            sources._checkpoint()
            digest=source_sha(path)
            rows=tables[path]
            set_id='set_legacy_'+fingerprint(path.relative_to(context.project).as_posix())[:24]
            dataset.candidate_set(path.stem,set_id=set_id,actor=actor)
            for index,row in enumerate(rows):
                sources._checkpoint()
                key=path.relative_to(context.project).as_posix()+':'+str(index)
                if prior(key,digest):continue
                try:
                    pid=image_position(row)
                    if not pid:continue
                    evidence={'kind':'legacy','source_path':str(path),'source_sha256':digest,'row':row,
                              'precision':'image_exact_with_legacy_time_only'}
                    existing=dataset.candidate(pid,set_id)
                    if path.parent.parent.parent.name=='bboxes' or 'x1' in row:
                        candidate=existing or dataset.decide(pid,'selected',set_id=set_id,actor=actor,evidence=evidence)
                        rid='region_legacy_'+fingerprint(key)[:28]
                        previous=next((r for r in dataset.regions(candidate['id']) if r['id']==rid),None)
                        region=previous or dataset.region(candidate['id'],[int(float(row['x1'])),int(float(row['y1'])),
                            int(float(row['x2']))-int(float(row['x1'])),int(float(row['y2']))-int(float(row['y1']))],
                            'twilight.unicorn@1',region_id=rid,actor=actor,review_status='legacy_official',evidence=evidence)
                        remember(key,digest,region);report['regions']+=1
                    else:
                        ai=path.stem.endswith('_ai')
                        decision='undecided' if ai else 'selected' if row.get('usable')=='1' else 'excluded' if row.get('usable')=='0' else 'undecided'
                        candidate=existing or dataset.decide(pid,decision,set_id=set_id,actor=actor,evidence=evidence)
                        remember(key,digest,candidate);report['candidates']+=1
                except (OSError,ValueError,KeyError) as exc:
                    report['conflicts'].append({'source':key,'reason':str(exc)})
                if jid: sources._progress(jid,index+1,len(rows))
    # A sample ID is only a candidate link. Pixels are checked before appending a source binding.
    report['sample_links']=0;report['unlinked_samples']=[]
    by_sample={r.get('legacy',{}).get('sample_id'):r for r in library.records() if r.get('legacy',{}).get('sample_id')}
    for region in dataset.regions():
        sample_id=region.get('evidence',{}).get('row',{}).get('sample_id')
        record=by_sample.get(sample_id)
        if not record:continue
        with sources.db() as db:
            linked=db.execute('SELECT 1 FROM generated_samples WHERE region_revision=?',(region['revision'],)).fetchone()
        if linked:continue
        try:
            updated=context.service.bind_legacy_region(region,record,actor=actor)
            with sources.db() as db:
                db.execute('INSERT OR IGNORE INTO generated_samples VALUES(?,?,?)',(region['revision'],updated['observation_id'],updated['source']['import_ref']))
            report['sample_links']+=1
        except (ValueError,OSError) as exc:
            report['unlinked_samples'].append({'sample_id':sample_id,'reason':str(exc)})
    output=library.root/'workflow/migrations'/(report['id']+'.json')
    _atomic_json(output,report)
    return {**report,'report_path':str(output)}
