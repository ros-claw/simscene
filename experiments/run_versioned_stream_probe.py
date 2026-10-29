"""Run a saved scene against a fixed case on the configured Isaac version."""
import json,sys,time
from pathlib import Path
from simscene.jobs import start,status
from simscene.scene import SceneStore
from simscene.verification.case_runner import evaluate
if len(sys.argv)!=4:raise SystemExit('usage: run_versioned_stream_probe.py SCENE_ID CASE_JSON STEPS')
scene,case,steps=sys.argv[1],sys.argv[2],int(sys.argv[3]);home=SceneStore().path
job=start(scene,steps,17,case,archive_verified_objects=True)
root=(home/'runs'/job['run_id']).resolve()
while True:
 state=status(job['job_id'])
 if state['state'] not in ('queued','running','paused'):break
 time.sleep(3)
(root/'job-status.json').write_text(json.dumps(state,indent=2)+'\n')
if state['state']=='completed':
 report=evaluate(root);(root/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'directory':str(root),'state':state['state'],'exit_code':state.get('exit_code')}))
raise SystemExit(0 if state['state']=='completed' else 1)
