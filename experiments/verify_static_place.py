"""Check recorded static-place observations against a separate fixed case."""
import json,math,sys
from pathlib import Path
run=json.loads(Path(sys.argv[1]).read_text()); case=json.loads(Path(sys.argv[2]).read_text())
samples=run['samples']; close=[s for s in samples if s['phase']=='close']; lift=[s for s in samples if s['phase']=='lift']; release=[s for s in samples if s['phase']=='retract']
counts=run.get('contact_counts',{})
checks={}
checks['lifted']=bool(close and lift and max(s['cube'][2] for s in lift)-close[-1]['cube'][2]>=case['minimum_lift_m'])
checks['left_contact_in_lift']=any(k.startswith('lift:') and 'left_inner_finger' in k and v>0 for k,v in counts.items())
checks['right_contact_in_lift']=any(k.startswith('lift:') and 'right_inner_finger' in k and v>0 for k,v in counts.items())
last=run.get('contact_last_step',{})
checks['no_late_finger_contact']=bool(release) and all(v <= release[-1]['step']-60 for k,v in last.items() if k.startswith('retract:') and ('finger' in k or 'knuckle' in k))
checks['fingers_retracted']=bool(release and 'left_finger' in release[-1] and 'right_finger' in release[-1] and all(math.dist(release[-1][side],release[-1]['cube']) >= case['minimum_finger_origin_distance_m'] for side in ('left_finger','right_finger')))
checks['gripper_open']=bool(release and release[-1].get('finger_joint_rad',float('inf'))<=case['open_joint_threshold_rad'])
checks['contained']=bool(release and all(case['target_bin_inner_min'][i]+case['cube_half_extent_m']-case['containment_tolerance_m']<=release[-1]['cube'][i]<=case['target_bin_inner_max'][i]-case['cube_half_extent_m']+case['containment_tolerance_m'] for i in range(3)))
tail=[s for s in release if release and s['step'] >= release[-1]['step']-case['stable_duration_s']*case['frame_rate_hz']]
checks['stable']=bool(len(tail)>=2 and (tail[-1]['step']-tail[0]['step'])/case['frame_rate_hz']>=case['stable_duration_s'] and max(math.dist(s['cube'],tail[-1]['cube']) for s in tail)<=case['max_displacement_m'])
print(json.dumps({'checks':checks,'passed':all(checks.values()),'limitations':['single static object','no full path or robot collision check','no moving belt']},indent=2))
