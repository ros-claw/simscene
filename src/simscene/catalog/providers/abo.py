"""Pinned codepawl/abo-glb JSONL adapter; never fetches model payloads."""
import hashlib
import json
import re
import time
from urllib.parse import quote
from .base import Provider, ProviderPage
from ..models import AssetRecord, AssetRef
from ..network import MetadataError, fetch_metadata
from ..registry import load_registry


class ABOProvider(Provider):
    source_id = 'abo-glb'

    def __init__(self, store, source=None, *, base_url='https://huggingface.co', max_index_bytes=32 * 1024 * 1024):
        self.store = store
        self.source = source or load_registry().get(self.source_id)
        self.entry = self.source.metadata_entries[0]
        if self.entry.path != 'metadata.jsonl' or self.entry.format != 'jsonl':
            raise ValueError('ABO requires the declared metadata.jsonl entry')
        if not re.fullmatch('[0-9a-fA-F]{40}', self.entry.revision or ''):
            raise ValueError('ABO metadata index must be pinned to a full commit SHA')
        self.base_url = base_url.rstrip('/')
        self.max_index_bytes = max_index_bytes
        self.configure(time.monotonic() + 12, [])

    @property
    def snapshot(self):
        snapshot = self.store.snapshot(self.source_id)
        return snapshot if snapshot and snapshot.startswith(self.entry.revision + ':') else 'index_not_refreshed'

    @property
    def metadata_url(self):
        return (self.base_url + '/datasets/' + self.source.repository + '/resolve/' +
                self.entry.revision + '/' + self.entry.path)

    def refresh(self):
        """Bounded pinned metadata transfer; also used lazily on first search.

        The caller's existing absolute deadline and ledger remain in force.
        Model files remain untouched.
        """
        self.check_deadline()
        payload = fetch_metadata(self.metadata_url, deadline=self.deadline,
                                 max_bytes=self.max_index_bytes, ledger=self.ledger)
        records = []
        for number, line in enumerate(payload.splitlines(), 1):
            self.check_deadline()
            if not line.strip():
                continue
            if len(line) > 128 * 1024 or number > 100000:
                raise MetadataError('ABO metadata exceeds bounded row schema')
            try:
                row = json.loads(line)
                records.append(self._record(row))
            except (ValueError, TypeError, KeyError) as error:
                raise MetadataError(f'ABO metadata schema changed at row {number}') from None
        if not records:
            raise MetadataError('ABO metadata index is empty')
        identity = self.entry.revision + ':' + hashlib.sha256(payload).hexdigest()
        self.store.replace_index(self.source_id, records, identity)
        return {'source_id': self.source_id, 'snapshot': identity, 'records': len(records),
                'metadata_bytes': len(payload), 'model_bytes': 0,
                'text_index': 'fts5' if self.store.fts else 'bounded_text_fallback'}

    def _record(self, row):
        required = {'id', 'file', 'name', 'product_type', 'size_metres', 'pack_bytes'}
        if not isinstance(row, dict) or not required <= set(row):
            raise ValueError('missing required ABO fields')
        identity, path = row['id'], row['file']
        if not isinstance(identity, str) or not identity or not isinstance(path, str):
            raise ValueError('invalid asset identity')
        if not re.fullmatch(r'[A-Za-z0-9_-]+', identity):
            raise ValueError('invalid upstream asset ID')
        if path != f'objects/{identity}/{identity}.glb':
            raise ValueError('unexpected or unsafe ABO selected file path')
        size = row['pack_bytes']
        if size is not None and (type(size) is not int or size < 1):
            raise ValueError('invalid declared model bytes')
        for key in ('name', 'product_type'):
            if row[key] is not None and not isinstance(row[key], str):
                raise ValueError('invalid ABO text field')
        tags = tuple(str(row[k]) for k in ('brand', 'color', 'material', 'style')
                     if isinstance(row.get(k), str) and row[k])
        revision = self.entry.revision
        preview = self.base_url + '/datasets/' + self.source.repository + '/resolve/' + revision + '/thumbs/' + quote(identity) + '.webp'
        return AssetRecord(
            ref=AssetRef(self.source_id, identity, revision), title=row['name'] or identity,
            category=row['product_type'] or None, tags=tags, format='glb', entry_path=path,
            preview={'url': preview, 'downloaded': False},
            license={'status': 'known', 'license': 'CC-BY-4.0', 'evidence': 'declared',
                     'basis': 'dataset_card', 'notices_required': True},
            dimensions_m=row['size_metres'], physics=None,
            availability={'status': 'declared', 'estimated_download_bytes': size,
                          'granularity': 'single_file', 'files_complete': None,
                          'acquisition': {'kind': 'hf_single_glb', 'repository': self.source.repository,
                                          'revision': revision, 'path': path}},
            provenance={'repository': self.source.repository, 'upstream_asset_id': identity,
                        'upstream_source': 'amazon-berkeley-objects',
                        'relationship': 'community_conversion', 'license': 'CC-BY-4.0',
                        'metadata_revision': revision, 'dimensions_evidence': 'declared',
                        'coordinate_system': 'Y-up', 'original_metadata': row},
            evidence_level='declared', capabilities={})

    def search(self, request):
        self.check_deadline()
        start = len(self.ledger)
        if self.snapshot == 'index_not_refreshed':
            self.refresh()
        self.check_deadline()
        records = self.store.search(self.source_id, request.query, limit=100)
        self.check_deadline()
        metadata_bytes = sum(entry.get('bytes', 0) for entry in self.ledger[start:]
                             if entry.get('category') == 'metadata')
        return ProviderPage(records, self.snapshot, bytes_read=metadata_bytes,
                            warnings=(() if self.store.fts else ('fts5_unavailable',)))

    def resolve(self, ref):
        if ref.source_id != self.source_id:
            raise ValueError('wrong source for ABO adapter')
        ref.validate_selection(huggingface=True)
        return self.store.get(ref)
