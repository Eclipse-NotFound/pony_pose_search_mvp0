"""Transactional upgrades; the pre-upgrade SQLite backup is never overwritten."""
from pathlib import Path
import sqlite3

from multispecies.catalog import require
from multispecies.records import new_id


def upgrade(catalog):
    with catalog.db() as db:
        version = db.execute("SELECT value FROM settings WHERE key='schema'").fetchone()[0]
    require(version in {'1', '2'}, '素材目录版本不兼容')
    if version == '2':
        return
    backup = catalog.root/('schema-v1-before-v2-'+new_id('backup')+'.sqlite3')
    with sqlite3.connect(catalog.database.as_uri()+'?mode=ro', uri=True) as source:
        with sqlite3.connect(backup) as target:
            source.backup(target)
    with catalog.db() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT value FROM settings WHERE key='schema'").fetchone()[0] == '2':
            return
        db.execute('''CREATE TABLE workflow_items(id TEXT PRIMARY KEY,kind TEXT NOT NULL,
                      parent_ref TEXT,head_id TEXT)''')
        db.execute('''CREATE TABLE workflow_revisions(id TEXT PRIMARY KEY,
                      item_id TEXT NOT NULL REFERENCES workflow_items(id),previous_id TEXT,
                      payload TEXT NOT NULL,sha256 TEXT NOT NULL,created TEXT NOT NULL)''')
        db.execute('CREATE INDEX workflow_kind_parent ON workflow_items(kind,parent_ref)')
        db.execute('''CREATE TABLE generated_samples(region_revision TEXT PRIMARY KEY,
                      observation_id TEXT NOT NULL,import_id TEXT NOT NULL)''')
        db.execute('''CREATE TABLE workflow_migrations(source_key TEXT PRIMARY KEY,
                      source_sha256 TEXT NOT NULL,result TEXT NOT NULL)''')
        db.execute("UPDATE settings SET value='2' WHERE key='schema'")
        db.execute("INSERT OR REPLACE INTO settings VALUES('schema_v1_backup',?)", (str(backup),))


class RevisionStore:
    """Private persistence used by dataset operations; updates are compare-and-swap."""
    def __init__(self, sources):
        self.sources = sources

    def read(self, key, revision=None):
        import json
        from .store import safe_id
        from multispecies.catalog import fingerprint
        with self.sources.db() as db:
            row = db.execute('''SELECT r.* FROM workflow_items i JOIN workflow_revisions r
                ON r.item_id=i.id AND r.id=COALESCE(?,i.head_id) WHERE i.id=?''',
                (revision, safe_id(key))).fetchone()
        require(row is not None, '找不到工作记录或修订')
        result = json.loads(row['payload'])
        require(fingerprint(result) == row['sha256'], '工作记录内容已变化')
        return result

    def get(self, key):
        with self.sources.db() as db:
            found=db.execute('SELECT 1 FROM workflow_items WHERE id=?',(key,)).fetchone()
        return self.read(key) if found else None

    def list(self, kind, parent=None):
        import json
        from multispecies.catalog import fingerprint
        with self.sources.db() as db:
            rows=db.execute('SELECT r.payload,r.sha256 FROM workflow_items i JOIN workflow_revisions r ON r.id=i.head_id WHERE i.kind=? AND (? IS NULL OR i.parent_ref=?) ORDER BY i.id',(kind,parent,parent)).fetchall()
        result=[]
        for row in rows:
            item=json.loads(row['payload']);require(fingerprint(item)==row['sha256'],'工作记录内容已变化');result.append(item)
        return result

    def history(self, key):
        with self.sources.db() as db:
            ids = [r[0] for r in db.execute('SELECT id FROM workflow_revisions WHERE item_id=? ORDER BY created,id', (key,))]
        return [self.read(key, rid) for rid in ids]

    def save(self, kind, key, data, *, expected=None, parent=None, actor):
        from .store import dumps, safe_id
        from multispecies.catalog import fingerprint
        from multispecies.library import ConflictError
        from multispecies.records import now
        require(isinstance(actor, str) and actor.strip(), '需要操作人名称')
        safe_id(key)
        rid = new_id('rev')
        payload = {**data, 'id': key, 'revision': rid, 'previous_revision': expected,
                   'kind': kind, 'actor': actor.strip(), 'created_at': now()}
        digest = fingerprint(payload)
        with self.sources.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM workflow_items WHERE id=?', (key,)).fetchone()
            if (old['head_id'] if old else None) != expected:
                raise ConflictError('工作记录已有新版本，请刷新后再保存')
            require(not old or old['kind'] == kind and old['parent_ref'] == parent, '记录类型或所属对象不可改变')
            if not old:
                db.execute('INSERT INTO workflow_items VALUES(?,?,?,NULL)', (key, kind, parent))
            db.execute('INSERT INTO workflow_revisions VALUES(?,?,?,?,?,?)',
                       (rid, key, expected, dumps(payload), digest, payload['created_at']))
            db.execute('UPDATE workflow_items SET head_id=? WHERE id=?', (rid, key))
        return payload
