"""Crash-aware idempotency for explicitly identified job requests."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
from .scene import SceneError, _id


def invoke(home, request_id, payload, launch, recover):
    _id(request_id)
    try:
        raw=json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    except (ValueError,TypeError,OverflowError,RecursionError) as error:
        raise SceneError(f'invalid request payload: {error}') from error
    digest=hashlib.sha256(raw).hexdigest()
    home=Path(home);home.mkdir(parents=True,exist_ok=True)
    directory=home/'job-requests';directory.mkdir(parents=True,exist_ok=True)
    parent_fd=os.open(home,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
    try:os.fsync(parent_fd)
    finally:os.close(parent_fd)
    record=directory/(request_id+'.json')
    def sync_directory():
        descriptor=os.open(directory,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
        try:os.fsync(descriptor)
        finally:os.close(descriptor)
    def write(value):
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf8',dir=directory,prefix='.request-',delete=False) as file:
            name=Path(file.name);json.dump(value,file,indent=2);file.flush();os.fsync(file.fileno())
        try:os.replace(name,record);sync_directory()
        finally:name.unlink(missing_ok=True)
    with (directory/(request_id+'.lock')).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if record.exists():
            try:prior=json.loads(record.read_text())
            except (OSError,ValueError) as error:raise SceneError('job request record is unreadable') from error
            if prior.get('payload_sha256')!=digest:
                raise SceneError('request ID reused with different job parameters')
            if prior.get('state') not in ('starting','started') or (prior.get('state')=='started' and not isinstance(prior.get('result'),dict)):
                raise SceneError('job request record is invalid')
            result=recover(request_id,digest)
            if prior.get('state')=='started' and result!=prior['result']:
                raise SceneError('previously started job record is missing or inconsistent')
            if result is False and prior.get('state')=='starting':
                record.unlink();sync_directory()
            elif not isinstance(result,dict):
                raise SceneError('previous request was interrupted and its launch outcome is uncertain')
            else:
                if prior.get('state')!='started':write({'payload_sha256':digest,'state':'started','result':result})
                return dict(result,replayed=True)
        write({'payload_sha256':digest,'state':'starting'})
        try:
            result=launch(request_id,digest)
        except Exception:
            # The caller can prove no launch occurred only when recover says
            # the reservation is absent; uncertain partial launches fail closed.
            recovered=recover(request_id,digest)
            if recovered is False:
                record.unlink(missing_ok=True);sync_directory()
            elif isinstance(recovered,dict):write({'payload_sha256':digest,'state':'started','result':recovered})
            raise
        write({'payload_sha256':digest,'state':'started','result':result})
        return dict(result,replayed=False)
