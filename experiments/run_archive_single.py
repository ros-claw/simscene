"""Test verified reclamation of one physically sorted upstream object."""
import json,os,time
from simscene.scene import SceneStore
from simscene.jobs import start,status
from simscene.robotics.gripper import mimic_commands
root=os.environ['SIMSCENE_XRDF_DIR'];urdf=root+'/robot.urdf'
initial=dict(zip(['joint1','joint2','joint3','joint4','joint5','joint6'],[1.5707829843,.1642120063,-1.8665936187,-.0000123875,-1.1107880308,0]))
initial.update(mimic_commands(urdf,'finger_joint',-.5))
seq=[{'type':'move','position':[0,-.5,.55],'min_steps':30,'max_steps':600,'max_joint_speed':1.3,'settle_steps':15,'tolerance_m':.01},
     {'type':'wait_object','object':'part0000','axis':'x','minimum':-.11,'maximum':-.03,'max_steps':12000},
     {'type':'track','object':'part0000','offset':[0,0,-.01],'steps':90},
     {'type':'track','object':'part0000','offset':[0,0,-.01],'steps':180,'gripper_value':.5},
     {'type':'move','object':'part0000','offset':[0,0,.23],'min_steps':120,'max_steps':400},
     {'type':'move','position':[.15,-.74,.55],'min_steps':150,'max_steps':500},
     {'type':'move','position':[.15,-.74,.32],'min_steps':150,'max_steps':500},
     {'type':'gripper','value':-.5,'steps':180},
     {'type':'move','position':[.15,-.74,.55],'min_steps':120,'max_steps':400},
     {'type':'move','position':[0,-.5,.55],'min_steps':150,'max_steps':500}]
cfg={'experimental':True,'model_directory':root,'tool_frame':'gripper_center','tcp_prim':'gripper_center','initial_joints':initial,
     'target_position':[-.05,-.5,.31],'gripper_urdf':urdf,'gripper_joint':'finger_joint','monitor_collisions':True,'sequence':seq}
objects={'arm':{'kind':'asset','asset_path':os.environ['SIMSCENE_ROBOT_USD'],'pose_follower':cfg},
         'belt':{'kind':'box','position':[0,-.5,.28],'size':[1.5,.15,.04],'collision':True,'conveyor':{'speed_m_s':.03,'direction':[1,0,0]}},
         'part0000':{'kind':'box','position':[-.7,-.5,.32],'size':[.04,.04,.04],'dynamic':True,'mass_kg':.1,'spawn_step':1,'class_label':'red'}}
for name,pos,size in [('floor',[.25,-.765,.28],[.30,.35,.04]),('wl',[.10,-.765,.35],[.02,.37,.1]),('wr',[.40,-.765,.35],[.02,.37,.1]),('wf',[.25,-.94,.35],[.28,.02,.1]),('wb',[.25,-.59,.35],[.28,.02,.1])]:
    objects['bin_'+name]={'kind':'box','position':pos,'size':size,'collision':True}
s=SceneStore();s.open('archive_single');s.apply('archive_single',0,'setup',[{'op':'add','id':name,'object':obj} for name,obj in objects.items()])
j=start('archive_single',4500,17,'tests/fixtures/archive_single_case.json',archive_verified_objects=True)
while True:
    r=status(j['job_id'])
    if r['state'] not in ('queued','running','paused'):print(json.dumps(r,indent=2));break
    time.sleep(2)
