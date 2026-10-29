"""Experimental scene-driven moving-belt pick of one cube, not acceptance."""
import json,os,time
from simscene.scene import SceneStore
from simscene.jobs import start,status
from simscene.robotics.gripper import mimic_commands
root=os.environ['SIMSCENE_XRDF_DIR']; urdf=root+'/robot.urdf'
initial=dict(zip(['joint1','joint2','joint3','joint4','joint5','joint6'],[1.5707829843,.1642120063,-1.8665936187,-.0000123875,-1.1107880308,0]))
initial.update(mimic_commands(urdf,'finger_joint',-.5))
seq=[{'type':'track','object':'part','offset':[0,0,-.04],'steps':90},
     {'type':'track','object':'part','offset':[0,0,-.04],'steps':180,'gripper_value':.5},
     {'type':'move','object':'part','offset':[0,0,.23],'min_steps':120,'max_steps':400},
     {'type':'move','position':[.18,-.76,.52],'min_steps':150,'max_steps':500},
     {'type':'move','position':[.18,-.76,.28],'min_steps':150,'max_steps':500},
     {'type':'gripper','value':-.5,'steps':180},
     {'type':'move','position':[.18,-.76,.52],'min_steps':120,'max_steps':400}]
config={'experimental':True,'model_directory':root,'tool_frame':'gripper_center','tcp_prim':'gripper_center','initial_joints':initial,'target_position':[-.05,-.5,.28],'gripper_urdf':urdf,'gripper_joint':'finger_joint','sequence':seq}
objects={'arm':{'kind':'asset','asset_path':os.environ['SIMSCENE_ROBOT_USD'],'pose_follower':config},
         'belt':{'kind':'box','position':[0,-.5,.28],'size':[1.5,.2,.04],'collision':True,'conveyor':{'speed_m_s':.03,'direction':[1.,0.,0.]}},
         'part':{'kind':'box','position':[-.05,-.5,.32],'size':[.04,.04,.04],'dynamic':True}}
for name,pos,size in [('floor',[.18,-.76,.28],[.25,.25,.04]),('wl',[.055,-.76,.37],[.02,.27,.14]),('wr',[.305,-.76,.37],[.02,.27,.14]),('wf',[.18,-.885,.37],[.23,.02,.14]),('wb',[.18,-.635,.37],[.23,.02,.14])]:
    objects['bin_'+name]={'kind':'box','position':pos,'size':size,'collision':True}
store=SceneStore();store.open('moving');scene=store.get('moving')
if scene['revision']!=0: raise RuntimeError('use an empty SIMSCENE_HOME')
store.apply('moving',0,'setup',[{'op':'add','id':k,'object':v} for k,v in objects.items()])
job=start('moving',2000)
while True:
    result=status(job['job_id'])
    if result['state'] not in ('queued','running','paused'): print(json.dumps(result,indent=2));break
    time.sleep(2)
