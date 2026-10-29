"""Check that a running Isaac job exposes changing observations and frames."""
import json,time,shutil
from pathlib import Path
from simscene.scene import SceneStore,SceneError
from simscene.jobs import start,status,sample,camera_image
s=SceneStore();s.open('live-probe')
s.apply('live-probe',0,'setup',[
 {'op':'add','id':'floor','object':{'kind':'box','position':[0,0,-.05],'size':[2,2,.1],'collision':True}},
 {'op':'add','id':'cube','object':{'kind':'box','position':[0,0,.6],'size':[.2,.2,.2],'dynamic':True}},
 {'op':'add','id':'sun','object':{'kind':'light','intensity':1500}},
 {'op':'add','id':'view','object':{'kind':'camera','position':[1.5,1.5,1.5],'preview_fps':2}},
 {'op':'look_at','id':'view','target':[0,0,.3]}])
j=start('live-probe',600); observed=[]
while True:
    result=status(j['job_id'])
    if result['state'] not in ('queued','running','paused'):break
    try:
        obs=sample(j['job_id']);img=camera_image(j['job_id'],'view')
        if not observed or obs['physics_steps']!=observed[-1]['physics_steps']:
            observed.append({'physics_steps':obs['physics_steps'],'position':obs['positions'].get('/World/cube'),'image_bytes':Path(img).stat().st_size})
            if len(observed)==1:shutil.copyfile(img,'/tmp/simscene-live-first.png')
    except SceneError:pass
    time.sleep(.3)
print(json.dumps({'job':result,'live_observations':observed},indent=2))
