"""Exercise time-scheduled physics objects on a running conveyor."""
import json, time
from simscene.scene import SceneStore
from simscene.jobs import start, status
store=SceneStore();store.open('spawn-probe')
objects={
    'belt':{'kind':'box','position':[0,0,.28],'size':[1.5,.2,.04],'collision':True,'conveyor':{'speed_m_s':.03,'direction':[1,0,0]}},
    'part_a':{'kind':'box','position':[-.05,0,.32],'size':[.04,.04,.04],'dynamic':True,'spawn_step':30,'mass_kg':.1,'class_label':'red'},
    'part_b':{'kind':'box','position':[-.2,0,.32],'size':[.04,.04,.04],'dynamic':True,'spawn_step':120,'mass_kg':.1,'class_label':'blue'},
}
store.apply('spawn-probe',0,'setup',[{'op':'add','id':name,'object':obj} for name,obj in objects.items()])
job=start('spawn-probe',360)
while True:
    result=status(job['job_id'])
    if result['state'] not in ('queued','running','paused'):
        print(json.dumps(result,indent=2)); break
    time.sleep(2)
