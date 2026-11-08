"""NVIDIA USD Search adapter: reuses the legacy query builder, metadata only."""
import base64
import json
import os
import math
import time
from urllib.parse import urlsplit
from ...assets import USDSearch
from .base import Provider, ProviderPage
from ..models import AssetRecord, AssetRef, stable_hash
from ..network import MetadataError, fetch_metadata


class _MetadataSearch(USDSearch):
    def __init__(self, provider, base_url=None):
        super().__init__(base_url=base_url)
        self.provider = provider

    def request(self, path, params=None, body=None, binary=False, output=None, max_bytes=None):
        if path != '/search_hybrid' or params or binary or output is not None:
            raise MetadataError('catalog NVIDIA adapter permits only metadata search')
        headers = {}
        user, password = os.getenv('USD_SEARCH_API_USERNAME'), os.getenv('USD_SEARCH_API_PASSWORD')
        token = os.getenv('USD_SEARCH_API_TOKEN')
        if user and password:
            headers['Authorization'] = 'Basic ' + base64.b64encode((user + ':' + password).encode()).decode()
        elif token and token != 'x':
            headers['Authorization'] = 'Bearer ' + token
        payload = fetch_metadata(self.base_url + path, body=body, headers=headers,
                                 deadline=self.provider.deadline,
                                 max_bytes=self.provider.max_metadata_bytes,
                                 ledger=self.provider.ledger)
        try:
            return json.loads(payload)
        except (ValueError, TypeError):
            raise MetadataError('NVIDIA search returned invalid metadata JSON') from None


def _without_inline_images(value):
    """Do not persist inline image payloads even if a service ignores the flag."""
    preview_bytes = 0
    def clean(item, key=''):
        nonlocal preview_bytes
        if isinstance(item, dict):
            return {k: clean(v, k) for k, v in item.items()}
        if isinstance(item, list):
            return [clean(v, key) for v in item]
        if isinstance(item, str) and (item.startswith('data:image/') or
                                     ('image' in key.lower() and len(item) > 1024)):
            preview_bytes += len(item.encode('utf-8'))
            return None
        return item
    return clean(value), preview_bytes


class NvidiaProvider(Provider):
    source_id = 'nvidia-usd-search'

    def __init__(self, store, source=None, *, base_url=None, max_metadata_bytes=4 * 1024 * 1024, candidate_limit=100):
        self.store = store
        self.source = source
        if type(candidate_limit) is not int or not 1 <= candidate_limit <= 100:
            raise ValueError('NVIDIA candidate_limit must be 1..100')
        self.candidate_limit = candidate_limit
        self.max_metadata_bytes = max_metadata_bytes
        self.configure(time.monotonic() + 12, [])
        self.client = _MetadataSearch(self, base_url)

    @property
    def snapshot(self):
        # The service exposes no reliable remote index generation. A local query
        # freezes its own candidate buffer; it does not freeze the remote index.
        return 'remote_unversioned:' + stable_hash(self.client.base_url)

    def search(self, request):
        self.check_deadline()
        start = len(self.ledger)
        result = self.client.search(request.query, limit=self.candidate_limit, return_images=False)
        if not isinstance(result, dict) or not isinstance(result.get('hits'), list):
            raise MetadataError('NVIDIA search metadata schema changed')
        if len(result['hits']) > 100:
            raise MetadataError('NVIDIA search returned too many candidates')
        result, previews = _without_inline_images(result)
        records = []
        for hit in result['hits']:
            self.check_deadline()
            records.append(self._record(hit))
        if previews and len(self.ledger) > start:
            self.ledger[-1]['embedded_preview_bytes'] = previews
        return ProviderPage(tuple(records), self.snapshot,
                            sum(e['bytes'] for e in self.ledger[start:]),
                            ('inline_preview_received',) if previews else ())

    def _record(self, hit):
        if not isinstance(hit, dict) or not isinstance(hit.get('source'), dict):
            raise MetadataError('NVIDIA hit has no asset source')
        source = hit['source']
        url = source.get('asset_url')
        if not url:
            base, extension = source.get('base_key'), source.get('ext')
            if isinstance(base, str) and isinstance(extension, str) and extension:
                url = base if base.lower().endswith('.' + extension.lower()) else base + ('' if base.endswith('.') else '.') + extension
        if not isinstance(url, str) or not url:
            raise MetadataError('NVIDIA hit has no asset URL')
        parsed = urlsplit(url)
        # Omit signed/credential URLs from persistent results. They cannot be a
        # stable asset identity and should be resolved by the upstream service.
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise MetadataError('NVIDIA hit contains an unsafe asset locator')
        metadata = hit.get('metadata') or {}
        if not isinstance(metadata, dict):
            raise MetadataError('NVIDIA metadata must be an object')
        title = source.get('name') or source.get('title') or metadata.get('title') or parsed.path.rsplit('/', 1)[-1] or url
        if not isinstance(title, str):
            raise MetadataError('invalid NVIDIA title')
        # The bounded live response exposes already-scaled bbox dimensions in
        # metres. Keep this as upstream declaration, never local inspection.
        blob = source.get('usd_dimensions') or {}
        dimensions = [blob.get('scaled_bbox_dimension_' + axis) for axis in 'xyz'] if isinstance(blob, dict) else []
        if not (len(dimensions) == 3 and all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in dimensions)):
            dimensions = None
        revision = 'metadata-sha256:' + stable_hash({'url': url, 'etag': source.get('etag'),
                     'size': source.get('size'), 'modified_timestamp': source.get('modified_timestamp')})
        category = metadata.get('category') if isinstance(metadata.get('category'), str) else None
        tags = []
        semantic = source.get('plugin_rendering_to_vision_metadata_metadata_vlm_generated', [])
        if isinstance(semantic, list):
            for fact in semantic:
                if not isinstance(fact, dict) or not isinstance(fact.get('value_text'), list):
                    continue
                values = [v for v in fact['value_text'] if isinstance(v, str)]
                if fact.get('name') == 'caption' and values:
                    title = values[0]
                elif fact.get('name') == 'object_type' and values:
                    category = values[0]
                elif fact.get('name') in {'tags', 'queries', 'materials'}:
                    tags.extend(values)
        preview = {'image_key': hit['thumbnail_image_key'], 'downloaded': False} if isinstance(hit.get('thumbnail_image_key'), str) else None
        return AssetRecord(
            AssetRef(self.source_id, url, revision), title, category=category, tags=tuple(dict.fromkeys(tags)),
            format=str(source.get('ext', parsed.path.rsplit('.', 1)[-1])).lower(),
            entry_path=url, preview=preview, license={'status': 'unknown', 'license': None},
            dimensions_m=dimensions, physics=None,
            availability={'status': 'search_indexed', 'granularity': 'dependency_closure', 'asset_url': url,
                          'acquisition': {'kind': 'usd_dependency_closure', 'asset_url': url},
                          'estimated_download_bytes': None, 'minimum_download_bytes': source.get('size'),
                          'content_identity': 'not_established'},
            provenance={'search_service': self.source_id, 'upstream_asset_id': url, 'asset_url': url,
                        'source_location': url,
                        'upstream_library': source.get('source') or source.get('library'),
                        'metadata_snapshot': revision, 'dimensions_evidence': 'declared',
                        'original_source': source, 'original_metadata': metadata},
            evidence_level='declared', capabilities={})

    def resolve(self, ref):
        if ref.source_id != self.source_id:
            raise ValueError('wrong source for NVIDIA adapter')
        return self.store.get(ref)


NVIDIAProvider = NvidiaProvider
