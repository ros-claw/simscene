"""Start a diagnostic retiming of the v29 fresh agent's actual scene.

This is an engineering probe, not a fresh-agent acceptance session: it changes
that saved scene after the session and freezes a new case before launching.
"""
import hashlib
import json
import os
from pathlib import Path

from simscene.scene_edits.synchronize import synchronize
from simscene.jobs import start

source = Path('/tmp/simscene-formal-v19-camera-warmup/agent-acceptance/three_arm')
run = source/'state/runs/45b9f363c8064a5e8dea80dd008a0fb2'
home = Path(os.environ['SIMSCENE_HOME'])
home.mkdir(parents=True, exist_ok=False)
scene = json.loads((source/'state/tri_arm_sorting.json').read_text())
case = json.loads((run/'acceptance-case.json').read_text())
result = json.loads((run/'result.json').read_text())
proposal = synchronize(scene, result, case, case['expected_spawn_order'])
for operation in proposal['operations']:
    scene['objects'][operation['id']].update(operation['changes'])
adjustments = []
if os.environ.get('SIMSCENE_PROBE_SETTLE_STEPS'):
    settle = int(os.environ['SIMSCENE_PROBE_SETTLE_STEPS'])
    for item in case['objects']:
        if item['robot_id'] != 'panda':
            continue
        index = item['transfer_phase']
        phase = scene['objects']['panda']['pose_follower']['sequence'][index]
        if phase.get('settle_steps') != 15 or phase.get('max_joint_speed') != 1.3:
            raise ValueError('the previously observed Panda transfer configuration changed')
        phase['settle_steps'] = settle
        adjustments.append({'robot': 'panda', 'phase': index, 'old_settle_steps': 15,
                            'new_settle_steps': settle, 'max_joint_speed_unchanged': 1.3})
if os.environ.get('SIMSCENE_PROBE_PANDA_RETRACT_HEIGHT'):
    height = float(os.environ['SIMSCENE_PROBE_PANDA_RETRACT_HEIGHT'])
    if not .97 < height <= 1.2:
        raise ValueError('invalid Panda retraction height')
    for item in case['objects']:
        if item['robot_id'] != 'panda':
            continue
        index = item['release_phase'] + 1
        phase = scene['objects']['panda']['pose_follower']['sequence'][index]
        if phase.get('position', [None, None, None])[2] != .97:
            raise ValueError('the previously observed Panda retraction target changed')
        phase['position'][2] = height
        adjustments.append({'robot': 'panda', 'phase': index, 'old_retract_height_m': .97,
                            'new_retract_height_m': height,
                            'reason': 'increase clearance before returning past the near bin wall'})
geometry = []
if os.environ.get('SIMSCENE_PROBE_GREEN_WALL_CLEARANCE_M'):
    extra = float(os.environ['SIMSCENE_PROBE_GREEN_WALL_CLEARANCE_M'])
    if not 0 < extra <= .1:
        raise ValueError('invalid bin clearance adjustment')
    objects = scene['objects']
    wall = objects['green_bin_y_0p205']
    wall['position'][1] += extra
    for name in ('green_bin_floor', 'green_bin_x_-0p205', 'green_bin_x_0p205'):
        obj = objects[name]
        obj['position'][1] += extra/2
        obj['size'][1] += extra
    geometry.append({'bin': 'green', 'expanded_positive_y_m': extra,
                     'case_inner_bounds': 'unchanged conservative original bounds',
                     'reason': 'Panda finger reported a positive-separation proximity to the wall during retreat'})
scene['revision'] += 1
scene['requests'] = {}
case['source_scene_sha256'] = hashlib.sha256(json.dumps(scene, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
case['expected_spawn_order'] = [row['id'] for row in proposal['schedule']]
case['acceptance_thresholds'] = {'overall_success_rate': 1., 'per_robot_success_rate': 1., 'minimum_parallel_steps': 60}
(home/'tri_arm_sorting.json').write_text(json.dumps(scene, indent=2)+'\n')
(home/'proposal.json').write_text(json.dumps(proposal, indent=2)+'\n')
(home/'controller-adjustments.json').write_text(json.dumps(adjustments, indent=2)+'\n')
(home/'geometry-adjustments.json').write_text(json.dumps(geometry, indent=2)+'\n')
(home/'frozen-case.json').write_text(json.dumps(case, indent=2)+'\n')
steps = int(os.environ.get('SIMSCENE_PROBE_STEPS', '18000'))
job = start('tri_arm_sorting', steps, 17, continue_on_controller_error=True,
            archive_verified_objects=True, case=case, request_id='observed-overlap-probe')
(home/'launched.json').write_text(json.dumps(job, indent=2)+'\n')
print(json.dumps(job))
