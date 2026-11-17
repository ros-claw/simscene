"""Assemble a narrow, inspectable handoff for the fixed cabinet example.

This does not sign evidence, attest deadlines or perform a visual review.
"""
import hashlib
import json
import math
from pathlib import Path
import re
import zipfile


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def check_edit_binding(edit, video, run):
    """Check that each declared camera source belongs to this exact run."""
    errors = []
    try:
        video, run = Path(video).resolve(), Path(run).resolve()
        lock = json.loads((run / 'run-lock.json').read_text())
        result = json.loads((run / 'result.json').read_text())
        if (not isinstance(edit, dict) or edit.get('schema') != 'simscene.video_edit.v1'
                or Path(edit.get('path', '')).resolve() != video or edit.get('sha256') != _sha(video)):
            errors.append('edited video identity differs from its mapping')
        segments = edit.get('segments') if isinstance(edit, dict) else None
        if not isinstance(segments, list) or not segments:
            return errors + ['edited video has no source segments']
        if lock.get('requested_physics_steps') != 600 or not math.isclose(lock.get('physics_dt_s', 0), 1 / 60, abs_tol=1e-9):
            errors.append('fixed example requires 600 physics steps at 60 Hz')
        next_frame = 0
        next_output = 0.0
        frame_tables = {}
        for index, segment in enumerate(segments):
            if not isinstance(segment, dict):
                errors.append(f'segment {index} is invalid'); continue
            record = result.get('videos', {}).get(segment.get('camera'))
            valid = (isinstance(record, dict) and segment.get('run_id') == lock.get('run_id')
                     and Path(segment.get('run_directory', '')).resolve() == run
                     and Path(segment.get('source', '')).resolve() == Path(record.get('path', '')).resolve()
                     and segment.get('source_sha256') == _sha(record['path'])
                     and segment.get('source_frame_manifest_sha256') == _sha(record['frame_manifest'])
                     and segment.get('run_lock_sha256') == _sha(run / 'run-lock.json')
                     and segment.get('evidence_lock_sha256') == _sha(run / 'evidence-lock.json'))
            if not valid:
                errors.append(f'segment {index} does not match the run, camera or frame table')
                continue
            if segment['camera'] not in frame_tables:
                if record.get('fps') != 30 or record.get('frames') != 300:
                    errors.append(f'segment {index} does not use the native 30 fps recording')
                    continue
                frame_file = Path(record['frame_manifest'])
                if frame_file.stat().st_size > 5_000_000:
                    errors.append(f'segment {index} frame table is too large')
                    continue
                frames = [json.loads(line) for line in frame_file.read_text().splitlines()]
                if (len(frames) != 300 or any(
                        row.get('frame_id') != i or row.get('physics_step') != 2 + 2 * i
                        or not math.isclose(row.get('sim_time_s', -1), (2 + 2 * i) / 60, abs_tol=1e-8)
                        for i, row in enumerate(frames))):
                    errors.append(f'segment {index} frame table does not cover the fixed run')
                    continue
                frame_tables[segment['camera']] = frames
            start, end = segment.get('source_start_frame'), segment.get('source_end_frame_exclusive')
            if (type(start) is not int or type(end) is not int or not 0 <= start < end <= 300
                    or start != next_frame or segment.get('source_fps') != 30
                    or segment.get('speed') != 1 or segment.get('output_frames') != end - start):
                errors.append(f'segment {index} skips frames or changes their playback speed')
                continue
            expected = {'source_sim_start_s': (2 + 2 * start) / 60,
                        'source_sim_end_s': (2 + 2 * end) / 60,
                        'output_start_s': next_output,
                        'output_end_s': next_output + (end - start) / 30}
            if any(type(segment.get(key)) not in (int, float)
                   or not math.isclose(segment[key], value, abs_tol=1e-6)
                   for key, value in expected.items()):
                errors.append(f'segment {index} has inconsistent source or output timing')
                continue
            next_frame = end
            next_output = expected['output_end_s']
        if next_frame != 300 or not math.isclose(next_output, 10., abs_tol=1e-6):
            errors.append('technical video must cover the complete 10-second run in order')
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        errors.append('cannot verify edited source binding: ' + str(error))
    return errors


