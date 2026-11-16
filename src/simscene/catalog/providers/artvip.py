"""Curated, pinned ArtVIP object-tree metadata without downloading asset payloads."""
import hashlib
import json
from pathlib import PurePosixPath
import re
import time
from urllib.parse import quote

from .base import Provider, ProviderPage
from .hf_manifest import declared_license, safe_path
from ..models import AssetRecord, AssetRef
from ..network import MetadataError, fetch_metadata

AUDITED_REVISION = 'd22f2095bc9db29fdd4b60f4a3c4f8177e1f5e9e'
CARD_SHA256 = '3193c5d74ef7f1d4777fe0ff77d3f9f2f4c436969ea1802726da177897003f63'


class ArtVIPProvider(Provider):
    """Index only explicitly registered object directories at one immutable revision."""

    def __init__(self, store, source, *, base_url='https://huggingface.co', max_index_bytes=4*1024**2):
        if source.repository != 'X-Humanoid/ArtVIP':
            raise ValueError('ArtVIP license projection requires its audited repository')
        entries = source.metadata_entries
        if not 1 <= len(entries) <= 100 or any(entry.format != 'json' for entry in entries):
            raise ValueError('ArtVIP requires bounded explicit object-tree entries')
        revisions = {entry.revision for entry in entries}
        if len(revisions) != 1 or not re.fullmatch('[0-9a-f]{40}', next(iter(revisions)) or ''):
            raise ValueError('ArtVIP object trees require one immutable revision')
        paths = [safe_path(entry.path) for entry in entries]
        if (len(set(paths)) != len(paths) or any(not 3 <= len(PurePosixPath(p).parts) <= 5
                                                  or PurePosixPath(p).parts[0] != 'Articulated_objects'
                                                  for p in paths)):
            raise ValueError('ArtVIP metadata entries must be distinct selected object directories')
        self.store = store
        self.source = source
        self.source_id = source.source_id
        self.entry = entries[0]
        self.paths = tuple(paths)
        self.base_url = base_url.rstrip('/')
        self.max_index_bytes = max_index_bytes
        selection = hashlib.sha256(json.dumps(paths, separators=(',', ':')).encode()).hexdigest()
        self.prefix = self.entry.revision + ':' + selection + ':'
        self.suffix = ':artvip-tree-v2'
        self.configure(time.monotonic()+12, [])

    @property
    def snapshot(self):
        value = self.store.snapshot(self.source_id)
        return value if value and value.startswith(self.prefix) and value.endswith(self.suffix) else 'index_not_refreshed'

    def _record(self, folder, item):
        if folder not in self.paths or not isinstance(item, dict) or item.get('type') != 'file':
            raise ValueError('unregistered ArtVIP object')
        path = safe_path(item.get('path'))
        if PurePosixPath(path).parent.as_posix() != folder or PurePosixPath(path).suffix.lower() not in {'.usd', '.usda', '.usdc'}:
            raise ValueError('invalid selected ArtVIP root')
        size = item.get('size')
        lfs = item.get('lfs')
        digest = lfs.get('oid') if isinstance(lfs, dict) else None
        if (type(size) is not int or size <= 0 or not isinstance(digest, str)
                or not re.fullmatch('[0-9a-f]{64}', digest)
                or lfs.get('size') != size):
            raise ValueError('ArtVIP root lacks a complete LFS content pin')
        parts = PurePosixPath(folder).parts
        category = parts[-2].replace('_', ' ')
        card_url = ('https://huggingface.co/datasets/X-Humanoid/ArtVIP/resolve/'
                    + self.entry.revision + '/README.md')
        if self.entry.revision == AUDITED_REVISION:
            license_info = declared_license('Apache-2.0', basis='pinned_ArtVIP_dataset_card')
            license_info.update(card_url=card_url, card_sha256=CARD_SHA256)
        else:
            license_info = declared_license(None, basis='unreviewed_ArtVIP_dataset_card_revision')
            license_info.update(card_url=card_url, card_sha256=None)
        return AssetRecord(
            ref=AssetRef(self.source_id, folder, self.entry.revision),
            title=parts[-1].replace('_', ' '), category=category,
            tags=tuple(part.replace('_', ' ') for part in parts[1:-1]),
            format='usd', entry_path=path,
            license=license_info,
            physics=None, capabilities={}, evidence_level='declared',
            availability={'status': 'declared', 'granularity': 'dependency_closure',
                'estimated_download_bytes': None, 'files_complete': False,
                'acquisition': {'kind': 'hf_usd_package', 'repository': self.source.repository,
                    'revision': self.entry.revision, 'path': path, 'package_path': folder,
                    'files': [{'path': path, 'size': size, 'sha256': digest}],
                    'files_complete': False, 'dependency_mode': 'inspect_selected_usd_closure'}},
            provenance={'repository': self.source.repository, 'metadata_revision': self.entry.revision,
                'selected_object_directory': folder, 'root_tree_entry': item,
                'license_scope': 'dataset-card declaration; per-object notice not independently established',
                'structure_and_runtime': 'unknown until selected USD is inspected and tested'})

    def refresh(self):
        records = []
        used = 0
        digest = hashlib.sha256()
        try:
            for folder in self.paths:
                self.check_deadline()
                url = (self.base_url + '/api/datasets/' + self.source.repository + '/tree/'
                       + self.entry.revision + '/' + quote(folder, safe='/')
                       + '?recursive=false&expand=true&limit=100')
                headers = {}
                raw = fetch_metadata(url, deadline=self.deadline, max_bytes=self.max_index_bytes-used,
                                     ledger=self.ledger, response_metadata=headers)
                used += len(raw)
                items = json.loads(raw)
                if headers.get('link') or not isinstance(items, list) or len(items) >= 100:
                    raise ValueError('incomplete or oversized ArtVIP object listing')
                roots = []
                for item in items:
                    if not isinstance(item, dict) or item.get('type') not in {'file', 'directory'}:
                        raise ValueError('invalid ArtVIP tree entry')
                    path = safe_path(item.get('path'))
                    if PurePosixPath(path).parent.as_posix() != folder:
                        raise ValueError('unexpected nested ArtVIP tree entry')
                    if item['type'] == 'file' and PurePosixPath(path).suffix.lower() in {'.usd', '.usda', '.usdc'}:
                        roots.append(item)
                if len(roots) != 1:
                    raise ValueError('ArtVIP object requires one unambiguous USD root')
                records.append(self._record(folder, roots[0]))
                digest.update(folder.encode() + b'\0' + raw + b'\0')
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise MetadataError('ArtVIP object metadata changed; previous index preserved') from None
        snapshot = self.prefix + digest.hexdigest() + self.suffix
        self.store.replace_index(self.source_id, records, snapshot)
        return {'source_id': self.source_id, 'snapshot': snapshot, 'records': len(records),
                'metadata_bytes': used, 'model_bytes': 0}

    def _reproject(self, record):
        provenance = record.provenance or {}
        result = self._record(provenance.get('selected_object_directory'), provenance.get('root_tree_entry'))
        if result.ref != record.ref:
            raise ValueError('ArtVIP index identity differs from selected metadata')
        return result

    def search(self, request):
        self.check_deadline()
        start = len(self.ledger)
        if self.snapshot == 'index_not_refreshed':
            self.refresh()
        records = self.store.search(self.source_id, request.query, limit=100, revision=self.entry.revision)
        self.check_deadline()
        count = sum(item.get('bytes', 0) for item in self.ledger[start:] if item.get('category') == 'metadata')
        return ProviderPage(tuple(self._reproject(record) for record in records), self.snapshot,
                            bytes_read=count, warnings=(() if self.store.fts else ('fts5_unavailable',)))

    def resolve(self, ref):
        if ref.source_id != self.source_id or ref.revision != self.entry.revision:
            raise ValueError('ArtVIP selection differs from configured source revision')
        ref.validate_selection(huggingface=True)
        record = self.store.get(ref, require_snapshot_prefix=self.prefix, require_snapshot_suffix=self.suffix)
        return self._reproject(record)
