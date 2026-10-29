"""General composition test: gravity drives a line of seven dominoes."""
import json,math,time
from simscene.scene import SceneStore
from simscene.jobs import start,status
s=SceneStore();s.open('domino')
objects={
 'floor':{'kind':'box','position':[0,0,-.025],'size':[2,1,.05],'collision':True,'material':{'color':[.32,.35,.4],'roughness':.8}},
 'sun':{'kind':'light','intensity':1500},
 'view':{'kind':'camera','position':[1.2,-1,1.05],'record_fps':10}}
for i in range(7):
    angle=math.radians(18 if i==0 else 0)
    z=(.24*math.cos(angle)+.025*math.sin(angle))/2+.0005
    objects['tile'+str(i)]={'kind':'box','position':[-.35+i*.08,0,z],'size':[.025,.10,.24],'dynamic':True,
        'orientation_wxyz':[math.cos(angle/2),0,math.sin(angle/2),0],'mass_kg':.1,
        'material':{'color':[.15+.1*i,.25,.8-.1*i],'roughness':.4}}
s.apply('domino',0,'setup',[{'op':'add','id':k,'object':v} for k,v in objects.items()]+[{'op':'look_at','id':'view','target':[-.1,0,.1]}])
j=start('domino',600)
while True:
    result=status(j['job_id'])
    if result['state'] not in ('queued','running','paused'):print(json.dumps(result,indent=2));break
    time.sleep(2)
