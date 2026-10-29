"""Measure a real reactive arm motion with one explicitly tracked obstacle.

This is a diagnostic for one geometry and trajectory; it is not a general
collision-safety or swept-volume certification.
"""
import copy,json,math,sys,time
from pathlib import Path
from simscene.scene import SceneStore
from simscene.jobs import start,status
if len(sys.argv) not in (2,3) or len(sys.argv)==3 and sys.argv[2] not in ('detour','overhead'):
    raise SystemExit('usage: run_obstacle_motion_probe.py KAWASAKI_PROFILE_DIR [detour|overhead]')
profile=str(Path(sys.argv[1]).resolve());src=json.loads(Path('/tmp/simscene-stage-grip-18/stream.json').read_text())
arm=copy.deepcopy(src['objects']['kawasaki']);cfg=arm['pose_follower'];cfg['model_directory']=profile;cfg['gripper_urdf']=profile+'/robot.urdf'
cfg['target_position']=[-.05,-.5,.55];cfg['avoid_obstacles']=['pole'];cfg['obstacle_margin_m']=.01
cfg['sequence']=[{'type':'move','position':[-.05,-.5,.55],'min_steps':30,'max_steps':900,'tolerance_m':.015,'settle_steps':10},
                 {'type':'move','position':[.18,-.79,.55],'min_steps':30,'max_steps':1200,'tolerance_m':.015,'settle_steps':10}]
if len(sys.argv)==3 and sys.argv[2]=='detour':
    cfg['sequence'][1:1]=[{'type':'move','position':[-.15,-.72,.55],'min_steps':30,'max_steps':1200,'tolerance_m':.015,'settle_steps':10},
                         {'type':'move','position':[.05,-.85,.55],'min_steps':30,'max_steps':1200,'tolerance_m':.015,'settle_steps':10}]
if len(sys.argv)==3 and sys.argv[2]=='overhead':
    cfg['sequence'][1:1]=[{'type':'move','position':[-.05,-.5,1.0],'min_steps':30,'max_steps':1200,'tolerance_m':.015,'settle_steps':10},
                         {'type':'move','position':[.18,-.79,1.0],'min_steps':30,'max_steps':1200,'tolerance_m':.015,'settle_steps':10}]
# Exclude other robots and ground; the obstacle is an explicitly modeled box.
objects={'arm':arm,'pole':{'kind':'box','position':[.07,-.65,.58],'size':[.08,.08,.22],'collision':True},
         'ground':{'kind':'box','position':[0,0,-.05],'size':[4,4,.1],'material':{'color':[.3,.34,.38]}},
         'ambient':{'kind':'light','intensity':300,'light':{'type':'dome'}},
         'key':{'kind':'light','intensity':700},'camera':{'kind':'camera','position':[2,-2,1.6]}}
store=SceneStore();store.open('obstacle');store.apply('obstacle',0,'scene',[{'op':'add','id':k,'object':v} for k,v in objects.items()]+[{'op':'look_at','id':'camera','target':[0,-.5,.5]}])
from simscene.verification.acceptance import COLLISION_POLICY
policy={section:{'arm':copy.deepcopy(mapping['kawasaki'])} for section,mapping in COLLISION_POLICY.items()}
case={'expected_spawn_order':[],'objects':[{'part_path':'/World/unused','robot_id':'arm','tracking_phase':0,'release_phase':0}], 'collision_policy':policy}
case_path=store.path/'obstacle-policy.json';case_path.write_text(json.dumps(case,indent=2)+'\n')
job=start('obstacle',6000 if len(sys.argv)==3 else 2400,17,str(case_path),continue_on_controller_error=True);directory=(store.path/'runs'/job['run_id']).resolve()
while True:
 state=status(job['job_id'])
 if state['state'] not in ('queued','running','paused'):break
 time.sleep(3)
(directory/'job-status.json').write_text(json.dumps(state,indent=2)+'\n')
passed=False
if state['state']=='completed':
 from simscene.verification.overlap_audit import evaluate
 from simscene.run_integrity import verify as verify_inputs
 from simscene.evidence_integrity import verify as verify_outputs
 run=json.loads((directory/'result.json').read_text());spec=json.loads((directory/'spec.json').read_text())
 report=evaluate(run,spec,case,directory/'scene.usda');(directory/'overlap-audit.json').write_text(json.dumps(report,indent=2)+'\n')
 follower=run.get('followers',{}).get('arm',{});position=follower.get('tcp_position') or []
 distance=math.dist(position,[.18,-.79,.55]) if len(position)==3 else None
 inputs=verify_inputs(directory);outputs=verify_outputs(directory)
 checks={'actual_exit_zero':state.get('exit_code')==0 and state.get('exit_code_inferred') is False,
         'all_steps':run.get('actual_physics_steps')==run.get('requested_physics_steps'),
         'obstacle_tracked':'/World/pole' in follower.get('tracked_obstacles',[]),
         'motion_completed':follower.get('sequence_error') is None and follower.get('sequence_index')==follower.get('sequence_length'),
         'final_position':distance is not None and distance<=.03,'discrete_audit':report.get('passed') is True,
         'input_integrity':inputs.get('passed') is True,'output_integrity':outputs.get('passed') is True and not outputs.get('partial')}
 passed=all(checks.values())
 (directory/'motion-verification.json').write_text(json.dumps({'passed':passed,'checks':checks,'position_error_m':distance,
     'scope':'one discrete-sampled obstacle motion; not swept-volume or real-robot safety'},indent=2)+'\n')
print(json.dumps({'directory':str(directory),'state':state['state'],'passed':passed,'scope':'one experimental reactive arm motion with a static obstacle'}))
raise SystemExit(0 if passed else 1)
