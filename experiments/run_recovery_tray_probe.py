"""Physically test a missed 4 cm part falling off a conveyor into a tray."""
import hashlib,json,sys,time
from pathlib import Path
from simscene.scene import SceneStore
from simscene.jobs import start,status
from simscene.run_integrity import verify as verify_inputs
from simscene.evidence_integrity import verify as verify_outputs
if len(sys.argv)!=1:raise SystemExit('usage: run_recovery_tray_probe.py')
objects={
 'belt':{'kind':'box','position':[2,-.5,.28],'size':[5.8,.15,.04],'collision':True,'conveyor':{'speed_m_s':.03,'direction':[1,0,0]}},
 'floor':{'kind':'box','position':[2,-.5,-.06],'size':[12,6,.1],'collision':True},
 'reject_floor':{'kind':'box','position':[5.15,-.5,.04],'size':[.8,.7,.08],'collision':True},
 'reject_left':{'kind':'box','position':[5.15,-.85,.18],'size':[.8,.04,.28],'collision':True},
 'reject_right':{'kind':'box','position':[5.15,-.15,.18],'size':[.8,.04,.28],'collision':True},
 'reject_back':{'kind':'box','position':[5.55,-.5,.18],'size':[.04,.7,.28],'collision':True},
 'part':{'kind':'box','position':[4.75,-.5,.32],'size':[.04,.04,.04],'mass_kg':.1,'dynamic':True,'color':[.2,.7,.8]},
 'ambient':{'kind':'light','intensity':300,'light':{'type':'dome'}},'sun':{'kind':'light','intensity':600},
 'view':{'kind':'camera','position':[6,-2,2],'record_fps':6}}
store=SceneStore();store.open('recovery');store.apply('recovery',0,'setup',
 [{'op':'add','id':name,'object':obj} for name,obj in objects.items()]+[{'op':'look_at','id':'view','target':[4.95,-.5,.2]}])
case={'belt_end_x':4.9,'part':'/World/part','tray_floor':'/World/reject_floor',
      'inner_min':[4.75,-.83,.08],'inner_max':[5.53,-.17,.32],
      'scope':'single missed part recovery; not the complete sorting scenario'}
case_path=store.path/'recovery-case.json';case_path.write_text(json.dumps(case,indent=2)+'\n')
frozen=store.path/'recovery-probe-frozen.py';frozen.write_bytes(Path(__file__).read_bytes())
frozen_hash=hashlib.sha256(frozen.read_bytes()).hexdigest()
(store.path/'recovery-probe-frozen.sha256').write_text(frozen_hash+'\n')
job=start('recovery',1200,17,str(case_path));run=(store.path/'runs'/job['run_id']).resolve()
while True:
 current=status(job['job_id'])
 if current['state'] not in ('queued','running','paused'):break
 time.sleep(2)
(run/'job-status.json').write_text(json.dumps(current,indent=2)+'\n')
checks={};details={}
if current['state']=='completed':
 result=json.loads((run/'result.json').read_text());samples=result.get('samples',[])
 points=[s['positions']['/World/part'] for s in samples if '/World/part' in s.get('positions',{})]
 contacts=result.get('contact_counts',{})
 def first_contact(other):
  prefix='part|'+other+'|'
  values=[v.get('first_physics_step') for k,v in contacts.items() if k.startswith(prefix) and v.get('count',0)>0 and type(v.get('first_physics_step')) is int]
  return min(values) if values else None
 belt_contact=first_contact('/World/belt');floor_contact=first_contact('/World/reject_floor')
 final=points[-1] if points else None;tail=points[-20:]
 settled=bool(len(tail)>=10 and max(p[0] for p in tail)-min(p[0] for p in tail)<.003 and max(p[2] for p in tail)-min(p[2] for p in tail)<.003)
 inputs=verify_inputs(run);outputs=verify_outputs(run)
 checks={'observed_exit_zero':current.get('exit_code')==0 and current.get('exit_code_inferred') is False,
  'all_steps':result.get('actual_physics_steps')==1200,'belt_then_tray_contact':belt_contact is not None and floor_contact is not None and belt_contact<floor_contact,
  'crossed_belt_end':bool(points) and max(p[0] for p in points)>4.9,
  'settled_inside_tray':bool(final and 4.77<=final[0]<=5.51 and -.81<=final[1]<=-.19 and .095<=final[2]<=.105 and settled),
  'rendered_video':bool(result.get('videos',{}).get('view')),'case_frozen':inputs.get('checks',{}).get('acceptance_case') is True,
  'checker_frozen':hashlib.sha256(frozen.read_bytes()).hexdigest()==frozen_hash,
  'input_integrity':inputs.get('passed') is True,'output_integrity':outputs.get('passed') is True and not outputs.get('partial')}
 details={'final_position':final,'belt_contact_step':belt_contact,'tray_contact_step':floor_contact}
report={'passed':bool(checks) and all(checks.values()),'checks':checks,'details':details,'directory':str(run),'scope':case['scope']}
(run/'recovery-verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
raise SystemExit(0 if report['passed'] else 1)
