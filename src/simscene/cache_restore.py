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


def restore_prepared_reference(binding, asset_path, *, home=None):
    """Relocate an evicted prepared asset only to an exactly pinned run snapshot.

    This is a read-only lookup. It never fetches, converts, changes a manifest,
    or trusts a newly computed manifest hash in place of the caller's pin.
    Existing but damaged packages fail closed instead of silently relocating.
    """
    from .physics_binding import validate_asset_binding

    guidance = ' run asset_prepare with new request and select refreshed binding'
    def failure(detail):
        return ValueError('prepared_asset_evicted: ' + detail + ';' + guidance)

    def no_symlinks(path):
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError('prepared snapshot path contains a symlink')

    def relative(value):
        if not isinstance(value, str) or not value or '\\' in value or any(c in value for c in ('%', '?', '#', ':')):
            raise ValueError('unsafe run-relative prepared path')
        parts = value.split('/')
        if any(part in ('', '.', '..') for part in parts):
            raise ValueError('unsafe run-relative prepared path')
        return PurePosixPath(value)

    if not isinstance(binding, dict) or set(binding) != {'manifest_path', 'manifest_sha256'}:
        raise failure('an exact prepared manifest binding is required')
    expected = binding.get('manifest_sha256')
    if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
        raise failure('invalid pinned prepared manifest SHA-256')
    if not isinstance(binding.get('manifest_path'), str) or not binding['manifest_path'] or not isinstance(asset_path, str) or not asset_path:
        raise failure('prepared manifest and asset paths are required')
    original = Path(binding['manifest_path']).expanduser().absolute()
    selected = Path(asset_path).expanduser().absolute()
    try:
        no_symlinks(original); no_symlinks(selected)
        if original.exists():
            validate_asset_binding(binding, asset_path=asset_path)
            return {'asset_path': asset_path, 'asset_binding': binding}
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        raise failure('existing prepared package or binding is invalid') from error

    state = Path(home if home is not None else get('data_directory', '~/.local/share/simscene/scenes')).expanduser().absolute()
    runs = state / 'runs'
    try:
        no_symlinks(runs)
        if not runs.is_dir():
            raise failure('no durable run snapshot proves the selected manifest')
        total_bytes = 0
        inspected = 0
        from itertools import islice
        for run in sorted(islice(runs.iterdir(), 10001)):
            inspected += 1
            if inspected > 10000:
                raise failure('durable run lookup exceeded its bounded record count')
            # Only direct run asset locks are eligible, never arbitrary packages.
            lock_path = run / 'asset-lock.json'
            try:
                no_symlinks(lock_path)
                if not run.is_dir() or not lock_path.is_file():
                    continue
                size = lock_path.stat().st_size
                if size > 4 * 1024**2:
                    continue
                total_bytes += size
                if total_bytes > 64 * 1024**2:
                    raise failure('durable run lookup exceeded its metadata byte budget')
                records = json.loads(lock_path.read_text())
                if not isinstance(records, dict):
                    continue
            except ValueError as error:
                if str(error).startswith('prepared_asset_evicted:'):
                    raise
                continue
            except (OSError, TypeError, RecursionError):
                continue
            for record in records.values():
                if not isinstance(record, dict) or record.get('kind') != 'prepared_snapshot' or record.get('manifest_sha256') != expected:
                    continue
                try:
                    manifest_relative = relative(record.get('manifest_relative_to_run'))
                    root_relative = relative(record.get('root_relative_to_run'))
                    if (len(manifest_relative.parts) != 3 or manifest_relative.parts[0] != 'assets'
                            or manifest_relative.parts[-1] != 'manifest.json'
                            or len(root_relative.parts) < 3 or root_relative.parts[:2] != manifest_relative.parts[:2]):
                        raise ValueError('prepared run snapshot is not a safe asset package')
                    manifest_path = run.joinpath(*manifest_relative.parts)
                    candidate_root = run.joinpath(*root_relative.parts)
                    no_symlinks(manifest_path); no_symlinks(candidate_root)
                    relocated = {'manifest_path': str(manifest_path), 'manifest_sha256': expected}
                    manifest = validate_asset_binding(relocated, asset_path=str(candidate_root))
                    if (record.get('prepared_id') != manifest.get('prepared_id') or not isinstance(manifest.get('prepared_id'), str)
                            or not re.fullmatch('[0-9a-f]{64}', manifest['prepared_id'])):
                        raise ValueError('prepared identity differs from its durable run record')
                    if root_relative != manifest_relative.parent / relative(manifest['main']):
                        raise ValueError('prepared run root differs from the manifest entry')
                    if selected != original.parent / manifest['main']:
                        raise ValueError('caller asset path differs from the selected prepared entry')
                    return {'asset_path': str(candidate_root), 'asset_binding': relocated}
                except (OSError, ValueError, KeyError, TypeError, RecursionError):
                    continue
    except (OSError, TypeError, ValueError) as error:
        if str(error).startswith('prepared_asset_evicted:'):
            raise
        raise failure('durable prepared snapshot lookup failed') from error
    raise failure('no unchanged durable run snapshot proves the selected manifest')
