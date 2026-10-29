"""Initial three-arm parallel physical diagnostic, not formal acceptance.

Three individual cubes begin near their stations. This does not represent a
continuous upstream stream, routing or the final multi-run acceptance case.
"""
import json,math,os,time
from simscene.jobs import start,status
from simscene.scene import SceneStore
from simscene.robotics.gripper import mimic_commands
assets=os.environ.get('SIMSCENE_ASSETS','/data/omniverse/Assets/Isaac/6.0')
kroot=os.environ.get('SIMSCENE_KAWASAKI_PROFILE','/tmp/simscene-rs007l-xrdf')
froot=os.environ.get('SIMSCENE_FRANKA_PROFILE','/tmp/simscene-franka-profile')
uroot=os.environ.get('SIMSCENE_UR10_PROFILE','/tmp/simscene-ur10-profile')
def world(base,p):return [base[0]+p[1],base[1]-p[0],p[2]]
rot=[math.sqrt(.5),0,0,-math.sqrt(.5)]
objects={'belt':{'kind':'box','position':[2,-.5,.28],'size':[5.8,.15,.04],'collision':True,'conveyor':{'speed_m_s':.03,'direction':[1,0,0]}}}
def bin_geometry(prefix, base, x,y,width):
    for suffix,pos,size in [('floor',[x,y,.28],[width,width,.04]),('left',[x-width/2,y,.35],[.02,width+.02,.1]),('right',[x+width/2,y,.35],[.02,width+.02,.1]),('front',[x,y-width/2,.35],[width-.02,.02,.1]),('back',[x,y+width/2,.35],[width-.02,.02,.1])]:
        objects['bin_'+prefix+'_'+suffix]={'kind':'box','position':world(base,pos),'orientation_wxyz':rot,'size':size,'collision':True}

def motion(pos):return {'type':'move','position':pos,'min_steps':30,'max_steps':600,'max_joint_speed':1.3,'settle_steps':15}
# Kawasaki workstation, native coordinate system.
kq=dict(zip(['joint1','joint2','joint3','joint4','joint5','joint6'],[1.5707829843,.1642120063,-1.8665936187,-.0000123875,-1.1107880308,0]));kq.update(mimic_commands(kroot+'/robot.urdf','finger_joint',-.5))
kseq=[{'type':'track','object':'part_k','offset':[0,0,-.01],'steps':90},{'type':'track','object':'part_k','offset':[0,0,-.01],'steps':180,'gripper_value':.5},
 {'type':'move','object':'part_k','offset':[0,0,.23],'min_steps':120,'max_steps':400},
 {'type':'move','position':[.18,-.79,.55],'min_steps':150,'max_steps':500},{'type':'move','position':[.18,-.79,.32],'min_steps':150,'max_steps':500},
 {'type':'gripper','value':-.5,'steps':180},{'type':'move','position':[.18,-.79,.55],'min_steps':120,'max_steps':400}]
kcfg={'experimental':True,'model_directory':kroot,'tool_frame':'gripper_center','tcp_prim':'gripper_center','initial_joints':kq,'target_position':[-.05,-.5,.31],
 'gripper_urdf':kroot+'/robot.urdf','gripper_joint':'finger_joint','monitor_collisions':True,'sequence':kseq}
objects['kawasaki']={'kind':'asset','asset_path':assets+'/Isaac/Robots/Kawasaki/RS007L/rs007l_onrobot_rg2.usd','pose_follower':kcfg}
objects['part_k']={'kind':'box','position':[-.05,-.5,.32],'size':[.04,.04,.04],'dynamic':True,'class_label':'red'}
for n,p,sz in [('floor',[.18,-.79,.28],[.25,.25,.04]),('wl',[.055,-.79,.35],[.02,.27,.1]),('wr',[.305,-.79,.35],[.02,.27,.1]),('wf',[.18,-.915,.35],[.23,.02,.1]),('wb',[.18,-.665,.35],[.23,.02,.1])]:objects['bin_k_'+n]={'kind':'box','position':p,'size':sz,'collision':True}
# Franka workstation, rotated to face the shared belt.
fbase=[2.,-.05]; fq=[-.0114430609,-.1461084292,.0110332323,-2.2183429949,.0018318037,2.0722426326,.7839902483]
fi={'panda_joint'+str(i+1):v for i,v in enumerate(fq)};fi.update({'panda_finger_joint1':.04,'panda_finger_joint2':.04})
fseq=[{'type':'track','object':'part_f','offset':[0,0,.02],'steps':90},{'type':'track','object':'part_f','offset':[0,0,.02],'steps':180,'gripper_value':0.},
 {'type':'move','object':'part_f','offset':[0,0,.20],'min_steps':30,'max_steps':600,'max_joint_speed':1.3,'settle_steps':15},
 motion(world(fbase,[.59,.32,.55])),motion(world(fbase,[.59,.32,.37])),{'type':'gripper','value':.04,'steps':180},motion(world(fbase,[.59,.32,.55]))]