def check_visual_review(review, video, duration_s, required_windows=None):
    """Validate an attributed review record; its content remains a declaration."""
    errors = []
    try:
        if not isinstance(review, dict) or review.get('decision') not in ('accept', 'change_needed'):
            return ['an explicit accept or change_needed visual decision is required']
        if not isinstance(review.get('reviewer'), str) or not review['reviewer'].strip():
            errors.append('visual reviewer is required')
        if review.get('video_sha256') != _sha(video):
            errors.append('visual review belongs to a different video')
        windows = review.get('reviewed_windows')
        if (not isinstance(windows, list) or not windows or type(duration_s) not in (int, float)
                or not math.isfinite(duration_s) or duration_s <= 0):
            return errors + ['reviewed action windows and finite video duration are required']
        observed = []
        for window in windows:
            if not isinstance(window, dict):
                errors.append('visual window is invalid'); continue
            start, end = window.get('start_s'), window.get('end_s')
            if (type(start) not in (int, float) or type(end) not in (int, float)
                    or not math.isfinite(start) or not math.isfinite(end)
                    or not 0 <= start < end <= duration_s + 1e-6
                    or not isinstance(window.get('observation'), str) or not window['observation'].strip()):
                errors.append('visual window is outside the video or lacks an observation')
            else:
                observed.append((start, end))
        for required in required_windows or ():
            cursor = required['start_s']
            for start, end in sorted(observed):
                if start <= cursor + 1e-6:
                    cursor = max(cursor, end)
            if cursor < required['end_s'] - 1e-6:
                errors.append('visual review does not cover a required action or final-result window')
    except (OSError, ValueError, TypeError) as error:
        errors.append('cannot read visual-review evidence: ' + str(error))
    return errors


