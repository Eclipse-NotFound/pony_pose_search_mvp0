"""SQLite catalogue, immutable source versions/positions and restartable work."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import zipfile

from PIL import Image
from multispecies.catalog import DataError, fingerprint, require
from multispecies.records import new_id, now
from . import media


def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def safe_id(value):
    require(isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,150}", value), "无效的素材或位置编号")
    return value


class Interrupted(Exception):
    pass


class SourceCatalog:
    def __init__(self, directory):
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.cache = self.root/"cache"
        self.cache.mkdir(exist_ok=True)
        self.database = self.root/"catalog.sqlite3"
        self._stop, self._wake = threading.Event(), threading.Event()
        self._thread = None
        self.handlers = {}
        with self.db() as c:
            c.executescript('''
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
              INSERT OR IGNORE INTO settings VALUES('schema','1');
              INSERT OR IGNORE INTO settings VALUES('paused','false');
              CREATE TABLE IF NOT EXISTS roots(id TEXT PRIMARY KEY,path TEXT NOT NULL UNIQUE,label TEXT NOT NULL,
                  selections TEXT,excludes TEXT NOT NULL DEFAULT '[]',created TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS versions(id TEXT PRIMARY KEY,sha256 TEXT NOT NULL,kind TEXT NOT NULL,
                  metadata TEXT NOT NULL,created TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS files(id TEXT PRIMARY KEY,root_id TEXT NOT NULL REFERENCES roots(id),
                  rel_path TEXT NOT NULL,format TEXT NOT NULL,kind TEXT NOT NULL,group_key TEXT,stat TEXT NOT NULL,
                  version_id TEXT REFERENCES versions(id),state TEXT NOT NULL,error TEXT,present INTEGER NOT NULL DEFAULT 1,
                  scanned TEXT NOT NULL,UNIQUE(root_id,rel_path));
              CREATE INDEX IF NOT EXISTS files_group ON files(root_id,group_key);
              CREATE TABLE IF NOT EXISTS file_versions(file_id TEXT NOT NULL REFERENCES files(id),version_id TEXT NOT NULL REFERENCES versions(id),
                  seen TEXT NOT NULL,PRIMARY KEY(file_id,version_id));
              CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,kind TEXT NOT NULL,parameters TEXT NOT NULL,task_key TEXT NOT NULL UNIQUE,
                  state TEXT NOT NULL,done INTEGER NOT NULL DEFAULT 0,total INTEGER NOT NULL DEFAULT 0,error TEXT,result TEXT,
                  created TEXT NOT NULL,updated TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS positions(id TEXT PRIMARY KEY,file_id TEXT NOT NULL REFERENCES files(id),version_id TEXT NOT NULL REFERENCES versions(id),
                  payload TEXT NOT NULL,created TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS imports(id TEXT PRIMARY KEY,request_hash TEXT NOT NULL,record TEXT NOT NULL,state TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS bindings(observation_id TEXT PRIMARY KEY,annotation_id TEXT NOT NULL,position_id TEXT NOT NULL REFERENCES positions(id),
                  image_ref TEXT NOT NULL,roi TEXT NOT NULL,import_id TEXT NOT NULL REFERENCES imports(id));
            ''')
            require(c.execute("SELECT value FROM settings WHERE key='schema'").fetchone()[0] in {'1', '2'}, "素材目录版本不兼容")
        from .schema import upgrade
        upgrade(self)

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.database, timeout=15)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        try:
            with c:
                yield c
        finally:
            c.close()

    def queue(self, kind, parameters, key=None):
        key = key or new_id("request")
        with self.db() as c:
            old = c.execute("SELECT id FROM jobs WHERE task_key=?", (key,)).fetchone()
            if old:
                return old[0]
            jid = new_id("job")
            c.execute("INSERT INTO jobs(id,kind,parameters,task_key,state,created,updated) VALUES(?,?,?,?,?,?,?)",
                      (jid, kind, dumps(parameters), key, 'queued', now(), now()))
        self._wake.set()
        return jid

    def add_inputs(self, paths, *, excludes=None):
        require(isinstance(paths, list) and 0 < len(paths) <= 64, "每次输入1至64个文件或文件夹路径")
        require(excludes is None or isinstance(excludes, list) and all(isinstance(x, str) for x in excludes), "排除规则必须是名称列表")
        grouped = {}
        for value in paths:
            require(isinstance(value, str) and Path(value).is_absolute(), "请填写完整的本机路径")
            path = Path(value).resolve()
            require(path.exists(), f"找不到素材：{path}")
            require(not path.is_relative_to(self.root), "不能将编目库自身作为素材导入")
            folder = path.is_dir() and media.kind_of(path) != "xfl"
            root, member = (path, None) if folder else (path.parent, path.name)
            key = str(root)
            if member is None:
                grouped[key] = None
            elif key not in grouped:
                grouped[key] = [member]
            elif grouped[key] is not None:
                grouped[key].append(member)
        roots = []
        with self.db() as c:
            for path, selections in grouped.items():
                row = c.execute("SELECT * FROM roots WHERE path=?", (path,)).fetchone()
                if row:
                    old = json.loads(row["selections"]) if row["selections"] else None
                    merged = None if old is None or selections is None else sorted(set(old+selections))
                    rid = row["id"]
                    c.execute("UPDATE roots SET selections=?,excludes=? WHERE id=?", (dumps(merged) if merged is not None else None, dumps(excludes or json.loads(row['excludes'])), rid))
                else:
                    rid = new_id("root")
                    c.execute("INSERT INTO roots(id,path,label,selections,excludes,created) VALUES(?,?,?,?,?,?)",
                              (rid, path, Path(path).name or path, dumps(selections) if selections is not None else None, dumps(excludes or []), now()))
                roots.append(rid)
        return {"root_ids": roots, "job_ids": [self.queue("scan", {"root_id": rid}) for rid in roots]}

    def get_root(self, rid):
        with self.db() as c:
            row = c.execute("SELECT * FROM roots WHERE id=?", (safe_id(rid),)).fetchone()
        require(row is not None, "素材根目录不存在")
        return dict(row)

    def set_excludes(self, rid, excludes):
        """Change future scanning rules without widening a file-only root."""
        self.get_root(rid)
        require(isinstance(excludes, list) and all(isinstance(x, str) for x in excludes), '排除规则必须是名称列表')
        with self.db() as c:
            c.execute('UPDATE roots SET excludes=? WHERE id=?', (dumps(excludes), rid))
        return self.queue('scan', {'root_id': rid})

    def _paths(self, root, selections, excludes):
        excluded = set(excludes+['.git', '__pycache__', '$RECYCLE.BIN'])
        if selections is not None:
            for rel in selections:
                p = media.within(root/rel, root)
                if p.exists():
                    yield p
            return
        for parent, dirs, files in os.walk(root, followlinks=False):
            kept = []
            for name in sorted(dirs):
                p = Path(parent)/name
                if name in excluded or p.is_symlink() or p.resolve().is_relative_to(self.root):
                    continue
                media.within(p, root)
                if (p/"DOMDocument.xml").is_file():
                    yield p
                else:
                    kept.append(name)
            dirs[:] = kept
            for name in sorted(files):
                p = Path(parent)/name
                if name not in excluded and not p.is_symlink() and not p.resolve().is_relative_to(self.root):
                    yield media.within(p, root)

    def _checkpoint(self):
        while self.paused:
            if self._stop.wait(.2):
                raise Interrupted()
        if self._stop.is_set():
            raise Interrupted()

    @property
    def paused(self):
        with self.db() as c:
            return c.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0] == 'true'

    def pause(self, value):
        require(isinstance(value, bool), "暂停值必须是开关")
        with self.db() as c:
            c.execute("UPDATE settings SET value=? WHERE key='paused'", ('true' if value else 'false',))
        self._wake.set()

    def _progress(self, jid, done, total=0):
        with self.db() as c:
            c.execute("UPDATE jobs SET done=?,total=?,updated=? WHERE id=?", (done, total, now(), jid))

    def scan(self, rid, *, force=False, jid=None):
        spec = self.get_root(rid)
        root = Path(spec["path"])
        require(root.is_dir(), "素材根目录目前不可访问；保留原记录，可重新定位根目录")
        start, count, changed = now(), 0, 0
        selections = json.loads(spec["selections"]) if spec["selections"] else None
        for path in self._paths(root, selections, json.loads(spec["excludes"])):
            self._checkpoint()
            rel, kind = path.relative_to(root).as_posix(), media.kind_of(path)
            signature, error = {}, None
            try:
                signature = media.signature(path)
            except OSError as exc:
                error = str(exc)
            with self.db() as c:
                old = c.execute("SELECT * FROM files WHERE root_id=? AND rel_path=?", (rid, rel)).fetchone()
                fid = old['id'] if old else new_id('file')
                needs_probe = not old or force or old['stat'] != dumps(signature) or old['state'] == 'error' or not old['version_id']
                state = 'error' if error else 'registered' if needs_probe else old['state']
                values = (rid, rel, path.suffix[1:].upper() if path.is_file() else 'XFL', kind, path.stem.casefold(), dumps(signature), state, error, start, fid)
                if old:
                    c.execute("UPDATE files SET root_id=?,rel_path=?,format=?,kind=?,group_key=?,stat=?,state=?,error=?,present=1,scanned=? WHERE id=?", values)
                else:
                    c.execute("INSERT INTO files(root_id,rel_path,format,kind,group_key,stat,state,error,scanned,id) VALUES(?,?,?,?,?,?,?,?,?,?)", values)
            if needs_probe and not error:
                # One pending task per file/signature; failed tasks require retry or a force scan.
                key = None if force else 'probe:'+fid+':'+fingerprint(signature)
                existing = self.queue('probe', {"file_id": fid}, key)
                if self.job(existing)['state'] == 'failed':
                    self.retry(existing)
                changed += 1
            count += 1
            if jid and count % 25 == 0:
                self._progress(jid, count)
        with self.db() as c:
            c.execute("UPDATE files SET present=0 WHERE root_id=? AND scanned<?", (rid, start))
        if jid:
            self._progress(jid, count, count)
        return {"files_seen": count, "scheduled": changed}

    def file(self, fid):
        with self.db() as c:
            row = c.execute('''SELECT f.*,r.path root_path,r.label root_label,v.sha256,v.metadata FROM files f JOIN roots r ON r.id=f.root_id
                LEFT JOIN versions v ON v.id=f.version_id WHERE f.id=?''', (safe_id(fid),)).fetchone()
        require(row is not None, "素材未登记")
        result = dict(row)
        result['stat'] = json.loads(result['stat'])
        result['metadata'] = json.loads(result['metadata']) if result['metadata'] else {}
        result['name'] = Path(result['rel_path']).name
        result['path'] = str(Path(result['root_path'])/result['rel_path'])
        result['availability'] = self.availability(result)
        return result

    def availability(self, file, version_id=None):
        if version_id and file['version_id'] != version_id:
            return 'changed'
        try:
            path = media.within(file['path'], file['root_path'])
            if not Path(file['root_path']).is_dir():
                return 'offline'
            if not path.exists():
                return 'missing'
            if file['state'] in {'registered', 'processing'}:
                return 'checking'
            # XFL member changes are fully checked before every position/action.
            if path.is_file() and media.signature(path) != file['stat']:
                return 'changed'
            return 'available'
        except (OSError, DataError):
            return 'unreadable'

    def verified_path(self, fid, version_id=None):
        file = self.file(fid)
        vid = version_id or file['version_id']
        require(vid is not None, "素材内容尚未读取完成")
        with self.db() as c:
            version = c.execute("SELECT * FROM versions WHERE id=?", (safe_id(vid),)).fetchone()
            linked = c.execute("SELECT 1 FROM file_versions WHERE file_id=? AND version_id=?", (fid, vid)).fetchone()
        require(version is not None and linked is not None, "此内容版本不属于所选素材")
        path = media.within(file['path'], file['root_path'])
        require(path.exists(), "原素材离线或已移动；缓存仍保留，请重新定位")
        require(media.identity(path) == version['sha256'], "原素材内容已改变，不能将旧位置套到新版本；请重新扫描")
        return path, dict(version)

    def probe(self, fid):
        file = self.file(fid)
        path = media.within(file['path'], file['root_path'])
        require(path.exists(), "素材已离线")
        with self.db() as c:
            c.execute("UPDATE files SET state='processing',error=NULL WHERE id=?", (fid,))
        before = media.identity(path)
        vid = 'version_'+fingerprint([file['kind'], before])
        thumb = self.cache/(new_id('thumb')+'.jpg')
        try:
            error = None
            try:
                meta = media.inspect(path, file['kind'], thumb)
            except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
                error = str(exc)
                meta = {'capabilities': ['file'], 'note': '文件已登记；内容读取失败，可单独重试', 'probe_error': error}
            require(media.identity(path) == before, "读取过程中源文件已变化，本次结果未提交；请重试")
            if thumb.exists():
                final = self.cache/(vid+'.jpg')
                os.replace(thumb, final)
                meta['thumbnail'] = final.name
            signature = media.signature(path)
            with self.db() as c:
                c.execute("INSERT INTO versions VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET metadata=excluded.metadata", (vid, before, file['kind'], dumps(meta), now()))
                c.execute("INSERT OR IGNORE INTO file_versions VALUES(?,?,?)", (fid, vid, now()))
                c.execute("UPDATE files SET version_id=?,stat=?,state=?,error=?,present=1 WHERE id=?", (vid, dumps(signature), 'error' if error else 'ready', error, fid))
        finally:
            thumb.unlink(missing_ok=True)
        if error:
            raise DataError(error)
        return {"file_id": fid, "version_id": vid}

    def list_files(self, *, query='', format='', root_id='', limit=48, offset=0):
        require(isinstance(limit, int) and 1 <= limit <= 200 and isinstance(offset, int) and offset >= 0, "分页范围无效")
        clauses, values = [], []
        for sql, value in (("lower(rel_path) LIKE ?", '%'+query.lower()+'%' if query else None), ('format=?', format.upper() if format else None), ('root_id=?', root_id or None)):
            if value is not None:
                clauses.append(sql); values.append(value)
        where = ' WHERE '+' AND '.join(clauses) if clauses else ''
        with self.db() as c:
            total = c.execute('SELECT count(*) FROM files'+where, values).fetchone()[0]
            ids = [row[0] for row in c.execute('SELECT id FROM files'+where+' ORDER BY rel_path,id LIMIT ? OFFSET ?', values+[limit, offset])]
            poses = dict(c.execute('SELECT p.file_id,count(*) FROM bindings b JOIN positions p ON p.id=b.position_id GROUP BY p.file_id'))
        items = []
        for fid in ids:
            item = self.file(fid)
            item['pose_count'] = poses.get(fid, 0)
            if 'scenes' in item['metadata']:
                item['metadata']['scene_count'] = len(item['metadata'].pop('scenes'))
            items.append(item)
        return {"items": items, "total": total, "offset": offset, "limit": limit}

    def related(self, fid):
        file = self.file(fid)
        with self.db() as c:
            rows = c.execute("SELECT id FROM files WHERE group_key=? AND id!=? AND kind IN ('fla','xfl','video','image','swf') ORDER BY (root_id=?) DESC,kind,rel_path LIMIT 50",
                             (file['group_key'], fid, file['root_id'])).fetchall()
        items = [self.file(row[0]) for row in rows]
        return [{"file_id": item['id'], "name": item['name'], "path": item['path'], "kind": item['kind'],
                 "status": "candidate", "evidence": "已登记范围中的同名文件；同一根目录优先，帧与角色未核对"} for item in items]

    def position(self, pid):
        with self.db() as c:
            row = c.execute("SELECT * FROM positions WHERE id=?", (safe_id(pid),)).fetchone()
        require(row is not None, "素材位置不存在")
        return {**dict(row), "payload": json.loads(row['payload'])}

    def create_position(self, fid, *, ordinal0=0, stream_index=None, version_id=None):
        file = self.file(fid)
        path, version = self.verified_path(fid, version_id)
        vid, kind, meta = version['id'], version['kind'], json.loads(version['metadata'])
        require(kind in {'video', 'image'}, "此格式目前只支持文件定位，未实现工程画面渲染")
        require('pose_input' in meta.get('capabilities', []), "该素材当前无法读取画面，请先重试内容读取")
        if kind == 'video':
            stream = meta['default_stream'] if stream_index is None else stream_index
            require(isinstance(stream, int) and not isinstance(stream, bool), "视频流编号无效")
            key = fingerprint([vid, stream, media.decoder_version()])
            index_path = self.cache/('index_'+key+'.json')
            if index_path.exists():
                index = json.loads(index_path.read_text(encoding='utf-8'))
            else:
                index = media.frame_index(path, stream, meta)
                require(media.identity(path) == version['sha256'], "建立帧索引时源文件变化，请重新扫描")
                temp = index_path.with_suffix('.tmp')
                temp.write_text(dumps(index), encoding='utf-8')
                os.replace(temp, index_path)
            position = media.frame_position(index, ordinal0)
        else:
            require('image' in meta.get('capabilities', []), "该图片类型不能建立静态位置")
            position = {"kind": 'image', "precision": 'image_exact', "coordinates": meta['coordinates'], "exif_orientation": meta['exif_orientation'], "raw_size": meta['raw_size'],
                        "renderer": {'pillow': media.PILLOW_VERSION, 'method': 'exif_transpose_rgba_png_v1'}}
        pid = 'position_'+fingerprint([fid, vid, position])
        final = self.cache/(pid+'.png')
        with self.db() as c:
            existing = c.execute("SELECT 1 FROM positions WHERE id=?", (pid,)).fetchone()
        if existing and final.exists():
            known = self.position(pid)
            if media.sha_file(final) == known['payload']['image_sha256']:
                return known
        temp = self.cache/(new_id('frame')+'.png')
        try:
            position['image_size'] = media.extract(path, kind, position, temp)
            require(media.identity(path) == version['sha256'], "取帧过程中源文件改变，本次画面未保存")
            position['image_sha256'] = media.sha_file(temp)
            position['cache'] = final.name
            if existing:
                require(position['image_sha256'] == self.position(pid)['payload']['image_sha256'], '重新解码的画面与旧缓存指纹不同；未覆盖旧位置')
            os.replace(temp, final)
            with self.db() as c:
                c.execute("INSERT OR IGNORE INTO positions VALUES(?,?,?,?,?)", (pid, fid, vid, dumps(position), now()))
        finally:
            temp.unlink(missing_ok=True)
        return self.position(pid)

    def cached_image(self, pid):
        p = self.position(pid)
        path = media.within(self.cache/p['payload']['cache'], self.cache)
        require(path.is_file(), "画面缓存缺失；原素材可用时请重新取帧")
        require(media.sha_file(path) == p['payload']['image_sha256'], "画面缓存已改变，需要重新取帧")
        return path

    def create_proxy(self, pid):
        position = self.position(pid)
        require(position['payload']['kind'] == 'video_frame', "只有视频位置支持播放")
        path, version = self.verified_path(position['file_id'], position['version_id'])
        stream = position['payload']['stream_index']
        name = 'proxy_'+fingerprint([version['id'], stream, media.decoder_version(), 'preview_startpts_v1'])+'.mp4'
        target = self.cache/name
        if not target.exists():
            temp = self.cache/(new_id('proxy')+'.mp4')
            try:
                media.proxy(path, stream, temp)
                require(media.identity(path) == version['sha256'], "生成播放文件时原素材发生变化")
                os.replace(temp, target)
            finally:
                temp.unlink(missing_ok=True)
        # The proxy starts at its first decoded frame; the stream's declared
        # start can differ. Account for that before requesting a nearby seek.
        index_path = self.cache/('index_'+fingerprint([version['id'], stream, media.decoder_version()])+'.json')
        index = json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else media.frame_index(path, stream, json.loads(version['metadata']))
        first, pts = index['frames'][0]['pts'], position['payload']['pts']
        seconds = None if first is None or pts is None else (pts-first)*index['time_base'][0]/index['time_base'][1]
        return {"cache_name": name, "position_id": pid, "seconds": seconds, "precision": "time_approx"}

    def rebind_root(self, rid, path, jid=None):
        require(isinstance(path, str) and Path(path).is_absolute(), "新根目录需要完整路径")
        target = Path(path).resolve()
        require(target.is_dir(), "新的素材根目录不存在")
        spec = self.get_root(rid)
        with self.db() as c:
            files = [dict(r) for r in c.execute('SELECT id,rel_path,version_id FROM files WHERE root_id=?', (rid,))]
        checked = []
        for i, row in enumerate(files):
            self._checkpoint()
            p = media.within(target/row['rel_path'], target)
            require(p.exists(), '新目录缺少：'+row['rel_path'])
            if row['version_id']:
                with self.db() as c:
                    sha = c.execute('SELECT sha256 FROM versions WHERE id=?', (row['version_id'],)).fetchone()[0]
                require(media.identity(p) == sha, '新目录有同名不同内容：'+row['rel_path'])
            checked.append((dumps(media.signature(p)), row['id']))
            if jid:
                self._progress(jid, i+1, len(files))
        with self.db() as c:
            require(c.execute('SELECT path FROM roots WHERE id=?', (rid,)).fetchone()[0] == spec['path'], '根目录已被其他操作修改')
            c.execute('UPDATE roots SET path=? WHERE id=?', (str(target), rid))
            c.executemany('UPDATE files SET stat=?,present=1 WHERE id=?', checked)
        return {"root_id": rid, "verified_files": len(checked), "path": str(target)}

    def job(self, jid):
        with self.db() as c:
            row = c.execute('SELECT * FROM jobs WHERE id=?', (safe_id(jid),)).fetchone()
        require(row is not None, '任务不存在')
        parameters = json.loads(row['parameters'])
        label = ''
        fid = parameters.get('file_id') or parameters.get('fid')
        with self.db() as c:
            if fid:
                item = c.execute('SELECT rel_path FROM files WHERE id=?', (fid,)).fetchone()
                label = item[0] if item else fid
            elif parameters.get('root_id'):
                item = c.execute('SELECT path FROM roots WHERE id=?', (parameters['root_id'],)).fetchone()
                label = item[0] if item else parameters['root_id']
        return {**dict(row), 'parameters': parameters, 'label': label, 'result': json.loads(row['result']) if row['result'] else None}

    def retry(self, jid):
        with self.db() as c:
            c.execute("UPDATE jobs SET state='queued',error=NULL,updated=? WHERE id=? AND state='failed'", (now(), safe_id(jid)))
        self._wake.set()

    def cancel(self, jid):
        with self.db() as c:
            row=c.execute('SELECT kind,state FROM jobs WHERE id=?',(safe_id(jid),)).fetchone()
            require(row is not None,'找不到任务')
            require(row['state']=='queued' or row['kind'] in {'train','predict'},'此任务执行中请使用暂停；尚不支持单独取消')
            c.execute("UPDATE jobs SET state=?,updated=? WHERE id=? AND state IN ('queued','running')",
                      ('cancelled' if row['state']=='queued' else 'cancel_requested',now(),jid))

    def status(self, limit=20, offset=0):
        require(type(limit) is int and 1<=limit<=500 and type(offset) is int and offset>=0, "任务分页范围无效")
        with self.db() as c:
            states = dict(c.execute('SELECT state,count(*) FROM jobs GROUP BY state'))
            roots = [dict(r) for r in c.execute('SELECT * FROM roots ORDER BY created')]
            jobs = [r[0] for r in c.execute("SELECT id FROM jobs ORDER BY CASE WHEN state='running' THEN 0 WHEN state='failed' THEN 1 WHEN state='queued' THEN 2 ELSE 3 END,updated DESC LIMIT ? OFFSET ?",(limit,offset))]
            totals = dict(c.execute('SELECT state,count(*) FROM files GROUP BY state'))
        return {'paused': self.paused, 'roots': roots, 'states': states, 'files': totals, 'jobs': [self.job(j) for j in jobs]}

    def run_next(self):
        if self.paused or self._stop.is_set():
            return False
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute("""SELECT * FROM jobs WHERE state='queued' ORDER BY
                CASE kind WHEN 'position' THEN 0 WHEN 'proxy' THEN 1 WHEN 'rebind' THEN 2 WHEN 'scan' THEN 3 ELSE 4 END,
                created,id LIMIT 1""").fetchone()
            if not row:
                return False
            c.execute("UPDATE jobs SET state='running',updated=? WHERE id=?", (now(), row['id']))
        jid, params = row['id'], json.loads(row['parameters'])
        try:
            if row['kind'] == 'scan':
                result = self.scan(params['root_id'], force=params.get('force', False), jid=jid)
            elif row['kind'] == 'probe':
                result = self.probe(params['file_id'])
            elif row['kind'] == 'position':
                result = self.create_position(**params)
            elif row['kind'] == 'proxy':
                result = self.create_proxy(params['position_id'])
            elif row['kind'] == 'rebind':
                result = self.rebind_root(params['root_id'], params['path'], jid)
            elif row['kind'] in self.handlers:
                result = self.handlers[row['kind']](params, jid)
            else:
                raise DataError('未知素材任务')
            with self.db() as c:
                c.execute("UPDATE jobs SET state='done',result=?,error=NULL,updated=? WHERE id=?", (dumps(result), now(), jid))
        except (Interrupted, media.Cancelled):
            with self.db() as c:
                c.execute("UPDATE jobs SET state='queued',updated=? WHERE id=?", (now(), jid))
        except Exception as exc:
            with self.db() as c:
                c.execute("UPDATE jobs SET state='failed',error=?,updated=? WHERE id=?", (str(exc), now(), jid))
                if row['kind'] == 'probe':
                    c.execute("UPDATE files SET state='error',error=? WHERE id=?", (str(exc), params['file_id']))
        return True

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, name='source-catalog', daemon=True)
        self._thread.start()

    def _worker(self):
        lock = (self.root/'.worker.lock').open('a+b')
        lock.seek(0, 2)
        if lock.tell() == 0:
            lock.write(b'0'); lock.flush()
        lock.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lock.close()
            return  # Another process owns background work; this process can still enqueue.
        try:
            media._context.stop = self._stop
            with self.db() as c:
                c.execute("UPDATE jobs SET state='failed',error='上次模型任务中断；重试会重新开始' WHERE state IN ('running','cancel_requested') AND kind IN ('train','predict')")
                c.execute("UPDATE jobs SET state='queued' WHERE state='running'")
            while not self._stop.is_set():
                if not self.run_next():
                    self._wake.wait(.4); self._wake.clear()
        finally:
            lock.close()  # OS releases the exclusive lease, including after process termination.

    def stop(self):
        self._stop.set(); self._wake.set()
        if self._thread:
            self._thread.join(timeout=3)

    def export(self):
        with self.db() as c:
            c.execute('BEGIN')  # All tables describe one consistent committed point in time.
            result = {table: [dict(row) for row in c.execute('SELECT * FROM '+table)] for table in ('settings','roots','files','versions','file_versions','positions','imports','bindings','jobs','workflow_items','workflow_revisions','generated_samples','workflow_migrations')}
        return {'schema': 'source_catalog_export_v2', 'exported_at': now(), **result}
