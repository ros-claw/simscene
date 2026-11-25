"""Run and verify the packaged one-asset first delivery via MCP."""
import json
from pathlib import Path
import shutil

from .cabinet_mcp_workflow import (
    MCPJournal, WorkflowError, _next_path, _sha, _write, check_identity,
    check_run_scene, prepare_fixed_asset, wait_for_export, wait_for_job,
)
from .cases import freeze_case_file
from .integration_delivery import check_edit_binding, check_visual_review
from .io import resolve_operations

EXAMPLE = 'first_delivery'
STEPS = 240
FPS = 30


def _read(path):
    return json.loads(path.read_text())


async def run(session, plugin, wheel, root, scene_id, resume=False, *, collect_only=False):
    if collect_only and not resume:
        raise WorkflowError('collection mode requires recovery of a previous invocation')
    example = plugin/'examples'/EXAMPLE
    journal_dir = root/'mcp-calls'
    journal_dir.mkdir(exist_ok=resume)
    journal = MCPJournal(session, journal_dir)
    response = await session.read_resource('simscene://runtime/identity')
    identity = json.loads(response.contents[0].text)
    check_identity(identity, plugin, wheel)
    if resume:
        if _read(root/'identity.json') != identity:
            raise WorkflowError('recovery requires the original installed package and wheel')
        scene = _read(root/'scene.json')
        scene_id = scene['scene_id']
    else:
        _write(root/'identity.json', identity)
        response = await session.read_resource('simscene://recipes/examples')
        examples = json.loads(response.contents[0].text)
        if not any(item['id'] == EXAMPLE for item in examples['examples']):
            raise WorkflowError('this installed package does not contain the first delivery example')
        environment = await journal.call('environment_probe', {})
        if not environment.get('isaac', {}).get('available'):
            raise WorkflowError('set SIMSCENE_ISAAC_PYTHON to an executable Isaac Sim python.sh')
        if not all(shutil.which(tool) for tool in ('ffmpeg', 'ffprobe')):
            raise WorkflowError('install FFmpeg and ffprobe on the simulation host before recording')
        lock_path = example/'assets.lock.json'
        selections = _read(lock_path)['assets']
        binding = await prepare_fixed_asset(
            journal, root, scene_id, 'box', 'Ready to Use Rolled Fondant Pure White',
            selections['box'], 1024**2,
        )
        bindings = {'box': binding}
        _write(root/'bindings.json', bindings)
        operations = resolve_operations(_read(example/'recipe.json'), bindings, selections=selections)
        opened = await journal.call('scene_open', {'scene_id': scene_id})
        await journal.call('scene_apply', {'scene_id': scene_id, 'base_revision': opened['revision'],
                                           'request_id': scene_id+'-create', 'operations': operations})
        scene = await journal.call('scene_get', {'scene_id': scene_id})
        _write(root/'scene.json', scene)
        await journal.call('scene_measure', {'scene_id': scene_id, 'ids': ['table', 'box'],
                                             'include_overlap_candidates': True})
        if (await journal.call('scene_validate', {'scene_id': scene_id})).get('issues') != []:
            raise WorkflowError('scene validation reported issues; see the saved MCP response')
        frozen = freeze_case_file(example/'case.json', root/'bindings.json', lock_path, root/'case.json')
        _write(root/'case-freeze.json', frozen)
    case_path = root/'case.json'
    frozen = _read(root/'case-freeze.json')
    case_digest = _sha(case_path)
    if frozen.get('case_sha256') != case_digest or frozen.get('template_sha256') != _sha(example/'case.json'):
        raise WorkflowError('the case or packaged template differs from the saved freeze')
    request = {'scene_id': scene_id, 'steps': STEPS, 'seed': 42,
               'case_path': str(root/'case.json'), 'request_id': scene_id+'-physics'}
    request_path = root/'physics-request.json'
    if resume:
        if _read(request_path) != request:
            raise WorkflowError('original physics request differs from the saved scene')
    else:
        _write(request_path, request)
    receipt = root/'physics-job.json'
    if resume and receipt.is_file():
        job = _read(receipt)
    elif collect_only:
        raise WorkflowError('no saved physics job ID; collection cannot start a new job')
    else:
        if await journal.call('scene_get', {'scene_id': scene_id}) != scene:
            raise WorkflowError('the scene changed before physics; keep the saved scene and start a fresh example')
        job = await journal.call('simulation_start', request)
        _write(receipt, job)
    job_id = job['job_id']
    state = await wait_for_job(journal, job_id, _next_path(root/'physics-wait.json'), 1800)
    run_directory = Path(state['result_file']).resolve().parent
    if run_directory.name != job['run_id']:
        raise WorkflowError('physics job and completed run do not match')
    check_run_scene(scene, run_directory)
    if _read(run_directory/'run-lock.json').get('acceptance_case_sha256') != case_digest:
        raise WorkflowError('the verified run does not contain the saved frozen case')
    check_path = _next_path(root/'physical-check.json')
    checked = await journal.call('run_verify', {'job_id': job_id, 'case_type': 'rigid_asset_smoke'})
    _write(check_path, checked)
    if checked.get('passed') is not True:
        raise WorkflowError(f'physical verification failed; see {check_path}')
    movie = root/'first-delivery.mp4'
    request = {'segments': [{'run_directory': str(run_directory), 'camera': 'drop',
                             'start_sim_time_s': 2/60, 'end_sim_time_s': (STEPS+2)/60}],
               'destination': str(movie), 'request_id': scene_id+'-video', 'output_resolution': [1920, 1080]}
    exported = await wait_for_export(journal, root, request, resume, collect_only=collect_only)
    inspection = await journal.call('video_inspect', {'path': str(movie), 'output_dir': str(_next_path(root/'frames')),
                                                       'representative_count': 5})
    inspection_path = _next_path(root/'video-inspection.json')
    _write(inspection_path, inspection)
    edit = movie.with_suffix('.edit.json')
    errors = check_edit_binding(_read(edit), movie, run_directory, physics_steps=STEPS)
    if (errors or not (inspection.get('simulation_timeline') or {}).get('passed')
            or inspection.get('decoded_frame_count') != STEPS//2):
        raise WorkflowError('video inspection or source mapping failed: '+', '.join(errors))
    result = {'schema': 'simscene.first_delivery.v1', 'status': 'needs_visual_review',
              'physical_status': 'passed', 'media_status': 'passed', 'visual_review': 'pending',
              'physics_job_id': job_id, 'run_id': run_directory.name, 'export_job_id': exported['job_id'],
              'scene': str(root/'scene.json'), 'scene_sha256': _sha(root/'scene.json'),
              'case': str(case_path), 'case_sha256': case_digest,
              'video': str(movie), 'edit_map': str(edit),
              'video_sha256': _sha(movie), 'edit_map_sha256': _sha(edit),
              'check': str(check_path), 'check_sha256': _sha(check_path), 'inspection': str(inspection_path)}
    result_path = _next_path(root/'delivery.json')
    _write(result_path, result)
    return {**result, 'receipt': str(result_path)}


def record_review(directory, review_file):
    """Bind an attributed review to the completed technical delivery."""
    root = Path(directory).resolve()
    receipt = _read(root/'delivery.json')
    movie = root/'first-delivery.mp4'
    edit = movie.with_suffix('.edit.json')
    checked = Path(receipt['check']).resolve()
    if (receipt.get('schema') != 'simscene.first_delivery.v1' or receipt.get('status') != 'needs_visual_review'
            or receipt.get('physical_status') != 'passed' or receipt.get('media_status') != 'passed'
            or Path(receipt['video']).resolve() != movie or Path(receipt['edit_map']).resolve() != edit
            or Path(receipt['scene']).resolve() != root/'scene.json' or _sha(root/'scene.json') != receipt['scene_sha256']
            or Path(receipt['case']).resolve() != root/'case.json' or _sha(root/'case.json') != receipt['case_sha256']
            or checked.parent != root or _sha(checked) != receipt['check_sha256'] or _read(checked).get('passed') is not True
            or _sha(movie) != receipt['video_sha256'] or _sha(edit) != receipt['edit_map_sha256']):
        raise WorkflowError('delivery artifacts differ from the technical receipt')
    review = _read(Path(review_file))
    errors = check_visual_review(review, movie, STEPS/60, [{'start_s': 0., 'end_s': .5}, {'start_s': 2., 'end_s': STEPS/60}])
    if errors:
        raise WorkflowError('review does not cover the fall and settled result: '+', '.join(errors))
    decision = review['decision']
    receipt.update(status='ready_for_submission' if decision == 'accept' else 'change_needed',
                   visual_review=decision, review=review)
    output = _next_path(root/'reviewed-delivery.json')
    _write(output, receipt)
    return {'status': receipt['status'], 'video': str(movie), 'receipt': str(output)}
