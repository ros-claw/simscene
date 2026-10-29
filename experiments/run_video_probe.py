"""Record one continuously simulated camera view for inspection."""
import json, time
from simscene.scene import SceneStore
from simscene.jobs import start, status
s=SceneStore();s.open('video-probe')
s.apply('video-probe',0,'setup',[
 {'op':'add','id':'floor','object':{'kind':'box','position':[0,0,-.05],'size':[2,2,.1],'collision':True}},
 {'op':'add','id':'cube','object':{'kind':'box','position':[0,0,.6],'size':[.2,.2,.2],'dynamic':True,'color':[.8,.2,.1]}},
 {'op':'add','id':'sun','object':{'kind':'light','intensity':1500}},
 {'op':'add','id':'view','object':{'kind':'camera','position':[1.5,1.5,1.5],'record_fps':10}},
 {'op':'look_at','id':'view','target':[0,0,.3]}])
job=start('video-probe',120)
while True:
    result=status(job['job_id'])
    if result['state'] not in ('queued','running','paused'):print(json.dumps(result,indent=2));break
    time.sleep(2)
