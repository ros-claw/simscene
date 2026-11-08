"""Generate and run one small paired engineering bench from editable modules.

Each output directory is exclusive. Conditions and both initial scenes are
written before physics. This checks one configuration, not a parameter range
or the archived whole-room acceptance suite.
"""
import argparse
import copy
import json
import math
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from simscene.mechanism_modules import compile_plan
from simscene.geometry import camera_orientation
from simscene.scene import SceneStore
from simscene.replay import sha
from simscene import jobs
from simscene.workflows import wait_job


def save(path, value):
    with Path(path).open('x') as f:
        json.dump(value, f, indent=2, allow_nan=False); f.write('\n')


def build(kind):
    if kind == 'line':
        plan = compile_plan('domino_line', 'bench', {'count': 20, 'origin': [0, 0, .35], 'spacing_m': .09})
        objects = {op['id']: op['object'] for op in plan['operations']}
        angle = math.radians(12); h, t = .14, .018
        objects['bench_tile_001']['orientation_wxyz'] = [math.cos(angle/2), 0, math.sin(angle/2), 0]
        objects['bench_tile_001']['position'] = [t/2+h/2*math.sin(angle)-t/2*math.cos(angle), 0,
                                                 .35+h/2*math.cos(angle)+t/2*math.sin(angle)+.0001]
        negative = copy.deepcopy(objects); negative.pop('bench_tile_010')
        eye, target = [.85, -1.8, 1.3], [.85, 0, .37]
        conditions = {'positive': 'all 20 tiles reach >=60 degrees from upright',
                      'negative': 'only tile010 is removed: 0.18m gap exceeds 0.14m height; first nine tip >=60; tiles011..020 stay <5 degrees and <0.005m from initial',
                      'scope': 'Gravity-started first tile. This is not the unique-ball whole-room chain.'}
    else:
        plan = compile_plan('door_bridge', 'bench', {'origin': [0, 0, .7]})
        objects = {op['id']: op['object'] for op in plan['operations']}
        angle = math.radians(2); top = .7125
        objects['source_table'] = {'kind': 'box', 'size': [.72, .25, .04], 'position': [-.36, 0, top+.36*math.tan(angle)-.02/math.cos(angle)],
            'orientation_wxyz': [math.cos(angle/2), 0, math.sin(angle/2), 0], 'collision': True, 'physics': {'static_friction': .4, 'dynamic_friction': .3}}
        objects['target_table'] = {'kind': 'box', 'size': [.4, .3, .04], 'position': [.8, 0, top-.02], 'collision': True}
        objects['target_stop'] = {'kind': 'box', 'size': [.04, .3, .1], 'position': [1.02, 0, top+.05], 'collision': True}
        objects['payload'] = {'kind': 'sphere', 'size': [.05]*3, 'position': [-.55, 0, top+.55*math.tan(angle)+.0255],
            'dynamic': True, 'collision': True, 'mass_kg': .03, 'physics': {'static_friction': .4, 'dynamic_friction': .3, 'restitution': 0, 'sleep_threshold': 0, 'enable_ccd': True}, 'color': [.85, .3, .1]}
        negative = copy.deepcopy(objects); negative['bench_hinge']['joint']['upper_limit'] = -80
        eye, target = [.1, -1.7, 1.45], [.2, 0, .78]
        conditions = {'positive': 'door reaches within 5 degrees of horizontal; payload crosses x>0.72 while above z0.70',
                      'negative': 'only hinge upper limit 0 becomes -80: door stays raised, payload still advances >0.15m but never completes supported crossing',
                      'scope': 'Unlatched gravity bridge; no triggered latch or timed payload release.'}
    extras = {'bench_camera': {'kind': 'camera', 'position': eye, 'orientation_wxyz': camera_orientation(eye, target),
               'camera': {'resolution': [640, 360]}, 'record_fps': 10},
              'bench_light': {'kind': 'light', 'position': [0, -1, 3], 'intensity': 2000}}
    for scene in (objects, negative):
        scene.update(copy.deepcopy(extras))
    return plan, objects, negative, conditions


