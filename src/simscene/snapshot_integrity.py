"""Pinned, exhaustive content identities for acquired run asset snapshots.

This module reads files and USD/MDL dependencies; it never fetches, repairs,
rewrites or simulates an asset. Legacy cache locks alone are not relocation
proof because their package manifest was not pinned by the run asset lock.
"""
import json
import re
from pathlib import Path, PurePosixPath

from .cache import _sha256

PIN_FIELDS = {'snapshot_integrity_version', 'snapshot_lock_sha256', 'snapshot_files', 'snapshot_mdl_runtime_files'}


def _require(value, message):
    if not value:
        raise ValueError(message)


def _relative(value):
    _require(isinstance(value, str) and value and '\\' not in value, 'invalid snapshot relative path')
    path = PurePosixPath(value)
    _require(not path.is_absolute() and '..' not in path.parts and path.parts and path.as_posix() == value and value != '.', 'unsafe or noncanonical snapshot path')
    return path


def _files(entries):
    _require(isinstance(entries, list) and entries, 'snapshot requires a complete file inventory')
    result, seen = [], set()
    for item in entries:
        _require(isinstance(item, dict) and {'path', 'size', 'sha256'} <= set(item) <= {'path', 'size', 'sha256', 'url'}, 'invalid snapshot file record')
        name = _relative(item['path']).as_posix()
        _require(name != 'simscene-lock.json' and name not in seen, 'duplicate or reserved snapshot file')
        _require(type(item['size']) is int and item['size'] >= 0 and isinstance(item['sha256'], str) and re.fullmatch('[0-9a-f]{64}', item['sha256']), 'invalid snapshot file size/hash')
        _require('url' not in item or isinstance(item['url'], str) and item['url'], 'invalid snapshot source URL')
        result.append(dict(item));seen.add(name)
    return sorted(result, key=lambda value: value['path'])


def _state(package):
    package = Path(package)
    lock = package/'simscene-lock.json'
    _require(package.is_dir() and not package.is_symlink() and lock.is_file() and not lock.is_symlink(), 'snapshot package/manifest missing or symlinked')
    metadata = json.loads(lock.read_text())
    files = _files(metadata.get('files'))
    actual = set()
    for node in package.rglob('*'):
        _require(not node.is_symlink() and node.resolve().is_relative_to(package.resolve()), 'snapshot contains a symlink or escaped file')
        if node.is_file():
            actual.add(node.relative_to(package).as_posix())
        else:
            _require(node.is_dir(), 'snapshot contains a nonregular filesystem entry')
    _require(actual == {item['path'] for item in files} | {'simscene-lock.json'}, 'snapshot file inventory has missing or unlisted extra files')
    for item in files:
        path = package.joinpath(*PurePosixPath(item['path']).parts)
        _require(path.is_file() and path.stat().st_size == item['size'] and _sha256(path) == item['sha256'], 'snapshot file content changed: '+item['path'])
    return metadata, files


def pin_snapshot(package, launcher=None, runtime=None):
    """Capture exhaustive manifest/content proof at run snapshot creation."""
    _, files = _state(package)
    from .mdl_snapshot import runtime_closure
    return {'snapshot_integrity_version': 1, 'snapshot_lock_sha256': _sha256(Path(package)/'simscene-lock.json'), 'snapshot_files': files,
            'snapshot_mdl_runtime_files': runtime_closure(package, files, launcher, runtime)}


def verify_snapshot(package, record, run_root=None, launcher=None):
    """Recheck new proof fields; partial or forged proof is never legacy."""
    _require(PIN_FIELDS <= set(record), 'snapshot relocation proof is missing')
    _require(type(record['snapshot_integrity_version']) is int and record['snapshot_integrity_version'] == 1, 'unsupported snapshot integrity version')
    package = Path(package)
    if run_root is not None:
        root = Path(run_root).resolve()
        _require(package.resolve().is_relative_to(root), 'snapshot package escapes the run')
        relative = package.relative_to(root)
        _require(not any(root.joinpath(*relative.parts[:i]).is_symlink() for i in range(1, len(relative.parts)+1)), 'snapshot ancestor is symlinked')
    _require(isinstance(record['snapshot_lock_sha256'], str) and _sha256(package/'simscene-lock.json') == record['snapshot_lock_sha256'], 'snapshot manifest hash changed')
    metadata, files = _state(package)
    _require(files == _files(record['snapshot_files']), 'pinned snapshot file closure changed')
    _require(metadata.get('source') == record.get('source') and metadata.get('package_sha256') == record.get('package_sha256'), 'snapshot source/package provenance changed')
    from .mdl_snapshot import runtime_closure
    _require(isinstance(record['snapshot_mdl_runtime_files'], dict) and record['snapshot_mdl_runtime_files'] == runtime_closure(package, files, launcher, record.get('runtime_provided_dependencies', {})), 'pinned runtime MDL closure changed')
    return metadata, files


