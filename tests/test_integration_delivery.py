"""A handoff must not turn missing or mismatched evidence into completion."""
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import zipfile
import os
import subprocess

import pytest


def implementation():
    assert importlib.util.find_spec('simscene.recipes.integration_delivery') is not None, 'delivery handoff is unavailable'
    return importlib.import_module('simscene.recipes.integration_delivery')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def media_fixture(tmp_path):
    run = tmp_path / 'run-a'
    run.mkdir()
    lock = run / 'run-lock.json'
    lock.write_text(json.dumps({'run_id': 'run-a'}))
    evidence = run / 'evidence-lock.json'
    evidence.write_text('{}')
    source = run / 'camera_overview.mp4'
    source.write_bytes(b'source')
    frames = run / 'camera_overview.frames.jsonl'
    frames.write_text('{}\n')
    (run / 'result.json').write_text(json.dumps({'videos': {'overview': {
        'path': str(source), 'frame_manifest': str(frames)}}}))
    video = tmp_path / 'edit.mp4'
    video.write_bytes(b'edited')
    manifest = {'schema': 'simscene.video_edit.v1', 'path': str(video), 'sha256': digest(video),
                'segments': [{'run_id': 'run-a', 'run_directory': str(run), 'camera': 'overview',
                    'source': str(source), 'source_sha256': digest(source),
                    'source_frame_manifest_sha256': digest(frames),
                    'run_lock_sha256': digest(lock), 'evidence_lock_sha256': digest(evidence)}]}
    return run, video, manifest


def test_missing_artifacts_produce_incomplete_receipt_without_automatic_review(tmp_path):
    mod = implementation()
    result = mod.collect_delivery({'scene': str(tmp_path / 'missing.json')})
    assert result['status'] == 'incomplete'
    assert result['visual_review'] == 'not_supplied'
    assert 'scene' in result['missing'] and 'run' in result['missing']
    assert result['physical_status'] == 'not_checked'


def test_receipt_helper_preserves_an_incomplete_result_and_existing_output(tmp_path):
    script = Path(__file__).resolve().parents[1] / 'experiments/assemble_integration_receipt.py'
    assert script.is_file(), 'installed receipt helper is unavailable'
    output = tmp_path / 'receipt.json'
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'))
    command = [sys.executable, str(script), '--output', str(output)]
    first = subprocess.run(command, env=env, capture_output=True, text=True)
    assert first.returncode == 2
    assert json.loads(output.read_text())['status'] == 'incomplete'
    original = output.read_bytes()
    second = subprocess.run(command, env=env, capture_output=True, text=True)
    assert second.returncode != 0 and output.read_bytes() == original


def test_media_mapping_requires_the_actual_run_camera_and_frame_manifest(tmp_path):
    mod = implementation()
    run, video, edit = media_fixture(tmp_path)
    assert mod.check_edit_binding(edit, video, run) == []
    wrong = json.loads(json.dumps(edit))
    wrong['segments'][0]['run_id'] = 'another-run'
    assert mod.check_edit_binding(wrong, video, run)
    wrong = json.loads(json.dumps(edit))
    wrong['segments'][0]['camera'] = 'another-camera'
    assert mod.check_edit_binding(wrong, video, run)
    (run / 'camera_overview.frames.jsonl').write_text('tampered\n')
    assert mod.check_edit_binding(edit, video, run)


def test_visual_review_is_bound_to_the_actual_video_and_remains_a_declaration(tmp_path):
    mod = implementation()
    video = tmp_path / 'film.mp4'
    video.write_bytes(b'candidate')
    review = {'decision': 'accept', 'reviewer': 'human-or-agent', 'video_sha256': digest(video),
              'reviewed_windows': [{'start_s': 0., 'end_s': 1., 'observation': 'action visible'}]}
    assert mod.check_visual_review(review, video, duration_s=1.) == []
    review['video_sha256'] = '0' * 64
    assert mod.check_visual_review(review, video, duration_s=1.)
    review['video_sha256'] = digest(video)
    review['reviewed_windows'] = []
    assert mod.check_visual_review(review, video, duration_s=1.)


def test_missing_review_does_not_hide_an_available_physical_result(tmp_path, monkeypatch):
    mod = implementation()
    from simscene.verification import automatic_cabinet_layout
    run, example = tmp_path / 'run', tmp_path / 'example'
    run.mkdir(); example.mkdir()
    monkeypatch.setattr(automatic_cabinet_layout, 'verify', lambda *_: {'passed': True})
    result = mod.collect_delivery({'run': str(run), 'example_directory': str(example)})
    assert result['status'] == 'incomplete'
    assert result['physical_status'] == 'passed'
    assert result['visual_review'] == 'not_supplied'


def test_runtime_identity_must_match_the_actual_installed_build_record(tmp_path):
    mod = implementation()
    server = tmp_path / 'plugin/server'
    package = server / 'vendor/simscene'
    worker = package / 'worker/isaac_run.py'
    worker.parent.mkdir(parents=True)
    module = package / '__init__.py'; module.write_text('module')
    mcp = package / 'mcp_server.py'; mcp.write_text('server')
    worker.write_text('worker')
    wheel = tmp_path / 'package.whl'
    files = [module, mcp, worker]
    with zipfile.ZipFile(wheel, 'w') as archive:
        for item in files:
            archive.write(item, 'simscene/' + str(item.relative_to(package)))
    claimed = {'source_commit': 'a' * 40, 'source_clean': True, 'wheel_sha256': digest(wheel)}
    (server / 'build-info.json').write_text(json.dumps(claimed))
    runtime = {'schema': 'simscene.runtime_identity.v1', 'module_path': str(module),
               'mcp_server_path': str(mcp), 'worker_path': str(worker),
               'module_sha256': digest(module), 'mcp_server_sha256': digest(mcp),
               'worker_sha256': digest(worker), 'build_info': claimed,
               'python_executable': sys.executable}
    recorded = {str(item.relative_to(package)): digest(item) for item in files}
    assert mod._identity_errors({'runtime_identity': runtime, 'wheel_path': str(wheel)},
                                {'worker_code_sha256': recorded, 'queue_launcher_python': sys.executable}) == []
    # The same wheel and files exist, but the actual installed build-info
    # names another commit. A supplied JSON claim cannot override it.
    (server / 'build-info.json').write_text(json.dumps({**claimed, 'source_commit': 'b' * 40}))
    errors = mod._identity_errors({'runtime_identity': runtime, 'wheel_path': str(wheel)},
                                  {'worker_code_sha256': recorded, 'queue_launcher_python': sys.executable})
    assert any('build' in error for error in errors)
