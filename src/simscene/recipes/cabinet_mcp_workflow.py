"""Compact, evidence-preserving MCP workflow for one pinned cabinet recipe.

The workflow performs real MCP calls and records their complete responses.
It does not create a visual review or turn a completed job into acceptance.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import timedelta


class WorkflowError(RuntimeError):
    """A selected asset, operation or verification could not be completed."""


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _write(path, value):
    with Path(path).open('x', encoding='utf8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def check_identity(identity, plugin, wheel):
    plugin, wheel = Path(plugin).resolve(), Path(wheel).resolve()
    module = plugin / 'server/vendor/simscene/__init__.py'
    if not module.is_file() or Path(identity.get('module_path', '')).resolve() != module:
        raise WorkflowError('MCP is not running the requested installed package')
    info = identity.get('build_info')
    if (not wheel.is_file() or not isinstance(info, dict) or info.get('source_clean') is not True
            or info.get('wheel_sha256') != _sha(wheel)):
        raise WorkflowError('installed build does not match the supplied clean-source wheel')
    try:
        installed_info = json.loads((plugin/'server/build-info.json').read_text())
    except (OSError, ValueError) as error:
        raise WorkflowError('installed build identity is unreadable') from error
    if installed_info != info:
        raise WorkflowError('installed build record differs from the MCP identity')
    if identity.get('module_sha256') and identity['module_sha256'] != _sha(module):
        raise WorkflowError('installed module changed after MCP startup')
    package = module.parent
    try:
        with zipfile.ZipFile(wheel) as archive:
            names = [name for name in archive.namelist() if name.startswith('simscene/') and not name.endswith('/')]
            expected = {name[len('simscene/'):] for name in names}
            required = {'__init__.py', 'mcp_server.py', 'worker/isaac_run.py',
                        'recipes/cabinet_mcp_workflow.py'}
            actual = {str(path.relative_to(package)) for path in package.rglob('*')
                      if path.is_file() and not path.is_symlink() and '__pycache__' not in path.parts
                      and path.suffix != '.pyc'}
            if len(expected) != len(names) or not required <= expected or actual != expected:
                raise WorkflowError('installed package inventory differs from the wheel')
            for name in expected:
                if '..' in Path(name).parts or hashlib.sha256(archive.read('simscene/'+name)).hexdigest() != _sha(package/name):
                    raise WorkflowError('installed package content differs from the wheel: ' + name)
    except (OSError, ValueError, zipfile.BadZipFile, KeyError) as error:
        raise WorkflowError('cannot verify installed package against its wheel') from error
    manifest_file = plugin/'server/resource-manifest.json'
    try:
        if info.get('resource_manifest_sha256') != _sha(manifest_file):
            raise WorkflowError('installed resource manifest differs from the build record')
        manifest = json.loads(manifest_file.read_text())
        files = manifest.get('files')
        if manifest.get('schema') != 'simscene.packaged_resources.v1' or not isinstance(files, dict) or not files:
            raise WorkflowError('installed resource manifest is invalid')
        for name, digest in files.items():
            relative = Path(name)
            if relative.is_absolute() or '..' in relative.parts or not name or '\\' in name:
                raise WorkflowError('installed resource manifest contains an unsafe path')
            path = plugin/relative
            if path.is_symlink() or not path.is_file() or _sha(path) != digest:
                raise WorkflowError('installed resource changed: ' + name)
    except (OSError, ValueError, TypeError, AttributeError) as error:
        raise WorkflowError('cannot verify installed resources') from error


def new_scene_id():
    return 'compact_cabinet_' + uuid.uuid4().hex[:16]


def read_recovery_request(root):
    root = Path(root).resolve()
    try:
        request = json.loads((root/'physics-request.json').read_text())
        if (set(request) != {'scene_id', 'steps', 'seed', 'case_path', 'request_id'}
                or request['steps'] != 600 or request['seed'] != 42
                or Path(request['case_path']).resolve() != root/'case.json'
                or not isinstance(request['scene_id'], str) or not request['scene_id']
                or request['request_id'] != request['scene_id'] + '-physics'):
            raise ValueError('invalid fixed request')
        return request
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise WorkflowError('original physics recovery request is missing or invalid') from error


def _scene_hash(scene):
    return hashlib.sha256(json.dumps(scene, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def check_run_scene(scene, run_directory):
    try:
        lock = json.loads((Path(run_directory)/'run-lock.json').read_text())
        if (lock.get('source_scene_sha256') != _scene_hash(scene)
                or lock.get('scene_revision') != scene.get('revision')):
            raise WorkflowError('run scene or revision differs from the saved scene')
    except (OSError, ValueError, TypeError, AttributeError) as error:
        raise WorkflowError('cannot bind the run to the saved scene') from error


def _next_path(path):
    path = Path(path)
    if not path.exists():
        return path
    for index in range(1, 10000):
        candidate = path.with_name(f'{path.stem}-recheck-{index}{path.suffix}')
        if not candidate.exists():
            return candidate
    raise WorkflowError('too many retained recovery records')


class MCPJournal:
    """Keep complete responses in files while returning ordinary Python values."""
    def __init__(self, session, directory):
        self.session = session
        self.directory = Path(directory)
        self.counter = len(list(self.directory.glob('*-request.json')))

    async def call(self, name, arguments):
        self.counter += 1
        started = time.time()
        base = f'{self.counter:03d}-{name}'
        _write(self.directory/f'{base}-request.json', {'tool': name, 'arguments': arguments, 'started_unix': started})
        try:
            response = await self.session.call_tool(name, arguments)
        except Exception as error:
            _write(self.directory/f'{base}-response.json', {'tool': name, 'finished_unix': time.time(),
                    'exception': {'type': type(error).__name__, 'message': str(error)[:1000]}})
            raise WorkflowError(f'{name} failed; inspect the recorded MCP exception') from error
        raw = response.model_dump(mode='json', exclude_none=True)
        _write(self.directory/f'{base}-response.json', {'tool': name, 'finished_unix': time.time(), 'response': raw})
        if response.isError:
            raise WorkflowError(f'{name} failed; inspect the recorded MCP response')
        value = response.structuredContent
        if value is None:
            try:
                value = json.loads(response.content[0].text)
            except (IndexError, AttributeError, ValueError, TypeError) as error:
                raise WorkflowError(f'{name} did not return structured JSON') from error
        if not isinstance(value, dict):
            raise WorkflowError(f'{name} returned an unexpected result')
        return value


async def wait_for_job(journal, job_id, receipt, timeout):
    waited = await journal.call('job_status', {'job_id': job_id, 'wait_seconds': float(timeout),
                                               'receipt_path': str(receipt)})
    if waited.get('state') != 'completed':
        raise WorkflowError(f'job {job_id} {waited.get("state", "unknown")}; reconnect using its saved job ID')
    actual = await journal.call('job_status', {'job_id': job_id})
    if actual.get('state') != 'completed':
        raise WorkflowError(f'job {job_id} {actual.get("state", "unknown")} after waiting')
    return actual


async def wait_for_export(journal, root, request, resume, *, collect_only=False):
    from ..video_export_jobs import export_job_id

    request_path = root/'video-request.json'
    job_id = export_job_id(request['request_id'])
    if not request_path.exists():
        if collect_only:
            raise WorkflowError('no saved video export request; collection cannot start a new job')
        _write(request_path, request)
        handle = await journal.call('video_export_start', request)
        if handle.get('job_id') != job_id:
            raise WorkflowError('export job ID differs from the saved request')
        _write(root/'video-job.json', handle)
    elif not resume or json.loads(request_path.read_text()) != request:
        raise WorkflowError('existing video request differs or recovery was not requested')
    # A lost start response still identifies the same durable reservation.
    actual = await wait_for_job(journal, job_id, _next_path(root/'video-wait.json'), 1800)
    movie = Path(request['destination'])
    result = actual.get('result') or {}
    if (actual.get('job_id') != job_id or result.get('video') != str(movie)
            or result.get('edit_map') != str(movie.with_suffix('.edit.json'))):
        raise WorkflowError('export job does not match the requested movie and edit map')
    return actual


def _helper(plugin, directory, name, arguments):
    command = [sys.executable, str(plugin/'experiments'/name), *map(str, arguments)]
    env = dict(os.environ, PYTHONPATH=str(plugin/'server/vendor'))
    process = subprocess.run(command, env=env, capture_output=True, text=True)
    log = directory / f'helper-{len(list(directory.glob("helper-*.json")))+1:03d}.json'
    _write(log, {'command': command, 'returncode': process.returncode,
                 'stdout': process.stdout, 'stderr': process.stderr})
    if process.returncode:
        raise WorkflowError(f'{name} failed; inspect {log}')
    try:
        return json.loads(process.stdout)
    except ValueError as error:
        raise WorkflowError(f'{name} did not return JSON; inspect {log}') from error


async def run(session, plugin, wheel, root, scene_id, resume=False, *, collect_only=False):
    plugin, wheel, root = Path(plugin).resolve(), Path(wheel).resolve(), Path(root).resolve()
    if collect_only and not resume:
        raise WorkflowError('collection mode requires recovery of a previous invocation')
    example = plugin/'examples/automatic_cabinet_layout'
    journal_dir = root/'mcp-calls'
    if resume and not journal_dir.is_dir():
        raise WorkflowError('recovery requires the original MCP journal')
    journal_dir.mkdir(exist_ok=resume)
    journal = MCPJournal(session, journal_dir)
    response = await session.read_resource('simscene://runtime/identity')
    identity = json.loads(response.contents[0].text)
    check_identity(identity, plugin, wheel)
    identity_record = {'runtime_identity': identity, 'wheel_path': str(wheel)}
    if resume:
        if json.loads((root/'identity.json').read_text()) != identity_record:
            raise WorkflowError('recovery requires the same installed package and wheel')
        physics_request = read_recovery_request(root)
        if scene_id and scene_id != physics_request['scene_id']:
            raise WorkflowError('recovery scene ID differs from the saved request')
        scene_id = physics_request['scene_id']
        scene = json.loads((root/'scene.json').read_text())
    else:
        _write(root/'identity.json', identity_record)
        response = await session.read_resource('simscene://recipes/examples')
        examples = json.loads(response.contents[0].text)
        _write(root/'examples.json', examples)
        if not any(x.get('id') == 'automatic_cabinet_layout' for x in examples.get('examples', [])):
            raise WorkflowError('installed fixed cabinet recipe is unavailable')
        lock = json.loads((example/'assets.lock.json').read_text())
        bindings = {}
        for role, query in [('cabinet', 'Lift-Up Wall Cabinet'),
                            ('book_a', 'AmazonBasics Classic Blank Notebook'),
                            ('box', 'Ready to Use Rolled Fondant Pure White')]:
            selected = lock['assets'][role]
            found = await journal.call('catalog_search', {'query': query,
                     'filters': {'source_ids': [selected['source_ref']['source_id']]}, 'limit': 20})
            budgets = found.get('budgets', {})
            if budgets.get('model_bytes') != 0 or budgets.get('preview_bytes') != 0:
                raise WorkflowError(f'{role} metadata search downloaded a model or preview, or did not report bytes')
            item = next((x for x in found.get('items', []) if x.get('ref') == selected['source_ref']), None)
            if not item:
                raise WorkflowError(f'locked {role} was not returned by the catalog')
            plan = await journal.call('asset_plan', {'asset_ref': item['ref'], 'profile_id': selected['profile_id'],
                                      'parameters': selected['parameters'], 'budget_bytes': 50_000_000})
            if not plan.get('ready_to_fetch'):
                raise WorkflowError(f'locked {role} is blocked; inspect asset_plan')
            job = await journal.call('asset_prepare', {'plan_id': plan['plan_id'],
                                                       'request_id': f'{scene_id}-prepare-{role}'})
            _write(root/f'prepare-{role}-job.json', job)
            done = await wait_for_job(journal, job['job_id'], root/f'prepare-{role}-wait.json', 300)
            prepared = done['result']
            bindings[role] = {'asset_path': prepared['root'], 'asset_binding': {
                'manifest_path': prepared['manifest_path'], 'manifest_sha256': prepared['manifest_sha256']}}
        _write(root/'bindings.json', bindings)
        _helper(plugin, root, 'apply_scene_recipe.py', [example/'recipe.json', '--asset-catalog', root/'bindings.json',
                '--asset-lock', example/'assets.lock.json', '--save-directory', root/'ops', '--operations-only'])
        operations = json.loads((root/'ops/resolved-operations.json').read_text())
        opened = await journal.call('scene_open', {'scene_id': scene_id})
        await journal.call('scene_apply', {'scene_id': scene_id, 'base_revision': opened['revision'],
                                           'request_id': f'{scene_id}-create', 'operations': operations})
        scene = await journal.call('scene_get', {'scene_id': scene_id})
        _write(root/'scene-before-layout.json', scene)
        _helper(plugin, root, 'check_motion_clearance.py', ['--scene', root/'scene-before-layout.json',
                '--owner', 'cabinet', '--profile', 'usdcraft_lift_cabinet_v1', '--output', root/'motion-before.json'])
        sweep = json.loads((root/'motion-before.json').read_text())
        if sweep.get('status') != 'not_checked' or not sweep.get('keepout_bounds'):
            raise WorkflowError('cabinet motion envelope was not computed')
        reserve = json.loads((example/'supplemental-checks.json').read_text())['reserved_volume']
        if not all(all(reserve['min'][i] <= bound['min'][i] and reserve['max'][i] >= bound['max'][i]
                       for i in range(3)) for bound in sweep['keepout_bounds']):
            raise WorkflowError('fixed reserved volume no longer encloses the measured cabinet sweep')
        proposal = await journal.call('scene_plan_layout', {'scene_id': scene_id, 'ids': ['box','book_a','book_b'],
                 'support': 'table', 'seed': 42, 'clearance_m': .05, 'gap_m': .04,
                 'avoid_ids': ['cabinet'], 'keepout_bounds': [reserve]})
        await journal.call('scene_apply', {'scene_id': scene_id, 'base_revision': proposal['base_revision'],
                                           'request_id': f'{scene_id}-layout', 'operations': proposal['operations']})
        scene = await journal.call('scene_get', {'scene_id': scene_id}); _write(root/'scene.json', scene)
        _helper(plugin, root, 'check_motion_clearance.py', ['--scene', root/'scene.json', '--owner', 'cabinet',
                '--profile', 'usdcraft_lift_cabinet_v1', '--object', 'box', '--object', 'book_a', '--object', 'book_b',
                '--output', root/'motion-after.json'])
        if json.loads((root/'motion-after.json').read_text()).get('status') != 'clear':
            raise WorkflowError('the applied layout conflicts with the cabinet motion envelope')
        measurements = await journal.call('scene_measure', {'scene_id': scene_id,
              'ids': ['floor','table','cabinet','box','book_a','book_b'], 'include_overlap_candidates': True})
        _write(root/'measurements.json', measurements)
        validation = await journal.call('scene_validate', {'scene_id': scene_id})
        if validation.get('issues') != []:
            raise WorkflowError('scene validation reported issues; inspect MCP transcript')
        _helper(plugin, root, 'freeze_recipe_case.py', [example/'case.json', '--bindings', root/'bindings.json',
                '--asset-lock', example/'assets.lock.json', '--output', root/'case.json'])
        physics_request = {'scene_id': scene_id, 'steps': 600, 'seed': 42,
                           'case_path': str(root/'case.json'), 'request_id': f'{scene_id}-physics'}
        _write(root/'physics-request.json', physics_request)
    job_file = root/'physics-job.json'
    if resume and job_file.exists():
        job = json.loads(job_file.read_text())
    elif collect_only:
        raise WorkflowError('no saved physics job ID; collection cannot start a new job')
    else:
        current_scene = await journal.call('scene_get', {'scene_id': scene_id})
        if _scene_hash(current_scene) != _scene_hash(scene):
            raise WorkflowError('current scene differs from the saved preflight scene')
        job = await journal.call('simulation_start', physics_request)
        _write(job_file, job)
    status = await wait_for_job(journal, job['job_id'], _next_path(root/'physics-wait.json'), 1800)
    result_file = status.get('result_file')
    if not isinstance(result_file, str) or not Path(result_file).is_file():
        raise WorkflowError('completed job did not expose a result file')
    run_directory = Path(result_file).resolve().parent
    if run_directory.name != job.get('run_id'):
        raise WorkflowError('job and run identifiers do not match')
    check_run_scene(scene, run_directory)
    for name in ('run_verify_lock','run_verify_evidence','run_verify'):
        verified = await journal.call(name, {'job_id': job['job_id']})
        _write(_next_path(root/f'{name}.json'), verified)
        if verified.get('passed') is not True:
            raise WorkflowError(f'{name} did not pass')
    physical_check = _next_path(root/'physical-check.json')
    command = [sys.executable, str(example/'check.py'), '--run', str(run_directory),
               '--output', str(physical_check)]
    checked = subprocess.run(command, env=dict(os.environ, PYTHONPATH=str(plugin/'server/vendor')),
                             capture_output=True, text=True)
    _write(_next_path(root/'physical-check-process.json'), {'command': command, 'returncode': checked.returncode,
                                                 'stdout': checked.stdout, 'stderr': checked.stderr})
    if checked.returncode or json.loads(physical_check.read_text()).get('passed') is not True:
        raise WorkflowError('independent fixed-cabinet physical checker did not pass')
    segments = [{'run_directory': str(run_directory), 'camera': camera,
                 'start_sim_time_s': start, 'end_sim_time_s': end} for camera,start,end in
                [('overview',2/60,1.),('detail',1.,6.),('overview',6.,10+2/60)]]
    movie = root/'technical-1080p.mp4'
    export_request = {'segments': segments, 'destination': str(movie),
                      'request_id': f'{scene_id}-video', 'output_resolution': [1920, 1080]}
    exported = await wait_for_export(journal, root, export_request, resume, collect_only=collect_only)
    _write(_next_path(root/'video-export.json'), exported)
    inspected = await journal.call('video_inspect', {'path': str(movie), 'output_dir': str(_next_path(root/'decoded')),
                                                     'representative_count': 9})
    inspection_path = _next_path(root/'video-inspection.json')
    _write(inspection_path, inspected)
    if not (inspected.get('simulation_timeline') or {}).get('passed'):
        raise WorkflowError('video timeline inspection did not pass')
    from .integration_delivery import check_edit_binding
    media_errors = check_edit_binding(json.loads(movie.with_suffix('.edit.json').read_text()), movie, run_directory)
    if media_errors or inspected.get('decoded_frame_count') != 300:
        raise WorkflowError('technical video does not match the complete recorded run: ' + '; '.join(media_errors))
    paths = {'scene': str(root/'scene.json'), 'run': str(run_directory), 'case': str(root/'case.json'),
             'recipe': str(example/'recipe.json'), 'identity': str(root/'identity.json'), 'video': str(movie),
             'edit_map': str(movie.with_suffix('.edit.json')), 'example_directory': str(example)}
    delivery_file = root/'delivery-paths.json'
    if delivery_file.exists():
        if json.loads(delivery_file.read_text()) != paths:
            raise WorkflowError('existing delivery paths do not match the recovered run')
    else:
        _write(delivery_file, paths)
    return {'status': 'physical_and_media_checked_needs_visual_review', 'job_id': job['job_id'],
            'run_id': job['run_id'], 'directory': str(root), 'delivery_paths': str(root/'delivery-paths.json'),
            'video_inspection': str(inspection_path), 'video': str(movie),
            'next': 'Actually inspect the opening, closing and final video windows; save an attributed review and assemble a receipt.',
            'scope': 'Fixed example only; sampled frames are not uninterrupted playback or an automatic visual acceptance.'}


def select_launcher(plugin, requested=None):
    configured = os.environ.get('SIMSCENE_MCP_LAUNCHER')
    if configured:
        selected = Path(configured).expanduser().resolve()
        if requested and Path(requested).expanduser().resolve() != selected:
            raise WorkflowError('requested launcher differs from the configured MCP launcher')
        return selected
    return Path(requested).expanduser().resolve() if requested else Path(plugin).resolve()/'server/launch.py'


async def run_installed(plugin, wheel, root, scene_id, launcher=None, resume=False, *, collect_only=False):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    plugin, root = Path(plugin).resolve(), Path(root).resolve()
    if resume:
        if not root.is_dir():raise WorkflowError('recovery output directory does not exist')
    else:
        root.mkdir(parents=True, exist_ok=False)
    launcher = select_launcher(plugin, launcher)
    if not launcher.is_file():
        raise WorkflowError('MCP launcher does not exist')
    params = StdioServerParameters(command=sys.executable, args=[str(launcher)], env=dict(os.environ), cwd=str(root))
    with _next_path(root/'mcp-stderr.log').open('x', encoding='utf8') as error_log:
        async with stdio_client(params, errlog=error_log) as (reader, writer):
            async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=1900)) as session:
                await session.initialize()
                return await run(session, plugin, wheel, root, scene_id, resume=resume, collect_only=collect_only)
