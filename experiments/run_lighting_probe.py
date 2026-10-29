"""Real headless ambient and key-light probe; visually review its saved frame."""
import json,sys,time
from pathlib import Path
from simscene.scene import SceneStore
from simscene.jobs import start,status
store=SceneStore();store.open('lighting')
ops=[{'op':'add','id':'floor','object':{'kind':'box','position':[0,0,-.05],'size':[6,6,.1],'collision':True,'material':{'color':[.26,.3,.35],'roughness':.7}}},
     {'op':'add','id':'cube','object':{'kind':'box','position':[0,0,.25],'size':[.5,.5,.5],'dynamic':True,'material':{'color':[.05,.5,.2],'roughness':.5}}},
     {'op':'add','id':'ambient','object':{'kind':'light','intensity':300,'light':{'type':'dome'}}},
     {'op':'add','id':'sun','object':{'kind':'light','intensity':700,'orientation_wxyz':[.92387953,.38268343,0,0]}},
     {'op':'add','id':'camera','object':{'kind':'camera','position':[3,-3,2]}},
     {'op':'look_at','id':'camera','target':[0,0,.25]}]
store.apply('lighting',0,'scene',ops);job=start('lighting',120,17);directory=(store.path/'runs'/job['run_id']).resolve()
while True:
 current=status(job['job_id'])
 if current['state'] not in ('queued','running','paused'):break
 time.sleep(3)
(directory/'job-status.json').write_text(json.dumps(current,indent=2)+'\n')
print(json.dumps({'directory':str(directory),'state':current['state'],'scope':'lighting render and simple physics smoke; no robot behavior'}))
raise SystemExit(0 if current['state']=='completed' else 1)
