"""Physically test that a runaway target is rejected before robot pursuit."""
import json
import math
import sys
import time
from simscene.jobs import start,status,sample
from simscene.scene import SceneStore

if len(sys.argv)!=2:raise SystemExit('usage: run_workspace_guard_probe.py SOURCE_SCENE_JSON')
scene=json.load(open(sys.argv[1]));robot=scene['objects']['ur10']
config=robot['pose_follower'];config['sequence']=[{'type':'track','object':'stray','offset':[0,0,.025],'steps':90,
    'workspace_min':[3.8,-.7,.2],'workspace_max':[4.4,-.3,.6]}]
config.pop('diagnose_overlaps',None)
objects={'ur10':robot,'stray':{'kind':'box','dynamic':True,'position':[4,-.5,-50],'size':[.04,.04,.04]},
         'belt':scene['objects']['belt'],
         'status':{'kind':'box','position':[4,-1,.7],'size':[.1,.1,.1],'indicator':{'robot_id':'ur10'}}}
store=SceneStore();store.open('guard_probe');store.apply('guard_probe',0,'build',[{'op':'add','id':name,'object':obj} for name,obj in objects.items()])
job=start('guard_probe',120,17,continue_on_controller_error=True)
while True:
    result=status(job['job_id'])
    if result['state'] not in ('queued','running','paused'):break
    time.sleep(1)
print(json.dumps(result,indent=2))
if result['state']!='completed':raise SystemExit(1)
data=result['result'];follower=data['followers']['ur10']
stationary=math.dist(follower['initial_position'],follower['tcp_position'])<.05
indicator=sample(job['job_id']).get('displays',{}).get('status',{}).get('controller_phase_state')
raise SystemExit(0 if data['actual_physics_steps']==120 and data['task_status']=='failed' and
                 'outside workspace' in (follower['sequence_error'] or '') and stationary and indicator=='error' else 1)
