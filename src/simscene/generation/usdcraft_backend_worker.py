"""Only a bundled guide-plate model is passed to the reviewed USDCraft SDK."""
import hashlib
from importlib import metadata, resources, util
from importlib.machinery import PathFinder
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import sys

from .usdcraft_sdk import COMMIT, RECIPE, parameters


def validate_task(task, folder, *, normalize=True):
    folder = Path(folder).resolve()
    if not isinstance(task, dict):
        raise ValueError('invalid USDCraft SDK backend task')
    if task.get('operation') == 'probe':
        if (set(task) not in ({'operation', 'output'}, {'operation', 'output', 'checkout_path'})
                or task['output'] != str(folder / 'observed.json')
                or 'checkout_path' in task and (not isinstance(task['checkout_path'], str)
                                                or not Path(task['checkout_path']).is_absolute())):
            raise ValueError('invalid USDCraft SDK probe output')
        return
    expected = {'operation', 'recipe_id', 'parameters', 'expected_runtime', 'template_sha256',
                'output', 'runtime_output', 'report_output'}
    if (set(task) != expected or task.get('operation') != 'generate' or task.get('recipe_id') != RECIPE
            or not isinstance(task.get('expected_runtime'), dict)
            or not isinstance(task.get('template_sha256'), str) or not re.fullmatch('[0-9a-f]{64}', task['template_sha256'])
            or task.get('output') != str(folder / 'source.usda')
            or task.get('runtime_output') != str(folder / 'backend-runtime.json')
            or task.get('report_output') != str(folder / 'sdk-report.json')
            or normalize and parameters(RECIPE, task['parameters']) != task['parameters']):
        raise ValueError('invalid trusted USDCraft SDK generation task')


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _git(root, *args):
    git_env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
                   GIT_OPTIONAL_LOCKS='0', GIT_NO_REPLACE_OBJECTS='1')
    return subprocess.run(['/usr/bin/git', '-C', str(root), *args], env=git_env,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=20).stdout


def _verify_checkout(root, commit):
    """Compare every committed file to its Git blob, ignoring index flags."""
    root = Path(root).resolve()
    top = Path(os.fsdecode(_git(root, 'rev-parse', '--show-toplevel')).strip()).resolve()
    if top != root or _git(root, 'rev-parse', 'HEAD').decode().strip() != commit:
        raise ValueError('USDCraft checkout is not at the reviewed commit')
    entries = _git(root, 'ls-tree', '-rz', '--full-tree', commit).split(b'\0')
    committed = set(); directories = {''}
    digest = hashlib.sha256()
    for entry in entries:
        if not entry:
            continue
        header, name = entry.split(b'\t', 1)
        mode, kind, blob = header.split(b' ')
        if mode not in (b'100644', b'100755') or kind != b'blob' or not re.fullmatch(b'[0-9a-f]{40}', blob):
            raise ValueError('unsupported committed SDK file mode or Git blob')
        relative = os.fsdecode(name)
        path = root / relative
        if (path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root.parent)
                or not path.is_file() or not path.resolve().is_relative_to(root)):
            raise ValueError('USDCraft checkout has an unsafe committed file')
        data = path.read_bytes()
        blob_hash = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest().encode()
        if blob_hash != blob:
            raise ValueError('USDCraft checkout file differs from commit blob: ' + relative)
        digest.update(name + b'\0' + hashlib.sha256(data).hexdigest().encode() + b'\0')
        committed.add(relative)
        parent = Path(relative).parent
        while parent != Path('.'):
            directories.add(parent.as_posix())
            parent = parent.parent
    if not committed:
        raise ValueError('USDCraft checkout has no committed files')
    for current, names, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        for name in list(names):
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            if current_path == root and name in {'.git', '.venv'}:
                names.remove(name)
            elif name == '__pycache__' and not path.is_symlink():
                # The subprocess has a fresh PYTHONPYCACHEPREFIX and cannot
                # read these ordinary checkout caches.
                names.remove(name)
            elif path.is_symlink() or relative not in directories:
                raise ValueError('unexpected or untracked checkout directory: ' + relative)
        for name in files:
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink() or relative not in committed:
                raise ValueError('unexpected or untracked checkout file: ' + relative)
    return digest.hexdigest()


def _verify_import_origins(root, search_paths):
    root = Path(root).resolve()
    for name in ('sdk', 'usdcraft', 'storage', 'viewer'):
        spec = PathFinder.find_spec(name, search_paths)
        expected = root / name / '__init__.py'
        if not spec or not spec.origin or Path(spec.origin).resolve() != expected:
            raise ValueError('USDCraft package import origin is shadowed: ' + name)


def _bootstrap(task):
    """Add trusted venv packages without executing .pth or sitecustomize."""
    from urllib.parse import unquote, urlsplit
    if not sys.flags.no_site or not sys.pycache_prefix:
        raise ValueError('USDCraft backend requires -S and isolated bytecode cache')
    venv = Path(sys.executable).absolute().parent.parent
    site_packages = venv / 'lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages'
    if not (venv / 'pyvenv.cfg').is_file() or not site_packages.is_dir():
        raise ValueError('USDCraft requires an independent Python virtual environment')
    checkout = task.get('checkout_path') if task.get('operation') == 'probe' else task.get('expected_runtime', {}).get('repository_path')
    if checkout is None:
        metadata_files = list(site_packages.glob('usdcraft-*.dist-info/direct_url.json'))
        if len(metadata_files) != 1:
            raise ValueError('USDCraft editable checkout location is missing or ambiguous')
        info = json.loads(metadata_files[0].read_text())
        url = urlsplit(info.get('url', ''))
        if info.get('dir_info', {}).get('editable') is not True or url.scheme != 'file' or url.netloc not in ('', 'localhost'):
            raise ValueError('USDCraft must be installed from a local editable checkout')
        checkout = unquote(url.path)
    root = Path(checkout).resolve()
    _verify_checkout(root, COMMIT)
    search_paths = [*sys.path, str(site_packages), str(root)]
    _verify_import_origins(root, search_paths)
    sys.path[:] = search_paths
    return root


