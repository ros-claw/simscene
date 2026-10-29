"""Experimental scene-driven Franka static pick; not a verified profile."""
import json,os,time
from simscene.scene import SceneStore
from simscene.jobs import start,status
root=os.environ['SIMSCENE_XRDF_DIR'];urdf=root+'/robot.urdf'
q=[-.0111837814,-.131869765,.01086485,-2.242756326,.00166566,2.110893645,.784128394]
initial={'panda_joint'+str(i+1):v for i,v in enumerate(q)};initial.update({'panda_finger_joint1':.04,'panda_finger_joint2':.04})
seq=[{'type':'gripper','value':0.,'steps':180}, {'type':'move','position':[.5,0,.5],'min_steps':120,'max_steps':400},
     {'type':'move','position':[.5,.25,.5],'min_steps':150,'max_steps':500}, {'type':'move','position':[.5,.25,.32],'min_steps':120,'max_steps':400},
     {'type':'gripper','value':.04,'steps':180}, {'type':'move','position':[.5,.25,.5],'min_steps':120,'max_steps':400}]
c={'experimental':True,'model_directory':root,'tool_frame':'simscene_tcp','tcp_prim':'panda_hand','tcp_offset':[0,0,.1034],
   'initial_joints':initial,'target_position':[.5,0,.32],'gripper_urdf':urdf,'gripper_joint':'panda_finger_joint1',
   'gripper_mapping':{'panda_finger_joint2':1.0},'sequence':seq}
objects={'arm':{'kind':'asset','asset_path':os.environ['SIMSCENE_ROBOT_USD'],'pose_follower':c},
         'table':{'kind':'box','position':[.5,0,.28],'size':[.18,.18,.04],'collision':True},
         'part':{'kind':'box','position':[.5,0,.32],'size':[.04,.04,.04],'dynamic':True}}
for name,pos,size in [('floor',[.5,.25,.28],[.2,.2,.04]),('wl',[.4,.25,.37],[.02,.22,.14]),('wr',[.6,.25,.37],[.02,.22,.14]),('wf',[.5,.15,.37],[.18,.02,.14]),('wb',[.5,.35,.37],[.18,.02,.14])]:
    objects['bin_'+name]={'kind':'box','position':pos,'size':size,'collision':True}
s=SceneStore();s.open('franka');s.apply('franka',0,'setup',[{'op':'add','id':k,'object':v} for k,v in objects.items()]);j=start('franka',1500)
while True:
    result=status(j['job_id'])
    if result['state'] not in ('queued','running','paused'):print(json.dumps(result,indent=2));break
    time.sleep(2)
