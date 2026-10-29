"""Measure a gravity-fed chute and moving belt in real Isaac, on an idle GPU.

This isolates the feeder geometry before attempting to combine it with robots.
No object poses are written during the run. The physical observations and
input/output locks, rather than a controller status, determine the result.
"""
import json
import math
import time
from simscene.jobs import start, status
from simscene.scene import SceneStore
from simscene.run_integrity import verify as verify_inputs
from simscene.evidence_integrity import verify as verify_outputs

s = SceneStore()
scene = s.open('chute_probe')
if scene['revision'] or scene['objects']:
    raise SystemExit('chute_probe scene already exists; use a fresh SIMSCENE_HOME')
angle = .65
orientation = [math.cos(angle/2), 0, math.sin(angle/2), 0]
objects = {
    'belt': {'kind': 'box', 'position': [.5, -.5, .28], 'size': [2.8, .15, .04],
             'collision': True, 'conveyor': {'speed_m_s': .03, 'direction': [1, 0, 0]}},
    'chute': {'kind': 'box', 'position': [-1, -.5, .6], 'size': [.8, .12, .02],
              'orientation_wxyz': orientation, 'collision': True},
    'chute_left': {'kind': 'box', 'position': [-1, -.56, .65], 'size': [.8, .01, .10],
                   'orientation_wxyz': orientation, 'collision': True},
    'chute_right': {'kind': 'box', 'position': [-1, -.44, .65], 'size': [.8, .01, .10],
                    'orientation_wxyz': orientation, 'collision': True},
    'floor': {'kind': 'box', 'position': [0, -.5, -.05], 'size': [5, 3, .1], 'collision': True},
    'light': {'kind': 'light', 'intensity': 1500},
    'camera': {'kind': 'camera', 'position': [-.35, -2.5, 1.6], 'record_fps': 6},
}
for i in range(3):
    objects[f'part{i}'] = {'kind': 'box', 'position': [-1.23, -.5, .84],
                           'size': [.04, .04, .04], 'mass_kg': .1, 'dynamic': True,
                           'spawn_step': 1 + 600*i, 'color': [.8, .15+i*.25, .1]}
ops = [{'op': 'add', 'id': name, 'object': obj} for name, obj in objects.items()]
ops.append({'op': 'look_at', 'id': 'camera', 'target': [-.8, -.5, .42]})
s.apply('chute_probe', 0, 'construct', ops)
job = start('chute_probe', 1800, 17)
directory = s.path / 'runs' / job['run_id']
while True:
    current = status(job['job_id'])
    if current['state'] not in ('queued', 'running', 'paused'):
        break
    time.sleep(2)
(directory/'job-status.json').write_text(json.dumps(current, indent=2)+'\n')
if current['state'] != 'completed':
    print(json.dumps({'passed': False, 'directory': str(directory), 'job': current}))
    raise SystemExit(1)
run = json.loads((directory/'result.json').read_text())
parts = {}
for i in range(3):
    name = f'part{i}'
    points = [sample['positions']['/World/'+name] for sample in run['samples']
              if '/World/'+name in sample['positions']]
    contacts = run.get('contact_counts', {})
    chute_contact = any(k.startswith(name+'|/World/chute|') and v['count'] > 0 for k, v in contacts.items())
    belt_contact = any(k.startswith(name+'|/World/belt|') and v['count'] > 0 for k, v in contacts.items())
    # The final retained state must be on the belt, downstream of the chute.
    final = points[-1] if points else None
    parts[name] = {'samples': len(points), 'chute_contact': chute_contact,
                   'belt_contact': belt_contact, 'final_position': final,
                   'passed': bool(final and chute_contact and belt_contact and final[0] > -.65
                                  and abs(final[1]+.5) < .09 and .29 <= final[2] <= .36)}
report = {'parts': parts, 'duration_completed': run['actual_physics_steps'] == 1800,
          'input_integrity': verify_inputs(directory)['passed'],
          'output_integrity': verify_outputs(directory)['passed'],
          'scope': 'gravity-fed physical chute and nonzero conveyor in isolation; not robot sorting acceptance'}
report['passed'] = all(item['passed'] for item in parts.values()) and all(
    report[key] for key in ('duration_completed', 'input_integrity', 'output_integrity'))
(directory/'chute-verification.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps({'directory': str(directory), **report}, indent=2))
raise SystemExit(0 if report['passed'] else 1)
