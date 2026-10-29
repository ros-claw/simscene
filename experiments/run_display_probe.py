"""Exercise a live spawned-object counter in the actual Isaac renderer."""
import json
import time
from simscene.jobs import start,status
from simscene.scene import SceneStore

objects={'counter':{'kind':'counter','position':[-.075,0,.5],'counter':{'source':'spawned','digits':3,'color':[.1,1,.2]}},
         'floor':{'kind':'box','position':[0,0,-.05],'size':[2,2,.1],'collision':True},
         'sun':{'kind':'light','intensity':800},'view':{'kind':'camera','position':[0,-1.2,.6],'record_fps':6}}
for i,step in enumerate((1,61,121)):
    objects['part'+str(i)]={'kind':'box','position':[-.3+i*.3,.2,.2],'size':[.04]*3,'dynamic':True,'spawn_step':step,'class_label':'demo'}
store=SceneStore();store.open('display_probe')
store.apply('display_probe',0,'build',[{'op':'add','id':name,'object':obj} for name,obj in objects.items()]+[{'op':'look_at','id':'view','target':[0,0,.5]}])
job=start('display_probe',180,17)
while True:
    result=status(job['job_id'])
    if result['state'] not in ('queued','running','paused'):break
    time.sleep(1)
print(json.dumps(result,indent=2))
raise SystemExit(0 if result['state']=='completed' else 1)
