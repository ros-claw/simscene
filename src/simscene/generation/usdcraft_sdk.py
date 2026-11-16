"""Trusted fixed-template generation through an optional USDCraft SDK runtime."""

COMMIT = '46fec187bdce40845c30863a56143047edc4a263'
RECIPE = 'usdcraft_sdk_guide_plate_v1'
SDK_TIMEOUT_SECONDS = 180


class GenerationCancelled(Exception):
    """The durable job was cancelled while its SDK process group was running."""


def _stop_group(process):
    """Kill the isolated group and wait for live descendants to exit on Linux."""
    import os
    from pathlib import Path
    import signal
    import time

    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)
    proc = Path('/proc')
    if not proc.is_dir():
        raise RuntimeError('cannot verify that the SDK process group has terminated')
    deadline = time.monotonic() + 5
    while True:
        live = False
        for entry in proc.iterdir():
            if not entry.name.isdecimal():
                continue
            try:
                raw = (entry / 'stat').read_text()
                fields = raw[raw.rfind(')') + 2:].split()
                if int(fields[2]) == process.pid and fields[0] not in ('Z', 'X'):
                    live = True
                    break
            except (OSError, IndexError, ValueError):
                continue
        if not live:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError('SDK process group did not terminate')
        time.sleep(.02)


def parameters(recipe_id, value):
    if recipe_id != RECIPE:
        raise ValueError('unknown trusted USDCraft SDK template')
    from .sand3d import parameters as normalize
    return normalize('guide_plate_v1', value)


def validate_runtime(runtime):
    observed = runtime.get('observed', {}) if isinstance(runtime, dict) else {}
    if (not isinstance(runtime, dict) or runtime.get('schema_version') != 1
            or runtime.get('backend') != 'usdcraft_sdk' or runtime.get('reviewed_commit') != COMMIT
            or not isinstance(runtime.get('python'), str) or not runtime['python']
            or not isinstance(observed, dict) or observed.get('usdcraft_commit') != COMMIT
            or observed.get('usdcraft_version') != '1.0.0' or observed.get('source_clean') is not True):
        raise ValueError('generation_runtime_unavailable: configure an explicitly probed reviewed USDCraft SDK runtime')
    return runtime


def _run(task, python, folder):
    import os
    from pathlib import Path
    import subprocess
    import tempfile
    import time
    from ..preparation.jobs import write

    python = str(Path(python).expanduser().absolute())
    if not Path(python).is_file():
        raise ValueError('independent USDCraft SDK interpreter is missing')
    folder = Path(folder).resolve()
    cache = folder / '.sdk-cache'; cache.mkdir(exist_ok=True)
    temporary = folder / '.sdk-tmp'; temporary.mkdir(exist_ok=True)
    bytecode = Path(tempfile.mkdtemp(prefix='.sdk-pycache-', dir=folder))
    task_path = folder / 'sdk-backend-task.json'
    write(task_path, task)
    env = {'PATH': str(Path(python).parent) + ':/usr/bin:/bin',
           'LANG': 'C.UTF-8', 'PYTHONPATH': str(Path(__file__).parents[2]),
           'XDG_CACHE_HOME': str(cache), 'TMPDIR': str(temporary), 'PYTHONDONTWRITEBYTECODE': '1',
           'PYTHONPYCACHEPREFIX': str(bytecode),
           'OMP_NUM_THREADS': '2', 'OPENBLAS_NUM_THREADS': '2', 'MALLOC_ARENA_MAX': '2'}
    with (folder / 'sdk-backend.log').open('ab') as log:
        command = [python, '-S', '-m', 'simscene.generation.usdcraft_backend_worker', str(task_path)]
        process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                                   cwd=folder, start_new_session=True)
        try:
            deadline = time.monotonic() + SDK_TIMEOUT_SECONDS
            while True:
                if task.get('operation') == 'generate' and (folder.parent / 'cancel-request.json').exists():
                    raise GenerationCancelled('USDCraft SDK generation cancelled')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, SDK_TIMEOUT_SECONDS)
                try:
                    code = process.wait(timeout=min(remaining, .1))
                    break
                except subprocess.TimeoutExpired:
                    pass
            if code:
                raise subprocess.CalledProcessError(code, command)
            if task.get('operation') == 'generate' and (folder.parent / 'cancel-request.json').exists():
                raise GenerationCancelled('USDCraft SDK generation cancelled')
        except BaseException:
            # SDK compilation uses multiprocessing. Killing only the immediate
            # backend leaves descendants alive and able to mutate job files.
            _stop_group(process)
            raise


