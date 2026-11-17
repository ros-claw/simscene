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


class MCPJournal:
    """Keep complete responses in files while returning ordinary Python values."""
    def __init__(self, session, directory):
        self.session = session
        self.directory = Path(directory)
        self.counter = 0

    async def call(self, name, arguments):
        self.counter += 1
        started = time.time()
        response = await self.session.call_tool(name, arguments)
        raw = response.model_dump(mode='json', exclude_none=True)
        _write(self.directory / f'{self.counter:03d}-{name}.json',
               {'tool': name, 'arguments': arguments, 'started_unix': started,
                'finished_unix': time.time(), 'response': raw})
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


async def run(session, plugin, wheel, root, scene_id):
    plugin, wheel, root = Path(plugin).resolve(), Path(wheel).resolve(), Path(root).resolve()
    example = plugin/'examples/automatic_cabinet_layout'
    journal_dir = root/'mcp-calls'; journal_dir.mkdir()
    journal = MCPJournal(session, journal_dir)
    response = await session.read_resource('simscene://runtime/identity')
    identity = json.loads(response.contents[0].text)
    check_identity(identity, plugin, wheel)
    _write(root/'identity.json', {'runtime_identity': identity, 'wheel_path': str(wheel)})
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
    job = await journal.call('simulation_start', {'scene_id': scene_id, 'steps': 600, 'seed': 42,
          'case_path': str(root/'case.json'), 'request_id': f'{scene_id}-physics'})
    _write(root/'physics-job.json', job)  # The durable ID remains available if the client disconnects.
    status = await wait_for_job(journal, job['job_id'], root/'physics-wait.json', 1800)
    result_file = status.get('result_file')
    if not isinstance(result_file, str) or not Path(result_file).is_file():
        raise WorkflowError('completed job did not expose a result file')
    run_directory = Path(result_file).resolve().parent
    if run_directory.name != job.get('run_id'):
        raise WorkflowError('job and run identifiers do not match')
    for name in ('run_verify_lock','run_verify_evidence','run_verify'):
        verified = await journal.call(name, {'job_id': job['job_id']})
        _write(root/f'{name}.json', verified)
        if verified.get('passed') is not True:
            raise WorkflowError(f'{name} did not pass')
    command = [sys.executable, str(example/'check.py'), '--run', str(run_directory),
               '--output', str(root/'physical-check.json')]
    checked = subprocess.run(command, env=dict(os.environ, PYTHONPATH=str(plugin/'server/vendor')),
                             capture_output=True, text=True)
    _write(root/'physical-check-process.json', {'command': command, 'returncode': checked.returncode,
                                                 'stdout': checked.stdout, 'stderr': checked.stderr})
    if checked.returncode or json.loads((root/'physical-check.json').read_text()).get('passed') is not True:
        raise WorkflowError('independent fixed-cabinet physical checker did not pass')
    segments = [{'run_directory': str(run_directory), 'camera': camera,
                 'start_sim_time_s': start, 'end_sim_time_s': end} for camera,start,end in
                [('overview',2/60,1.),('detail',1.,6.),('overview',6.,10+2/60)]]
    movie = root/'technical-1080p.mp4'
    exported = await journal.call('video_export', {'segments': segments, 'destination': str(movie),
                                                   'output_resolution': [1920,1080]})
    _write(root/'video-export.json', exported)
    inspected = await journal.call('video_inspect', {'path': str(movie), 'output_dir': str(root/'decoded'),
                                                     'representative_count': 9})
    _write(root/'video-inspection.json', inspected)
    if not (inspected.get('simulation_timeline') or {}).get('passed'):
        raise WorkflowError('video timeline inspection did not pass')
    from .integration_delivery import check_edit_binding
    media_errors = check_edit_binding(json.loads(movie.with_suffix('.edit.json').read_text()), movie, run_directory)
    if media_errors or inspected.get('decoded_frame_count') != 300:
        raise WorkflowError('technical video does not match the complete recorded run: ' + '; '.join(media_errors))
    paths = {'scene': str(root/'scene.json'), 'run': str(run_directory), 'case': str(root/'case.json'),
             'recipe': str(example/'recipe.json'), 'identity': str(root/'identity.json'), 'video': str(movie),
             'edit_map': str(movie.with_suffix('.edit.json')), 'example_directory': str(example)}
    _write(root/'delivery-paths.json', paths)
    return {'status': 'physical_and_media_checked_needs_visual_review', 'job_id': job['job_id'],
            'run_id': job['run_id'], 'directory': str(root), 'delivery_paths': str(root/'delivery-paths.json'),
            'video_inspection': str(root/'video-inspection.json'), 'video': str(movie),
            'next': 'Actually inspect the opening, closing and final video windows; save an attributed review and assemble a receipt.',
            'scope': 'Fixed example only; sampled frames are not uninterrupted playback or an automatic visual acceptance.'}


async def run_installed(plugin, wheel, root, scene_id, launcher=None):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    plugin, root = Path(plugin).resolve(), Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    launcher = Path(launcher).resolve() if launcher else plugin/'server/launch.py'
    if not launcher.is_file():
        raise WorkflowError('MCP launcher does not exist')
    params = StdioServerParameters(command=sys.executable, args=[str(launcher)], env=dict(os.environ), cwd=str(root))
    with (root/'mcp-stderr.log').open('w', encoding='utf8') as error_log:
        async with stdio_client(params, errlog=error_log) as (reader, writer):
            async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=1900)) as session:
                await session.initialize()
                return await run(session, plugin, wheel, root, scene_id)
