"""Machine-side waiting and compact durable receipts for existing jobs."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time


def wait_job(job_id, receipt_path, timeout_s=1800, poll_interval_s=1):
    from .jobs import status
    if (type(timeout_s) not in (int, float) or not 0 < timeout_s <= 86400
            or type(poll_interval_s) not in (int, float) or not .05 <= poll_interval_s <= 60):
        raise ValueError('bounded positive timeout and polling interval required')
    output = Path(receipt_path).expanduser().resolve()
    if output.exists():
        raise ValueError('preserve an existing job receipt')
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    while True:
        state = status(job_id)
        if state['state'] not in ('queued', 'running', 'paused', 'stalled', 'acquiring', 'converting', 'inspecting', 'generating'):
            break
        if time.monotonic()-started >= timeout_s:
            raise TimeoutError('wait budget exhausted; original job is preserved, not restarted or cancelled')
        time.sleep(poll_interval_s)
    observed_exit = type(state.get('exit_code')) is int and state.get('exit_code_inferred') is False
    result = state.get('result') or {}
    receipt = {'schema': 'simscene.job_wait_receipt.v1', 'job_id': job_id,
               'run_id': state.get('run_id'), 'state': state['state'],
               'exit_code': state.get('exit_code'), 'exit_code_observed': observed_exit,
               'result_file': state.get('result_file'), 'log': state.get('log'),
               'progress': state.get('progress'), 'task_status': result.get('task_status'),
               'started_at_utc': started_at, 'completed_at_utc': datetime.now(timezone.utc).isoformat(),
               'wait_wall_s': time.monotonic()-started, 'physical_verification': 'separate required step',
               'physics_accepted': False, 'new_job_started': False,
               'scope': 'Observed completion of the same job, not an independent physical verdict; no old client exit is reconstructed.'}
    if state.get('type')=='asset_preparation':
        receipt.update(job_type='asset_preparation',completion_confirmed=state.get('completion_confirmed') is True,
                       preparation_record=state.get('record_path'),prepared_manifest=result.get('manifest_path'),
                       prepared_manifest_sha256=result.get('manifest_sha256'),
                       scope='Durable preparation completion, not a simulator exit or physical task verdict.')
    if state.get('type')=='asset_generation':
        receipt.update(job_type='asset_generation',completion_confirmed=state.get('completion_confirmed') is True,
                       generation_record=state.get('record_path'),generated_source=result.get('asset_ref'),
                       scope='Durable generated-source completion; preparation and physical verification are separate required steps.')
    with output.open('x') as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2, allow_nan=False); f.write('\n')
    summary={k: receipt[k] for k in ('job_id', 'run_id', 'state', 'exit_code', 'exit_code_observed', 'physics_accepted')}
    if 'completion_confirmed' in receipt:summary['completion_confirmed']=receipt['completion_confirmed']
    return summary | {
        'receipt_ref': str(output), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}
