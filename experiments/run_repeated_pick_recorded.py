"""Exploratory two-workpiece continuous-belt pick, one arm; not acceptance."""
import json, os, time
from simscene.scene import SceneStore
from simscene.jobs import start, status
from simscene.robotics.gripper import mimic_commands
root=os.environ['SIMSCENE_XRDF_DIR'];urdf=root+'/robot.urdf'
initial=dict(zip(['joint1','joint2','joint3','joint4','joint5','joint6'],[1.5707829843,.1642120063,-1.8665936187,-.0000123875,-1.1107880308,0]))
initial.update(mimic_commands(urdf,'finger_joint',-.5))
def cycle(part, bin_x):
    return [
        {'type':'wait_object','object':part,'axis':'x','minimum':-.051,'maximum':.0,'max_steps':2400},
        {'type':'track','object':part,'offset':[0,0,-.01],'steps':90},
        {'type':'track','object':part,'offset':[0,0,-.01],'steps':180,'gripper_value':.5},
        {'type':'move','object':part,'offset':[0,0,.23],'min_steps':120,'max_steps':400},
        {'type':'move','position':[bin_x,-.79,.55],'min_steps':150,'max_steps':500},
        {'type':'move','position':[bin_x,-.79,.32],'min_steps':150,'max_steps':500},
        {'type':'gripper','value':-.5,'steps':180},
        {'type':'move','position':[bin_x,-.79,.55],'min_steps':120,'max_steps':400},
        {'type':'move','position':[0,-.5,.55],'min_steps':150,'max_steps':500},
        {'type':'move','position':[0,-.5,.31],'min_steps':150,'max_steps':500}]
config={'experimental':True,'model_directory':root,'tool_frame':'gripper_center','tcp_prim':'gripper_center','initial_joints':initial,'target_position':[0,-.5,.28],'gripper_urdf':urdf,'gripper_joint':'finger_joint','monitor_collisions':True,'sequence':cycle('part_a',.18)+cycle('part_b',-.18)}
objects={'arm':{'kind':'asset','asset_path':os.environ['SIMSCENE_ROBOT_USD'],'pose_follower':config},
         'belt':{'kind':'box','position':[0,-.5,.28],'size':[1.5,.2,.04],'collision':True,'conveyor':{'speed_m_s':.03,'direction':[1.,0.,0.]}},
         'part_a':{'kind':'box','position':[-.05,-.5,.32],'size':[.04,.04,.04],'dynamic':True,'spawn_step':30,'class_label':'red'},
         'part_b':{'kind':'box','position':[-.05,-.5,.32],'size':[.04,.04,.04],'dynamic':True,'spawn_step':1600,'class_label':'blue'}}
for prefix,x in [('red',.18),('blue',-.18)]:
    for name,pos,size in [('floor',[x,-.79,.28],[.25,.25,.04]),('wl',[x-.125,-.79,.35],[.02,.27,.10]),('wr',[x+.125,-.79,.35],[.02,.27,.10]),('wf',[x,-.915,.35],[.23,.02,.10]),('wb',[x,-.665,.35],[.23,.02,.10])]:
        objects['bin_'+prefix+'_'+name]={'kind':'box','position':pos,'size':size,'collision':True}
objects['view']={'kind':'camera','position':[1.7,-2.2,1.8],'record_fps':5}
objects['light']={'kind':'light','intensity':1500}
store=SceneStore();store.open('repeat');store.apply('repeat',0,'setup',[{'op':'add','id':k,'object':v} for k,v in objects.items()]+[{'op':'look_at','id':'view','target':[0,-.55,.35]}])
job=start('repeat',3200)
while True:
    result=status(job['job_id'])
    if result['state'] not in ('queued','running','paused'):print(json.dumps(result,indent=2));break
    time.sleep(2)