def measure(run, kind):
    from simscene.run_integrity import verify as input_check
    from simscene.evidence_integrity import verify as output_check
    input_ok = input_check(run)['passed']; output_ok = output_check(run)['passed']
    data = json.loads((run/'result.json').read_text()); samples = data['samples']; spec = json.loads((run/'spec.json').read_text())
    timeline_ok = [s['physics_steps'] for s in samples] == list(range(1, 481)) and data['actual_physics_steps'] == 480
    def tilt(q):
        return math.degrees(math.acos(max(-1, min(1, 1-2*(q[1]*q[1]+q[2]*q[2])))))
    result = {'input_integrity': input_ok, 'output_integrity': output_ok, 'complete_per_step_timeline': timeline_ok}
    if kind == 'line':
        initial = data['initial_observation']['positions']; values = {}
        for i in range(1, 21):
            path = '/World/bench_tile_'+str(i).zfill(3)
            # Static intervention is intentionally absent from dynamic journals.
            if i == 10 and 'bench_tile_010' not in spec['objects']:
                continue
            values[str(i)] = {'maximum_tilt_degrees': max(tilt(s['orientations_wxyz'][path]) for s in samples),
                'maximum_displacement_m': max(math.dist(s['positions'][path], initial[path]) for s in samples)}
        result['tiles'] = values
    else:
        door = [tilt(s['orientations_wxyz']['/World/bench_panel']) for s in samples]
        payload = [s['positions']['/World/payload'] for s in samples]
        result.update({'minimum_door_tilt_degrees': min(door), 'maximum_door_tilt_degrees': max(door),
                       'payload_maximum_x_m': max(p[0] for p in payload),
                       'payload_supported_crossing': any(p[0]>.72 and p[2]>.70 for p in payload)})
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--kind', choices=['line', 'bridge'], required=True)
    p.add_argument('--output', type=Path, required=True); p.add_argument('--isaac-python', required=True)
    a = p.parse_args(); out = a.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    os.environ['SIMSCENE_HOME'] = str(out/'state'); os.environ['SIMSCENE_ISAAC_PYTHON'] = str(Path(a.isaac_python).resolve())
    os.environ['SIMSCENE_GPU'] = '0'; os.environ['SIMSCENE_PHYSICS_DEVICE'] = 'cpu'
    plan, positive, negative, conditions = build(a.kind)
    save(out/'module-plan.json', plan)
    save(out/'conditions.json', {'schema': 'simscene.module_engineering_bench.v1', 'steps': 480, **conditions})
    for mode, objects in [('positive', positive), ('negative', negative)]:
        save(out/(mode+'-initial-scene.json'), {'objects': objects})
    save(out/'pre-run-freeze.json', {name: sha(out/name) for name in ['module-plan.json', 'conditions.json', 'positive-initial-scene.json', 'negative-initial-scene.json']})
    measurements = {}; launches = {}
    for mode, objects in [('positive', positive), ('negative', negative)]:
        scene_id = 'module_'+a.kind+'_'+mode; store = SceneStore(); store.open(scene_id)
        store.apply(scene_id, 0, 'authored_initial_state', [*({'op': 'add', 'id': k, 'object': v} for k, v in objects.items()),
            {'op': 'set_observation', 'observation': {'sample_interval_steps': 1, 'strict_start': True, 'record_contact_pairs': True}}])
        launch = jobs.start(scene_id, steps=480, seed=42, case_path=str(out/'conditions.json'), request_id=mode+'_single_start')
        launches[mode] = launch; save(out/(mode+'-launch.json'), launch)
        receipt = wait_job(launch['job_id'], out/(mode+'-wait.json'), timeout_s=1200)
        assert receipt['state'] == 'completed' and receipt['exit_code'] == 0 and receipt['exit_code_observed']
        run = out/'state/runs'/launch['run_id']
        measurements[mode] = measure(run, a.kind); save(out/(mode+'-measurements.json'), measurements[mode])
    pos, neg = measurements['positive'], measurements['negative']
    checks = {'all_input_output_timelines': all(v[k] for v in measurements.values() for k in ('input_integrity', 'output_integrity', 'complete_per_step_timeline'))}
    if a.kind == 'line':
        checks.update({'all20_tip': all(v['maximum_tilt_degrees']>=60 for v in pos['tiles'].values()),
            'control_upstream_tips': all(neg['tiles'][str(i)]['maximum_tilt_degrees']>=60 for i in range(1,10)),
            'control_downstream_quiet': all(neg['tiles'][str(i)]['maximum_tilt_degrees']<5 and neg['tiles'][str(i)]['maximum_displacement_m']<.005 for i in range(11,21))})
    else:
        checks.update({'door_lands': pos['minimum_door_tilt_degrees']<5, 'payload_crosses': pos['payload_supported_crossing'],
            'control_door_stays_raised': neg['minimum_door_tilt_degrees']>75,
            'control_payload_activated': neg['payload_maximum_x_m']>-.4,
            'control_supported_crossing_blocked': not neg['payload_supported_crossing']})
    save(out/'bench-result.json', {'passed': all(checks.values()), 'checks': checks, 'measurements': measurements,
        'launches': launches, 'scope': 'One paired configuration, read-only engineering checks. Not independent whole-room acceptance or parameter-range certification.'})
    print(json.dumps({'passed': all(checks.values()), 'checks': checks, 'output': str(out)}, indent=2))
    raise SystemExit(0 if all(checks.values()) else 1)


if __name__ == '__main__':
    main()
