"""Exercise the production interface with real isolated files and module CLIs."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'scripts/common'), str(ROOT/'scripts/m10')]
from multispecies import DataError, new_observation
from multispecies.catalog import load_json
from workflow import ProjectContext
from workflow.inventory import inventory, create_copy
from workbench_model import WorkbenchSession


@pytest.fixture
def context(tmp_path):
    ctx = ProjectContext(ROOT, tmp_path/'library')
    image = Image.new('RGB', (90, 70), 'white'); image.putpixel((0, 0), (0, 0, 0))
    path = tmp_path/'image.png'; image.save(path)
    asset = ctx.library.upload_image(path.read_bytes())
    for label in ('query', '<script>candidate & name</script>'):
        record = new_observation(ctx.library.catalog, profile_ref='pony.quadruped@2draft1',
                                 image_ref=asset['id'], image_size=asset['size'], actor='fixture')
        record['source']['label'] = label
        ctx.library.save(record)
        ctx.library.edit(record['observation_id'], record['annotation']['id'],
                         {'parts': {'core': {'presence': 'present'}},
                          'directions': {'core.head': {'value': [1, 0], 'visibility': 'visible'}}},
                         actor='fixture', review={'status': 'approved', 'targets': ['parts.core', 'directions.core.head']})
    yield ctx
    ctx.close()


def pair(context):
    records = context.library.records()
    query = next(r for r in records if r['source']['label'] == 'query')
    return query, next(r for r in records if r['observation_id'] != query['observation_id'])


def test_saved_query_result_and_export_survive_label_changes_and_restart(context):
    query, candidate = pair(context)
    session = WorkbenchSession(ROOT, context=context)
    session.load(query['observation_id'])
    session.edit({'directions': {'core.head': {'value': [0, 1]}}}, 'reviewer')
    with pytest.raises(DataError, match='保存'):
        session.find('pony.body14@1', {}, {})
    updated = session.save('reviewer')
    spec = session.prepare_query('pony.body14@1', {'top_n': 1, 'view_weight': .2, 'layout_weight': 0}, {})
    assert spec['annotation_id'] == updated['annotation']['id']
    result = session.search_saved_query()
    assert result['results'][0]['score'] == pytest.approx(.5)
    assert result['candidate_snapshot_sha256']
    context.library.edit(candidate['observation_id'], candidate['annotation']['id'],
                         {'directions': {'core.head': {'value': [0, 1]}}}, actor='later')
    # M09 exports the previous run, not a recomputation on the newer HEAD.
    exported = context.poses.export(result['run_id'], include_html=True)
    assert load_json(exported['json']) == result
    assert result['results'][0]['annotation_id'] == candidate['annotation']['id']
    html = exported['html'].read_text(encoding='utf-8')
    assert '<script>' not in html and '&lt;script&gt;candidate &amp; name&lt;/script&gt;' in html
    reopened = WorkbenchSession(ROOT, context=context)
    assert reopened.query_id == spec['id'] and reopened.last_results == result
    assert reopened.export_results()[1] == exported['json']
    context.library.edit(query['observation_id'], updated['annotation']['id'],
                         {'directions': {'core.head': {'value': [-1, 0]}}}, actor='new query')
    assert context.poses.statuses()['M07'][0] == '需更新'
    assert context.poses.query(spec['id'])['annotation_id'] == updated['annotation']['id']


@pytest.mark.parametrize('options,filters', [({'allow_mirror': 'false'}, {}),
    ({'collections': 'manual'}, {}), ({'unknown': True}, {}), ({}, {'exact': 'true'}),
    ({'view_weight': .3}, {}), ({'top_n': True}, {}), ({'group_weights': []}, {})])
def test_invalid_query_never_creates_half_saved_query(context, options, filters):
    query, _ = pair(context)
    with pytest.raises(DataError):
        context.poses.prepare_query(query['observation_id'], options=options, source_filters=filters)
    assert context.poses.current() == {}
    assert not list((context.poses.root/'queries').glob('*.json'))


def test_catalog_change_requires_a_new_query_and_corrupt_runs_cannot_be_exported(context):
    query, _ = pair(context)
    spec = context.poses.prepare_query(query['observation_id'])
    result = context.poses.search(spec['id'])
    context.library.add_character('new', species_ref='pony', profile_ref='pony.quadruped@2draft1')
    with pytest.raises(DataError, match='目录已变化'):
        context.poses.search(spec['id'])
    path = context.poses.root/'runs'/(result['run_id']+'.json')
    data = load_json(path); data['results'][0]['score'] = 999
    path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(DataError, match='内容已变化'):
        context.poses.export(result['run_id'])


def test_saved_query_from_another_client_is_used_by_the_module_entry(context):
    query, candidate = pair(context)
    session = WorkbenchSession(ROOT, context=context)
    session.load(query['observation_id'])
    old = session.prepare_query('pony.body14@1', {}, {})
    newer = context.poses.prepare_query(candidate['observation_id'], options={'allow_mirror': True})
    result = session.search_saved_query()
    assert result['query_id'] == newer['id'] != old['id']
    assert result['options']['allow_mirror'] is True
    context.library.edit(query['observation_id'], query['annotation']['id'],
                         {'directions': {'core.head': {'value': [0, -1]}}}, actor='another client')
    with pytest.raises(DataError, match='新修订'):
        session.prepare_query('pony.body14@1', {}, {})


def test_original_module_commands_use_the_same_library(context, tmp_path):
    query, candidate = pair(context)
    patch = tmp_path/'patch.json'; patch.write_text(json.dumps({'directions': {'core.head': {'value': [0, 1]}}}), encoding='utf-8')
    scripts = {'M05': 'annotate_keypoints.py', 'M07': 'annotate_query_pose.py',
               'M08': 'search_similar_poses.py', 'M09': 'generate_results_html.py'}
    def call(module, *args):
        command = [sys.executable, str(ROOT/'scripts'/module.lower()/scripts[module]),
                   '--project-root', str(ROOT), '--library', str(context.library.root), *args]
        p = subprocess.run(command, env=dict(os.environ, PYTHONUTF8='1'), capture_output=True, text=True, encoding='utf-8', timeout=30)
        assert p.returncode == 0, p.stdout+p.stderr
        return json.loads(p.stdout)
    updated = call('M05', '--observation', query['observation_id'], '--revision', query['annotation']['id'],
                   '--patch', str(patch), '--actor', 'cli reviewer')
    spec = call('M07', '--observation', query['observation_id'])
    assert spec['annotation_id'] == updated['annotation']['id']
    run = call('M08', '--query-ref', spec['id'])
    assert run['results'][0]['score'] == pytest.approx(.5)
    paths = call('M09', '--run-ref', run['run_id'])
    assert load_json(paths['json']) == context.poses.result(run['run_id'])
    assert Path(paths['html']).is_file()
    session = WorkbenchSession(ROOT, context=context)
    assert session.last_results == run


def test_inventory_copy_preserves_ids_and_reports_source_conflicts(context, tmp_path):
    # Simulate a legacy source changing after an imported annotation was revised.
    query, _ = pair(context)
    source = tmp_path/'legacy.json'; source.write_text('{"changed":true}', encoding='utf-8')
    record = context.library.read(query['observation_id'])
    record['evidence'].append({'id': 'legacy_fixture', 'kind': 'legacy', 'source_path': str(source),
                               'source_sha256': '0'*64})
    from multispecies.records import new_id
    record['annotation']['parent_ids'] = [record['annotation']['id']]
    record['annotation']['id'] = new_id('ann')
    context.library.save(record, expected_revision=query['annotation']['id'])
    before = inventory(tmp_path, context.library.root)
    assert len(before['conflicts']) == 1 and before['conflicts'][0]['has_later_revision']
    destination = tmp_path/'isolated copy'
    result = create_copy(tmp_path, destination, context.library.root)
    assert result['counts']['observations'] == 2
    assert before['inventory_sha256'] == inventory(tmp_path, context.library.root)['inventory_sha256']
    copied = ProjectContext(ROOT, destination)
    try:
        assert copied.library.read(record['observation_id']) == record
        assert copied.sources.status()['paused'] is True
        assert all(Path(a['path']).is_relative_to(destination) for a in copied.library.assets.values())
        assert copied.library.verify()['records'] == 2
        with pytest.raises(DataError, match='已存在'):
            create_copy(tmp_path, destination, context.library.root)
    finally:
        copied.close()


def test_incomplete_copy_cannot_be_used_as_active_library(tmp_path):
    path = tmp_path/'incomplete'; path.mkdir(); (path/'INCOMPLETE.json').write_text('{}')
    with pytest.raises(DataError, match='尚未完成'):
        ProjectContext(ROOT, path)


def test_copy_with_pending_source_import_keeps_an_incomplete_marker(context, tmp_path):
    with context.sources.db() as db:
        db.execute("INSERT INTO imports VALUES('pending_fixture','request_hash','{}','prepared')")
    destination=tmp_path/'pending copy'
    with pytest.raises(DataError, match='未完成入库'):
        create_copy(tmp_path, destination, context.library.root)
    assert (destination/'INCOMPLETE.json').is_file()
    with pytest.raises(DataError, match='尚未完成'):
        ProjectContext(ROOT, destination)
