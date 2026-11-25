"""Durable trusted-template jobs with request replay and conservative reconnects."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

from ..preparation.jobs import write

TERMINAL = {'completed','failed','cancelled'}


def owns(job_id):
    return isinstance(job_id,str) and job_id.startswith('gen-')


def directory(job_id, *, config=None):
    if not isinstance(job_id,str) or not re.fullmatch('gen-[0-9a-f]{32}',job_id):
        raise ValueError('invalid generation job ID')
    from ..catalog.config import read
    return Path((config or read())['home'])/'generation_jobs'/job_id


def _receipt(record):
    return {'job_id':record['job_id'],'type':'asset_generation','recipe_id':record['recipe_id']}


def _request_digest(payload):
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _check_expected_intent(expected,recipe_id,parameters,runtime,package):
    """Match a portable lock to the actual runtime and copied trusted template."""
    from ..recipes.io import _generation_intent
    if not isinstance(expected,dict):raise ValueError('invalid portable lock intent')
    if recipe_id=='usdcraft_sdk_guide_plate_v1':
        from .usdcraft_sdk import COMMIT
        generator='usdcraft_sdk'
    else:
        from .sand3d import COMMIT
        generator='sand3d'
    root=Path(package).resolve();template=root/'generation'/'templates'/(recipe_id+'.py')
    if template.is_symlink() or not template.is_file() or not template.resolve().is_relative_to(root):
        raise ValueError('portable lock requires a copied trusted template')
    identity={'recipe_id':recipe_id,'parameters':parameters,'seed':0,'toolchain':runtime,
              'template_sha256':hashlib.sha256(template.read_bytes()).hexdigest()}
    if generator=='usdcraft_sdk':identity['generation_contract_version']=3
    actual=_generation_intent(identity,{'generator':generator,'reviewed_commit':COMMIT})
    if actual!=expected:raise ValueError('frozen runtime or copied template differs from the portable lock')


def _resume_legacy_request(home, request_id, payload):
    """Reconnect old reservations whose original request hash included runtime.

    Do not rewrite the old request or its frozen task. An interrupted or
    ambiguous reservation stays uncertain and can never trigger another job.
    """
    from ..scene import SceneError, _id
    _id(request_id)
    home=Path(home);directory=home/'job-requests'
    if not directory.is_dir():return None
    record_path=directory/(request_id+'.json')
    with (directory/(request_id+'.lock')).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if not record_path.exists():return None
        try: prior=json.loads(record_path.read_text())
        except (OSError,ValueError) as error:raise SceneError('job request record is unreadable') from error
        if prior.get('payload_sha256')==_request_digest(payload):return None
        found=[]
        for path in (home/'generation_jobs').glob('gen-*/job.json'):
            try:record=json.loads(path.read_text())
            except (OSError,ValueError) as error:raise SceneError('generation reservation is unreadable') from error
            if record.get('request_id')==request_id:found.append((path,record))
        if len(found)!=1:raise SceneError('request ID reused with different job parameters or an uncertain reservation')
        path,record=found[0]
        try:task=json.loads((path.parent/'task.json').read_text())
        except (OSError,ValueError) as error:raise SceneError('legacy generation task is unreadable') from error
        if not isinstance(task,dict) or any(task.get(key)!=value for key,value in payload.items()) or not isinstance(task.get('runtime'),dict):
            raise SceneError('request ID reused with different job parameters')
        legacy=dict(payload,runtime=task['runtime'])
        if (record.get('job_id')!=path.parent.name or record.get('request_payload_sha256')!=prior.get('payload_sha256')
                or prior.get('payload_sha256')!=_request_digest(legacy)):
            raise SceneError('legacy generation reservation is inconsistent')
        receipt=_receipt(record)
        if prior.get('state') not in ('starting','started') or (prior.get('state')=='started' and prior.get('result')!=receipt):
            raise SceneError('legacy generation request record is inconsistent')
        return dict(receipt,replayed=True)


def start(recipe_id, parameters, request_id=None, *, config=None, expected_intent=None):
    from ..catalog.config import read
    from ..request_registry import invoke
    from ..jobs import _process_identity
    config=config or read()
    if recipe_id == 'usdcraft_sdk_guide_plate_v1':
        from .usdcraft_sdk import parameters as normalize, validate_runtime
        runtime_key = 'usdcraft_generation_runtime'
    else:
        from .sand3d import parameters as normalize
        validate_runtime = None
        runtime_key = 'generation_runtime'
    normalized=normalize(recipe_id,parameters)
    request_id=request_id or 'generate-'+uuid.uuid4().hex
    payload={'operation':'asset_generate','recipe_id':recipe_id,'parameters':normalized}
    if expected_intent is not None:payload['expected_generation_intent']=expected_intent
    legacy=_resume_legacy_request(config['home'],request_id,payload)
    if legacy is not None:return legacy
    safe_prelaunch_abort=False
    def recover(identifier,digest):
        found=[]
        for path in (Path(config['home'])/'generation_jobs').glob('gen-*/job.json'):
            try:record=json.loads(path.read_text())
            except (OSError,ValueError):return None
            if record.get('request_id') == identifier:
                if record.get('request_payload_sha256') != digest or record.get('job_id') != path.parent.name:return None
                found.append(_receipt(record))
        return found[0] if len(found)==1 else (False if not found and safe_prelaunch_abort else None)
    def launch(identifier,digest):
        nonlocal safe_prelaunch_abort
        try:
            manifest=config.get(runtime_key)
            if not manifest or not Path(manifest).is_file() or Path(manifest).stat().st_size>65536:
                raise ValueError('generation_runtime_unavailable: configure the separately probed runtime manifest for this template')
            runtime=json.loads(Path(manifest).read_text())
            if validate_runtime:
                validate_runtime(runtime)
            else:
                from .sand3d import COMMIT
                if runtime.get('reviewed_commit') != COMMIT or runtime.get('observed',{}).get('sand3d_commit') != COMMIT:
                    raise ValueError('generation_runtime_unavailable: unreviewed generator version')
        except Exception:
            # Only this callback can prove that this failure happened before
            # a job directory or supervisor was created. A later process that
            # merely finds no reservation must still report uncertainty.
            safe_prelaunch_abort=True
            raise
        try:
            job_id='gen-'+uuid.uuid4().hex
            root=directory(job_id,config=config);root.mkdir(parents=True)
            package=root/'runtime'/'simscene'
            shutil.copytree(Path(__file__).parents[1],package,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            if expected_intent is not None:
                _check_expected_intent(expected_intent,recipe_id,normalized,runtime,package)
            write(root/'config.json',config);write(root/'task.json',dict(payload,runtime=runtime))
            record={'schema_version':1,'job_id':job_id,'type':'asset_generation','recipe_id':recipe_id,'state':'queued',
                    'request_id':identifier,'request_payload_sha256':digest,'created_unix_ns':time.time_ns()}
            write(root/'job.json',record)
        except Exception:
            safe_prelaunch_abort=True
            raise
        with (root/'worker.log').open('ab') as log:
            process=subprocess.Popen([sys.executable,'-m','simscene.generation.worker',str(root)],
                env=dict(os.environ,PYTHONPATH=str(root/'runtime')),cwd=str(root),stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        write(root/'launch.json',{'pid':process.pid,'identity':_process_identity(process.pid)})
        return _receipt(record)
    return invoke(config['home'],request_id,payload,launch,recover)


def status(job_id, *, config=None):
    root=directory(job_id,config=config)
    record=json.loads((root/'job.json').read_text())
    if record.get('job_id') != job_id:raise ValueError('generation reservation identity changed')
    if record['state'] not in TERMINAL:
        from ..jobs import _process_identity
        launch=json.loads((root/'launch.json').read_text()) if (root/'launch.json').is_file() else {}
        if not launch.get('identity') or _process_identity(launch.get('pid')) != launch['identity']:
            return dict(record,state='uncertain',reason='No matching live supervisor; reconnect never relaunches this request',completion_confirmed=False)
    return dict(record,completion_confirmed=record['state'] in TERMINAL)


def cancel(job_id, *, config=None):
    root=directory(job_id,config=config)
    record=status(job_id,config=config)
    if record['state'] in TERMINAL:return record
    write(root/'cancel-request.json',{'requested_unix_ns':time.time_ns()})
    return dict(record,cancel_pending=True,completion_confirmed=False)
