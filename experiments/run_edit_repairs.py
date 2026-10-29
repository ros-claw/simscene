"""Run separately frozen edit-repair sessions from the accepted agent scene.

Original failed edit results remain unchanged. The retime repair case permits
small explicit waypoint/timeout repairs and additionally requires every item,
the original containment bounds, overlap and the discrete collision audit.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

base = Path('/code/rosclaw/simscene')
package = Path('/home/dell/.local/share/simscene/plugins/simscene-v30')
accepted = Path('/tmp/simscene-agent-v30e-suite/agent-acceptance/three_arm')
scene = accepted/'state/triarm_bright_sorting.json'
verification = json.loads((accepted/'verification.json').read_text())
if verification.get('passed') is not True:
    raise SystemExit('source scene has not passed its frozen three-arm checker')
run = Path(verification['run_directory'])
lock = json.loads((run/'run-lock.json').read_text())
canonical = json.dumps(json.loads(scene.read_text()), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
if hashlib.sha256(canonical).hexdigest() != lock['source_scene_sha256']:
    raise SystemExit('source scene no longer matches its accepted run')
root = Path('/tmp/simscene-v30-edit-repairs')
out = base/'evidence/agent-v30-edit-repairs'
root.mkdir(parents=True, exist_ok=False)
out.mkdir(parents=True, exist_ok=False)
progress = root/'progress.json'
records = []
def write(state, **extra):
    data = {'state': state, 'sessions': records, **extra}
    progress.write_text(json.dumps(data, indent=2)+'\n')
    (out/'progress.json').write_text(json.dumps(data, indent=2)+'\n')
write('running')
for mode in ('retime_repair', 'relocate_repair'):
    directory = root/mode
    write('running', current=mode)
    with (root/(mode+'.stdout')).open('w') as stdout, (root/(mode+'.stderr')).open('w') as stderr:
        proc = subprocess.run([sys.executable, str(base/'experiments/agent_edit_eval.py'), str(package), str(scene), mode, str(directory)],
                              cwd=base, env=os.environ.copy(), stdout=stdout, stderr=stderr)
    item = {'name': mode, 'agent_exit_code': proc.returncode, 'passed': False, 'directory': str(directory)}
    try:
        check = subprocess.run([sys.executable, str(directory/'frozen-checker.py'), str(directory)], cwd=base,
                               env=dict(os.environ, PYTHONPATH=str(package/'server/vendor')), capture_output=True, text=True)
        (directory/'verification.json').write_text(check.stdout)
        (directory/'verification.stderr').write_text(check.stderr)
        item['passed'] = proc.returncode == 0 and check.returncode == 0 and json.loads(check.stdout)['passed'] is True
    except (OSError, ValueError, KeyError) as error:
        item['error'] = str(error)
    cleanup = '''import json,sys\nfrom pathlib import Path\nfrom simscene.jobs import status,cancel\nr=Path(sys.argv[1]);out=[]\nfor p in (r/'state'/'runs').glob('*/job.json'):\n try:\n  j=json.loads(p.read_text())['job_id'];s=status(j)\n  if s['state'] in ('queued','running','paused','stalled'):out.append(cancel(j))\n except Exception as e:out.append({'path':str(p),'error':str(e)})\n(r/'post-session-cleanup.json').write_text(json.dumps({'when':'after session and frozen verification','jobs':out},indent=2)+'\\n')\n'''
    env = dict(os.environ, PYTHONPATH=str(package/'server/vendor'), SIMSCENE_HOME=str(directory/'state'))
    done = subprocess.run([sys.executable, '-c', cleanup, str(directory)], cwd=base, env=env, capture_output=True, text=True)
    if done.returncode:
        item['passed'] = False
        item['cleanup_error'] = done.stderr[-2000:]
    records.append(item)
    shutil.copytree(directory, out/mode)
    write('running')
write('complete' if all(item['passed'] for item in records) else 'requires_investigation')
raise SystemExit(0 if all(item['passed'] for item in records) else 1)