def _identity_errors(identity, run_lock):
    """Compare reported MCP files and wheel with the actual frozen worker copy."""
    errors = []
    try:
        runtime = identity['runtime_identity']
        info = runtime['build_info']
        wheel = Path(identity['wheel_path']).resolve()
        module = Path(runtime['module_path']).resolve()
        server = Path(runtime['mcp_server_path']).resolve()
        worker = Path(runtime['worker_path']).resolve()
        package = module.parent
        if (runtime.get('schema') != 'simscene.runtime_identity.v1' or module.name != '__init__.py'
                or server != package / 'mcp_server.py' or worker != package / 'worker' / 'isaac_run.py'):
            errors.append('reported MCP and worker paths do not belong to one package')
        for field, path in [('module_sha256', module), ('mcp_server_sha256', server), ('worker_sha256', worker)]:
            if runtime.get(field) != _sha(path):errors.append('loaded file changed: ' + field)
        installed_info = json.loads((package.parent.parent / 'build-info.json').read_text())
        if info != installed_info:
            errors.append('reported build record differs from the installed build-info.json')
        if (not isinstance(info, dict) or info.get('wheel_sha256') != _sha(wheel)
                or info.get('source_clean') is not True
                or not isinstance(info.get('source_commit'), str)
                or not re.fullmatch(r'[0-9a-f]{40,64}', info['source_commit'])):
            errors.append('wheel or clean source commit identity is missing or mismatched')
        if Path(runtime.get('python_executable', '')).resolve() != Path(run_lock.get('queue_launcher_python', '')).resolve():
            errors.append('MCP interpreter differs from the run queue launcher')
        recorded = run_lock.get('worker_code_sha256')
        if not isinstance(recorded, dict) or not recorded:
            errors.append('run lacks a worker source snapshot')
        else:
            actual = {str(path.relative_to(package)) for path in package.rglob('*')
                      if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc'}
            if actual != set(recorded):
                errors.append('installed package and frozen worker file inventories differ')
            elif any(_sha(package / name) != digest for name, digest in recorded.items()):
                errors.append('installed package and frozen worker bytes differ')
            else:
                with zipfile.ZipFile(wheel) as archive:
                    wheel_files = {name[len('simscene/'):] for name in archive.namelist()
                                   if name.startswith('simscene/') and not name.endswith('/')}
                    if wheel_files != set(recorded) or any(
                            hashlib.sha256(archive.read('simscene/' + name)).hexdigest() != digest
                            for name, digest in recorded.items()):
                        errors.append('wheel contents differ from the installed worker snapshot')
    except (OSError, ValueError, TypeError, KeyError, AttributeError, zipfile.BadZipFile) as error:
        errors.append('cannot verify installed identity: ' + str(error))
    return errors


def collect_delivery(paths):
    """Recheck available inputs and report incomplete work without inventing review."""
    required = ('scene', 'run', 'case', 'recipe', 'identity', 'video', 'edit_map', 'review', 'example_directory')
    if not isinstance(paths, dict) or set(paths) - set(required):
        raise ValueError('delivery inputs must use the supported artifact names')
    artifacts, missing = {}, []
    for name in required:
        value = paths.get(name)
        path = Path(value).expanduser().resolve() if isinstance(value, str) and value else None
        exists = path is not None and (path.is_dir() if name in ('run', 'example_directory') else path.is_file())
        if not exists:
            missing.append(name)
        else:
            artifacts[name] = {'path': str(path)}
            if path.is_file():artifacts[name]['sha256'] = _sha(path)
    report = {'schema': 'simscene.integration_delivery.v1', 'status': 'incomplete',
              'physical_status': 'not_checked', 'media_status': 'not_checked',
              'visual_review': 'not_supplied' if 'review' in missing else 'not_checked',
              'missing': missing, 'errors': [], 'artifacts': artifacts,
              'scope': ('Fixed cabinet example and its one-run edit. A visual decision is an attributed '
                        'review declaration; hashes are not signatures or deadline evidence.')}
    present = lambda *names: all(name not in missing for name in names)
    run = Path(paths['run']).resolve() if present('run') else None
    example = Path(paths['example_directory']).resolve() if present('example_directory') else None
    lock = None
    if run:
        try:
            lock = json.loads((run / 'run-lock.json').read_text())
        except (OSError, ValueError, TypeError) as error:
            report['errors'].append('run lock unavailable: ' + str(error))
    if run and example:
        try:
            from ..verification.automatic_cabinet_layout import verify
            physical = verify(run, example)
            report['physical_status'] = 'passed' if physical.get('passed') is True else 'failed'
            if report['physical_status'] != 'passed':report['errors'].append('fixed physical checker did not pass')
        except Exception as error:
            report['physical_status'] = 'error'
            report['errors'].append('fixed physical checker could not complete: ' + str(error))
    if lock and present('scene'):
        try:
            if _canonical(json.loads(Path(paths['scene']).read_text())) != lock.get('source_scene_sha256'):
                report['errors'].append('scene content does not match the recorded run')
        except (OSError, ValueError, TypeError) as error:
            report['errors'].append('cannot compare source scene: ' + str(error))
    if lock and present('case') and _sha(paths['case']) != lock.get('acceptance_case_sha256'):
        report['errors'].append('acceptance case does not match the recorded run')
    if example and present('recipe'):
        try:
            if _sha(paths['recipe']) != _sha(example / 'recipe.json'):
                report['errors'].append('recipe differs from the fixed example')
        except OSError as error:
            report['errors'].append('cannot compare fixed recipe: ' + str(error))
    if lock and present('identity'):
        try:
            identity = json.loads(Path(paths['identity']).read_text())
            report['errors'].extend(_identity_errors(identity, lock))
            package = Path(identity['runtime_identity']['module_path']).resolve().parent
            if example and example != package.parent.parent.parent / 'examples' / 'automatic_cabinet_layout':
                report['errors'].append('fixed example is not from the identified installed package')
        except (OSError, ValueError, TypeError, KeyError) as error:
            report['errors'].append('cannot read installed identity: ' + str(error))
    inspected = None
    if run and present('video', 'edit_map'):
        try:
            video, edit_file = Path(paths['video']).resolve(), Path(paths['edit_map']).resolve()
            media_errors = []
            if edit_file != video.with_suffix('.edit.json'):
                media_errors.append('edit mapping is not the video\'s accompanying mapping')
            media_errors.extend(check_edit_binding(json.loads(edit_file.read_text()), video, run))
            from ..video_tools import inspect
            inspected = inspect(video, representative_count=1)
            if not (inspected.get('simulation_timeline') or {}).get('passed'):
                media_errors.append('edited video provenance or timeline did not pass')
            metadata = inspected.get('metadata') or {}
            streams = metadata.get('streams') or []
            stream = streams[0] if streams else {}
            if (inspected.get('decoded_frame_count') != 300
                    or not math.isclose(inspected.get('duration_s', 0), 10., abs_tol=.02)
                    or stream.get('width') != 1920 or stream.get('height') != 1080
                    or stream.get('avg_frame_rate') not in ('30/1', '30')):
                media_errors.append('technical video must decode as 10 seconds of native 1080p30')
            report['media_status'] = 'failed' if media_errors else 'passed'
            report['errors'].extend(media_errors)
        except Exception as error:
            report['media_status'] = 'error'
            report['errors'].append('media check could not complete: ' + str(error))
    if inspected and present('review', 'video'):
        try:
            review = json.loads(Path(paths['review']).read_text())
            # Frame zero corresponds to physics step two; the one-run edit has
            # already been checked for contiguous original-speed coverage.
            required_windows = [
                {'start_s': 0., 'end_s': 1. - 2 / 60},
                {'start_s': 4. - 2 / 60, 'end_s': 5. - 2 / 60},
                {'start_s': 9. - 2 / 60, 'end_s': 10.},
            ]
            report['errors'].extend(check_visual_review(
                review, paths['video'], inspected.get('duration_s'), required_windows))
            report['visual_review'] = review.get('decision', 'not_checked') if isinstance(review, dict) else 'not_checked'
            if report['visual_review'] != 'accept':report['errors'].append('visual review is not accepted')
        except (OSError, ValueError, TypeError) as error:
            report['errors'].append('visual review could not be read: ' + str(error))
    if (not missing and not report['errors'] and report['physical_status'] == 'passed'
            and report['media_status'] == 'passed' and report['visual_review'] == 'accept'):
        report['status'] = 'ready_for_submission'
    return report
