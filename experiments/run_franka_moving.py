"""Exploratory single moving-belt Franka pick using simulator object state."""
import json,os,time
from simscene.scene import SceneStore
from simscene.jobs import start,status
root=os.environ['SIMSCENE_XRDF_DIR'];urdf=root+'/robot.urdf'
q=[-.0114430609,-.1461084292,.0110332323,-2.2183429949,.0018318037,2.0722426326,.7839902483]
initial={'panda_joint'+str(i+1):v for i,v in enumerate(q)};initial.update({'panda_finger_joint1':.04,'panda_finger_joint2':.04})
seq=[{'type':'track','object':'part','offset':[0,0,.035],'steps':90},
     {'type':'track','object':'part','offset':[0,0,.035],'steps':180,'gripper_value':0.},
     {'type':'move','object':'part','offset':[0,0,.20],'min_steps':30,'max_steps':600,'max_joint_speed':.8,'settle_steps':4},
     {'type':'move','position':[.5,.4,.55],'min_steps':30,'max_steps':600,'max_joint_speed':.8,'settle_steps':4},
     {'type':'move','position':[.5,.4,.355],'min_steps':30,'max_steps':600,'max_joint_speed':.8,'settle_steps':4},
     {'type':'gripper','value':.04,'steps':180},
     {'type':'move','position':[.5,.4,.55],'min_steps':30,'max_steps':600,'max_joint_speed':.8,'settle_steps':4}]
c={'experimental':True,'model_directory':root,'tool_frame':'simscene_tcp','tcp_prim':'panda_hand','tcp_offset':[0,0,.1034],
   'initial_joints':initial,'target_position':[.45,0,.355],'gripper_urdf':urdf,'gripper_joint':'panda_finger_joint1',
   'gripper_mapping':{'panda_finger_joint2':1.0},'sequence':seq,'monitor_collisions':True,'max_joint_speed':.5}
objects={'arm':{'kind':'asset','asset_path':os.environ['SIMSCENE_ROBOT_USD'],'pose_follower':c},
         'belt':{'kind':'box','position':[.5,0,.28],'size':[1.2,.15,.04],'collision':True,'conveyor':{'speed_m_s':.03,'direction':[1,0,0]}},
         'part':{'kind':'box','position':[.45,0,.32],'size':[.04,.04,.04],'dynamic':True}}
for name,pos,size in [('floor',[.5,.4,.28],[.4,.4,.04]),('wl',[.3,.4,.37],[.02,.42,.14]),('wr',[.7,.4,.37],[.02,.42,.14]),('wf',[.5,.2,.37],[.38,.02,.14]),('wb',[.5,.6,.37],[.38,.02,.14])]:
    objects['bin_'+name]={'kind':'box','position':pos,'size':size,'collision':True}
s=SceneStore();s.open('moving');s.apply('moving',0,'setup',[{'op':'add','id':k,'object':v} for k,v in objects.items()]);j=start('moving',1800)
while True:
    result=status(j['job_id'])
    if result['state'] not in ('queued','running','paused'):print(json.dumps(result,indent=2));break
    time.sleep(2)
