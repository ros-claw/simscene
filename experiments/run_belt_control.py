"""Paired moving/zero conveyor test of an isolated cube from rest."""
import json,os,time
from simscene.scene import SceneStore
from simscene.jobs import start,status
speed=0.0 if os.getenv('SIMSCENE_TEST_ZERO_BELT')=='1' else .1
objects={'belt':{'kind':'box','position':[0,0,-.05],'size':[4,1,.1],'collision':True,'conveyor':{'speed_m_s':speed,'direction':[1,0,0]}},
         'part':{'kind':'box','position':[0,0,.102],'size':[.2,.2,.2],'dynamic':True,'mass_kg':.1}}
s=SceneStore();s.open('belt_control');s.apply('belt_control',0,'setup',[{'op':'add','id':k,'object':v} for k,v in objects.items()])
j=start('belt_control',600,17,'tests/fixtures/belt_control_case.json')
while True:
    result=status(j['job_id'])
    if result['state'] not in ('queued','running','paused'):print(json.dumps(result,indent=2));break
    time.sleep(1)
