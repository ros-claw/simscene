"""Verify and snapshot the exact selected Jetbot USD dependency files."""
import hashlib
from pathlib import Path, PurePosixPath
import re
import shutil


def verify_runtime(isaac_python, lock):
    launcher = Path(isaac_python).expanduser().resolve()
    root = launcher.parent
    if not launcher.is_file() or not (root / 'VERSION').is_file():
        raise ValueError('Isaac launcher or VERSION is missing')
    if not isinstance(lock.get('launcher_sha256'), str) or sha256(launcher) != lock['launcher_sha256']:
        raise ValueError('Isaac launcher differs from the tested launcher hash')
    if (root / 'VERSION').read_text().strip() != lock.get('isaac_version'):
        raise ValueError('Isaac version differs from the tested runtime')
    files = lock.get('files')
    if not isinstance(files, dict) or not files or len(files) > 100:
        raise ValueError('invalid runtime source lock')
    for name, expected in files.items():
        if (not isinstance(name, str) or not name or '\\' in name or name.startswith('/') or
                any(part in ('', '.', '..') for part in name.split('/')) or
                not isinstance(expected, str) or re.fullmatch('[0-9a-f]{64}', expected) is None):
            raise ValueError('unsafe runtime dependency lock')
        path = root.joinpath(*PurePosixPath(name).parts)
        if not path.is_file() or not path.resolve().is_relative_to(root) or sha256(path) != expected:
            raise ValueError('runtime dependency missing or changed: ' + name)
    return root


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify_asset_files(asset_path, lock):
    asset = Path(asset_path).expanduser().absolute()
    if (not isinstance(lock, dict) or lock.get('asset') != asset.name or
            asset.is_symlink() or not asset.is_file()):
        raise ValueError('asset root is missing, symlinked, or differs from the lock')
    base = asset.parent
    base_real = base.resolve()
    entries = lock.get('files')
    if not isinstance(entries, list) or not entries or len(entries) > 50:
        raise ValueError('invalid asset file list')
    found = {}
    total = 0
    for entry in entries:
        name = entry.get('path') if isinstance(entry, dict) else None
        if (not isinstance(name, str) or not name or '\\' in name or name.startswith('/') or
                any(part in ('', '.', '..') for part in name.split('/'))):
            raise ValueError('unsafe asset path')
        relative = PurePosixPath(name)
        if relative.is_absolute() or name in found:
            raise ValueError('duplicate or absolute asset path')
        size = entry.get('bytes')
        digest = entry.get('sha256')
        if (type(size) is not int or not 0 < size <= 35_000_000 or
                not isinstance(digest, str) or re.fullmatch('[0-9a-f]{64}', digest) is None):
            raise ValueError('invalid asset size or digest')
        path = base.joinpath(*relative.parts)
        cursor = base
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError('symlink in locked asset path')
        if (not path.is_file() or not path.resolve().is_relative_to(base_real) or
                path.stat().st_size != size or sha256(path) != digest):
            raise ValueError('locked asset missing or hash/size mismatch: ' + name)
        found[name] = path
        total += size
    if total != lock.get('total_bytes') or total > 48_000_000 or lock['asset'] not in found:
        raise ValueError('asset closure total or root differs from lock')
    return found


def snapshot_assets(asset_path, lock, destination):
    files = verify_asset_files(asset_path, lock)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    for relative, source in files.items():
        target = destination.joinpath(*PurePosixPath(relative).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    result = destination / lock['asset']
    verify_asset_files(result, lock)
    return result
