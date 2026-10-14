"""Read-only migration audit and an explicit, non-overwriting library copy."""
from collections import Counter
import csv
import hashlib
from pathlib import Path
import shutil
import sqlite3

from multispecies.catalog import fingerprint, load_json, require
from multispecies.library import _atomic_json
from multispecies.records import now


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def inventory(project, library=None):
    """Does not construct Library/SourceCatalog, start workers or change labels."""
    project = Path(project).resolve()
    root = Path(library).resolve() if library else project/'data/pose_library_v2'
    entries, issues, conflicts = [], [], []
    patterns = {
        'candidates': 'candidates/**/*.csv', 'regions': 'bboxes/**/*.csv',
        'samples': 'crops/**/crops_index*.csv', 'keypoints': 'keypoints/**/*.json',
        'derived_poses': 'poses/**/*.json', 'queries': 'queries/**/*.json',
        'training_records': 'models/**/training_record.json', 'models': 'models/**/*.pt',
    }
    for kind, pattern in patterns.items():
        for path in sorted(project.glob(pattern)):
            entry = {'kind': kind, 'path': path.relative_to(project).as_posix(),
                     'bytes': path.stat().st_size, 'sha256': file_hash(path), 'records': None}
            try:
                if path.suffix == '.csv':
                    with path.open(encoding='utf-8-sig', newline='') as stream:
                        entry['records'] = sum(1 for _ in csv.DictReader(stream))
                elif path.suffix == '.json':
                    data = load_json(path)
                    entry['records'] = len(data['items']) if isinstance(data, dict) and isinstance(data.get('items'), list) else 1
            except (ValueError, OSError) as exc:
                issues.append({'path': entry['path'], 'problem': str(exc)})
            entries.append(entry)
    heads, versions, source_checks, source_hashes = [], [], [], {}
    collections = Counter()
    bound = 0
    for pointer in sorted((root/'observations').glob('*/HEAD.json')):
        try:
            aid = load_json(pointer)['annotation_id']
            record = load_json(pointer.parent/(aid+'.json'))
            heads.append({'observation_id': record['observation_id'], 'annotation_id': aid,
                          'sha256': fingerprint(record), 'image_ref': record['image_ref'],
                          'legacy_sample_id': record.get('legacy', {}).get('sample_id')})
            collections[record['collection']] += 1
            bound += bool(record['source'].get('locator_ref'))
            for path in sorted(pointer.parent.glob('*.json')):
                versions.append({'path': path.relative_to(root).as_posix(), 'sha256': file_hash(path)})
            for evidence in record.get('evidence', []):
                if not evidence.get('source_path') or not evidence.get('source_sha256'):
                    continue
                source = Path(evidence['source_path'])
                source = source if source.is_absolute() else project/source
                key = str(source.resolve())
                if key not in source_hashes:
                    source_hashes[key] = file_hash(source) if source.is_file() else None
                actual = source_hashes[key]
                status = 'unchanged' if actual == evidence['source_sha256'] else 'missing' if actual is None else 'changed'
                check = {'observation_id': record['observation_id'], 'path': key,
                         'expected_sha256': evidence['source_sha256'], 'actual_sha256': actual, 'status': status}
                source_checks.append(check)
                if status != 'unchanged':
                    conflicts.append({**check, 'has_later_revision': bool(record['annotation']['parent_ids']),
                                      'resolution': '核对来源与当前修订；禁止覆盖'})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            issues.append({'path': str(pointer), 'problem': str(exc)})
    assets = []
    for path in sorted((root/'assets').glob('*.json')):
        asset = load_json(path)
        assets.append({'id': asset['id'], 'path': asset['path'], 'sha256': asset['sha256'],
                       'metadata_sha256': file_hash(path), 'issues': asset['issues']})
    catalog_path = root/'catalog.json'
    result = {'schema_version': 'pose_migration_inventory_v1', 'project_root': str(project), 'library_root': str(root),
              'legacy_files': entries, 'heads': heads, 'revision_files': versions,
              'catalog_sha256': file_hash(catalog_path) if catalog_path.exists() else None,
              'assets': assets, 'source_checks': source_checks, 'conflicts': conflicts, 'issues': issues,
              'counts': {'observations': len(heads), 'collections': dict(collections),
                         'revisions': len(versions)-len(heads), 'bound_locations': bound, 'images': len(assets),
                         'source_evidence': dict(Counter(r['status'] for r in source_checks)),
                         'legacy_file_counts': dict(Counter(r['kind'] for r in entries)),
                         'legacy': {kind: sum(r['records'] or 0 for r in entries if r['kind'] == kind) for kind in patterns}},
              'limits': ['图片内容沿用资产指纹，本报告未逐张重新解码。',
                         '旧采样位置不提升为精确源帧；目录数据库复制另用 SQLite 备份。']}
    result['inventory_sha256'] = fingerprint(result)
    result['created_at'] = now()
    return result


