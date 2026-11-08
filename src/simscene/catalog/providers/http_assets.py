"""Selected-resolution HTTP material/HDRI metadata, with explicit file roles.

These projectors consume official API responses. They make no network requests
and never turn a material into a geometry/physics capability.
"""
import hashlib
import json
from pathlib import PurePosixPath
import re
from urllib.parse import urlsplit

from ..models import AssetRecord, AssetRef
from .base import Provider
from .hf_manifest import declared_license


def _file(item, role, color_space, allowed_host):
    if not isinstance(item, dict):
        raise ValueError('selected HTTP file metadata required')
    url = item.get('url'); parsed = urlsplit(url or '')
    if (parsed.scheme != 'https' or parsed.hostname != allowed_host or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('selected HTTP asset URL is outside its official origin')
    name = PurePosixPath(parsed.path).name
    if not name or '%' in name or '\\' in name or name in ('.', '..'):
        raise ValueError('unsafe selected HTTP asset filename')
    size = item.get('size'); md5 = item.get('md5')
    if type(size) is not int or size <= 0 or not isinstance(md5, str) or not re.fullmatch('[0-9a-f]{32}', md5):
        raise ValueError('selected HTTP file requires declared size and MD5')
    return {'path': name, 'url': url, 'size': size, 'md5': md5,
            'role': role, 'color_space': color_space}


def polyhaven_record(asset_id, info, files, *, kind, resolution='1k', file_format=None):
    """Freeze one official asset's selected PBR maps or single HDRI only.

    The revision hashes the complete supplied metadata, while variant_id makes
    requested resolution/encoding explicit. MD5 is upstream evidence; acquisition
    must additionally record SHA256 of actual downloaded bytes.
    """
    if not isinstance(asset_id, str) or not re.fullmatch('[a-z0-9_]+', asset_id):
        raise ValueError('invalid Poly Haven asset ID')
    if resolution not in ('1k', '2k', '4k', '8k'):
        raise ValueError('explicit supported resolution required')
    if not isinstance(info, dict) or not isinstance(files, dict) or kind not in ('hdri', 'material'):
        raise ValueError('official Poly Haven metadata and explicit asset kind required')
    if info.get('type') != (0 if kind == 'hdri' else 1):
        raise ValueError('requested asset kind differs from official metadata')
    encoding = file_format or ('exr' if kind == 'hdri' else 'jpg')
    if encoding not in (('exr', 'hdr') if kind == 'hdri' else ('jpg', 'png', 'exr')):
        raise ValueError('unsupported selected asset encoding')
    roles = [('hdri', 'environment', 'linear')] if kind == 'hdri' else [
        ('Diffuse', 'base_color', 'sRGB'), ('Rough', 'roughness', 'raw'),
        ('nor_gl', 'normal_opengl', 'raw'), ('Metal', 'metallic', 'raw')]
    selected = []
    try:
        for key, role, color in roles:
            selected.append(_file(files[key][resolution][encoding], role, color, 'dl.polyhaven.org'))
    except KeyError:
        raise ValueError('selected resolution/encoding/PBR map is unavailable') from None
    if len({item['path'] for item in selected}) != len(selected):
        raise ValueError('duplicate selected HTTP asset member')
    revision = hashlib.sha256(json.dumps({'info': info, 'files': files}, sort_keys=True,
                             separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    descriptor = {'kind': 'http_files', 'source': 'polyhaven', 'files': selected,
                  'files_complete': True, 'resolution': resolution,
                  'format': encoding, 'asset_type': kind}
    tags = info.get('tags', [])
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise ValueError('invalid official HTTP asset tags')
    return AssetRecord(ref=AssetRef('polyhaven', asset_id, revision, resolution+'-'+encoding),
        title=info.get('name') or asset_id, category=kind, tags=tuple(tags), format=encoding,
        entry_path=selected[0]['path'], license=declared_license('cc0-1.0', basis='official_polyhaven_license'),
        dimensions_m=None, physics=None, capabilities={}, evidence_level='declared',
        preview={'url': info['thumbnail_url'], 'downloaded': False} if info.get('thumbnail_url') else None,
        availability={'status': 'declared', 'estimated_download_bytes': sum(item['size'] for item in selected),
                      'granularity': 'selected_resolution_files', 'files_complete': True, 'acquisition': descriptor},
        provenance={'url': 'https://polyhaven.com/a/'+asset_id, 'metadata_api': 'https://api.polyhaven.com',
                    'credit': 'Poly Haven', 'license_url': 'https://polyhaven.com/license',
                    'metadata_sha256': revision, 'source_file_hash': info.get('files_hash'),
                    'authors': info.get('authors', {}), 'asset_type': kind,
                    'normal_convention': 'OpenGL' if kind == 'material' else None})


class PolyHavenProvider(Provider):
    """Bounded explicitly configured IDs; metadata-only official API refresh.

    metadata_entries paths are ``hdris/<slug>`` or ``textures/<slug>``. A bounded
    curated list avoids fetching an entire remote catalog or semantic searches.
    """
    def __init__(self, store, source, *, base_url='https://api.polyhaven.com', max_metadata_bytes=1024*1024):
        import time
        self.store=store;self.source=source;self.source_id=source.source_id
        if self.source_id!='polyhaven':raise ValueError('Poly Haven provider requires explicit source ID')
        if not 1<=len(source.metadata_entries)<=32:raise ValueError('bounded selected Poly Haven IDs required')
        self.base_url=base_url.rstrip('/');self.max_metadata_bytes=max_metadata_bytes
        self.configure(time.monotonic()+12, [])

    def configure(self, deadline, ledger):
        self.deadline=deadline;self.ledger=ledger;return self

    def check_deadline(self):
        Provider.check_deadline(self)

    @property
    def snapshot(self):
        return self.store.snapshot(self.source_id) or 'index_not_refreshed'

    def refresh(self):
        from ..network import fetch_metadata, MetadataError
        records=[];hashes=[];total=0
        for entry in self.source.metadata_entries:
            self.check_deadline()
            match=re.fullmatch('(hdris|textures)/([a-z0-9_]+)',entry.path)
            if not match:raise MetadataError('invalid selected Poly Haven metadata entry')
            category,identity=match.groups();responses=[]
            for endpoint in ('info','files'):
                remaining=self.max_metadata_bytes-total
                if remaining<=0:raise MetadataError('Poly Haven metadata budget exceeded')
                payload=fetch_metadata(self.base_url+'/'+endpoint+'/'+identity,deadline=self.deadline,
                    max_bytes=remaining,ledger=self.ledger,headers={'User-Agent':'SimScene catalog adapter/0.2 (Poly Haven)'})
                total+=len(payload);hashes.append(hashlib.sha256(payload).hexdigest())
                try:responses.append(json.loads(payload))
                except ValueError:raise MetadataError('Poly Haven metadata JSON changed') from None
            try:records.append(polyhaven_record(identity,*responses,kind='hdri' if category=='hdris' else 'material'))
            except ValueError as error:raise MetadataError(str(error)) from None
        snapshot=hashlib.sha256(''.join(hashes).encode()).hexdigest()
        self.store.replace_index(self.source_id,records,snapshot)
        return {'source_id':self.source_id,'snapshot':snapshot,'records':len(records),'metadata_bytes':total,'model_bytes':0}

    def search(self, request):
        from .base import ProviderPage
        start=len(self.ledger);self.check_deadline()
        if self.snapshot=='index_not_refreshed':self.refresh()
        return ProviderPage(tuple(self.store.search(self.source_id,request.query,limit=100)),self.snapshot,
            sum(item.get('bytes',0) for item in self.ledger[start:]),('selected_metadata_list_only',))

    def resolve(self, ref):
        if ref.source_id!=self.source_id:raise ValueError('wrong source for Poly Haven provider')
        return self.store.get(ref)
