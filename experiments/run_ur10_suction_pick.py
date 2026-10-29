"""Experimental scene-driven UR10 short-suction static pick and place."""
import json,os,time
from simscene.scene import SceneStore
from simscene.jobs import start,status
root=os.environ['SIMSCENE_XRDF_DIR'];p=json.load(open(root+'/profile.json'))
initial=dict(zip(['shoulder_pan_joint','shoulder_lift_joint','elbow_joint','wrist_1_joint','wrist_2_joint','wrist_3_joint'],[-.3340939157,-1.9129483852,2.1030217123,-1.7608695245,-1.5707965136,1.2367162245]))
seq=[{'type':'gripper','value':.5,'steps':120,'required_object':'part'},
     {'type':'move','position':[.5,0,.55],'min_steps':90,'max_steps':500},
     {'type':'move','position':[.5,.28,.55],'min_steps':90,'max_steps':500},
     {'type':'move','position':[.5,.28,.345],'min_steps':90,'max_steps':500},
     {'type':'gripper','value':-.5,'steps':120},
     {'type':'move','position':[.5,.28,.55],'min_steps':90,'max_steps':500}]
c={'experimental':True,'model_directory':root,'tool_frame':p['tool_frame'],'tcp_prim':p['tcp_prim'],'tcp_offset':p['tcp_offset'],
   'tcp_orientation_wxyz':p['tcp_orientation_wxyz'],'initial_joints':initial,'target_position':[.5,0,.345],
   'suction':{'prim':p['surface_gripper_prim'],'max_grip_distance':.02,'force_limit':100},'monitor_collisions':True,'sequence':seq}
objects={'arm':{'kind':'asset','asset_path':os.environ['SIMSCENE_ROBOT_USD'],'variants':{'Gripper':'Short_Suction'},'pose_follower':c},
         'table':{'kind':'box','position':[.5,0,.28],'size':[.15,.15,.04],'collision':True},
         'part':{'kind':'box','position':[.5,0,.32],'size':[.04,.04,.04],'dynamic':True}}
for name,pos,size in [('floor',[.5,.28,.28],[.25,.25,.04]),('wl',[.375,.28,.37],[.02,.27,.14]),('wr',[.625,.28,.37],[.02,.27,.14]),('wf',[.5,.155,.37],[.23,.02,.14]),('wb',[.5,.405,.37],[.23,.02,.14])]:
    objects['bin_'+name]={'kind':'box','position':pos,'size':size,'collision':True}
s=SceneStore();s.open('suction');s.apply('suction',0,'setup',[{'op':'add','id':k,'object':v} for k,v in objects.items()]);j=start('suction',1800)
while True:
    r=status(j['job_id'])
    if r['state'] not in ('queued','running','paused'):print(json.dumps(r,indent=2));break
    time.sleep(2)