def create_copy(project, destination, library=None):
    """Copy immutable labels/managed images plus a SQLite backup; retain IDs.

    External images remain read-only references. Existing targets are refused.
    A failed/interrupted copy retains INCOMPLETE.json for diagnosis, never serves
    as an implicit replacement for the original library.
    """
    before = inventory(project, library)
    source, dest = Path(before['library_root']), Path(destination).resolve()
    require((source/'catalog.json').is_file(), '源资料库不存在')
    require(not before['issues'], '源清单有读取错误，请先处理后复制')
    require(dest != source and not source.is_relative_to(dest) and not dest.is_relative_to(source), '副本必须位于源库以外的独立目录')
    require(not dest.exists(), '副本目录已存在；不会覆盖，请选择新目录')
    dest.mkdir(parents=True)
    _atomic_json(dest/'INCOMPLETE.json', {'source': str(source), 'created_at': now()})
    shutil.copy2(source/'catalog.json', dest/'catalog.json')
    for name in ('assets', 'images', 'observations', 'workflow', 'training', 'models', 'jobs'):
        if (source/name).exists():
            shutil.copytree(source/name, dest/name)
    for path in (dest/'assets').glob('*.json'):
        asset = load_json(path)
        image = Path(asset['path'])
        if image.is_relative_to(source):
            target = dest/image.relative_to(source)
            if not target.exists() and image.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(image, target)
            asset['path'] = str(target)
            _atomic_json(path, asset)
    database = source/'sources/catalog.sqlite3'
    if database.exists():
        (dest/'sources').mkdir(exist_ok=True)
        with sqlite3.connect(database.as_uri()+'?mode=ro', uri=True) as origin:
            with sqlite3.connect(dest/'sources/catalog.sqlite3') as target:
                origin.backup(target)
                require(target.execute("SELECT count(*) FROM imports WHERE state!='done'").fetchone()[0] == 0,
                        '来源库仍有未完成入库；此副本保留未完成标记，请待原操作完成后重新复制')
                target.execute("UPDATE settings SET value='true' WHERE key='paused'")
                target.execute("UPDATE jobs SET state='queued' WHERE state='running'")
        if (source/'sources/cache').exists():
            shutil.copytree(source/'sources/cache', dest/'sources/cache')
    after = inventory(project, source)
    require(before['inventory_sha256'] == after['inventory_sha256'], '复制期间来源已变化；此副本标为未完成，请重新盘点')
    _atomic_json(dest/'migration_manifest.json', before)
    _atomic_json(dest/'staging.json', {'schema_version': 'pose_staging_copy_v1', 'source_library': str(source),
                                      'project_root': str(Path(project).resolve()), 'inventory_sha256': before['inventory_sha256'],
                                      'created_at': now(), 'external_images': 'retained_references', 'sources_paused': True})
    (dest/'INCOMPLETE.json').unlink()
    return {'library': str(dest), 'inventory': str(dest/'migration_manifest.json'), 'counts': before['counts'],
            'conflicts': before['conflicts'], 'external_images': 'retained_references'}