def probe_runtime(python, output, *, checkout=None):
    import json
    from pathlib import Path
    from ..preparation.jobs import write
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise FileExistsError('runtime observation must be a new file')
    output.parent.mkdir(parents=True, exist_ok=True)
    folder = output.with_name(output.name + '.probe')
    folder.mkdir()
    result = folder / 'observed.json'
    task = {'operation': 'probe', 'output': str(result)}
    if checkout is not None:
        task['checkout_path'] = str(Path(checkout).expanduser().absolute())
    _run(task, python, folder)
    runtime = {'schema_version': 1, 'backend': 'usdcraft_sdk', 'python': str(Path(python).expanduser().absolute()),
               'reviewed_commit': COMMIT, 'observed': json.loads(result.read_text())}
    validate_runtime(runtime)
    write(output, runtime)
    return runtime


def generate_asset(recipe_id, value, runtime, *, output_directory, config):
    """Publish only the checked output of the shipped SDK guide-plate template."""
    import fcntl
    import hashlib
    from importlib.resources import files
    import json
    import os
    from pathlib import Path
    import shutil
    import tempfile
    from ..catalog.models import AssetRecord, AssetRef, stable_hash
    from ..catalog.store import CatalogStore
    from ..preparation.jobs import write
    from .sand3d import sha

    p = parameters(recipe_id, value)
    validate_runtime(runtime)
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=False)
    template = files('simscene.generation').joinpath('templates/' + RECIPE + '.py').read_bytes()
    template_sha = hashlib.sha256(template).hexdigest()
    task = {'operation': 'generate', 'recipe_id': recipe_id, 'parameters': p,
            'expected_runtime': runtime['observed'], 'template_sha256': template_sha,
            'output': str(output / 'source.usda'),
            'runtime_output': str(output / 'backend-runtime.json'), 'report_output': str(output / 'sdk-report.json')}
    _run(task, runtime['python'], output)
    source = output / 'source.usda'
    if not source.is_file() or source.is_symlink() or not 0 < source.stat().st_size <= 16 * 1024**2:
        raise ValueError('generation_failed: SDK output missing or exceeded size cap')
    if json.loads((output / 'backend-runtime.json').read_text()) != runtime['observed']:
        raise ValueError('generation_failed: SDK runtime changed during generation')
    report_path = output / 'sdk-report.json'
    report = json.loads(report_path.read_text())
    if not isinstance(report, dict) or any(report.get(key) != expected for key, expected in
            [('check', 'passed'), ('compile', 'passed'), ('closure', 'resolved_locally')]):
        raise ValueError('generation_failed: SDK checks or USD closure did not pass')
    # These auxiliary build artifacts contain per-job paths or binary USD
    # serialization details. Their hashes are kept in the job report, not in
    # the immutable source manifest whose identity is the exported USDA.
    volatile_report_fields = {'compiled_root_sha256', 'compile_report_sha256'}
    stable_report = {key: item for key, item in report.items() if key not in volatile_report_fields}
    identity = {'generation_contract_version': 3, 'recipe_id': recipe_id, 'parameters': p, 'seed': 0,
                'template_sha256': template_sha, 'toolchain': runtime,
                'output_sha256': sha(source)}
    revision = stable_hash(identity)
    ref = AssetRef('local-usdcraft-sdk', recipe_id, revision)
    closure = [{'path': 'source.usda', 'sha256': identity['output_sha256'], 'size_bytes': source.stat().st_size}]
    generated = {'schema_version': 1, 'schema': 'simscene.generated_source.v1', 'asset_ref': ref.to_dict(),
                 'identity': identity, 'files': closure, 'root': 'source.usda',
                 'unit_contract': {'input': 'm', 'output': 'm', 'up_axis': 'Z'},
                 'execution_scope': 'shipped template in a trusted Python and dependency runtime with process limits; no filesystem/network sandbox',
                 'source_physics': 'native rigid body, mass and collider generated; inspection and preparation required',
                 'generator_check': stable_report, 'physics_status': 'not_prepared', 'actual_download_bytes': 0}
    write(output / 'generated.json', generated)
    destination = Path(config['home']) / 'generated_assets' / revision
    destination.parent.mkdir(parents=True, exist_ok=True)
    with (destination.parent / '.publish.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if destination.exists():
            published = json.loads((destination / 'generated.json').read_text())
            if published != generated or sha(destination / 'source.usda') != identity['output_sha256']:
                raise ValueError('immutable generated source collision')
        else:
            with tempfile.TemporaryDirectory(dir=destination.parent, prefix='.publish-') as temporary:
                staging = Path(temporary) / 'asset'; staging.mkdir()
                shutil.copyfile(source, staging / 'source.usda')
                write(staging / 'generated.json', generated)
                os.replace(staging, destination)
    descriptor = {'kind': 'generated_package', 'manifest_path': str(destination / 'generated.json'),
                  'manifest_sha256': sha(destination / 'generated.json'), 'revision': revision}
    license_info = {'status': 'known', 'license': 'Apache-2.0', 'evidence': 'declared',
                    'basis': 'project-owned template and reviewed USDCraft SDK repository',
                    'generator_license': 'Apache-2.0', 'notices_required': True,
                    'license_url': 'https://github.com/NVlabs/USDCraft/blob/' + COMMIT + '/LICENSE',
                    'notice_url': 'https://github.com/NVlabs/USDCraft/blob/' + COMMIT + '/NOTICE',
                    'third_party_notices_url': 'https://github.com/NVlabs/USDCraft/blob/' + COMMIT + '/THIRD_PARTY_NOTICES.md'}
    record = AssetRecord(ref=ref, title='USDCraft SDK parametric guide plate', category='guide', format='usda',
        entry_path='source.usda', dimensions_m=[p['length_m'], p['width_m'], p['thickness_m']],
        license=license_info, physics={'rigid_body': {'value': True, 'evidence': 'declared'},
                                      'collider': {'value': True, 'evidence': 'declared'}},
        availability={'status': 'declared', 'granularity': 'generated', 'estimated_download_bytes': 0,
                      'acquisition': descriptor},
        provenance={'generator': 'usdcraft_sdk', 'reviewed_commit': COMMIT, 'identity': identity,
                    'generated_manifest_sha256': descriptor['manifest_sha256'],
                    'source_physics': generated['source_physics'], 'generator_check': stable_report},
        evidence_level='declared', capabilities={})
    detail = CatalogStore(config['index_directory']).remember(record)
    return {'asset_ref': ref.to_dict(), 'generated_manifest_path': descriptor['manifest_path'],
            'generated_manifest_sha256': descriptor['manifest_sha256'], 'detail_ref': detail,
            'sdk_report_path': str(report_path), 'sdk_report_sha256': sha(report_path),
            'runtime_trust_boundary': 'Python executable, third-party dependencies and local job storage are trusted; no filesystem/network sandbox',
            'actual_download_bytes': 0, 'physics_status': 'not_prepared', 'source_physics': generated['source_physics']}
