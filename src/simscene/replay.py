"""Extract exact recorded rigid poses for camera-only rendering, not simulation.

No pose interpolation, new physics success or native original-camera provenance
is asserted. The source's immutable bytes and explicit per-frame steps are kept.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def prepare(run_directory, shots_path, destination):
    import numpy as np
    from .run_integrity import verify as verify_inputs
    from .evidence_integrity import verify as verify_outputs
    run = Path(run_directory).expanduser().resolve()
    dest = Path(destination).expanduser().resolve()
    if dest.exists() or dest.is_relative_to(run):
        raise ValueError('use a new replay directory outside the source run')
    shots_path = Path(shots_path).resolve()
    shots = json.loads(shots_path.read_text())
    if not isinstance(shots, list) or not 1 <= len(shots) <= 32:
        raise ValueError('one to32 explicit replay shots required')
    ids, needed, expanded = set(), set(), []
    for shot in shots:
        if set(shot)-{'id', 'start_step', 'end_step', 'stride', 'camera', 'resolution', 'playback_fps', 'render_updates'}:
            raise ValueError('unsupported replay shot field')
        name = shot['id']
        if not isinstance(name, str) or not name.replace('_', '').isalnum() or name in ids:
            raise ValueError('unique alphanumeric shot id required')
        ids.add(name)
        from .capture import resolution
        from .passive import finite, vector
        resolution(shot.get('resolution', [1920, 1080]))
        camera = shot.get('camera')
        if not isinstance(camera, dict) or set(camera)-{'position','target','follow_body','eye_offset','target_offset','focal_length_mm'}:
            raise ValueError('explicit static or following camera required')
        if 'follow_body' in camera:
            if ('position' in camera or 'target' in camera or not isinstance(camera['follow_body'],str)
                    or not vector(camera.get('eye_offset')) or not vector(camera.get('target_offset',[0,0,0]))):
                raise ValueError('following camera needs a body and finite metric offsets')
        elif not vector(camera.get('position')) or not vector(camera.get('target')) or math.dist(camera['position'],camera['target'])<1e-4:
            raise ValueError('camera needs distinct finite position and target')
        if not finite(camera.get('focal_length_mm',45)) or not .1 <= camera.get('focal_length_mm',45) <= 2000:
            raise ValueError('invalid camera focal length')
        if type(shot.get('render_updates',6)) is not int or not 0 <= shot.get('render_updates',6) <= 120:
            raise ValueError('render_updates must be0..120')
        start, end, stride = shot['start_step'], shot['end_step'], shot.get('stride', 2)
        if any(type(v) is not int for v in (start, end, stride)) or not 0 <= start < end <= 72000 or stride not in (1, 2, 3, 4, 6):
            raise ValueError('bounded integer [start,end) and recorded-step stride required')
        fps = shot.get('playback_fps', 30)
        if type(fps) is not int or fps not in (10, 15, 20, 30):
            raise ValueError('unsupported playback fps')
        steps = list(range(start, end, stride)); needed.update(steps)
        expanded.append({**shot, 'source_steps': steps, 'playback_fps': fps,
                         'playback_speed': stride*fps/60, 'duration_s': len(steps)/fps})
    if len(needed) > 18000:
        raise ValueError('replay extraction exceeds18000 exact source samples')
    for verifier in (verify_inputs, verify_outputs):
        result = verifier(run)
        if result.get('passed') is not True:
            raise ValueError('source run integrity failed')
    source_sha = sha(run/'result.json')
    spec = json.loads((run/'spec.json').read_text())
    data = json.loads((run/'result.json').read_text())
    if data.get('partial') is True:
        raise ValueError('complete source result required')
    paths = sorted('/World/'+name.replace('-', '_') for name, obj in spec['objects'].items() if obj.get('dynamic'))
    scheduled = {'/World/'+name.replace('-', '_'): obj['spawn_step']
                 for name, obj in spec['objects'].items() if obj.get('dynamic') and obj.get('spawn_step', 0)}
    rows = {}
    for sample in [data.get('initial_observation', {}), *data.get('samples', [])]:
        if not isinstance(sample,dict):
            raise ValueError('missing recorded sample')
        step = sample.get('physics_steps')
        if step not in needed:
            continue
        if step in rows:
            raise ValueError('duplicate source sample')
        if not math.isclose(sample['simulation_time_s'], step/60, abs_tol=1e-7):
            raise ValueError('source clock is not60Hz')
        rows[step] = sample
    if set(rows) != needed:
        raise ValueError('missing source steps; replay never interpolates or fills gaps')
    steps = sorted(rows)
    poses = np.zeros((len(steps), len(paths), 7), dtype=np.float64)
    present = np.zeros((len(steps), len(paths)), dtype=np.bool_)
    for i, step in enumerate(steps):
        row = rows[step]
        for j, path in enumerate(paths):
            position = row.get('positions', {}).get(path)
            rotation = row.get('orientations_wxyz', {}).get(path)
            if position is None or rotation is None:
                if path in scheduled and step <= scheduled[path]:
                    continue
                raise ValueError('missing recorded rigid pose: '+path+' step'+str(step))
            values = np.array([*position, *rotation], dtype=np.float64)
            if values.shape != (7,) or not np.isfinite(values).all() or abs(np.linalg.norm(values[3:])-1) > 1e-3:
                raise ValueError('invalid recorded pose')
            poses[i, j] = values; present[i, j] = True
    del data, rows
    if sha(run/'result.json') != source_sha:
        raise ValueError('source changed during extraction')
    dest.mkdir(parents=True)
    np.savez_compressed(dest/'poses.npz', steps=np.array(steps, dtype=np.int32), poses=poses, present=present)
    request = {'schema': 'simscene.recorded_pose_replay.v1', 'source_run_directory': str(run),
               'source_run_id': run.name, 'source_sha256': {name: sha(run/name) for name in
                     ['result.json', 'spec.json', 'scene.usda', 'run-lock.json', 'evidence-lock.json']},
               'physics_hz': 60, 'body_paths': paths, 'poses_path': str(dest/'poses.npz'),
               'poses_sha256': sha(dest/'poses.npz'), 'shots': expanded,
               'scope': 'Camera-only render of exact recorded rigid poses. Not another physics run, not original native-camera footage; no missing-step fill or physical pose interpolation.'}
    (dest/'request.json').write_text(json.dumps(request, indent=2, allow_nan=False)+'\n')
    return {'request': str(dest/'request.json'), 'sha256': sha(dest/'request.json'),
            'exact_samples': len(steps), 'bodies': len(paths), 'new_physics_runs': 0}


def launch(request_path, isaac_python, background=True):
    request_path = Path(request_path).expanduser().resolve()
    request = json.loads(request_path.read_text())
    if request.get('schema') != 'simscene.recorded_pose_replay.v1':
        raise ValueError('recorded-pose request required')
    root = request_path.parent
    metadata = root/'render-launch.json'
    if metadata.exists():
        prior = json.loads(metadata.read_text())
        if prior['request_sha256'] != sha(request_path):
            raise ValueError('changed request requires a new replay directory')
        return {'launch_ref': str(metadata), 'request_sha256': prior['request_sha256'],
                'pid': prior['pid'], 'deduplicated': True, 'new_physics_runs': 0}
    worker = Path(__file__).resolve().parent/'worker'
    command = [sys.executable, str(worker/'gpu_queue.py'), str(root/'gpu-queue.json'),
               str(Path(isaac_python).expanduser()), str(worker/'replay_render.py'), str(request_path),
               '--request-sha256', sha(request_path)]
    # Reserve before launch; failed reservations are preserved rather than
    # silently replayed as another attempt.
    with (root/'render-launch-reservation.json').open('x') as f:
        json.dump({'request_sha256': sha(request_path), 'command': command}, f, indent=2)
    with (root/'renderer.stdout.log').open('x') as out, (root/'renderer.stderr.log').open('x') as err:
        child = subprocess.Popen(command, stdout=out, stderr=err, start_new_session=True)
    value = {'request_sha256': sha(request_path), 'pid': child.pid, 'command': command,
             'worker_sha256': sha(worker/'replay_render.py'), 'new_physics_runs': 0}
    with metadata.open('x') as f:
        json.dump(value, f, indent=2); f.write('\n')
    if not background:
        code = child.wait()
        if code:
            raise RuntimeError('render failed; inspect '+str(root/'renderer.stderr.log'))
        return status(request_path)
    return {'launch_ref': str(metadata), 'pid': child.pid, 'deduplicated': False, 'new_physics_runs': 0}


def status(request_path):
    request_path = Path(request_path).expanduser().resolve()
    root = request_path.parent
    complete, failure, exited = root/'render-complete.json', root/'render-failure.json', root/'process-exit.json'
    code = json.loads(exited.read_text())['exit_code'] if exited.exists() else None
    state = 'failed' if failure.exists() or code not in (None, 0) else 'rendered' if complete.exists() and code == 0 else 'running_or_queued'
    if complete.exists():
        receipt = json.loads(complete.read_text())
        if receipt.get('request_sha256') != sha(request_path):state = 'stale_request'
        elif receipt.get('new_physics_steps') != 0 or receipt.get('new_physics_runs') != 0:state = 'failed'
    return {'state': state, 'exit_code': code, 'receipt_ref': str(complete) if complete.exists() else None,
            'failure_ref': str(failure) if failure.exists() else None, 'new_physics_runs': 0,
            'scope': 'Rendering status only; the original run remains the physics authority.'}
