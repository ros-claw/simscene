"""Official SimReady Central metadata filters, distinct from legacy USD search.

No optional Python>=3.11 SDK or language-model parser is imported. Queries are
literal filename filters; per-owner packaging/license admission remains separate.
"""
import hashlib
import json
import math
import re
import time
from urllib.parse import urlencode, urlsplit
from pathlib import PurePosixPath
from .base import Provider, ProviderPage
from ..models import AssetRecord, AssetRef, stable_hash
from ..network import MetadataError, fetch_metadata


class SimReadyCentralProvider(Provider):
    source_id = 'simready-central'

    def __init__(self, store, source=None, *, base_url='https://nvidia-simready-central.hf.space', max_metadata_bytes=1024*1024):
        self.store=store;self.source=source;self.base_url=base_url.rstrip('/');self.max_metadata_bytes=max_metadata_bytes
        self.configure(time.monotonic()+12,[])

    @property
    def snapshot(self):
        return 'remote_unversioned:'+stable_hash(self.base_url)

    def search(self, request):
        self.check_deadline()
        if request.category or request.size_range_m or request.required_capabilities:
            raise MetadataError('Central literal filename adapter cannot establish category/size/capability predicates',code='unsupported_filter')
        if request.formats and any(value not in ('usd','usda','usdc') for value in request.formats):
            raise MetadataError('Central adapter currently indexes selected USD metadata only',code='unsupported_filter')
        # The public endpoint supports ordinary filename wildcards. Do not pass
        # prose to description or silently invoke /llm_parse or text embeddings.
        phrase=request.query.strip()
        if len(phrase)>128 or any(c in phrase for c in '\n\r;,' ):
            raise MetadataError('use one bounded literal filename phrase',code='unsupported_query')
        params={'file_name':'*'+phrase+'*','file_extension_include':'usd*','limit':min(20,request.limit),
                'return_metadata':'true','return_images':'false'}
        start=len(self.ledger)
        payload=fetch_metadata(self.base_url+'/search?'+urlencode(params),deadline=self.deadline,
                               max_bytes=self.max_metadata_bytes,ledger=self.ledger)
        try:
            hits=json.loads(payload)
            if not isinstance(hits,list) or len(hits)>params['limit']:raise ValueError('bounded array required')
            records=tuple(self._record(hit) for hit in hits)
        except (ValueError,KeyError,TypeError):
            raise MetadataError('Central metadata schema changed; response is not an empty successful search',code='metadata_schema_changed') from None
        for record in records:self.store.remember(record)
        return ProviderPage(records,self.snapshot,sum(item.get('bytes',0) for item in self.ledger[start:]),
            ('literal_filename_filter_only','owner_license_and_package_closure_not_verified','remote_index_generation_unknown'))

    def _record(self, hit):
        if not isinstance(hit,dict) or not isinstance(hit.get('url'),str):raise ValueError('Central result locator required')
        url=hit['url'];parsed=urlsplit(url)
        if parsed.scheme!='https' or parsed.hostname!='huggingface.co' or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Central locator requires explicit pinned HF dataset URL')
        match=re.fullmatch(r'/datasets/([\w.-]+/[\w.-]+)/(?:blob|resolve)/([0-9a-f]{40})/(.+)',parsed.path)
        if not match:raise ValueError('Central locator has no immutable revision')
        repo,revision,path=match.groups()
        if '%' in path or '\\' in path or '..' in path.split('/') or PurePosixPath(path).suffix not in ('.usd','.usda','.usdc'):
            raise ValueError('unsafe Central selected path')
        metadata=hit.get('metadata') or {}
        if not isinstance(metadata,dict):raise ValueError('Central metadata must be an object')
        size=metadata.get('size')
        if type(size) not in (int,float) or not math.isfinite(size) or not size>0 or size!=int(size):size=None
        else:size=int(size)
        identity=hashlib.sha256((repo+'/'+path).encode()).hexdigest()
        return AssetRecord(ref=AssetRef(self.source_id,identity,revision),title=PurePosixPath(path).stem,
            format='usd',entry_path=path,license={'status':'unknown','license':None,'basis':'Central does not grant owner content licenses'},
            physics=None,capabilities={},evidence_level='declared',
            availability={'status':'package_admission_required','estimated_download_bytes':size,'files_complete':None,
                'granularity':'dependency_closure','acquisition':None,'reason':'owner_license_packaging_and_source_hash_not_yet_verified'},
            provenance={'url':url,'repository':repo,'selected_revision':revision,'metadata_service':self.base_url,
                'service_metadata':metadata,'license_scope':'per owner/package; Central index membership is not a license grant'})

    def resolve(self, ref):
        if ref.source_id!=self.source_id:raise ValueError('wrong Central source')
        ref.validate_selection(huggingface=True);return self.store.get(ref)
