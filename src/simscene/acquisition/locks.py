"""Shared cache lock and bounded private job input copying."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path

from ..assets import SearchError
from ..cache import AssetCache


@contextmanager
def cache_lock(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / '.cache.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def copy_acquired_to_job(acquired, directory, destination, staging_budget_bytes=4 * 1024**3):
    """Copy verified inputs under the cache lock into an atomic private tree.

    The destination must not exist. Its temporary sibling is deliberately not
    named .partial-*, so legacy cache cleanup cannot delete a live job input.
    """
    if type(staging_budget_bytes) is not int or staging_budget_bytes < 0:
        raise ValueError('invalid staging budget')
    destination = Path(destination).absolute()
    cache = AssetCache(None, directory)
    digest = acquired.get('package_sha256', '')
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise ValueError('invalid acquired package identity')
    if destination.exists() or destination.is_symlink():
        raise ValueError('job input destination already exists')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with cache_lock(cache.directory):
        result = cache._verified_cached(cache.directory / digest, digest, acquired['source'])
        manifest = hashlib.sha256(json.dumps(result['files'], sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        if result.get('manifest_sha256') not in (None, manifest) or acquired.get('manifest_sha256') not in (None, manifest) or acquired.get('source_manifest_hash') not in (None, manifest):
            raise SearchError('acquired manifest changed')
        size = sum(f['size'] for f in result['files'])
        if size > staging_budget_bytes:
            raise SearchError('job input exceeds staging budget')
        with tempfile.TemporaryDirectory(dir=destination.parent, prefix='.job-input-') as temporary:
            output = Path(temporary) / 'contents'; output.mkdir()
            for item in result['files']:
                target = output / item['path']; target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(cache.directory / digest / item['path'], target)
            relative = Path(result['root']).relative_to(cache.directory / digest)
            cache_result = result
            result = dict(acquired, **cache_result)
            for key in ('source_ref', 'license', 'provenance', 'source_manifest_hash', 'actual_download_bytes', 'transfer_ledger'):
                if key in acquired:
                    result[key] = acquired[key]
            result.update(root=str(destination / relative), manifest_sha256=manifest, source_manifest_hash=manifest, job_copy_bytes=size)
            encoded = json.dumps(result, indent=2)
            if size + len(encoded.encode()) > staging_budget_bytes:
                raise SearchError('job input manifest exceeds staging budget')
            (output / 'simscene-lock.json').write_text(encoded)
            output.rename(destination)
            return result
