"""Reacquire an evicted selected asset without silently changing its content."""
import json
import os
import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from .assets import SearchError, USDSearch
from .cache import AssetCache
from .settings import get


def restore_reference(value):
    """Return an existing path, or restore a previously locked cache asset.

    A saved scene can outlive a capacity eviction. Tiny provenance records
    retain the selected source and a fingerprint of all locked dependencies.
    If the source now serves different content, restoration fails closed so a
    caller must explicitly inspect and select the changed asset.
    """
    original=Path(value).expanduser().resolve()
    if original.is_file():return original
    for package in original.parents:
        if not re.fullmatch(r'[0-9a-f]{64}',package.name):continue
        cache_dir=package.parent
        provenance_dir=cache_dir/'.provenance'
        if provenance_dir.is_symlink():continue
        record_path=provenance_dir/(package.name+'.json')
        if not record_path.is_file() or record_path.is_symlink():continue
        try:
            if record_path.stat().st_size>16384:raise ValueError('oversized source provenance')
            record=json.loads(record_path.read_text())
            source=record['source'];root_relative=PurePosixPath(record['root_relative'])
            expected=record['content_sha256']
            parsed=urlsplit(source)
            if (parsed.scheme!='https' or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment or
                    root_relative.is_absolute() or '..' in root_relative.parts or not root_relative.parts or
                    not isinstance(expected,str) or not re.fullmatch(r'[0-9a-f]{64}',expected)):
                raise ValueError('invalid source provenance')
            old_root=package.joinpath(*root_relative.parts)
            selected_relative=os.path.relpath(original,old_root.parent)
            capacity=int(get('cache_bytes',2*1024**3))
            if record.get('repository') or record.get('revision'):
                from .huggingface_cache import acquire
                if not isinstance(record.get('repository'),str) or not isinstance(record.get('revision'),str):
                    raise ValueError('incomplete Hugging Face provenance')
                restored=acquire(record['repository'],record['revision'],root_relative.as_posix(),cache_dir,capacity)
            else:
                restored=AssetCache(USDSearch(),cache_dir,capacity).acquire(source)
            if restored.get('dependency_status') not in ('resolved_locally','resolved_with_runtime'):
                raise SearchError('restored asset dependencies remain incomplete or unverified')
            if AssetCache.content_identity(restored.get('files'))!=expected:
                raise SearchError('evicted asset source content changed; inspect and select it again')
            new_package=(cache_dir/restored['package_sha256']).resolve()
            new_root=Path(restored['root']).resolve()
            target=(new_root.parent/selected_relative).resolve()
            relative=target.relative_to(new_package).as_posix()
            if relative not in {item['path'] for item in restored['files']} or not target.is_file():
                raise SearchError('selected asset is missing from the restored package')
            return target
        except (OSError,ValueError,KeyError,TypeError) as error:
            raise SearchError(f'cannot restore evicted asset {original}: {error}') from error
    return original
