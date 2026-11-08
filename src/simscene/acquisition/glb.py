"""Selected, immutable-revision GLB acquisition without executing asset code."""
import base64
import hashlib
import json
import os
import posixpath
import re
import shutil
import struct
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit
from urllib.request import Request, build_opener
from urllib.error import URLError, HTTPError
from http.client import HTTPException

from ..assets import SearchError, CredentialSafeRedirect
from ..cache import AssetCache, _sha256
from ..huggingface_cache import _url
from .locks import cache_lock


def _download(url, destination, budget):
    """HF transfer with exact failed-request byte accounting."""
    from .transfer import current_budget, BudgetExceeded
    transaction = current_budget()
    if transaction is not None:
        token = os.getenv('HF_TOKEN')
        headers = {'Authorization': 'Bearer ' + token} if token else {}
        try:
            return transaction.download(url, destination, headers=headers, max_bytes=budget)
        except BudgetExceeded:
            raise
        except SearchError as error:
            # The existing GLB acquisition path treats ordinary upstream misses
            # as retryable immutable incomplete closures; hard caps stay fatal.
            failure = SearchError('Hugging Face download failed: ' + str(error))
            failure.actual_download_bytes = 0  # transaction owns cumulative accounting
            raise failure from error
    count = 0
    token = os.getenv('HF_TOKEN')
    headers = {'Authorization': 'Bearer ' + token} if token else {}
    digest = hashlib.sha256()
    try:
        with build_opener(CredentialSafeRedirect()).open(Request(url, headers=headers), timeout=60) as response, destination.open('wb') as output:
            length = response.headers.get('Content-Length')
            if length is not None and (int(length) < 0 or int(length) > budget):
                raise SearchError('GLB transfer budget exceeded')
            while True:
                if count == budget:
                    if length is not None and count == int(length):
                        break
                    raise SearchError('GLB transfer budget exhausted before confirmed EOF')
                block = response.read(min(1024 * 1024, budget - count))
                if not block:
                    break
                count += len(block)
                if count > budget:
                    raise SearchError('GLB transfer budget exceeded')
                output.write(block); digest.update(block)
            if length is not None and count != int(length):
                raise SearchError('download declared size mismatch')
        return count, digest.hexdigest()
    except (OSError, URLError, HTTPError, HTTPException, ValueError, SearchError) as error:
        destination.unlink(missing_ok=True)
        message = str(error) if isinstance(error, SearchError) else 'Hugging Face download failed: ' + str(error)
        failure = SearchError(message)
        failure.actual_download_bytes = count + len(getattr(error, 'partial', b''))
        raise failure from error


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def _path(value):
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValueError('invalid repository path')
    if value.startswith('/') or '\\' in value or any(ord(c) < 32 for c in value):
        raise ValueError('unsafe repository path')
    if any(p in ('', '.', '..') for p in value.split('/')):
        raise ValueError('unsafe repository path')
    # Reject encoded separators/traversal, including multiply encoded forms.
    decoded = value
    for _ in range(8):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        if any(p in ('.', '..') for p in next_value.split('/')) or '\\' in next_value or next_value.count('/') != value.count('/'):
            raise ValueError('encoded unsafe repository path')
        decoded = next_value
    if '%' in unquote(value) or '%' in decoded:
        raise ValueError('ambiguous encoded repository path')
    if urlsplit(value).scheme or '?' in value or '#' in value or ':' in value:
        raise ValueError('external repository path')
    return PurePosixPath(decoded)


def _dependency(root, uri):
    if not isinstance(uri, str) or not uri:
        raise ValueError('invalid GLB dependency URI')
    if uri.startswith('data:'):
        header, sep, payload = uri.partition(',')
        if not sep or ';base64' not in header:
            raise ValueError('only base64 embedded data URIs are supported')
        try:
            return None, len(base64.b64decode(payload, validate=True))
        except (ValueError, base64.binascii.Error) as error:
            raise ValueError('invalid embedded data URI') from error
    # Literal parent references may resolve within the selected repository;
    # encoded parent references are deliberately rejected.
    if uri.startswith('/') or '\\' in uri or urlsplit(uri).scheme or '?' in uri or '#' in uri or ':' in uri:
        raise ValueError('external GLB dependency URI is unsupported')
    for part in uri.split('/'):
        if '%' in part and (unquote(part) != part):
            decoded = part
            for _ in range(8):
                decoded = unquote(decoded)
                if decoded in ('.', '..') or '/' in decoded or '\\' in decoded:
                    raise ValueError('encoded unsafe GLB dependency URI')
    normalized = posixpath.normpath(posixpath.join(root.parent.as_posix(), uri))
    return _path(normalized), None


