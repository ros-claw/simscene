"""Load one previously selected USD Search asset from the server cache."""
import json,os,time
from simscene.scene import SceneStore
from simscene.jobs import start,status
asset=os.environ['SIMSCENE_SELECTED_ASSET']
s=SceneStore();s.open('online-asset')
s.apply('online-asset',0,'setup',[
 {'op':'add','id':'machine','object':{'kind':'asset','asset_path':asset}},
 {'op':'add','id':'floor','object':{'kind':'box','position':[2,1,-.05],'size':[8,7,.1],'collision':True,'material':{'color':[.3,.35,.4],'roughness':.8}}},
 {'op':'add','id':'sun','object':{'kind':'light','intensity':1500}},
 {'op':'add','id':'view','object':{'kind':'camera','position':[7,-4,4]}},
 {'op':'look_at','id':'view','target':[2,.7,.5]}])
j=start('online-asset',120)
while True:
    result=status(j['job_id'])
    if result['state'] not in ('queued','running','paused'):print(json.dumps(result,indent=2));break
    time.sleep(2)
