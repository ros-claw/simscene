"""Persistent preparation reservations; reconnecting never restarts a conversion."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

TERMINAL = {'completed', 'failed', 'cancelled'}


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', dir=path.parent, prefix='.record-', delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.flush(); os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
    finally: temporary.unlink(missing_ok=True)


def directory(job_id, *, config=None):
    from ..catalog.config import read
    if not isinstance(job_id, str) or not re.fullmatch('prep-[0-9a-f]{32}', job_id):
        raise ValueError('invalid preparation job ID')
    return Path((config or read())['home'])/'preparation_jobs'/job_id


def owns(job_id):
    return isinstance(job_id, str) and job_id.startswith('prep-')


def _identity(pid):
    from ..jobs import _process_identity
    return _process_identity(pid)


def _receipt(record):
    return {'job_id':record['job_id'], 'type':'asset_preparation', 'plan_id':record['plan_id']}


def recover(request_id, digest, *, config=None):
    from ..catalog.config import read
    root = Path((config or read())['home'])/'preparation_jobs'
    found = []
    for path in root.glob('prep-*/job.json'):
        if path.is_symlink() or path.parent.is_symlink(): return None
        try: record = json.loads(path.read_text())
        except (OSError, ValueError): return None
        if record.get('request_id') != request_id: continue
        if record.get('request_payload_sha256') != digest: return None
        if record.get('job_id') != path.parent.name: return None
        found.append(_receipt(record))
    if len(found) == 1: return found[0]
    # An absent/missing reservation is not proof that no child was launched.
    # Lost files after an interrupted launch must never trigger an automatic retry.
    return None


def start(plan_id, request_id=None, *, config=None):
    from ..catalog.config import read
    from ..acquisition.plans import load_plan
    from ..request_registry import invoke
    config = config or read(); plan = load_plan(plan_id, config=config)
    if not plan['ready_to_fetch']:
        raise ValueError('plan_not_ready: '+json.dumps(plan['blocking_reasons']))
    request_id = request_id or 'prepare-'+uuid.uuid4().hex
    payload = {'operation':'asset_prepare', 'plan_id':plan_id, 'plan_payload_sha256':plan['plan_payload_sha256']}
    def launch(identifier, digest):
        job_id = 'prep-'+uuid.uuid4().hex; root = directory(job_id, config=config)
        root.mkdir(parents=True)
        write(root/'plan.json', plan); write(root/'config.json', config)
        package = root/'runtime'/'simscene'
        shutil.copytree(Path(__file__).parents[1], package, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        record = {'schema_version':1, 'job_id':job_id, 'type':'asset_preparation', 'plan_id':plan_id,
                  'state':'queued', 'request_id':identifier, 'request_payload_sha256':digest,
                  'created_unix_ns':time.time_ns(), 'checkpoints':[]}
        # A durable reservation precedes launch. Crash here is uncertain, never a retry.
        write(root/'job.json', record)
        env = dict(os.environ, PYTHONPATH=str(root/'runtime'), PYTHONUNBUFFERED='1')
        with (root/'worker.log').open('ab') as log:
            process = subprocess.Popen([sys.executable, '-m', 'simscene.preparation.worker', str(root)],
                                       env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        write(root/'launch.json', {'pid':process.pid, 'identity':_identity(process.pid)})
        return _receipt(record)
    return invoke(config['home'], request_id, payload, launch,
                  lambda identifier,digest:recover(identifier,digest,config=config))


def status(job_id, *, config=None):
    root = directory(job_id, config=config)
    record = json.loads((root/'job.json').read_text())
    if record.get('job_id') != job_id: raise ValueError('invalid preparation record')
    result = {key:record[key] for key in ('job_id','type','plan_id','state','checkpoints') if key in record}
    if record['state'] not in TERMINAL:
        try: launch = json.loads((root/'launch.json').read_text())
        except (OSError, ValueError): launch = None
        if launch is None or not launch.get('identity') or _identity(launch['pid']) != launch['identity']:
            result.update(state='uncertain', error_code='interrupted_job',
                          error='Worker is absent or launch is uncertain; no process has been restarted.')
    for key in ('result','error','error_code','actual_download_bytes'):
        if key in record: result[key] = record[key]
    if (root/'cancel-request.json').is_file(): result['cancel_requested'] = True
    result['record_path'] = str(root/'job.json')
    if record['state']=='completed':
        result['completion_confirmed']=True
        result['physical_verification']='not_run; evaluate a separate frozen simulation run'
    return result


def cancel(job_id, *, config=None):
    root = directory(job_id, config=config); result = status(job_id, config=config)
    if result['state'] not in TERMINAL:
        write(root/'cancel-request.json', {'job_id':job_id, 'requested_unix_ns':time.time_ns()})
        result.update(cancel_requested=True, message='Cancellation awaits a download checkpoint or converter termination confirmation.')
    return result
