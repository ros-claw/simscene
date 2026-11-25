"""Export reservations must survive losing the initiating client."""
import hashlib
import json
import subprocess
import sys
import time

import pytest

from simscene import jobs
from simscene.scene import SceneError


def test_failed_export_reuses_the_original_job_after_a_lost_response(tmp_path, monkeypatch):
    from simscene import mcp_server
    monkeypatch.setenv('SIMSCENE_HOME', str(tmp_path/'state'))
    destination = tmp_path/'movie.mp4'
    segments = [{'run_directory': str(tmp_path/'missing-run'), 'camera': 'overview'}]
    request_id = 'cabinet-export'
    handle = mcp_server.video_export_start(segments, str(destination), request_id)
    job_id = 'export-' + hashlib.sha256(request_id.encode()).hexdigest()

    # The tool response was lost. Read the stable ID via another interpreter.
    status = json.loads(subprocess.check_output(
        [sys.executable, '-c', f'import json; from simscene.jobs import status; print(json.dumps(status({job_id!r})))'],
        text=True,
    ))
    assert status['job_id'] == job_id == handle['job_id']
    again = mcp_server.video_export_start(segments, str(destination), request_id)
    assert again['job_id'] == job_id and again['replayed'] is True
    with pytest.raises(SceneError, match='different job parameters'):
        mcp_server.video_export_start(segments, str(tmp_path/'other.mp4'), request_id)

    deadline = time.monotonic()+12
    while time.monotonic() < deadline:
        status = jobs.status(job_id)
        if status['state'] not in {'queued', 'running'}:
            break
        time.sleep(.05)
    assert status['state'] == 'failed'
    assert 'run-lock.json' in status['error']
    assert not destination.exists()
    assert not destination.with_suffix('.edit.json').exists()
    assert len(list((tmp_path/'state'/'video_exports').iterdir())) == 1


def test_late_export_is_recoverable_but_does_not_produce_an_on_time_wait_receipt(tmp_path, monkeypatch):
    from simscene import workflows

    actual_clock = time.time_ns()
    finished = actual_clock + 2_000_000_000
    state = {'job_id': 'export-test', 'type': 'video_export', 'state': 'completed',
             'finished_unix_ns': finished, 'completion_confirmed': True,
             'result': {'visual_review': 'pending'}}
    monkeypatch.setattr(jobs, 'status', lambda _: state)
    original = tmp_path/'original.json'
    monkeypatch.setattr(workflows.time, 'time_ns', lambda: actual_clock)
    with pytest.raises(TimeoutError, match='original job is preserved'):
        workflows.wait_job('export-test', original, timeout_s=1)
    assert not original.exists()
    late = tmp_path/'recovered.json'
    monkeypatch.setattr(workflows.time, 'time_ns', lambda: finished)
    assert workflows.wait_job('export-test', late, timeout_s=1)['completion_confirmed'] is True
    evidence = json.loads(late.read_text())
    assert evidence['finished_unix_ns'] == finished
    assert evidence['visual_review'] == 'pending'
    assert evidence['physics_accepted'] is False
