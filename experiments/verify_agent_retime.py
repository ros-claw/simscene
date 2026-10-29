"""Verify a pre-registered natural-language conveyor timing edit."""
import hashlib
import json
import math
import copy
from pathlib import Path
import statistics
import sys
from simscene.run_integrity import verify as verify_inputs
from simscene.evidence_integrity import verify as verify_outputs

if len(sys.argv) != 2:
    raise SystemExit('usage: verify_agent_retime.py EVALUATION_DIRECTORY')
root = Path(sys.argv[1]).resolve()
case_path = root/'pre_registered_case.json'
case = json.loads(case_path.read_text())
if case.get('schema') != 'simscene.agent_retime_case.v1':
    raise SystemExit('unsupported case')
before = json.loads((root/'before.json').read_text())
after = json.loads((root/'after.json').read_text())
bo = before['objects']; ao = after['objects']
old_belts = {n: o for n, o in bo.items() if o.get('conveyor')}
new_belts = {n: o for n, o in ao.items() if o.get('conveyor')}
checks = {'case_copy_hash_matches': (root/'pre_registered_case.sha256').read_text().strip()
          == hashlib.sha256(case_path.read_bytes()).hexdigest(),
          'agent_session_completed': (root/'exit-code.txt').read_text().strip() == '0',
          'no_external_intervention': not (root/'external-intervention.json').exists() and not (root/'external-interventions.jsonl').exists(),
          'same_scene_and_new_revision': before['scene_id'] == after['scene_id'] and after['revision'] > before['revision'],
          'one_retained_belt': len(old_belts) == 1 and set(old_belts) == set(new_belts)}
try:
    expected=(root/'frozen-checker.sha256').read_text().strip()
    checks['checker_matches_frozen_copy']=hashlib.sha256((root/'frozen-checker.py').read_bytes()).hexdigest()==expected and hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()==expected
except OSError:
    checks['checker_matches_frozen_copy']=False
name = next(iter(old_belts), '')
old_speed = old_belts.get(name, {}).get('conveyor', {}).get('speed_m_s', 0)
new_speed = new_belts.get(name, {}).get('conveyor', {}).get('speed_m_s', 0)
tol = case['relative_tolerance']
checks['speed_reduced_as_requested'] = bool(old_speed and new_speed and math.isclose(
    new_speed/old_speed, case['speed_factor'], rel_tol=tol))
old_items = {n: o['spawn_step'] for n, o in bo.items() if o.get('spawn_step', 0) > 0}
new_items = {n: o['spawn_step'] for n, o in ao.items() if o.get('spawn_step', 0) > 0}
old_order = sorted(old_items, key=old_items.get)
new_order = sorted(new_items, key=new_items.get)
old_intervals = [old_items[b]-old_items[a] for a, b in zip(old_order, old_order[1:])]
new_intervals = [new_items[b]-new_items[a] for a, b in zip(new_order, new_order[1:])]
checks['same_items_and_order'] = len(old_order) >= 2 and old_order == new_order
checks['spawn_spacing_increased_as_requested'] = bool(checks['same_items_and_order'] and all(
    a > 0 and math.isclose(b/a, case['spawn_interval_factor'], rel_tol=tol)
    for a, b in zip(old_intervals, new_intervals)))
def functional_objects(objects):
    value = {name: copy.deepcopy(obj) for name, obj in objects.items() if obj.get('kind') not in ('camera', 'light')}
    for obj in value.values():
        obj.pop('spawn_step', None)
        if isinstance(obj.get('conveyor'), dict):
            obj['conveyor'].pop('speed_m_s', None)
    return value
checks['other_functional_configuration_preserved'] = functional_objects(bo) == functional_objects(ao)
runs = []
for run_path in sorted((root/'state'/'runs').glob('*')):
    try:
        spec = json.loads((run_path/'spec.json').read_text())
        result = json.loads((run_path/'result.json').read_text())
        if spec['scene_id'] == after['scene_id'] and spec['revision'] == after['revision']:
            runs.append((run_path, spec, result))
    except (OSError, ValueError, KeyError):
        continue