def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate GLB JSON key')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('nonfinite GLB JSON value')


def inspect_glb(path, *, max_json_bytes=16 * 1024**2, max_chunks=64, max_decoded_bytes=4 * 1024**3):
    """Validate bounded GLB framing and enumerate exact buffer/image URIs.

    Codec payloads are not decoded. Unknown extensions remain explicitly
    unverified instead of implying a complete dependency scan.
    """
    if type(max_decoded_bytes) is not int or max_decoded_bytes <= 0:
        raise ValueError('decoded GLB budget must be a positive integer')
    path = Path(path)
    size = path.stat().st_size
    with path.open('rb') as stream:
        header = stream.read(12)
        if len(header) != 12:
            raise ValueError('truncated GLB header')
        magic, version, declared = struct.unpack('<4sII', header)
        if magic != b'glTF' or version != 2 or declared != size or size % 4:
            raise ValueError('invalid GLB header, version or declared size')
        chunks = []; document = None; binary_size = None
        while stream.tell() < size:
            if len(chunks) >= max_chunks:
                raise ValueError('GLB exceeds chunk count budget')
            raw = stream.read(8)
            if len(raw) != 8:
                raise ValueError('truncated GLB chunk header')
            length, kind = struct.unpack('<II', raw)
            if length % 4 or length > size - stream.tell():
                raise ValueError('invalid GLB chunk size')
            if not chunks and kind != 0x4E4F534A:
                raise ValueError('GLB first chunk must contain JSON')
            if kind == 0x4E4F534A:
                if document is not None or length > max_json_bytes:
                    raise ValueError('duplicate or oversized GLB JSON')
                document = json.loads(stream.read(length).decode('utf-8'), object_pairs_hook=_json_pairs, parse_constant=_invalid_constant)
            elif kind == 0x004E4942:
                if binary_size is not None or len(chunks) != 1:
                    raise ValueError('duplicate or misplaced GLB binary chunk')
                binary_size = length; stream.seek(length, 1)
            else:
                stream.seek(length, 1)
            chunks.append(kind)
    if not isinstance(document, dict) or not isinstance(document.get('asset'), dict) or document['asset'].get('version') != '2.0':
        raise ValueError('invalid GLB JSON asset version')
    if document['asset'].get('minVersion', '2.0') != '2.0':
        raise ValueError('unsupported GLB minimum asset version')
    buffers = document.get('buffers', []); views = document.get('bufferViews', [])
    images = document.get('images', [])
    for values in (buffers, views, images):
        if not isinstance(values, list) or any(not isinstance(v, dict) for v in values):
            raise ValueError('invalid GLB buffer/image array')
    dependencies = []; embedded = []
    meshopt = 'EXT_meshopt_compression'
    required = document.get('extensionsRequired', [])
    if not isinstance(required, list) or any(not isinstance(value, str) for value in required):
        raise ValueError('invalid GLB required extensions declaration')
    fallback_buffers = set()
    declared_buffer_bytes = 0
    for index, buffer in enumerate(buffers):
        length = buffer.get('byteLength')
        if type(length) is not int or length < 0:
            raise ValueError('invalid GLB buffer byteLength')
        declared_buffer_bytes += length
        if declared_buffer_bytes > max_decoded_bytes:
            raise ValueError('GLB declared buffers exceed decoded byte budget')
        extensions = buffer.get('extensions', {})
        if not isinstance(extensions, dict) or (meshopt in extensions and not isinstance(extensions[meshopt], dict)):
            raise ValueError('invalid meshopt buffer extension')
        fallback = extensions.get(meshopt, {}).get('fallback', False)
        if type(fallback) is not bool:
            raise ValueError('invalid meshopt fallback flag')
        if fallback:
            fallback_buffers.add(index)
        if 'uri' in buffer:
            dependencies.append({'kind': 'buffer', 'uri': buffer['uri'], 'byte_length': length})
        elif index == 0 and binary_size is not None and length <= binary_size <= length + 3:
            pass
        elif index > 0 and fallback and meshopt in required:
            # Required meshopt permits a URI-less decoded-storage placeholder.
            # This validates framing only; no codec is executed here.
            pass
        else:
            raise ValueError('GLB buffer does not match binary chunk')
    decoded_output_bytes = 0
    compressed_views = 0
    for view in views:
        index = view.get('buffer'); offset = view.get('byteOffset', 0); length = view.get('byteLength')
        if type(index) is not int or not 0 <= index < len(buffers) or type(offset) is not int or type(length) is not int or min(offset, length) < 0 or offset + length > buffers[index]['byteLength']:
            raise ValueError('GLB buffer view is out of bounds')
        extensions = view.get('extensions', {})
        if not isinstance(extensions, dict):
            raise ValueError('invalid GLB buffer view extensions')
        compressed = extensions.get(meshopt)
        if compressed is None:
            if index in fallback_buffers:
                raise ValueError('meshopt fallback buffer referenced by an uncompressed view')
            continue
        if not isinstance(compressed, dict):
            raise ValueError('invalid meshopt compressed view')
        source = compressed.get('buffer'); encoded_offset = compressed.get('byteOffset', 0)
        encoded_length = compressed.get('byteLength'); stride = compressed.get('byteStride'); count = compressed.get('count')
        if (type(source) is not int or not 0 <= source < len(buffers) or source in fallback_buffers
                or type(encoded_offset) is not int or encoded_offset < 0
                or type(encoded_length) is not int or encoded_length <= 0
                or encoded_offset + encoded_length > buffers[source]['byteLength']):
            raise ValueError('meshopt encoded buffer range is invalid')
        if type(stride) is not int or stride <= 0 or type(count) is not int or count <= 0 or stride * count != length:
            raise ValueError('meshopt decoded count/stride does not match buffer view')
        if 'byteStride' in view and (type(view['byteStride']) is not int or view['byteStride'] != stride):
            raise ValueError('meshopt parent buffer view stride mismatch')
        mode = compressed.get('mode'); filter_ = compressed.get('filter', 'NONE')
        if mode not in ('ATTRIBUTES', 'TRIANGLES', 'INDICES') or filter_ not in ('NONE', 'OCTAHEDRAL', 'QUATERNION', 'EXPONENTIAL'):
            raise ValueError('unsupported meshopt mode or filter')
        if ((mode == 'ATTRIBUTES' and (stride % 4 or stride > 256))
                or (mode == 'TRIANGLES' and count % 3)
                or (mode in ('TRIANGLES', 'INDICES') and (stride not in (2, 4) or filter_ != 'NONE'))
                or (filter_ == 'OCTAHEDRAL' and stride not in (4, 8))
                or (filter_ == 'QUATERNION' and stride != 8)
                or (filter_ == 'EXPONENTIAL' and stride % 4)):
            raise ValueError('meshopt mode/filter/stride constraints are invalid')
        decoded_output_bytes += stride * count
        compressed_views += 1
        if decoded_output_bytes > max_decoded_bytes:
            raise ValueError('meshopt decoded views exceed decoded byte budget')
    for image in images:
        if 'uri' in image:
            if 'bufferView' in image:
                raise ValueError('GLB image has ambiguous storage')
            dependencies.append({'kind': 'image', 'uri': image['uri'], 'byte_length': None})
        elif type(image.get('bufferView')) is not int or not 0 <= image['bufferView'] < len(views):
            raise ValueError('GLB image buffer view is invalid')
    # Only the base glTF schema is interpreted here. All extensions, including
    # compression codecs, require a later converter-aware inspection.
    declared = []
    for key in ('extensionsUsed', 'extensionsRequired'):
        values = document.get(key, [])
        if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
            raise ValueError('invalid GLB extensions declaration')
        declared.extend(values)
    # Extension blocks can also be present without an extensionsUsed entry.
    pending = [document]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            if 'extensions' in node:
                if not isinstance(node['extensions'], dict):
                    raise ValueError('invalid GLB extension block')
                declared.extend(node['extensions'].keys())
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
    extensions = sorted(set(declared))
    for item in dependencies:
        if isinstance(item['uri'], str) and item['uri'].startswith('data:'):
            _, length = _dependency(PurePosixPath('asset.glb'), item['uri'])
            if item['byte_length'] is not None and length != item['byte_length']:
                raise ValueError('embedded buffer size mismatch')
            embedded.append(item)
    return {'schema_version': 1, 'size': size, 'dependencies': dependencies,
            'extensions': extensions, 'unknown_chunks': [x for x in chunks if x not in (0x4E4F534A, 0x004E4942)],
            'dependency_status': 'unverified_extensions' if extensions or any(x not in (0x4E4F534A, 0x004E4942) for x in chunks) else 'inspected',
            'embedded_dependencies': len(embedded), 'declared_buffer_bytes': declared_buffer_bytes,
            'meshopt_decoded_bytes': decoded_output_bytes, 'meshopt_compressed_views': compressed_views}


