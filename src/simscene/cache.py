"""Bounded package cache; entries are verified before they become visible."""
import hashlib
import json
import os
import shutil
import tempfile
import re
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from .assets import SearchError


def _sha256(path):
    result = hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda: file.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()

def _runtime_status(lock):
    """Interpret unresolved system materials against the current runtime.

    The on-disk lock retains the original unresolved list so moving the cache
    to a different host cannot accidentally preserve a stale runtime result.
    """
    from .runtime_dependencies import classify
    from copy import deepcopy
    result=deepcopy(lock)
    dependencies=classify(lock.get('unresolved_dependencies',[]))
    result['runtime_provided_dependencies']=dependencies['runtime_provided']
    result['unresolved_dependencies']=dependencies['unresolved']
    if lock.get('dependency_status')=='missing' and not dependencies['unresolved'] and dependencies['runtime_provided']:
        result['dependency_status']='resolved_with_runtime'
    return result

class AssetCache:
    def __init__(self, client, directory, max_bytes=2 * 1024**3):
        self.client = client
        self.directory = Path(directory).expanduser()
        self.max_bytes = max_bytes
        if max_bytes <= 0:
            raise ValueError('max_bytes must be positive')
        self.directory.mkdir(parents=True, exist_ok=True)

    def acquire(self, asset_url, refresh=False):
        import fcntl
        with (self.directory / '.cache.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self._cleanup_partials()
            result = self._acquire(asset_url, refresh)
            self._write_provenance(result)
            return result

    @staticmethod
    def content_identity(files):
        """Fingerprint downloaded content independently of ZIP timestamps."""
        if not isinstance(files,list) or not files:
            raise ValueError('package has no content records')
        entries=[]
        for item in files:
            if not isinstance(item,dict) or not isinstance(item.get('url'),str) or type(item.get('size')) is not int or not re.fullmatch(r'[0-9a-f]{64}',str(item.get('sha256',''))):
                raise ValueError('invalid package content record')
            entries.append((item['url'],item['size'],item['sha256']))
        data=json.dumps(sorted(entries),separators=(',',':'),ensure_ascii=False).encode()
        return hashlib.sha256(data).hexdigest()

    def _write_provenance(self, metadata):
        """Keep a small source/content lock after a 3D package is evicted."""
        try:
            digest=metadata['package_sha256'];source=metadata['source']
            if not isinstance(digest,str) or not re.fullmatch(r'[0-9a-f]{64}',digest) or not isinstance(source,str):return
            parsed=urlsplit(source)
            if parsed.scheme!='https' or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:return
            package=(self.directory/digest).resolve()
            relative=Path(metadata['root']).resolve().relative_to(package)
            identity=self.content_identity(metadata['files'])
            record={'source':source,'root_relative':relative.as_posix(),'content_sha256':identity}
            if metadata.get('repository') and metadata.get('revision'):
                record.update(repository=metadata['repository'],revision=metadata['revision'])
        except (KeyError,ValueError,TypeError):
            return
        folder=self.directory/'.provenance';folder.mkdir(exist_ok=True)
        if folder.is_symlink() or folder.resolve().parent!=self.directory.resolve():
            raise SearchError('unsafe cache provenance directory')
        with tempfile.NamedTemporaryFile(mode='w',dir=self.directory,prefix='.index-',delete=False) as file:
            name=file.name
            try:
                json.dump(record,file,indent=2);file.flush();os.fsync(file.fileno())
                os.replace(name,folder/(digest+'.json'))
            finally:
                if os.path.exists(name):os.unlink(name)

    def _cleanup_partials(self):
        """Remove abandoned staging files while holding the shared cache lock."""
        for path in self.directory.iterdir():
            if not path.name.startswith(('.partial-', '.index-')):
                continue
            if path.is_symlink() or not path.is_dir():
                path.unlink(missing_ok=True)
            else:
                shutil.rmtree(path)

    def _acquire(self, asset_url, refresh=False):
        index = self.directory / ('.source-' + hashlib.sha256(asset_url.encode()).hexdigest())
        if not refresh and index.is_file():
            digest = index.read_text().strip()
            if re.fullmatch(r'[0-9a-f]{64}', digest):
                target = self.directory / digest
                if target.is_dir():
                    return self._verified_cached(target, digest, asset_url)
        preview = self.client.request('/download/asset', {'asset_url': asset_url, 'manifest_only': 'true'})
        if preview.get('total_size', 0) > self.max_bytes:
            raise SearchError('Asset exceeds cache capacity')
        with tempfile.TemporaryDirectory(dir=self.directory, prefix='.partial-') as tmp:
            tmp = Path(tmp)
            archive = tmp / 'package.zip'
            self.client.request('/download/asset', {'asset_url': asset_url}, output=archive, max_bytes=self.max_bytes)
            digest = _sha256(archive)
            target = self.directory / digest
            if target.is_dir():
                cached = self._verified_cached(target, digest, asset_url)
                self._write_index(index, digest)
                return cached
            output = tmp / 'contents'
            output.mkdir()
            try:
                # Leave room for ../ references to sibling assets. USD Search
                # packages often flatten the root, while authored references
                # remain relative to its original URL hierarchy. The padding
                # mirrors the source URL depth without letting references
                # escape this package or reach another origin.
                source_parts = [part for part in urlsplit(asset_url).path.split('/') if part]
                if len(source_parts) > 64:
                    raise SearchError('Asset URL path is too deep')
                prefix = PurePosixPath('origin', *(['_'] * max(0, len(source_parts) - 1)))
                extraction = output.joinpath(*prefix.parts)
                extraction.mkdir(parents=True)
                with zipfile.ZipFile(archive) as z:
                    infos = z.infolist()
                    if sum(x.file_size for x in infos) > self.max_bytes:
                        raise SearchError('Unpacked asset exceeds cache capacity')
                    names = set()
                    for entry in infos:
                        path = PurePosixPath(entry.filename)
                        if path.is_absolute() or '..' in path.parts or '\\' in entry.filename or entry.filename in names or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                            raise SearchError('Unsafe package member')
                        names.add(entry.filename)
                    z.extractall(extraction)
                manifest = json.loads((extraction / 'manifest.json').read_text())
                if manifest.get('root_url') != asset_url:
                    raise SearchError('Package root does not match requested asset')
                if manifest.get('errors') or manifest.get('skipped'):
                    raise SearchError('Package has missing or externally resolved dependencies')
                files = []
                for item in manifest.get('files', []):
                    p = PurePosixPath(item['path'])
                    if p.is_absolute() or '..' in p.parts or '\\' in str(p):
                        raise SearchError('Unsafe manifest path')
                    path = extraction.joinpath(*p.parts)
                    if not path.is_file() or path.stat().st_size != item['size']:
                        raise SearchError('Package manifest does not match files')
                    files.append({'url': item['url'], 'path': str(prefix / p), 'size': item['size'], 'sha256': _sha256(path)})
                roots = [x['path'] for x in files if x['url'] == asset_url]
                if len(roots) != 1:
                    raise SearchError('Root asset missing or ambiguous')
                try:
                    from pxr import UsdUtils
                    from .dependencies import repair
                    scan = repair(output / roots[0], asset_url, output, self.max_bytes)
                    files.extend(scan['files'])
                    unresolved = [str(x).replace(str(output), str(target)) for x in scan['unresolved']]
                    dependency_status = 'missing' if unresolved else 'resolved_locally'
                except ImportError:
                    unresolved = []
                    dependency_status = 'unverified_usd_tools_unavailable'
                    scan = {'errors': []}
                lock = {'source': asset_url, 'package_sha256': digest, 'root': str(target / roots[0]), 'files': files, 'dependency_status': dependency_status, 'unresolved_dependencies': unresolved, 'repair_errors': scan['errors'], 'preview': preview}
                (output / 'simscene-lock.json').write_text(json.dumps(lock, indent=2))
                size = sum(p.stat().st_size for p in output.rglob('*') if p.is_file())
                if size > self.max_bytes:
                    raise SearchError('Unpacked asset exceeds cache capacity')
                self._evict(size)
                output.rename(target)
                self._write_index(index, digest)
                return _runtime_status(lock)
            except (zipfile.BadZipFile, KeyError, ValueError, OSError) as e:
                raise SearchError(f'Invalid asset package: {e}') from e

    def _write_index(self, index, digest):
        with tempfile.NamedTemporaryFile(mode='w', dir=self.directory, prefix='.index-', delete=False) as file:
            name = file.name
            try:
                file.write(digest)
                file.flush()
                os.fsync(file.fileno())
                os.replace(name, index)
            finally:
                if os.path.exists(name): os.unlink(name)

    def _verified_cached(self, target, digest, asset_url, touch=True):
        lock = json.loads((target / 'simscene-lock.json').read_text())
        if lock.get('package_sha256') != digest or lock.get('source') != asset_url:
            raise SearchError('Cached package lock does not match the request')
        files = lock.get('files')
        if not isinstance(files, list) or not files:
            raise SearchError('Cached package lock has no files')
        for item in files:
            relative = PurePosixPath(item['path'])
            if relative.is_absolute() or '..' in relative.parts or '\\' in str(relative):
                raise SearchError('Unsafe cached file path')
            cached = target.joinpath(*relative.parts)
            components = [target.joinpath(*relative.parts[:i]) for i in range(1, len(relative.parts)+1)]
            if (not cached.is_file() or target.is_symlink() or any(p.is_symlink() for p in components)
                    or not cached.resolve().is_relative_to(target.resolve())
                    or cached.stat().st_size != item['size'] or _sha256(cached) != item['sha256']):
                raise SearchError('Cached package integrity check failed')
        if touch:os.utime(target, None)
        return _runtime_status(lock)

    def _evict(self, incoming):
        entries = [p for p in self.directory.iterdir() if p.is_dir() and re.fullmatch(r'[0-9a-f]{64}', p.name) and (p / 'simscene-lock.json').is_file()]
        def size(p):
            return sum(f.stat().st_size for f in p.rglob('*') if f.is_file())
        used = sum(size(p) for p in entries)
        for p in sorted(entries, key=lambda p: p.stat().st_mtime):
            if used + incoming <= self.max_bytes:
                break
            try:self._write_provenance(json.loads((p/'simscene-lock.json').read_text()))
            except (OSError,ValueError) as error:
                raise SearchError(f'cannot preserve evicted asset provenance: {error}') from error
            used -= size(p)
            shutil.rmtree(p)