def _observe():
    """Pin the checked checkout, tool versions and interpreter without remote access."""
    sdk = util.find_spec('sdk'); package = util.find_spec('usdcraft')
    if not sdk or not package or not sdk.origin or not package.origin:
        raise ValueError('reviewed USDCraft SDK package is not installed')
    root = Path(sdk.origin).resolve().parent.parent
    _verify_import_origins(root, sys.path)
    tree_sha = _verify_checkout(root, COMMIT)
    dependencies = {}
    for name in ('usdcraft', 'usd-core', 'numpy', 'scipy', 'trimesh', 'pydantic', 'networkx'):
        dependencies[name] = metadata.version(name)
    from pxr import Usd
    return {'usdcraft_commit': COMMIT, 'usdcraft_version': dependencies['usdcraft'], 'source_clean': True,
            'source_tree_sha256': tree_sha, 'repository_path': str(root),
            'python_version': list(sys.version_info[:3]), 'python_executable_sha256': _sha(sys.executable),
            'usd_version': list(Usd.GetVersion()), 'dependencies': dependencies}


def run(task, folder):
    folder = Path(folder).resolve()
    validate_task(task, folder)
    observed = _observe()
    if observed['usdcraft_version'] != '1.0.0':
        raise ValueError('USDCraft SDK version differs from the reviewed release')
    if task['operation'] == 'probe':
        Path(task['output']).write_text(json.dumps(observed, sort_keys=True, indent=2) + '\n')
        return
    if observed != task['expected_runtime']:
        raise ValueError('generation runtime changed; explicitly probe again')
    template = resources.files('simscene.generation').joinpath('templates/' + RECIPE + '.py').read_bytes()
    if hashlib.sha256(template).hexdigest() != task['template_sha256']:
        raise ValueError('trusted USDCraft template differs from the frozen job')
    model = folder / 'model.py'
    dimensions = folder / 'dimensions.json'
    with model.open('xb') as stream:
        stream.write(template)
    with dimensions.open('x') as stream:
        json.dump(task['parameters'], stream, sort_keys=True, allow_nan=False)
    from usdcraft.compile import check_model, compile_model
    check_model(model)
    build = folder / 'sdk-build'
    artifacts = compile_model(model, build, clean=False, render=False)
    report = json.loads(Path(artifacts.report_path).read_text())
    if report.get('status') != 'success':
        raise ValueError('USDCraft strict compile did not pass')
    root = Path(artifacts.usdc_path).resolve()
    if not root.is_relative_to(build.resolve()) or not root.is_file() or root.is_symlink():
        raise ValueError('USDCraft compiled root escaped its job')
    from pxr import Sdf, Usd, UsdGeom, UsdPhysics, UsdUtils
    def verify_closure(path):
        layers, assets, unresolved = UsdUtils.ComputeAllDependencies(str(path))
        if assets or unresolved or len(layers) != 1 or Path(layers[0].realPath).resolve() != path.resolve():
            raise ValueError('generated selected USD is not a closed single file')
        stage = Usd.Stage.Open(str(path))
        if (not stage or str(stage.GetDefaultPrim().GetPath()) != '/Asset'
                or not stage.HasAuthoredMetadata('metersPerUnit') or UsdGeom.GetStageMetersPerUnit(stage) != 1.
                or not stage.HasAuthoredMetadata('upAxis') or UsdGeom.GetStageUpAxis(stage) != UsdGeom.Tokens.z):
            raise ValueError('generated USD lacks the expected root, metric units or Z-up')
        return stage
    stage = verify_closure(root)
    rigid = sum(prim.HasAPI(UsdPhysics.RigidBodyAPI) for prim in stage.Traverse())
    colliders = sum(prim.HasAPI(UsdPhysics.CollisionAPI) for prim in stage.Traverse())
    if rigid != 1 or colliders != 1:
        raise ValueError('generated guide plate did not preserve its declared native body and collider')
    output = Path(task['output'])
    if output.exists() or output.is_symlink() or not Sdf.Layer.FindOrOpen(str(root)).Export(str(output)):
        raise ValueError('could not export the isolated generated source')
    verify_closure(output)
    if _observe() != observed:
        raise ValueError('USDCraft SDK runtime changed during generation')
    details = {'check': 'passed', 'compile': 'passed', 'closure': 'resolved_locally',
               'native_rigid_bodies': rigid, 'native_colliders': colliders,
               'compiled_root_sha256': _sha(root), 'compile_report_sha256': _sha(artifacts.report_path)}
    Path(task['runtime_output']).write_text(json.dumps(observed, sort_keys=True, indent=2) + '\n')
    Path(task['report_output']).write_text(json.dumps(details, sort_keys=True, indent=2) + '\n')


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    resource.setrlimit(resource.RLIMIT_FSIZE, (32*1024**2, 32*1024**2))
    resource.setrlimit(resource.RLIMIT_AS, (8*1024**3, 8*1024**3))
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    task_path = Path(sys.argv[1]).resolve()
    folder = Path.cwd().resolve()
    if task_path != folder / 'sdk-backend-task.json':
        raise ValueError('backend task must be the isolated job task')
    task = json.loads(task_path.read_text())
    validate_task(task, folder, normalize=False)
    _bootstrap(task)
    run(task, folder)


if __name__ == '__main__':
    main()