fcfg={'experimental':True,'model_directory':froot,'tool_frame':'simscene_tcp','tcp_prim':'panda_hand','tcp_offset':[0,0,.1034],'initial_joints':fi,
 'target_position':world(fbase,[.45,0,.34]),'gripper_urdf':froot+'/robot.urdf','gripper_joint':'panda_finger_joint1','gripper_mapping':{'panda_finger_joint2':1.},'monitor_collisions':True,'max_joint_speed':.5,'sequence':fseq}
objects['franka']={'kind':'asset','asset_path':assets+'/Isaac/Robots/FrankaRobotics/FrankaPanda/franka.usd','position':[fbase[0],fbase[1],0],'orientation_wxyz':rot,'pose_follower':fcfg}
objects['part_f']={'kind':'box','position':world(fbase,[.45,0,.32]),'size':[.04,.04,.04],'dynamic':True,'class_label':'green'}
bin_geometry('f',fbase,.59,.32,.24)
for name,obj in objects.items():
    if name.startswith('bin_f_') and not name.endswith('_floor'):
        obj['position'][2]=.33;obj['size'][2]=.06
# UR10 suction workstation, rotated to face the same belt.
ubase=[4.,-.05];p=json.load(open(uroot+'/profile.json'))
ui=dict(zip(['shoulder_pan_joint','shoulder_lift_joint','elbow_joint','wrist_1_joint','wrist_2_joint','wrist_3_joint'],[-.3340939157,-1.9129483852,2.1030217123,-1.7608695245,-1.5707965136,1.2367162245]))
useq=[{'type':'track','object':'part_u','offset':[0,0,.025],'steps':90},{'type':'track','object':'part_u','offset':[0,0,.025],'steps':120,'gripper_value':.5,'required_object':'part_u'},
 {'type':'move','object':'part_u','offset':[0,0,.23],'min_steps':30,'max_steps':600,'max_joint_speed':.8,'settle_steps':4},
 motion(world(ubase,[.74,.22,.55])),motion(world(ubase,[.74,.22,.345])),{'type':'gripper','value':-.5,'steps':120},motion(world(ubase,[.74,.22,.55]))]
ucfg={'experimental':True,'model_directory':uroot,'tool_frame':p['tool_frame'],'tcp_prim':p['tcp_prim'],'tcp_offset':p['tcp_offset'],'tcp_orientation_wxyz':p['tcp_orientation_wxyz'],
 'initial_joints':ui,'target_position':world(ubase,[.45,0,.345]),'suction':{'prim':p['surface_gripper_prim'],'max_grip_distance':.02,'force_limit':100},'max_joint_speed':.5,'monitor_collisions':True,'sequence':useq}
objects['ur10']={'kind':'asset','asset_path':assets+'/Isaac/Robots/UniversalRobots/ur10/ur10.usd','position':[ubase[0],ubase[1],0],'orientation_wxyz':rot,'variants':{'Gripper':'Short_Suction'},'pose_follower':ucfg}
objects['part_u']={'kind':'box','position':world(ubase,[.45,0,.32]),'size':[.04,.04,.04],'dynamic':True,'class_label':'blue'}
bin_geometry('u',ubase,.74,.22,.32)
s=SceneStore();s.open('parallel');s.apply('parallel',0,'setup',[{'op':'add','id':k,'object':v} for k,v in objects.items()]);j=start('parallel',1800)
while True:
    result=status(j['job_id'])
    if result['state'] not in ('queued','running','paused'):print(json.dumps(result,indent=2));break
    time.sleep(2)
