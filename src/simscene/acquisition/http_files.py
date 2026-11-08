"""Bounded selected HTTP file acquisition, sharing verified cache/job snapshots."""
import hashlib
import json
from pathlib import Path
import re
import tempfile

from ..assets import SearchError
from ..cache import AssetCache
from ..catalog.models import AssetRef
from ..catalog.providers.http_assets import _file
from .locks import cache_lock, copy_acquired_to_job
from .transfer import TransferBudget, current_budget, transfer_scope

USER_AGENT = 'SimScene catalog adapter/0.2 (Poly Haven selected assets)'


def acquire_http_files(descriptor, ref, limits, config, source_record, license_info, provenance, job_directory=None):
    """Acquire only explicitly selected files; record SHA256 beyond upstream MD5.

    Current admission is narrowly scoped to official Poly Haven files. Materials
    and HDRIs remain files for lighting/shading APIs, never USD rigid assets.
    """
    if not isinstance(descriptor, dict) or descriptor.get('kind') != 'http_files' or descriptor.get('source') != 'polyhaven':
        raise ValueError('supported selected HTTP descriptor required')
    ref = AssetRef.from_dict(ref) if isinstance(ref, dict) else ref
    if ref.source_id != 'polyhaven' or not re.fullmatch('[a-z0-9_]+',ref.asset_id) or not re.fullmatch('[0-9a-f]{64}', ref.revision):
        raise ValueError('selected HTTP reference requires frozen metadata SHA256')
    if isinstance(source_record,dict) and source_record.get('ref') is not None and AssetRef.from_dict(source_record['ref'])!=ref:
        raise ValueError('selected HTTP record/reference differs')
    if isinstance(provenance,dict) and provenance.get('metadata_sha256') not in (None,ref.revision):
        raise ValueError('selected HTTP metadata revision differs')
    entries = descriptor.get('files')
    if not isinstance(entries, list) or not 1 <= len(entries) <= 16:
        raise ValueError('bounded selected HTTP file list required')
    files = [_file(item, item.get('role'), item.get('color_space'), 'dl.polyhaven.org') for item in entries]
    if any(item.get('path') != checked['path'] for item, checked in zip(entries, files)) or len({f['path'] for f in files}) != len(files):
        raise ValueError('selected HTTP member paths differ or collide')
    for key in ('download_bytes', 'unpacked_bytes', 'staging_bytes'):
        if type(limits.get(key)) is not int or limits[key] <= 0:
            raise ValueError('positive selected HTTP budgets required')
    capacity = config['asset_cache_capacity_bytes']; directory = Path(config['asset_cache_directory'])
    cache = AssetCache(None, directory, capacity)
    budget = current_budget() or TransferBudget(limits['download_bytes'], limits['unpacked_bytes'], limits['staging_bytes'])
    limit = min(capacity, limits['unpacked_bytes'], limits['staging_bytes'], budget.package_limit(capacity))
    if sum(item['size'] for item in files) > limit:
        raise SearchError('selected HTTP package exceeds staging/unpacked limit')
    identity = hashlib.sha256(json.dumps({'descriptor': descriptor, 'ref': ref.to_dict(), 'license': license_info,
        'provenance': provenance}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    index = directory/('.http-source-'+identity)
    source = 'https://polyhaven.com/a/'+ref.asset_id
    try:
        with cache_lock(directory), transfer_scope(budget):
            old = json.loads(index.read_text()) if index.is_file() else None
            if old is not None and (not isinstance(old,dict) or any(not re.fullmatch('[0-9a-f]{64}',str(old.get(key,''))) for key in ('package_sha256','content_sha256'))):
                raise SearchError('invalid selected HTTP cache identity')
            if old and (directory/old['package_sha256']).is_dir():
                result = cache._verified_cached(directory/old['package_sha256'], old['package_sha256'], source)
            else:
                with tempfile.TemporaryDirectory(dir=directory, prefix='.http-input-') as temporary:
                    output = Path(temporary)/'contents'; output.mkdir(); actual=[]
                    for item in files:
                        target = output/item['path']
                        size, digest = budget.download(item['url'], target, max_bytes=item['size'],
                            headers={'User-Agent': USER_AGENT}, same_origin='dl.polyhaven.org')
                        if size != item['size'] or hashlib.md5(target.read_bytes()).hexdigest() != item['md5']:
                            raise SearchError('verification_failed: selected HTTP size/MD5 mismatch')
                        actual.append(dict(item, size=size, sha256=digest))
                    fingerprint = hashlib.sha256(json.dumps(actual,sort_keys=True,separators=(',', ':')).encode()).hexdigest()
                    if old and old['content_sha256'] != fingerprint:
                        raise SearchError('immutable selected HTTP content changed after cache eviction')
                    key = hashlib.sha256((identity+fingerprint).encode()).hexdigest(); package=directory/key
                    result = {'source': source, 'package_sha256': key, 'root': str(package/files[0]['path']),
                        'files': actual, 'dependency_status': 'resolved_locally', 'unresolved_dependencies': [],
                        'source_ref': ref.to_dict(), 'license': license_info, 'provenance': provenance, 'metadata': source_record,
                        'asset_type': descriptor.get('asset_type'), 'resolution': descriptor.get('resolution')}
                    encoded=json.dumps(result,indent=2)
                    size=sum(item['size'] for item in actual)+len(encoded.encode())
                    if size>limit:raise SearchError('selected HTTP manifest exceeds staging/unpacked budget')
                    (output/'simscene-lock.json').write_text(encoded)
                    if package.exists():result=cache._verified_cached(package,key,source)
                    else:cache._evict(size);output.rename(package)
                    cache._write_index(index,json.dumps({'package_sha256':key,'content_sha256':fingerprint}))
                    cache._write_provenance(result)
            if sum(item['size'] for item in result['files'])+(directory/result['package_sha256']/'simscene-lock.json').stat().st_size>limit:
                raise SearchError('cached selected HTTP package exceeds staging/unpacked budget')
            manifest=hashlib.sha256(json.dumps(result['files'],sort_keys=True,separators=(',', ':'),ensure_ascii=False).encode()).hexdigest()
            result=dict(result,actual_download_bytes=budget.actual_download_bytes,transfer_ledger=budget.ledger,
                manifest_sha256=manifest,source_manifest_hash=manifest,asset_handle='acquired:sha256:'+result['package_sha256'])
        if job_directory is not None:
            result=copy_acquired_to_job(result,directory,Path(job_directory)/'source',staging_budget_bytes=limits['staging_bytes'])
        return result
    except Exception as error:
        error.actual_download_bytes=budget.actual_download_bytes;error.transfer_ledger=budget.ledger
        raise
