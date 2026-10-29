"""Render an actual short moving-camera diagnostic."""
import json,time
from simscene.scene import SceneStore
from simscene.jobs import start,status
s=SceneStore();s.open('orbit')
s.apply('orbit',0,'setup',[
    {'op':'add','id':'ground','object':{'kind':'box','size':[4,4,.1],'position':[0,0,-.05],'color':[.3,.35,.4]}},
    {'op':'add','id':'cube','object':{'kind':'box','size':[.4,.4,.4],'position':[0,0,.2],'color':[.8,.1,.1]}},
    {'op':'add','id':'light','object':{'kind':'light','intensity':1500}},
    {'op':'add','id':'view','object':{'kind':'camera','record_fps':6,'camera_orbit':{'center':[0,0,.2],'radius_m':2,'height_m':1,'duration_s':4}}}])
j=start('orbit',120,17)
while True:
    r=status(j['job_id'])
    if r['state'] not in ('queued','running','paused'):print(json.dumps(r,indent=2));break
    time.sleep(1)
