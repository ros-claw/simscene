"""Resolve relative HTTPS dependencies inside an extracted USD package."""
import hashlib
import os
from pathlib import Path
from urllib.parse import urljoin, urlsplit, quote, unquote
from urllib.request import build_opener, HTTPRedirectHandler
from urllib.error import URLError


class SameOriginRedirect(HTTPRedirectHandler):
    def __init__(self, origin):
        self.origin = origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        destination = urlsplit(urljoin(req.full_url, newurl))
        if destination.scheme != 'https' or destination.netloc != self.origin:
            raise ValueError('cross-origin redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def repair(root, root_url, package_dir, limit, max_passes=32):
    """Fetch missing relative dependencies from the root's HTTPS directory.

    Only paths within the package and the same HTTPS origin are attempted.
    Other references are reported for a configured resolver.
    """
    from pxr import Sdf, UsdUtils
    package_dir = Path(package_dir).resolve()
    root = Path(root).resolve()
    origin = urlsplit(root_url)
    fetched, errors = [], []
    attempted = set()
    for _ in range(max_passes):
        layers, _, unresolved = UsdUtils.ComputeAllDependencies(str(root))
        # USD may return an unresolved authored relative path without its layer
        # anchor. Recover that anchor from every resolved layer, including shader
        # asset attributes, before constructing an on-disk destination. Work on
        # anonymous copies: ModifyAssetPaths must never alter the source layers.
        anchors = {}
        for layer in layers:
            identifier = Path(layer.realPath or layer.identifier)
            if not identifier.is_absolute():
                continue
            copy = Sdf.Layer.CreateAnonymous()
            copy.TransferContent(layer)
            def collect(value):
                anchors.setdefault(value, set()).add(identifier.parent)
                return value
            UsdUtils.ModifyAssetPaths(copy, collect)
        progress = False
        # MDL source has its own module/texture dependency graph. Resolve it
        # under the same package, origin and byte bounds as USD references.
        from .mdl_dependencies import references as mdl_references
        material_missing=[]
        for module in package_dir.rglob('*.mdl'):
            try:material_missing.extend(p for p in mdl_references(module) if not p.is_file())
            except ValueError as error:errors.append({'dependency':str(module),'error':str(error)})
        unresolved=list(unresolved)+sorted(set(str(p) for p in material_missing))
        for item in unresolved:
            path = Path(str(item))
            if not path.is_absolute():
                parents = anchors.get(str(item), set())
                if not parents:
                    errors.append({'dependency':str(item), 'error':'non-local reference requires a resolver'})
                    continue
                paths = [parent / path for parent in sorted(parents)]
            else:
                paths = [path]
            for path in paths:
                result = _fetch(path, item, root, package_dir, root_url, origin, limit, attempted)
                if result.get('file'):
                    fetched.append(result['file'])
                    progress = True
                elif result.get('error'):
                    errors.append({'dependency':str(item), 'error':result['error']})
        if not progress:
            break
    _, _, unresolved = UsdUtils.ComputeAllDependencies(str(root))
    material_missing=[]
    for module in package_dir.rglob('*.mdl'):
        try:material_missing.extend(str(p) for p in mdl_references(module) if not p.is_file())
        except ValueError as error:material_missing.append(str(module)+': '+str(error))
    return {'files':fetched, 'unresolved':sorted(set([str(p) for p in unresolved]+material_missing)), 'errors':errors,'scan_version':2}


def _fetch(path, item, root, package_dir, root_url, origin, limit, attempted):
    """Fetch an anchored dependency only within the package and source origin."""
    if '://' in str(item) or str(item).startswith(('anon:', 'package:')):
        return {'error':'non-local reference requires a resolver'}
    for part in Path(str(item)).parts:
        if part == os.path.sep:
            continue
        decoded = unquote(part)
        if ('/' in decoded or '\\' in decoded or
                (decoded in ('.', '..') and decoded != part)):
            return {'error':'unsafe encoded path'}
    path = path.resolve()
    try:
        path.relative_to(package_dir)
    except ValueError:
        return {'error':'outside asset package directory'}
    relative = Path(os.path.relpath(path, root.parent))
    # The same authored relative name can occur in several layers. Only a
    # missing destination may be filled; never replace an existing asset that
    # happened to share the unresolved name from another layer.
    if path.exists():
        return {}
    if str(path) in attempted:
        return {}
    attempted.add(str(path))
    if origin.scheme != 'https' or not origin.netloc:
        return {'error':'HTTPS source required for repair'}
    url = urljoin(root_url, quote(relative.as_posix(), safe='/%'))
    split = urlsplit(url)
    if split.scheme != 'https' or split.netloc != origin.netloc:
        return {'error':'cross-origin reference'}
    tmp = path.with_name(path.name + '.simscene-partial')
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        used = sum(p.stat().st_size for p in package_dir.rglob('*') if p.is_file())
        hasher = hashlib.sha256()
        size = 0
        with build_opener(SameOriginRedirect(origin.netloc)).open(url, timeout=30) as response, tmp.open('wb') as output:
            final = urlsplit(response.geturl())
            if final.scheme != 'https' or final.netloc != origin.netloc:
                raise ValueError('cross-origin redirect')
            while True:
                block = response.read(1024 * 1024)
                if not block: break
                size += len(block)
                if used + size > limit:
                    raise ValueError('cache capacity exceeded')
                hasher.update(block)
                output.write(block)
        tmp.replace(path)
        return {'file':{'url':url, 'path':str(path.relative_to(package_dir)), 'size':size, 'sha256':hasher.hexdigest()}}
    except (OSError, URLError, ValueError) as e:
        tmp.unlink(missing_ok=True)
        return {'error':str(e)}
