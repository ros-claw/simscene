"""Small SQLite metadata index plus immutable detail/query snapshot documents."""
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from .models import AssetRecord, AssetRef, canonical_json, stable_hash


class CatalogStore:
    def __init__(self, directory):
        self.directory = Path(directory).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.database = self.directory / 'catalog.sqlite3'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS records (key TEXT PRIMARY KEY, source TEXT NOT NULL, asset_id TEXT NOT NULL, revision TEXT NOT NULL, payload TEXT NOT NULL, text TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS record_source ON records(source,revision)')
            db.execute('CREATE TABLE IF NOT EXISTS indexes (source TEXT PRIMARY KEY, snapshot TEXT NOT NULL)')
            try:
                db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS record_fts USING fts5(key UNINDEXED, source UNINDEXED, text)')
                self.fts = True
            except sqlite3.OperationalError:
                self.fts = False

    def connect(self):
        return sqlite3.connect(self.database, timeout=5)

    def write_document(self, kind, identity, data):
        if kind not in {'details', 'snapshots'} or not re.fullmatch('[0-9a-f]{64}', identity):
            raise ValueError('invalid catalog document identity')
        parent = self.directory / kind
        parent.mkdir(exist_ok=True)
        path = parent / (identity + '.json')
        payload = canonical_json(data, exclude_volatile=False)
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=parent, delete=False) as stream:
            temporary = stream.name
            try:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return str(path)

    def read_document(self, kind, identity):
        if kind not in {'details', 'snapshots'} or not re.fullmatch('[0-9a-f]{64}', identity):
            raise ValueError('invalid catalog document identity')
        path = self.directory / kind / (identity + '.json')
        # All snapshot documents are bounded by candidate count at creation.
        if path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError('catalog document too large')
        return json.loads(path.read_text())

    def put_detail(self, record):
        identity = stable_hash(record)
        return self.write_document('details', identity, record.to_dict())

    def remember(self, record):
        key = stable_hash(record.ref)
        text = ' '.join([record.title, record.category or '', *record.tags])
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO records VALUES (?,?,?,?,?,?)',
                       (key, record.ref.source_id, record.ref.asset_id, record.ref.revision,
                        canonical_json(record, exclude_volatile=False), text))
        return self.put_detail(record)

    def get(self, ref):
        key = stable_hash(ref)
        with self.connect() as db:
            row = db.execute('SELECT payload FROM records WHERE key=?', (key,)).fetchone()
        if row is None:
            raise KeyError('asset is absent from this pinned metadata index')
        return AssetRecord.from_dict(json.loads(row[0]))

    def snapshot(self, source_id):
        with self.connect() as db:
            row = db.execute('SELECT snapshot FROM indexes WHERE source=?', (source_id,)).fetchone()
        return row[0] if row else None

    def replace_index(self, source_id, records, snapshot):
        # Parse/validate outside the transaction; a broken index cannot erase a good one.
        prepared = []
        for record in records:
            if record.ref.source_id != source_id:
                raise ValueError('index contains an asset from another source')
            key = stable_hash(record.ref)
            text = ' '.join([record.title, record.category or '', *record.tags])
            prepared.append((key, source_id, record.ref.asset_id, record.ref.revision,
                             canonical_json(record, exclude_volatile=False), text))
        if len({r[0] for r in prepared}) != len(prepared):
            raise ValueError('duplicate asset reference in index')
        with self.connect() as db:
            db.execute('DELETE FROM records WHERE source=?', (source_id,))
            db.executemany('INSERT INTO records VALUES (?,?,?,?,?,?)', prepared)
            if self.fts:
                db.execute('DELETE FROM record_fts WHERE source=?', (source_id,))
                db.executemany('INSERT INTO record_fts VALUES (?,?,?)', [(r[0], r[1], r[5]) for r in prepared])
            db.execute('INSERT OR REPLACE INTO indexes VALUES (?,?)', (source_id, snapshot))

    def search(self, source_id, query, *, limit=100):
        tokens = re.findall(r'[^\W_]+', query, re.UNICODE)[:16]
        if not tokens:
            return ()
        with self.connect() as db:
            if self.fts:
                match = ' OR '.join('"' + t.replace('"', '""') + '"' for t in tokens)
                rows = db.execute('SELECT r.payload FROM record_fts f JOIN records r ON r.key=f.key WHERE record_fts MATCH ? AND r.source=? ORDER BY rank, r.asset_id LIMIT ?',
                                  (match, source_id, limit)).fetchall()
            else:
                clauses = ' OR '.join('LOWER(text) LIKE ? ESCAPE \'\\\'' for _ in tokens)
                terms = ['%' + t.lower().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%' for t in tokens]
                rows = db.execute(f'SELECT payload FROM records WHERE source=? AND ({clauses}) ORDER BY asset_id LIMIT ?',
                                  (source_id, *terms, limit)).fetchall()
        return tuple(AssetRecord.from_dict(json.loads(row[0])) for row in rows)
