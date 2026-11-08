"""Durable trusted-template jobs with request replay and conservative reconnects."""
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


def start(recipe_id, parameters, request_id=None, *, config=None):
    from ..catalog.config import read
    from ..request_registry import invoke
    from ..jobs import _process_identity
    from .sand3d import parameters as normalize
    config=config or read()
    normalized=normalize(recipe_id,parameters)
    manifest=config.get('generation_runtime')
    if not manifest or not Path(manifest).is_file() or Path(manifest).stat().st_size>65536:
        raise ValueError('generation_runtime_unavailable: configure a separately probed Sand3D runtime manifest')
    runtime=json.loads(Path(manifest).read_text())
    from .sand3d import COMMIT
    if runtime.get('reviewed_commit') != COMMIT or runtime.get('observed',{}).get('sand3d_commit') != COMMIT:
        raise ValueError('generation_runtime_unavailable: unreviewed generator version')
    request_id=request_id or 'generate-'+uuid.uuid4().hex
    payload={'operation':'asset_generate','recipe_id':recipe_id,'parameters':normalized,'runtime':runtime}
    def recover(identifier,digest):
        found=[]
        for path in (Path(config['home'])/'generation_jobs').glob('gen-*/job.json'):
            try:record=json.loads(path.read_text())
            except (OSError,ValueError):return None
            if record.get('request_id') == identifier:
                if record.get('request_payload_sha256') != digest or record.get('job_id') != path.parent.name:return None
                found.append(_receipt(record))
        return found[0] if len(found)==1 else None
    def launch(identifier,digest):
        job_id='gen-'+uuid.uuid4().hex
        root=directory(job_id,config=config);root.mkdir(parents=True)
        write(root/'config.json',config);write(root/'task.json',dict(payload,runtime=runtime))
        record={'schema_version':1,'job_id':job_id,'type':'asset_generation','recipe_id':recipe_id,'state':'queued',
                'request_id':identifier,'request_payload_sha256':digest,'created_unix_ns':time.time_ns()}
        package=root/'runtime'/'simscene'
        shutil.copytree(Path(__file__).parents[1],package,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        write(root/'job.json',record)
        with (root/'worker.log').open('ab') as log:
            process=subprocess.Popen([sys.executable,'-m','simscene.generation.worker',str(root)],
                env=dict(os.environ,PYTHONPATH=str(root/'runtime')),stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
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
