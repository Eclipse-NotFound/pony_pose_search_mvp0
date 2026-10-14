"""Bridge source positions to existing immutable observations, without changing scores."""
import copy
import io
import os
from pathlib import Path
import threading

from PIL import Image
from multispecies.catalog import DataError, fingerprint, number, require
from multispecies.records import new_observation, validate_observation
from .store import dumps, safe_id


def reveal_file(path):
    """Ask Explorer to select the verified file; do not execute a shell command."""
    require(os.name == 'nt', '文件定位目前用于 Windows；可复制路径手动打开')
    import ctypes
    from ctypes import wintypes
    shell, ole = ctypes.windll.shell32, ctypes.windll.ole32
    pidl = ctypes.c_void_p()
    shell.SHParseDisplayName.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    shell.SHParseDisplayName.restype = ctypes.c_long
    shell.SHOpenFolderAndSelectItems.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p, wintypes.DWORD]
    shell.SHOpenFolderAndSelectItems.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    initialized = ole.CoInitialize(None)
    try:
        require(shell.SHParseDisplayName(str(path), None, ctypes.byref(pidl), 0, None) >= 0, '系统未能解析这个素材路径')
        require(shell.SHOpenFolderAndSelectItems(pidl, 0, None, 0) >= 0, '系统未能打开文件位置')
    finally:
        if pidl:
            ole.CoTaskMemFree(pidl)
        if initialized >= 0:
            ole.CoUninitialize()
    return {'requested': True, 'path': str(path), 'message': '已请求文件管理器选中原素材；未回读系统窗口状态'}


