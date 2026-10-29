"""A host-wide, per-user cooperative GPU launch queue.

This wrapper holds an advisory lock until the launched simulator exits. It
starts no simulator or GPU context while waiting.
"""
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time


def launch(state_file, command, lock_directory=None):
    if not command:
        raise ValueError('a simulator command is required')
    state = Path(state_file).resolve()
    # TMPDIR can differ between plugin hosts. A stable per-user location is
    # necessary for independent clients on the same host to share the queue.
    directory = Path(lock_directory) if lock_directory else Path('/tmp')/('simscene-gpu-'+str(os.getuid()))
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    information = directory.lstat()
    if not stat.S_ISDIR(information.st_mode) or information.st_uid != os.getuid() or information.st_mode & 0o077:
        raise RuntimeError('GPU lock directory must be private and owned by the current user')
    descriptor = os.open(directory/'gpu.lock', os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0), 0o600)
    def atomic_write(path, payload, prefix):
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf8', dir=path.parent, prefix=prefix, delete=False) as stream:
            tmp=Path(stream.name);json.dump(payload,stream);stream.flush();os.fsync(stream.fileno())
        try:os.replace(tmp,path)
        finally:tmp.unlink(missing_ok=True)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError('GPU lock file must be a regular file owned by the current user')
        control=state.parent/'control-request.json';control_state=state.parent/'control-state.json'
        acknowledged=None
        while True:
            try:request=json.loads(control.read_text()) if control.is_file() else {}
            except (OSError,ValueError):request={}
            if request.get('action')=='pause':
                if ('pause',request.get('request_id'))!=acknowledged:
                    atomic_write(control_state,{'state':'paused','request_id':request.get('request_id')},'.control-')
                    acknowledged=('pause',request.get('request_id'))
                time.sleep(.1);continue
            if request.get('action')=='resume' and ('resume',request.get('request_id'))!=acknowledged:
                atomic_write(control_state,{'state':'running','request_id':request.get('request_id')},'.control-')
                acknowledged=('resume',request.get('request_id'))
            try:fcntl.flock(descriptor, fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                time.sleep(.1);continue
            # Respect a pause that arrived while the lock was being acquired.
            try:latest=json.loads(control.read_text()) if control.is_file() else {}
            except (OSError,ValueError):latest={}
            if latest.get('action')=='pause':
                fcntl.flock(descriptor,fcntl.LOCK_UN);continue
            break
        atomic_write(state,{'state':'running','started_unix_ns':time.time_ns()},'.queue-')
        os.set_inheritable(descriptor,True)
        # Keep a parent alive to persist the real simulator exit code even if
        # the MCP host goes away. The child inherits the lock too, so killing
        # this wrapper cannot admit a second GPU job while Isaac still runs.
        process=subprocess.Popen(command,close_fds=False)
        code=process.wait()
        atomic_write(state.parent/'process-exit.json',{'schema':'simscene.process_exit.v1',
            'run_id':state.parent.name,'queue_pid':os.getpid(),'child_pid':process.pid,'exit_code':code},'.exit-')
        return code
    finally:
        os.close(descriptor)


if __name__ == '__main__':
    if len(sys.argv)<3:
        raise SystemExit('usage: gpu_queue.py QUEUE_STATE EXECUTABLE [ARGS...]')
    raise SystemExit(launch(sys.argv[1],sys.argv[2:]))