def _dependencies(package, selected, files, runtime):
    """Prove local USD/MDL resolution; only explicit SDK MDLs may be external."""
    try:
        from pxr import Sdf, UsdUtils
    except ImportError as error:
        raise ValueError('USD bindings required for trusted snapshot relocation') from error
    allowed = {Path(value).resolve() for value in runtime.values()}
    members = {item['path'] for item in files}

    def checked(value):
        text = str(value)
        if text in runtime:
            return
        _require(text and '://' not in text and not text.startswith(('anon:', 'package:')), 'nonlocal or anonymous asset dependency')
        path = Path(text)
        _require(path.is_absolute(), 'dependency was not resolved to an absolute file')
        path = path.resolve()
        if path in allowed:
            return
        _require(path.is_relative_to(package.resolve()) and path.relative_to(package.resolve()).as_posix() in members and path.is_file(), 'asset dependency resolves outside its verified snapshot')

    usd = [package/item['path'] for item in files if Path(item['path']).suffix.lower() in ('.usd', '.usda', '.usdc')]
    _require(selected in usd, 'selected root is not a supported verified USD layer')
    # USD keeps a process-wide layer registry. Read the pinned bytes again,
    # even if a caller previously inspected this path before it was sealed.
    for layer_path in usd:
        layer = Sdf.Layer.FindOrOpen(str(layer_path))
        _require(layer is not None and layer.Reload(force=True), 'USD layer could not be freshly read')
    for layer_path in usd:
        layers, assets, unresolved = UsdUtils.ComputeAllDependencies(str(layer_path))
        _require(bool(layers), 'USD dependency scan did not load the layer')
        for layer in layers:
            checked(layer.realPath or layer.identifier)
        for asset in assets:
            checked(asset)
        _require(all(str(value) in runtime for value in unresolved), 'unresolved asset dependency outside explicit runtime MDLs')
    from .mdl_dependencies import references, TEXTURE
    for item in files:
        if not item['path'].lower().endswith('.mdl'):
            continue
        module = package/item['path']
        # The static scanner intentionally skips absolute texture literals.
        # Relocation proof must reject those instead of silently skipping them.
        source = module.read_text(errors='replace')
        token = re.compile(r'"(?:\\.|[^"\\])*"|/\*[\s\S]*?\*/|//[^\n]*')
        source = token.sub(lambda match: match.group(0) if match.group(0).startswith('"') else ' ', source)
        for literal in re.findall(r'"((?:\\.|[^"\\])*)"', source):
            if TEXTURE.search(literal):
                _require('\\' not in literal and ':' not in literal and not literal.startswith('/'), 'MDL contains a nonlocal texture literal')
        for target in references(module):
            checked(target)


def comparison_identity(run_root, obj, record, launcher):
    """Return intrinsic identity only from a newly pinned acquired snapshot."""
    root = Path(run_root).resolve()
    _require(record.get('kind') == 'snapshot', 'external/legacy asset paths have no relocation exemption')
    relative = _relative(record.get('root_relative_to_run'))
    _require(len(relative.parts) >= 3 and relative.parts[0] == 'assets', 'invalid selected snapshot root')
    package = root.joinpath(*relative.parts[:2])
    metadata, files = verify_snapshot(package, record, root, launcher)
    selected_relative = PurePosixPath(*relative.parts[2:]).as_posix()
    selected = package/selected_relative
    _require(selected_relative in {item['path'] for item in files} and Path(obj['asset_path']).expanduser().resolve() == selected.resolve(), 'selected asset root does not match the pinned spec path')
    _require(isinstance(record.get('source'), str) and record['source'], 'snapshot source missing')
    from .runtime_dependencies import classify
    dependencies = classify(metadata.get('unresolved_dependencies', []), isaac_python=launcher)
    _require(not dependencies['unresolved'], 'snapshot metadata has unresolved nonruntime dependencies')
    runtime, hashes = record.get('runtime_provided_dependencies', {}), record.get('runtime_dependency_sha256', {})
    _require(isinstance(runtime, dict) and isinstance(hashes, dict) and set(runtime) == set(hashes) == set(dependencies['runtime_provided']), 'runtime MDL dependency proof incomplete')
    for name, filename in runtime.items():
        path = Path(filename)
        _require(path.resolve() == Path(dependencies['runtime_provided'][name]).resolve() and path.is_file() and _sha256(path) == hashes[name], 'runtime MDL path/content changed')
    _dependencies(package, selected, files, runtime)
    return {'source': record['source'], 'selected_root_within_package': selected_relative,
            'files': files, 'runtime_mdl_sha256': dict(sorted(hashes.items())), 'runtime_mdl_files': record['snapshot_mdl_runtime_files'],
            # The cache's old absolute root is not used for selection. Every
            # other metadata field remains an exact provenance comparison.
            'package_metadata': {k: v for k, v in metadata.items() if k not in ('root', 'files')},
            'lock_metadata': {k: v for k, v in record.items() if k not in PIN_FIELDS | {'root_relative_to_run', 'runtime_provided_dependencies', 'runtime_dependency_sha256'}}}