class SourceService:
    def __init__(self, catalog, library):
        self.catalog, self.library = catalog, library
        self._imports = threading.RLock()

    def records(self):
        with self.catalog.db() as c:
            committed = {r[0] for r in c.execute("SELECT id FROM imports WHERE state='done'")}
        return [r for r in self.library.records() if not r['source'].get('import_ref') or r['source']['import_ref'] in committed]

    def import_observation(self, *, position_id, roi, form_ref, request_id, actor='本机用户', is_query=False,
                           occurrence_id=None, region_ref=None):
        safe_id(request_id)
        require(isinstance(actor, str) and 0 < len(actor.strip()) <= 100, '请填写标注者名称')
        require(isinstance(is_query, bool), '查询标记必须是开关')
        request_hash = fingerprint([position_id, roi, form_ref, actor, is_query])
        if occurrence_id or region_ref:
            request_hash = fingerprint([request_hash, occurrence_id, region_ref])
        with self._imports:
            with self.catalog.db() as c:
                old = c.execute('SELECT * FROM imports WHERE id=?', (request_id,)).fetchone()
            if old:
                require(old['request_hash'] == request_hash, '同一导入操作编号不能对应不同角色区域')
                import json
                record = json.loads(old['record'])
            else:
                position = self.catalog.position(position_id)
                full = self.catalog.cached_image(position_id)
                width, height = position['payload']['image_size']
                require(isinstance(roi, list) and len(roi) == 4 and all(isinstance(x, int) and not isinstance(x, bool) for x in roi), '角色区域需要四个整数：左、上、宽、高')
                x, y, w, h = roi
                require(x >= 0 and y >= 0 and w > 0 and h > 0 and x+w <= width and y+h <= height, '角色框超出原画面范围')
                form = self.library.catalog.get('forms', form_ref)
                with Image.open(full) as im:
                    cropped = im.crop((x, y, x+w, y+h))
                    out = io.BytesIO(); cropped.save(out, 'PNG')
                asset = self.library.upload_image(out.getvalue())
                record = new_observation(self.library.catalog, profile_ref=form['profile_ref'], image_ref=asset['id'], image_size=asset['size'],
                                         character_ref=form.get('character_ref'), form_ref=form_ref, actor=actor,
                                         collection='query' if is_query else 'manual', occurrence_id=occurrence_id)
                if region_ref:
                    record['source']['region_ref'] = copy.deepcopy(region_ref)
                file, p = self.catalog.file(position['file_id']), position['payload']
                record['source'].update(kind=p['kind'], media_ref=position['file_id'], label=file['name'],
                                        locator_ref=position_id, source_version_ref=position['version_id'], import_ref=request_id,
                                        frame_index=p.get('frame_index0') if p['kind'] == 'fla_frame' else p.get('presentation_ordinal0'),
                                        timestamp_sec=None if p['kind'] == 'fla_frame' else p.get('seconds'), precision=p['precision'],
                                        roi=roi, source_image_size=[width, height], source_to_image=[1, 0, 0, 1, -x, -y])
                if p['kind'] == 'fla_frame':
                    record['source']['engineering'] = {key: copy.deepcopy(p.get(key)) for key in (
                        'timeline_id', 'timeline_kind', 'timeline_name', 'frame_index0', 'frame_count',
                        'render_scope', 'renderer', 'export_ref')}
                # Same file versions and byte-identical copies stay connected for later training splits.
                with self.catalog.db() as c:
                    version = c.execute('SELECT sha256 FROM versions WHERE id=?', (position['version_id'],)).fetchone()
                record['split_groups'] = {'shot_ref': 'source_file:'+position['file_id'], 'asset_family_ref': 'source_content:'+version[0]}
                record['evidence'][0]['source_position_ref'] = position_id
                record['evidence'][0]['method'] = 'source_region_selected_parts_not_confirmed'
                validate_observation(record, self.library.catalog)
                with self.catalog.db() as c:
                    c.execute("INSERT INTO imports VALUES(?,?,?,'prepared')", (request_id, request_hash, dumps(record)))
            # Persist the same immutable IDs before committing the SQL link. Retrying after a crash is safe.
            self.library.save(record)
            self._commit_import(request_id, record)
            current = self.library.read(record['observation_id'])
            return {'record': current, 'asset': self.library.assets[current['image_ref']], 'location': self.describe(current)}

    def bind_legacy_region(self, region, record, *, actor='旧资料迁移'):
        """Bind an existing crop only when decoded pixels exactly match a verified ROI."""
        from multispecies.records import new_id, now
        request_id='legacy_binding_'+fingerprint([region['revision'],record['observation_id']])[:32]
        with self._imports:
            with self.catalog.db() as db:old=db.execute('SELECT record FROM imports WHERE id=?',(request_id,)).fetchone()
            if old:
                import json
                updated=json.loads(old[0])
                self.library.save(updated,expected_revision=updated['annotation']['parent_ids'][0]);self._commit_import(request_id,updated)
                return self.library.read(record['observation_id'])
            require(not record['source'].get('locator_ref'),'旧样本已有素材绑定，不能替换')
            position=self.catalog.position(region['position_id']);x,y,w,h=region['roi']
            raw,_=self.library.image_bytes(record['image_ref'])
            with Image.open(io.BytesIO(raw)) as crop, Image.open(self.catalog.cached_image(region['position_id'])) as full:
                exact=full.convert('RGBA').crop((x,y,x+w,y+h))
                require(crop.size==exact.size and crop.convert('RGBA').tobytes()==exact.tobytes(),'旧裁剪与当前框的像素不一致，保留旧定位')
            updated=copy.deepcopy(record);a=updated['annotation'];parent=a['id']
            a.update(id=new_id('ann'),parent_ids=[parent],author=actor,created_at=now())
            updated['source'].update(kind='image',legacy_location=copy.deepcopy(record['source']),
                locator_ref=region['position_id'],source_version_ref=position['version_id'],import_ref=request_id,
                precision='image_exact',roi=region['roi'],source_image_size=position['payload']['image_size'],
                source_to_image=[1,0,0,1,-x,-y],frame_index=None,timestamp_sec=None,
                region_ref={'id':region['id'],'revision':region['revision'],'candidate_id':region['candidate_id']})
            updated['evidence'].append({'id':new_id('ev'),'kind':'legacy','method':'verified_exact_crop_pixels',
                'source_position_ref':region['position_id'],'region_revision':region['revision'],'actor':actor,'created_at':now()})
            validate_observation(updated,self.library.catalog)
            with self.catalog.db() as db:
                db.execute("INSERT INTO imports VALUES(?,?,?,'prepared')",(request_id,fingerprint([region['revision'],record['image_ref']]),dumps(updated)))
            try:self.library.save(updated,expected_revision=parent)
            except ValueError:
                with self.catalog.db() as db:db.execute("DELETE FROM imports WHERE id=? AND state='prepared'",(request_id,))
                raise
            self._commit_import(request_id,updated)
            return updated

    def _commit_import(self, request_id, record):
        source = record['source']
        with self.catalog.db() as c:
            c.execute('INSERT OR IGNORE INTO bindings VALUES(?,?,?,?,?,?)', (record['observation_id'], record['annotation']['id'], source['locator_ref'], record['image_ref'], dumps(source['roi']), request_id))
            c.execute("UPDATE imports SET state='done' WHERE id=?", (request_id,))

    def recover(self):
        """Finish prepared imports after a process restart, using their original IDs."""
        import json
        with self.catalog.db() as c:
            rows = c.execute("SELECT id,record FROM imports WHERE state='prepared'").fetchall()
        for row in rows:
            record = json.loads(row['record'])
            self.library.save(record,expected_revision=record['annotation']['parent_ids'][0] if record['annotation']['parent_ids'] else None)
            self._commit_import(row['id'], record)

    def describe_position(self, pid):
        position = self.catalog.position(pid)
        file, p = self.catalog.file(position['file_id']), position['payload']
        with self.catalog.db() as c:
            sha = c.execute('SELECT sha256 FROM versions WHERE id=?', (position['version_id'],)).fetchone()[0]
        return {'position_id': pid, 'file_id': file['id'], 'version_id': position['version_id'], 'sha256': sha, 'path': file['path'],
                'name': file['name'], 'format': file['format'], 'root_id': file['root_id'], 'root_path': file['root_path'],
                'availability': self.catalog.availability(file, position['version_id']), 'precision': p['precision'],
                'position': p, 'image_url': '/api/sources/position-image/'+pid, 'related': self.catalog.related(file['id'])}

    def describe(self, record, assets=None):
        source = record['source']
        if source.get('locator_ref'):
            result = self.describe_position(source['locator_ref'])
            result.update(roi=source.get('roi'), source_to_image=source.get('source_to_image'), observation_id=record['observation_id'])
            return result
        asset = (self.library.assets if assets is None else assets)[record['image_ref']]
        # No filename heuristic can turn sampled legacy data into an absolute source frame.
        seconds = source.get('timestamp_sec')
        approximate = number(seconds) and seconds >= 0
        return {'position_id': None, 'file_id': None, 'path': asset['path'], 'name': source.get('label') or source.get('frame_id') or Path(asset['path']).name,
                'format': None, 'availability': 'unbound', 'precision': 'time_approx' if approximate else 'image_only',
                'position': {'kind': 'legacy', 'seconds': seconds if approximate else None, 'image_size': asset.get('size') or [640,480]}, 'related': [],
                'image_url': '/api/image/'+record['image_ref'], 'observation_id': record['observation_id'],
                'note': '留存图片可看；未绑定可核验的原素材位置。旧采样编号不视为源视频帧。'}

    def position_text(self, info, *, mirrored=False):
        p = info['position']
        lines = ['素材：'+info['name'], ('原文件：' if info['file_id'] else '留存图片：')+info['path'], '定位精度：'+info['precision'], '来源状态：'+info['availability']]
        if p.get('kind') == 'fla_frame':
            kind = '场景' if p['timeline_kind'] == 'scene' else '库元件'
            lines.append(f"工程时间轴：{kind}「{p['timeline_name']}」；编号：{p['timeline_id']}")
            lines.append(f"工程帧：第 {p['frame_index0']+1} 帧（该时间轴从1计；共 {p['frame_count']} 帧）")
            lines.append('渲染范围：'+('完整场景' if p['render_scope'] == 'scene' else '所选库元件本身；完整角色尚需筛选确认'))
        elif p.get('presentation_ordinal0') is not None:
            lines.append(f"视频帧：第 {p['presentation_ordinal0']+1} 帧（从1计）；视频流：{p['stream_index']}")
            lines.append(f"PTS：{p['pts']}；时间单位：{p['time_base'][0]}/{p['time_base'][1]}；起始 PTS：{p['start_pts']}")
        if p.get('kind') != 'fla_frame' and p.get('seconds') is not None:
            lines.append(('约片内时间：' if info['precision'] == 'time_approx' else '片内时间：')+f"{p['seconds']:.6f} 秒")
        if info.get('roi'):
            lines.append('角色框（原显示画面 x,y,宽,高）：'+str(info['roi']))
        if info.get('sha256'):
            lines.append('原内容 SHA-256：'+info['sha256'])
        lines.append('匹配朝向：'+('需左右翻转；原素材保持原朝向' if mirrored else '原始朝向'))
        for item in info['related']:
            if item['kind'] in {'fla','xfl'}:
                lines.append('关联工程（同名候选；帧与角色未核对）：'+self.catalog.file(item['file_id'])['path'])
        if info.get('note'):
            lines.append(info['note'])
        return '\n'.join(lines)

    def locate(self, *, file_id=None, position_id=None, observation_id=None):
        if position_id:
            p = self.catalog.position(position_id)
            path, _ = self.catalog.verified_path(p['file_id'], p['version_id'])
        elif file_id:
            path, _ = self.catalog.verified_path(file_id)
        else:
            record = self.library.read(observation_id)
            if record['source'].get('locator_ref'):
                return self.locate(position_id=record['source']['locator_ref'])
            self.library.image_bytes(record['image_ref'])  # Verify the retained image before revealing it.
            path = Path(self.library.assets[record['image_ref']]['path'])
        return reveal_file(path)

    def filter_records(self, records, filters):
        require(isinstance(filters, dict) and set(filters) <= {'format','root_id','available','exact','related'}, '未知素材筛选条件')
        for key in ('available','exact','related'):
            require(key not in filters or isinstance(filters[key], bool), '素材筛选开关无效')
        for key in ('format','root_id'):
            require(key not in filters or isinstance(filters[key], str), '素材筛选值无效')
        if not any(filters.values()):
            return records
        result, assets = [], self.library.assets
        for r in records:
            info = self.describe(r, assets)
            if (filters.get('format') and info['format'] != filters['format'] or filters.get('root_id') and info.get('root_id') != filters['root_id'] or
                filters.get('available') and info['availability'] != 'available' or filters.get('exact') and info['precision'] not in {'frame_exact','image_exact','timeline_exact'} or
                filters.get('related') and not (str(info.get('format') or '').lower() in {'fla','xfl'}
                                               or any(x['kind'] in {'fla','xfl'} for x in info['related']))):
                continue
            result.append(r)
        return result

    def legacy_report(self):
        assets = self.library.assets
        rows = [{'observation_id': r['observation_id'], 'legacy_frame_id': r['source'].get('frame_id'), **self.describe(r, assets)}
                for r in self.records() if not r['source'].get('locator_ref')]
        return {'records': rows, 'count': len(rows), 'policy': '仅报告已知线索；未改原记录或推测精确帧号'}
