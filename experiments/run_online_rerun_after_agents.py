"""Run a fresh online-agent session after the earlier agent batch is finished."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

if len(sys.argv)!=4:
    raise SystemExit('usage: run_online_rerun_after_agents.py PACKAGE SUITE_HOME OUTPUT_DIRECTORY')
package,suite,out=(Path(x).resolve() for x in sys.argv[1:])
progress=suite/'agent-acceptance'/'progress.json'
while True:
    try:state=json.loads(progress.read_text()).get('state','')
    except (OSError,ValueError):state=''
    if state in ('complete','requires_investigation') or state.startswith('blocked_by_'):break
    time.sleep(10)
if out.exists():raise SystemExit('rerun directory already exists')
run=subprocess.run([sys.executable,'experiments/agent_online_eval.py',str(package),str(out)],check=False)
checker=out/'frozen-checker.py';report=None
if checker.is_file():
    env=dict(os.environ,PYTHONPATH=str(package/'server/vendor'))
    checked=subprocess.run([sys.executable,str(checker),str(out)],capture_output=True,text=True,env=env,check=False)
    (out/'verification.json').write_text(checked.stdout);(out/'verification.stderr').write_text(checked.stderr)
    try:report=json.loads(checked.stdout)
    except ValueError:report=None
cleanup='''import json,sys\nfrom pathlib import Path\nfrom simscene.jobs import status,cancel\nroot=Path(sys.argv[1]);records=[]\nfor path in (root/'state'/'runs').glob('*/job.json'):\n try:\n  job=json.loads(path.read_text())['job_id'];current=status(job)\n  if current['state'] in ('queued','running','paused','stalled'):records.append(cancel(job))\n except Exception as error:records.append({'path':str(path),'error':str(error)})\n(root/'post-session-cleanup.json').write_text(json.dumps({'jobs':records},indent=2)+'\\n')\n'''
env=dict(os.environ,PYTHONPATH=str(package/'server/vendor'),SIMSCENE_HOME=str(out/'state'))
clean=subprocess.run([sys.executable,'-c',cleanup,str(out)],capture_output=True,text=True,env=env,check=False)
result={'agent_exit_code':run.returncode,'checker_exit_code':checked.returncode if checker.is_file() else None,
        'cleanup_exit_code':clean.returncode,'passed':run.returncode==0 and clean.returncode==0 and bool(report and report.get('passed')),
        'scope':'A new isolated agent session using the checker frozen before the session.'}
(out/'rerun-result.json').write_text(json.dumps(result,indent=2)+'\n')
target=Path('evidence/agent-online-v26-corrected-checker')
if target.exists():raise SystemExit('evidence destination already exists')
shutil.copytree(out,target)
print(json.dumps(result),flush=True)
raise SystemExit(0 if result['passed'] else 1)
