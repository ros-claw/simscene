"""Frozen native HF package acquisition using the existing USD repair/cache path."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile

from ..assets import SearchError
from ..cache import AssetCache
from ..huggingface_cache import acquire as acquire_usd, _parts, _url
from ..catalog.models import AssetRef
from .glb import _path
from .locks import cache_lock, copy_acquired_to_job
from .transfer import TransferBudget, current_budget, transfer_scope


def _manifest(files):
    return hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def _declared(descriptor):
    entries=descriptor.get('files')
    if not isinstance(entries,list) or not 1<=len(entries)<=4096:raise ValueError('native package requires bounded declared files')
    files={};folder=_path(descriptor['package_path'])
    for item in entries:
        path=_path(item['path']);size=item.get('size',item.get('size_bytes'));digest=item.get('sha256')
        if path in files or not path.is_relative_to(folder) or (size is not None and (type(size) is not int or size<0)):
            raise ValueError('invalid native package declared file')
        if not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest):raise ValueError('native package files require full SHA256')
        files[path]={'path':path.as_posix(),'size':size,'sha256':digest}
    if PurePosixPath(descriptor['path']) not in files:raise ValueError('native package root must be declared')
    return files


def _verify_declared(acquired,declared):
    actual={item['path']:item for item in acquired['files']}
    for path,item in declared.items():
        known=actual.get(path.as_posix())
        if known is None or known['sha256']!=item['sha256'] or item['size'] is not None and known['size']!=item['size']:
            raise SearchError('verification_failed: declared native package member differs: '+path.as_posix())


def acquire_hf_package(descriptor,ref,limits,config,source_record,license_info,provenance,job_directory=None):
    """Acquire one selected USD and verified declared members, never a repository.

    Existing HF acquisition discovers/repairs relative USD/MDL dependencies at the
    selected immutable revision. Declared sizes/hashes remain mandatory for BOM
    members; unknown additional dependencies are accepted only after that bounded
    dependency resolver actually discovers and validates them.
    """
    if not isinstance(descriptor,dict) or descriptor.get('kind')!='hf_usd_package':raise ValueError('native HF package descriptor required')
    ref=AssetRef.from_dict(ref) if isinstance(ref,dict) else ref
    ref.validate_selection(huggingface=True)
    repo,revision,root_path=_parts(descriptor['repository'],descriptor['revision'],descriptor['path'])
    if ref.revision!=revision:raise ValueError('native selected revision differs from frozen reference')
    if isinstance(source_record,dict) and source_record.get('ref') is not None and AssetRef.from_dict(source_record['ref'])!=ref:raise ValueError('native record/reference differs')
    declared=_declared(descriptor)
    for name in ('download_bytes','unpacked_bytes','staging_bytes'):
        if type(limits.get(name)) is not int or limits[name]<=0:raise ValueError('positive native acquisition budgets required')
    capacity=config['asset_cache_capacity_bytes'];directory=Path(config['asset_cache_directory'])
    if type(capacity) is not int or capacity<=0:raise ValueError('positive source cache capacity required')
    transaction=current_budget() or TransferBudget(limits['download_bytes'],limits['unpacked_bytes'],limits['staging_bytes'])
    identity=hashlib.sha256(json.dumps({'descriptor':descriptor,'ref':ref.to_dict(),'license':license_info},sort_keys=True,separators=(',',':')).encode()).hexdigest()
    cache=AssetCache(None,directory,capacity);index=directory/('.native-source-'+identity)
    result=None
    try:
        with cache_lock(directory):
            if index.is_file():
                known=index.read_text().strip()
                if re.fullmatch('[0-9a-f]{64}',known) and (directory/known).is_dir():
                    result=cache._verified_cached(directory/known,known,_url(repo,revision,root_path))
                    _verify_declared(result,declared)
        with transfer_scope(transaction):
            if result is None:
                # The shared downloader's opt-in budget hook accounts every
                # failed prefix and dependency request in this transaction.
                result=acquire_usd(repo,revision,root_path.as_posix(),directory,max_bytes=capacity)
                if result.get('dependency_status') not in {'resolved_locally','resolved_with_runtime'}:
                    raise SearchError('dependency_missing: selected native USD repair did not resolve its closure')
                with cache_lock(directory):
                    original=directory/result['package_sha256'];cache._verified_cached(original,result['package_sha256'],result['source'])
                    with tempfile.TemporaryDirectory(dir=directory,prefix='.native-input-') as temporary:
                        output=Path(temporary)/'contents';output.mkdir();files=[]
                        package_limit=min(capacity,limits['unpacked_bytes'],limits['staging_bytes'])
                        for item in result['files']:
                            if sum(f['size'] for f in files)+item['size']>package_limit:
                                raise SearchError('budget_exceeded: native copied members exceed staging/unpacked limit')
                            target=output/_path(item['path']);target.parent.mkdir(parents=True,exist_ok=True)
                            shutil.copyfile(original/item['path'],target);files.append(dict(item))
                        actual={item['path'] for item in files}
                        for path,item in declared.items():
                            if path.as_posix() in actual:continue
                            destination=output/path;destination.parent.mkdir(parents=True,exist_ok=True)
                            remaining=package_limit-sum(f['size'] for f in files)
                            if item['size'] is not None and item['size']>remaining:
                                raise SearchError('budget_exceeded: declared native member exceeds staging/unpacked limit')
                            size,digest=transaction.download(_url(repo,revision,path),destination,max_bytes=min(item['size'],remaining) if item['size'] is not None else remaining)
                            files.append({'path':path.as_posix(),'size':size,'sha256':digest,'url':_url(repo,revision,path)})
                        files.sort(key=lambda item:item['path'])
                        augmented=dict(result,files=files);_verify_declared(augmented,declared)
                        key=hashlib.sha256(json.dumps({'schema':'simscene.hf_native_package.v1','source':result['source'],'files':files,'ref':ref.to_dict(),'license':license_info,'provenance':provenance},sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
                        target=directory/key
                        augmented.update(package_sha256=key,root=str(target/root_path),source_ref=ref.to_dict(),
                            license=license_info,provenance=provenance,metadata=source_record,
                            manifest_sha256=_manifest(files),source_manifest_hash=_manifest(files))
                        augmented['unresolved_dependencies']=[str(value).replace(str(original),str(target)) for value in result.get('unresolved_dependencies',[])]
                        (output/'simscene-lock.json').write_text(json.dumps(augmented,indent=2))
                        total=sum(path.stat().st_size for path in output.rglob('*') if path.is_file())
                        if total>min(capacity,limits['unpacked_bytes'],limits['staging_bytes']):
                            raise SearchError('budget_exceeded: native package staging/unpacked size exceeds frozen limit')
                        if target.is_dir():result=cache._verified_cached(target,key,result['source'])
                        else:
                            cache._evict(total);output.rename(target);result=cache._verified_cached(target,key,result['source'])
                        cache._write_index(index,key);cache._write_provenance(result)
        _verify_declared(result,declared)
        package=directory/result['package_sha256']
        if sum(path.stat().st_size for path in package.rglob('*') if path.is_file())>min(capacity,limits['unpacked_bytes'],limits['staging_bytes']):
            raise SearchError('budget_exceeded: cached native package exceeds frozen staging/unpacked limit')
        if descriptor.get('files_complete') is True and {item['path'] for item in result['files']}!={path.as_posix() for path in declared}:
            raise SearchError('verification_failed: complete native descriptor omitted discovered dependencies')
        if result.get('dependency_status') not in {'resolved_locally','resolved_with_runtime'}:
            raise SearchError('dependency_missing: cached native USD closure is unresolved')
        result=dict(result,source_ref=ref.to_dict(),license=license_info,provenance=provenance,metadata=source_record,
                    manifest_sha256=_manifest(result['files']),source_manifest_hash=_manifest(result['files']),
                    actual_download_bytes=transaction.actual_download_bytes,transfer_ledger=transaction.ledger,
                    asset_handle='acquired:sha256:'+result['package_sha256'])
        if job_directory is not None:
            result=copy_acquired_to_job(result,directory,Path(job_directory)/'source',staging_budget_bytes=limits['staging_bytes'])
        return result
    except Exception as error:
        error.actual_download_bytes=transaction.actual_download_bytes;error.transfer_ledger=transaction.ledger
        raise
