"""Read-only runtime MDL proofs for complete prepared asset snapshots."""
from pathlib import Path, PurePosixPath
import re

from ..cache import _sha256
from ..mdl_snapshot import runtime_closure
from ..runtime_dependencies import classify

PROOF_FIELDS = frozenset({'runtime_provided_dependencies', 'runtime_dependency_sha256',
                          'prepared_mdl_runtime_files'})
BUILTINS = frozenset({'OmniPBR.mdl', 'OmniGlass.mdl'})


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _relative(value):
    _require(isinstance(value, str) and value and '\\' not in value, 'invalid prepared relative path')
    path = PurePosixPath(value)
    _require(not path.is_absolute() and '..' not in path.parts and path.parts
             and path.as_posix() == value and value != '.', 'unsafe prepared relative path')
    return path


def _inventory(package, manifest):
    package = Path(package).absolute()
    _require(package.is_dir() and not any(p.is_symlink() for p in (package, *package.parents)),
             'prepared package is missing or symlinked')
    package = package.resolve()
    _require(isinstance(manifest, dict), 'prepared manifest must be an object')
    entries = manifest.get('files')
    _require(isinstance(entries, list) and 0 < len(entries) <= 4096, 'prepared complete inventory required')
    files = []; names = set()
    for entry in entries:
        _require(isinstance(entry, dict), 'invalid prepared file record')
        name = _relative(entry.get('path')).as_posix()
        size = entry.get('size_bytes', entry.get('size'))
        digest = entry.get('sha256')
        _require(name not in names and name != 'manifest.json', 'duplicate or recursive prepared inventory')
        _require(type(size) is int and size >= 0 and isinstance(digest, str)
                 and re.fullmatch('[0-9a-f]{64}', digest), 'invalid prepared file size/hash')
        path = package / name
        _require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(package)
                 and path.stat().st_size == size and _sha256(path) == digest,
                 'prepared file missing or changed: ' + name)
        names.add(name); files.append({'path': name, 'size': size, 'sha256': digest})
    for node in package.rglob('*'):
        _require(not node.is_symlink() and node.resolve().is_relative_to(package), 'prepared package has a symlink/escaped file')
        _require(node.is_file() or node.is_dir(), 'prepared package has a nonregular entry')
    # Only the root manifest is excluded; nested manifests belong to inventory.
    actual = {node.relative_to(package).as_posix() for node in package.rglob('*')
              if node.is_file() and node != package / 'manifest.json'}
    _require(actual == names, 'prepared inventory is incomplete or has unlisted files')
    selected = _relative(manifest.get('main')).as_posix()
    _require(selected in names and Path(selected).suffix.lower() in {'.usd', '.usda', '.usdc'},
             'prepared selected main is not an inventoried USD layer')
    return package, files


def _runtime_roots(package, manifest, files, launcher):
    try:
        from pxr import Sdf, UsdUtils
    except ImportError as error:
        raise ValueError('USD bindings required for prepared runtime dependency proof') from error
    candidates = classify(sorted(BUILTINS), launcher)['runtime_provided'] if launcher else {}
    runtime = {}
    members = {(package / entry['path']).resolve() for entry in files}

    def builtin(value):
        text = str(value)
        if text in candidates:
            runtime[text] = candidates[text]
            return True
        # An absolute spelling is admitted only if it is exactly the classifier's
        # explicit SDK module path. Matching arbitrary paths by basename is unsafe.
        for name, path in candidates.items():
            if text == path:
                runtime[name] = path
                return True
        return False

    def checked(value):
        text = str(value)
        if builtin(text):
            return
        _require(text and '://' not in text and not text.startswith(('anon:', 'package:')),
                 'nonlocal prepared USD dependency')
        path = Path(text)
        _require(path.is_absolute() and path.is_file() and not path.is_symlink()
                 and path.resolve() in members, 'prepared USD dependency is outside its hashed package: ' + text)

    declarations = manifest.get('runtime_dependencies', [])
    _require(isinstance(declarations, list), 'prepared runtime_dependencies must be a list')
    for entry in declarations:
        _require(isinstance(entry, dict) and entry.get('kind') == 'target_runtime_mdl'
                 and isinstance(entry.get('attribute'), str) and entry['attribute']
                 and isinstance(entry.get('asset'), str) and entry['asset'],
                 'invalid prepared runtime MDL declaration')
        _require(builtin(entry['asset']), 'prepared runtime MDL is not an explicit SDK core builtin: ' + entry['asset'])

    # Original source USD files can retain builtin module references even when
    # the selected derived layer no longer needs them. They remain pinned inputs.
    layers = [package / entry['path'] for entry in files
              if Path(entry['path']).suffix.lower() in {'.usd', '.usda', '.usdc'}]
    for path in layers:
        layer = Sdf.Layer.FindOrOpen(str(path))
        _require(layer is not None and layer.Reload(force=True), 'prepared USD layer cannot be freshly read')
    for path in layers:
        dependencies, assets, unresolved = UsdUtils.ComputeAllDependencies(str(path))
        _require(bool(dependencies), 'prepared USD dependency scan loaded no layers')
        for layer in dependencies:
            checked(layer.realPath or layer.identifier)
        for asset in assets:
            checked(asset)
        for asset in unresolved:
            _require(builtin(asset), 'unclassified unresolved prepared dependency: ' + str(asset))
    return dict(sorted(runtime.items()))


def pin_prepared_runtime(package, manifest, launcher):
    """Pin actual builtin roots and their full existing strict MDL closure."""
    package, files = _inventory(package, manifest)
    runtime = _runtime_roots(package, manifest, files, launcher)
    return {'runtime_provided_dependencies': runtime,
            'runtime_dependency_sha256': {name: _sha256(Path(path)) for name, path in runtime.items()},
            'prepared_mdl_runtime_files': runtime_closure(package, files, launcher, runtime)}


def verify_prepared_runtime(package, manifest, record, launcher):
    """Recompute every dependency; legacy empty proof is accepted only when proven empty."""
    _require(isinstance(record, dict), 'prepared runtime proof record must be an object')
    observed = pin_prepared_runtime(package, manifest, launcher)
    present = PROOF_FIELDS & set(record)
    if not present:
        _require(not manifest.get('runtime_dependencies') and all(not value for value in observed.values()),
                 'prepared runtime MDL proof is missing')
        return True
    _require(present == PROOF_FIELDS, 'prepared runtime MDL proof is incomplete')
    for field in PROOF_FIELDS:
        _require(isinstance(record[field], dict) and record[field] == observed[field],
                 'prepared runtime dependency proof changed: ' + field)
    return True
