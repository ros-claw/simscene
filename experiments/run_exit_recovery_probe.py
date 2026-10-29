"""Launch a real simulator job then exit so another process can reattach."""
import json
from pathlib import Path
from simscene.jobs import start
from simscene.scene import SceneStore
s=SceneStore();s.open('recovery')
s.apply('recovery',0,'scene',[{'op':'add','id':'floor','object':{'kind':'box','position':[0,0,-.05],'size':[2,2,.1],'collision':True}},
 {'op':'add','id':'cube','object':{'kind':'box','position':[0,0,1],'size':[.2,.2,.2],'dynamic':True}},
 {'op':'add','id':'ambient','object':{'kind':'light','intensity':300,'light':{'type':'dome'}}},
 {'op':'add','id':'camera','object':{'kind':'camera','position':[2,-2,1.5]}},
 {'op':'look_at','id':'camera','target':[0,0,.3]}])
job=start('recovery',120,17)
Path(s.path/'launched-job.json').write_text(json.dumps(job,indent=2)+'\n')
print(json.dumps({'job':job,'purpose':'launcher exits before GPU worker; reattach separately to verify persistent process exit'}))