checks['completed_run_of_edited_revision'] = bool(runs)
measurements = []
run_path = None
if runs:
    run_path, spec, result = runs[-1]
    job_id = json.loads((run_path/'job.json').read_text()).get('job_id')
    calls = [event.get('item', {}) for event in (json.loads(line) for line in (root/'trace.jsonl').read_text().splitlines())
             if event.get('type') == 'item.completed' and event.get('item', {}).get('type') == 'mcp_tool_call'
             and event.get('item', {}).get('status') == 'completed' and event.get('item', {}).get('arguments', {}).get('job_id') == job_id]
    checks['agent_observed_edited_run'] = any(call.get('tool') in ('run_observe','scene_observe') for call in calls)
    def completed_call(call):
        if call.get('tool') == 'run_verify': return True
        if call.get('tool') != 'job_status': return False
        try: return json.loads(call['result']['content'][0]['text']).get('state') == 'completed'
        except (KeyError, IndexError, TypeError, ValueError): return False
    checks['agent_saw_completed_run'] = any(completed_call(call) for call in calls)
    try:
        checks['input_integrity'] = verify_inputs(run_path)['passed']
        sealed = verify_outputs(run_path)
        checks['output_integrity'] = sealed['passed'] and not sealed['partial']
    except (OSError, ValueError, KeyError, TypeError):
        checks['input_integrity'] = checks['output_integrity'] = False
    try:
        package = json.loads((root/'package-hashes.json').read_text())
        lock = json.loads((run_path/'run-lock.json').read_text())
        prefix = 'server/vendor/simscene/'
        worker = {n[len(prefix):]: digest for n, digest in package.items() if n.startswith(prefix)}
        checks['worker_matches_frozen_package'] = bool(worker) and worker == lock.get('worker_code_sha256')
        prefix = 'skills/'
        expected = {n[len(prefix):]: digest for n, digest in package.items() if n.startswith(prefix)}
        skills_root = root/'work'/'.agents'/'skills'
        observed = {str(path.relative_to(skills_root)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in skills_root.rglob('*') if path.is_file() and '__pycache__' not in path.parts}
        checks['skill_matches_frozen_package'] = bool(expected) and expected == observed
    except (OSError, ValueError, TypeError, KeyError):
        checks['worker_matches_frozen_package'] = checks['skill_matches_frozen_package'] = False
    checks['physics_completed'] = result['actual_physics_steps'] == result['requested_physics_steps'] > 0
    checks['edited_belt_in_run'] = spec['objects'].get(name, {}).get('conveyor') == ao.get(name, {}).get('conveyor')
    checks['edited_schedule_in_run'] = all(spec['objects'].get(n, {}).get('spawn_step') == step for n, step in new_items.items())
    direction = ao.get(name, {}).get('conveyor', {}).get('direction', [0, 0, 0])
    norm = math.sqrt(sum(v*v for v in direction))
    unit = [v/norm for v in direction] if norm else [0, 0, 0]
    events = result.get('spawn_events', [])
    checks['multiple_actual_spawns'] = len(events) >= 2 and all(
        e['id'] in new_items and e['physics_step'] == new_items[e['id']] for e in events)
    for event in events:
        name_part = event['id']; start = event['physics_step']
        points = []
        for sample in result.get('samples', []):
            dt = sample['physics_steps'] - start
            position = sample.get('positions', {}).get(event['path'])
            if case['sample_start_steps_after_spawn'] <= dt <= case['sample_end_steps_after_spawn'] and position:
                points.append((dt/60, sum(p*d for p, d in zip(position, unit))))
        if len(points) < case['minimum_samples']:
            continue
        mean_t = statistics.mean(p[0] for p in points); mean_x = statistics.mean(p[1] for p in points)
        denom = sum((t-mean_t)**2 for t, _ in points)
        if not denom:
            continue
        speed = sum((t-mean_t)*(x-mean_x) for t, x in points)/denom
        contacts = result.get('contact_counts', {})
        belt_contact = any(k.startswith(name_part+'|/World/'+name.replace('-', '_')+'|') and v.get('count', 0)>0
                           for k, v in contacts.items())
        ratio = speed/new_speed if new_speed else 0
        measurements.append({'part': name_part, 'speed_m_s': speed, 'samples': len(points),
                             'belt_contact': belt_contact, 'ratio_to_command': ratio})
    checks['measured_upstream_motion'] = any(m['belt_contact'] and
        case['measured_speed_ratio_min'] <= m['ratio_to_command'] <= case['measured_speed_ratio_max'] for m in measurements)
    checks['camera_observation_saved'] = bool(result.get('images'))
else:
    for key in ('agent_observed_edited_run', 'agent_saw_completed_run', 'input_integrity', 'output_integrity', 'worker_matches_frozen_package', 'skill_matches_frozen_package', 'physics_completed', 'edited_belt_in_run',
                'edited_schedule_in_run', 'multiple_actual_spawns', 'measured_upstream_motion', 'camera_observation_saved'):
        checks[key] = False
report = {'passed': all(checks.values()), 'checks': checks, 'run_directory': str(run_path) if run_path else None,
          'case_sha256': hashlib.sha256(case_path.read_bytes()).hexdigest(), 'measurements': measurements,
          'scope': case['scope']}
print(json.dumps(report, indent=2))
raise SystemExit(0 if report['passed'] else 1)