def acquire_glb(repo_id, revision, path, directory, download_budget_bytes=1024**3,
                cache_capacity_bytes=2 * 1024**3, *, staging_budget_bytes=4 * 1024**3,
                source_ref=None, metadata=None, license=None, provenance=None, additional_paths=None):
    """Acquire only one selected GLB and its explicit same-repository files."""
    if not isinstance(repo_id, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo_id) or any(p in ('.', '..') for p in repo_id.split('/')):
        raise ValueError('repository must be owner/name')
    if not isinstance(revision, str) or not re.fullmatch(r'[0-9a-fA-F]{40}', revision):
        raise ValueError('acquisition requires a full immutable 40-character commit SHA')
    revision = revision.lower(); root_path = _path(path)
    if source_ref is not None and (not isinstance(source_ref, dict) or not isinstance(source_ref.get('revision'), str) or source_ref['revision'].lower() != revision):
        raise ValueError('source_ref must match the selected immutable revision')
    if root_path.suffix.lower() != '.glb':
        raise ValueError('selected root must be a GLB file')
    for value in (download_budget_bytes, staging_budget_bytes, cache_capacity_bytes):
        if type(value) is not int or value < 0:
            raise ValueError('budgets must be nonnegative integers')
    if additional_paths is not None and not isinstance(additional_paths, (list, tuple)):
        raise ValueError('additional_paths must be a bounded list')
    extras = [_path(p) for p in (additional_paths or [])]
    if len(extras) > 128:
        raise ValueError('too many selected metadata/license files')
    cache = AssetCache(None, directory, cache_capacity_bytes)
    source = _url(repo_id, revision, root_path)
    selection = {'source': source, 'additional_paths': sorted(str(p) for p in extras), 'source_ref': source_ref,
                 'metadata': metadata, 'license': license, 'provenance': provenance}
    selection_hash = hashlib.sha256(_canonical(selection)).hexdigest()
    index = cache.directory / ('.source-' + selection_hash)
    lineage = cache.directory / ('.glb-lineage-' + selection_hash)
    with cache_lock(cache.directory):
        cache._cleanup_partials()
        observed = json.loads(lineage.read_text()) if lineage.is_file() else {}
        prior = None
        if index.is_file():
            digest = index.read_text().strip()
            if re.fullmatch(r'[0-9a-f]{64}', digest) and (cache.directory / digest).is_dir():
                # Corruption fails explicitly, never silently trusts a new download.
                prior = cache._verified_cached(cache.directory / digest, digest, source)
                if hashlib.sha256(_canonical(prior['files'])).hexdigest() != prior.get('manifest_sha256'):
                    raise SearchError('GLB cached manifest integrity check failed')
                if prior.get('dependency_status') != 'missing':
                    return dict(prior, actual_download_bytes=0)
        with tempfile.TemporaryDirectory(dir=cache.directory, prefix='.partial-glb-') as tmp:
            output = Path(tmp) / 'contents'; output.mkdir()
            files = []; actual = 0; errors = []; unresolved = []
            old_files = {f['path']: f for f in prior['files']} if prior else {}
            def fetch(relative):
                nonlocal actual
                name = relative.as_posix()
                target = output.joinpath(*relative.parts); target.parent.mkdir(parents=True, exist_ok=True)
                if name in old_files:
                    item = old_files[name]
                    if sum(f['size'] for f in files) + item['size'] > staging_budget_bytes:
                        raise SearchError('GLB staging budget exceeded')
                    shutil.copyfile(cache.directory / prior['package_sha256'] / name, target)
                    files.append(dict(item)); return
                remaining = min(download_budget_bytes - actual, staging_budget_bytes - sum(f['size'] for f in files))
                if remaining <= 0:
                    raise SearchError('GLB acquisition transfer or staging budget exceeded')
                url = _url(repo_id, revision, relative)
                try:
                    size, digest = _download(url, target, remaining)
                except SearchError as error:
                    actual += getattr(error, 'actual_download_bytes', 0)
                    raise
                # The downloader is streaming/bounded; also verify its contract.
                if target.stat().st_size != size or _sha256(target) != digest or size > remaining:
                    raise SearchError('download size or SHA-256 mismatch')
                actual += size
                if name in observed and observed[name] != digest:
                    raise SearchError('immutable source content changed; establish a new selection')
                files.append({'path': name, 'size': size, 'sha256': digest, 'url': url})
            fetch(root_path)
            scan = inspect_glb(output.joinpath(*root_path.parts), max_decoded_bytes=staging_budget_bytes)
            wanted = {p: None for p in extras}
            for dependency in scan['dependencies']:
                relative, embedded_size = _dependency(root_path, dependency['uri'])
                if relative is not None:
                    expected = dependency['byte_length']
                    if relative in wanted and wanted[relative] is not None and expected is not None and wanted[relative] != expected:
                        raise ValueError('conflicting dependency buffer lengths')
                    wanted[relative] = expected if expected is not None else wanted.get(relative)
            if len(wanted) > 1024:
                raise SearchError('GLB dependency count exceeds budget')
            for relative, expected in sorted(wanted.items()):
                if relative == root_path:
                    raise ValueError('GLB references itself as dependency')
                try:
                    fetch(relative)
                    if expected is not None and files[-1]['size'] != expected:
                        raise SearchError('GLB external buffer declared size mismatch')
                except SearchError as error:
                    # Hard budgets and structural mismatches are terminal. Only
                    # failed upstream requests form an immutable retryable lock.
                    if 'download failed:' not in str(error):
                        raise
                    unresolved.append(str(relative)); errors.append({'path': str(relative), 'error': str(error)})
            files.sort(key=lambda f: f['path'])
            manifest_hash = hashlib.sha256(_canonical(files)).hexdigest()
            identity = {'selection': selection, 'files': files, 'scan': scan, 'unresolved': unresolved}
            digest = hashlib.sha256(_canonical(identity)).hexdigest(); target = cache.directory / digest
            status = 'missing' if unresolved else ('unverified_extensions' if scan['dependency_status'] != 'inspected' else 'resolved_locally')
            result = {'schema_version': 1, 'asset_handle': 'acquired:sha256:' + digest,
                      'source_ref': source_ref or {'source_id': 'huggingface', 'asset_id': repo_id + '/' + path, 'revision': revision},
                      'source': source, 'repository': repo_id, 'revision': revision,
                      'package_sha256': digest, 'manifest_sha256': manifest_hash,
                      'root': str(target.joinpath(*root_path.parts)), 'files': files,
                      'dependency_status': status, 'unresolved_dependencies': unresolved, 'repair_errors': errors,
                      'actual_download_bytes': actual, 'license': license if license is not None else 'unknown',
                      'metadata': metadata, 'provenance': provenance, 'inspection': scan}
            (output / 'simscene-lock.json').write_text(json.dumps(result, indent=2))
            size = sum(p.stat().st_size for p in output.rglob('*') if p.is_file())
            if size > staging_budget_bytes or size > cache_capacity_bytes:
                raise SearchError('GLB package exceeds staging budget or cache capacity')
            if target.exists():
                cache._verified_cached(target, digest, source)
            else:
                cache._evict(size); output.rename(target)
            for item in files:
                observed[item['path']] = item['sha256']
            cache._write_index(lineage, json.dumps(observed, sort_keys=True))
            cache._write_index(index, digest); cache._write_provenance(result)
            return result
