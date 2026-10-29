"""Run one negative control from an existing saved three-arm stream scene."""
import copy
import json
import sys
import time
from pathlib import Path
from simscene.jobs import start,status
from simscene.scene import SceneStore
from simscene.verification.case_runner import evaluate

if len(sys.argv)!=4 or sys.argv[2] not in ('disable_drive','disable_suction','stop_belt'):
    raise SystemExit('usage: run_three_arm_negative_control.py SOURCE_SCENE MODE CASE_JSON')
source,mode,case=sys.argv[1:];store=SceneStore();scene=store.get(source)
objects=copy.deepcopy(scene['objects'])
if mode=='disable_drive':objects['kawasaki']['pose_follower']['arm_drives_enabled']=False;steps=12000
elif mode=='disable_suction':objects['ur10']['pose_follower']['suction_enabled']=False;steps=24000
else:objects['belt']['conveyor']['speed_m_s']=0.;steps=3000
name='control_'+mode
existing=store.open(name)
if existing['revision'] or existing['objects']:raise SystemExit('control scene already exists; use a fresh SIMSCENE_HOME or a different scene')
store.apply(name,0,'control',[{'op':'add','id':key,'object':obj} for key,obj in objects.items()])
job=start(name,steps,17,case,continue_on_controller_error=True,archive_verified_objects=True)
directory=(store.path/'runs'/job['run_id']).resolve()
while True:
    current=status(job['job_id'])
    if current['state'] not in ('queued','running','paused'):break
    time.sleep(3)
(directory/'job-status.json').write_text(json.dumps(current,indent=2)+'\n')
if current['state']=='completed':
    report=evaluate(directory);(directory/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'mode':mode,'directory':str(directory),'state':current['state'],'exit_code':current.get('exit_code')}))
raise SystemExit(0 if current['state']=='completed' and current.get('exit_code')==0 else 1)
