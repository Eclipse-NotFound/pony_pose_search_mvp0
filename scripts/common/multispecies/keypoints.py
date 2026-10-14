"""Defined schema points are independent from arbitrary arrow reference points."""
import copy
import math

from .catalog import fingerprint, require, xy
from pose_record import POINTS, EDGES
from .importers import LEGACY_MAPPING

SCHEMA = 'pony.schema21@1'
ORDER = [k for k in POINTS if not k.startswith('tail.')] + ['tail.root', 'tail.forward_reference']
PROFILES = {'pony.quadruped@2draft1'}
LABELS = {'head.center': '头部中心', 'head.forward_reference': '头部朝向参考', 'neck.reference': '颈部朝向参考',
          'body.front': '前躯中心', 'body.rear': '后躯中心', 'tail.root': '尾根连接方向', 'tail.forward_reference': '尾巴初始朝向参考'}
for group, title, names in (('front', '前肢', [('root','腿根'),('bend','转折'),('hoof','蹄端')]),
                            ('hind', '后肢', [('root','腿根'),('upper_bend','上转折'),('lower_bend','下转折'),('hoof','蹄端')])):
    for i in (1, 2):
        for name, label in names:
            LABELS[f'{group}.{i}.{name}'] = f'{title} {i} · {label}'


def blank(evidence):
    return {'schema_ref': SCHEMA, 'points': {k: {'value': None, 'visibility': 'unknown',
            'missing_reason': 'not_annotated', 'review_status': 'unreviewed', 'evidence_refs': [evidence]} for k in ORDER}}


def validate(record, refs):
    from .records import MISSING, VISIBILITY
    kp = record['annotation'].get('keypoints')
    if kp is None:
        return {}
    require(record['profile_ref'] in PROFILES and isinstance(kp, dict) and kp.get('schema_ref') == SCHEMA,
            '点位定义不支持此身体结构；不能套用另一物种的点位')
    require(isinstance(kp.get('points'), dict) and set(kp['points']) == set(ORDER), '点位必须完整对应 schema')
    size = record['coordinates']['image_size']
    fields = {}
    for key, point in kp['points'].items():
        require(isinstance(point, dict), '点位需要值、可见性和审核信息')
        value = point.get('value')
        require(value is None or xy(value), key+': 坐标必须是有限数值')
        require(value is None or size and 0 <= value[0] <= size[0] and 0 <= value[1] <= size[1], key+': 坐标超出图片')
        require(point.get('missing_reason') in MISSING if value is None else point.get('missing_reason') is None, key+': 缺失原因无效')
        require(point.get('visibility') in VISIBILITY, key+': 可见性无效')
        refs(point, key)
        fields['keypoints.'+key] = point
    return fields


def edit(record, patch, evidence):
    from .records import MISSING
    a = record['annotation']
    require(record['profile_ref'] in PROFILES, '当前身体没有已定义的点位模式，请使用方向标注')
    require(isinstance(patch, dict) and set(patch) <= {'schema_ref', 'points'} and patch.get('schema_ref', SCHEMA) == SCHEMA, '点位修改格式无效')
    if not a.get('keypoints'):
        a['keypoints'] = blank(evidence)
    changes = patch.get('points', {})
    require(isinstance(changes, dict) and set(changes) <= set(ORDER), '未知点位')
    changed = set()
    for key, value in changes.items():
        require(isinstance(value, dict) and set(value) <= {'value', 'missing_reason', 'visibility'}, '点位字段无效')
        point = a['keypoints']['points'][key]
        point.update(copy.deepcopy(value), review_status='unreviewed', evidence_refs=[evidence])
        point['missing_reason'] = (point.get('missing_reason') or 'not_annotated') if point['value'] is None else None
        if 'value' in value or 'visibility' in value:
            changed.add(key)
    if changed:
        a['layout'] = None
        for direction in a['directions'].values():
            derived = direction.get('derived_from')
            if derived and changed.intersection(derived['points']):
                derived['stale'] = True
                direction['review_status'] = 'unreviewed'


def proposals(record):
    from .records import unit
    kp = record['annotation'].get('keypoints')
    require(kp and kp['schema_ref'] == SCHEMA, '此记录尚未保存 schema 点位')
    result, conflicts = {}, []
    for old, pair in EDGES.items():
        key = LEGACY_MAPPING[old]
        points = [kp['points'][p] for p in pair]
        value, reference = None, None
        if all(p['value'] is not None and p['visibility'] not in {'occluded', 'out_of_frame'} for p in points):
            start, end = (p['value'] for p in points)
            if math.dist(start, end) > 1e-12:
                value = unit([end[i]-start[i] for i in (0, 1)])
                reference = {'start': start, 'end': end}
        old_direction = record['annotation']['directions'].get(key)
        if old_direction and old_direction['value'] is not None and (value is None or math.dist(old_direction['value'], value) > 1e-6):
            conflicts.append(key)
        result[key] = {'value': value, 'reference_points': reference, 'points': list(pair),
                       'points_sha256': fingerprint([kp['points'][p] for p in pair])}
    return {'directions': result, 'conflicts': conflicts, 'rule_ref': 'pony.schema21_to_body14@1'}


def derive(record, catalog, *, actor, replace=False):
    from .records import revise
    proposal = proposals(record)
    require(replace or not proposal['conflicts'], '点位派生方向与现有方向不同；请查看差异后明确选择替换')
    patches, parts = {}, {}
    for key, item in proposal['directions'].items():
        slot = key.split('.')[0]
        if record['annotation']['parts'][slot]['presence'] == 'absent':
            continue
        if item['value'] is not None and record['annotation']['parts'][slot]['presence'] == 'unknown':
            parts[slot] = {'presence': 'present'}
        if record['annotation']['parts'][slot]['presence'] != 'present' and slot not in parts:
            continue
        patches[key] = {'value': item['value'], 'visibility': 'visible' if item['value'] else 'unknown',
                        'missing_reason': None if item['value'] else 'invalid_geometry'}
        if item['reference_points']:
            patches[key]['reference_points'] = item['reference_points']
    require(patches, '没有可派生的点位方向')
    updated = revise(record, catalog, {'parts': parts, 'directions': patches}, actor=actor)
    for key in patches:
        item = proposal['directions'][key]
        updated['annotation']['directions'][key]['derived_from'] = {
            'rule_ref': proposal['rule_ref'], 'schema_ref': SCHEMA,
            'annotation_id': record['annotation']['id'], 'points': item['points'],
            'points_sha256': item['points_sha256'], 'stale': False}
    updated['evidence'][-1]['method'] = proposal['rule_ref']
    updated['evidence'][-1]['source_revision'] = record['annotation']['id']
    return updated
