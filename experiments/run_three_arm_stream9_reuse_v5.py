"""Exploratory routed stream from one upstream point, not formal acceptance.

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

def motion(pos):return {'type':'move','position':pos,'min_steps':30,'max_steps':600,'max_joint_speed':1.3,'settle_steps':15,'tolerance_m':.01}
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
bin_geometry('f',fbase,.59,.32,.20)
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

from simscene.composition import plan_stream
# Objects are all generated upstream; each robot waits for its assigned class.
for name in ('part_k','part_f','part_u'): del objects[name]
for robot in ('kawasaki','franka','ur10'):objects[robot]['pose_follower']['sequence']=[]
objects['bin_k_floor']['position']=[.25,-.765,.28];objects['bin_k_floor']['size']=[.30,.35,.04]
objects['bin_k_wl']['position']=[.10,-.765,.35];objects['bin_k_wl']['size']=[.02,.37,.1]
objects['bin_k_wr']['position']=[.40,-.765,.35];objects['bin_k_wr']['size']=[.02,.37,.1]
objects['bin_k_wf']['position']=[.25,-.94,.35];objects['bin_k_wf']['size']=[.28,.02,.1]
objects['bin_k_wb']['position']=[.25,-.59,.35];objects['bin_k_wb']['size']=[.28,.02,.1]
# The Franka fingers collided with the near end wall in the previous trial.
# Widen only along world X, retaining a conservative independent target region.
objects['bin_f_floor']['size']=[.20,.32,.04]
objects['bin_f_left']['size']=[.02,.34,.06]
objects['bin_f_right']['size']=[.02,.34,.06]
objects['bin_f_front']['position'][0]=2.16
objects['bin_f_back']['position'][0]=2.48
objects['sun']={'kind':'light','intensity':1500}
objects['floor']={'kind':'box','position':[2,-.5,-.05],'size':[7.5,3,.1],'material':{'color':[.3,.34,.39],'roughness':.8}}
objects['overview']={'kind':'camera','position':[10,-14,8],'preview_fps':1,'record_fps':2}
s=SceneStore();s.open('stream');s.apply('stream',0,'base',[{'op':'add','id':k,'object':v} for k,v in objects.items()]+[{'op':'look_at','id':'overview','target':[2,-.5,.5]}])
def template(phases, old):
    phases=json.loads(json.dumps(phases))
    for phase in phases:
        for key in ('object','required_object'):
            if phase.get(key)==old:phase[key]='$item'
    return phases
def route(robot,center,cycle,old,color):
    return {'robot_id':robot,'wait':{'axis':'x','minimum':center-.06,'maximum':center+.02,'max_steps':12000},'cycle':template(cycle,old),'color':color}

# Avoid timing out at a millimetre-scale target offset; the independent
# acceptance case still checks actual contacts, lift and placement.
fseq[2]['tolerance_m']=.01
# Slow only the transfer, preserving the tracking speed needed to acquire a moving item.
fseq[3]['rmp_max_joint_speed']=.40
# Add a return path and a different explicit destination for each class item.
def set_slot(phase, z_offset):
    phase['position']='$slot';phase['slot_offset']=[0,0,z_offset]
for seq,z in [(kseq,.23),(fseq,.13),(useq,.205)]:
    set_slot(seq[3],z);set_slot(seq[4],0);set_slot(seq[6],z)
kseq.append({'type':'move','position':[0,-.5,.55],'min_steps':150,'max_steps':500})
fseq.append(motion(world(fbase,[.45,0,.55])))
useq.append(motion(world(ubase,[.45,0,.55])))
routes={'red':route('kawasaki',-.05,kseq,'part_k',[.8,.1,.1]),'green':route('franka',2.,fseq,'part_f',[.1,.8,.1]),'blue':route('ur10',4.,useq,'part_u',[.1,.2,.8])}
routes['red']['slots']=[[.15,-.74,.32]]*3
routes['green']['slots']=[[2.32,-.64,.37]]*3
routes['blue']['slots']=[[4.12,-.79,.345]]*3
plan=plan_stream(s.get('stream'),'part',['blue','green','red']*3,routes,[-.70,-.5,.32],[.04,.04,.04],600,first_step=1)
# Move up before the incoming stream, and remain above it while waiting.
# The fixed independent case is tests/fixtures/three_arm_stream9_hover_case.json.
for operation in plan['operations']:
    if operation['op']=='update':
        robot=operation['id']
        hover={'kawasaki':[0,-.5,.55], 'franka':world(fbase,[.45,0,.55]), 'ur10':world(ubase,[.45,0,.55])}[robot]
        operation['changes']['pose_follower']['sequence'].insert(0,motion(hover))
s.apply('stream',1,'stream',plan['operations']);j=start('stream',16800,17,'tests/fixtures/three_arm_stream9_hover_case.json',archive_verified_objects=True)
while True:
    result=status(j['job_id'])
    if result['state'] not in ('queued','running','paused'):print(json.dumps(result,indent=2));break
    time.sleep(2)
