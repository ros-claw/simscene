"""Evidence checks for one frozen imported-rigid gravity diagnostic."""
import json
import math
from pathlib import Path
from .settling import stable

SCHEMA = 'simscene.rigid_asset_smoke.v1'


def _numbers(value, length):
    return isinstance(value, list) and len(value) == length and all(type(x) in (int, float) and math.isfinite(x) for x in value)


def _bounds(value):
    return isinstance(value, dict) and _numbers(value.get('min'), 3) and _numbers(value.get('max'), 3) and all(a < b for a, b in zip(value['min'], value['max']))


def _actor(value):
    return isinstance(value, str) and value.startswith('/World/') and '//' not in value and not any(p in ('.', '..') for p in value.split('/'))


def validate_case(case):
    if not isinstance(case, dict) or case.get('schema') != SCHEMA or case.get('schema_version') != 1:
        raise ValueError('unsupported rigid asset smoke case')
    objects = case.get('objects')
    if not isinstance(objects, dict) or not 0 < len(objects) <= 64:
        raise ValueError('rigid smoke case requires frozen object mappings')
    claimed = set()
    for name, item in objects.items():
        if not isinstance(name, str) or not isinstance(item, dict) or not _actor(item.get('motion_body')):
            raise ValueError('invalid rigid smoke object')
        if item['motion_body'] in claimed:
            raise ValueError('duplicate rigid smoke motion body')
        claimed.add(item['motion_body'])
        for key in ('contact_bodies', 'visual_roots', 'support_actors'):
            values = item.get(key)
            if not isinstance(values, list) or not values or any(not _actor(p) for p in values) or len(set(values)) != len(values):
                raise ValueError('invalid frozen rigid smoke actor paths')
        if set(item['contact_bodies']) & set(item['support_actors']):
            raise ValueError('support actors must be distinct from the dynamic body')
        required=item.get('required_contact_actors',[])
        if (not isinstance(required,list) or len(required)!=len(set(required))
                or any(not _actor(p) or p in item['contact_bodies'] for p in required)):
            raise ValueError('invalid required contact actor paths')
        if not _bounds(item.get('target_bounds')):
            raise ValueError('invalid frozen rigid smoke target bounds')
        for key in ('initial_height_m', 'min_drop_m'):
            if type(item.get(key)) not in (int, float) or not math.isfinite(item[key]):
                raise ValueError('invalid rigid smoke height/displacement')
        if item['min_drop_m'] <= 0 or item['min_drop_m'] < .01:
            raise ValueError('rigid smoke requires measurable gravity displacement')
    return case


def evaluate(run, case):
    """Evaluate measurements; persisted runs additionally require verify_run."""
    validate_case(case)
    try:
        if not isinstance(run, dict):
            raise ValueError('run measurements must be a mapping')
        return _evaluate(run, case)
    except (TypeError, KeyError, ValueError, AttributeError) as error:
        return {'schema_version': 1, 'passed': False, 'checks': {'valid_measurements': False}, 'errors': [str(error)], 'objects': {}}


def _evaluate(run, case):
    samples = run.get('samples', [])
    initial = run.get('initial_observation')
    frames = ([initial] if isinstance(initial, dict) else []) + (samples if isinstance(samples, list) else [])
    duration = run.get('simulation_time_s')
    valid_time = type(duration) in (int, float) and math.isfinite(duration) and duration >= 2
    times = [f.get('simulation_time_s') for f in frames if isinstance(f, dict)]
    timeline = (valid_time and len(times) == len(frames) and len(frames) >= 3
                and all(type(t) in (int, float) and math.isfinite(t) for t in times)
                and abs(times[0]) < 1e-8 and abs(times[-1] - duration) < 1e-6
                and all(0 < b - a <= .200001 for a, b in zip(times, times[1:])))
    steps = [f.get('physics_steps') for f in frames if isinstance(f, dict)]
    full_steps = (len(steps) == len(frames) and bool(steps)
                  and all(type(s) is int for s in steps) and steps[0] == 0
                  and all(a < b for a, b in zip(steps, steps[1:]))
                  and steps[-1] == run.get('actual_physics_steps') == run.get('requested_physics_steps')
                  and steps[-1] > 0)
    interval = run.get('observation_interval_steps')
    cadence = False
    if full_steps and type(interval) is int and 1 <= interval <= 12:
        expected = list(range(0, steps[-1], interval)) + [steps[-1]]
        cadence = steps == expected
    checks = {'complete_timeline': bool(timeline), 'full_physics_steps': bool(full_steps), 'complete_sample_cadence': cadence,
              'samples_not_truncated': run.get('samples_truncated') is False,
              'contacts_not_truncated': run.get('contacts_truncated') is False,
              'contact_geometry_complete': run.get('contact_geometry_incomplete') is False,
              'not_partial': run.get('partial') is False,
              'no_active_followers': not run.get('followers')}
    mappings = run.get('body_bindings', {})
    outcomes = {}
    for name, item in case['objects'].items():
        motion = item['motion_body']; binding = mappings.get(name, {}) if isinstance(mappings, dict) else {}
        obj_checks = {'frozen_body_binding_matches': all(binding.get(key) == item[key] for key in ('motion_body', 'contact_bodies', 'visual_roots'))}
        observed = bool(frames) and all(isinstance(f, dict) and _numbers(f.get('positions', {}).get(motion), 3) and _numbers(f.get('orientations_wxyz', {}).get(motion), 4) and _bounds(f.get('bounds', {}).get(name)) for f in frames)
        obj_checks['actual_body_full_observations'] = bool(observed)
        if observed and timeline:
            p0 = frames[0]['positions'][motion]; p1 = frames[-1]['positions'][motion]
            obj_checks['frozen_initial_height_matches'] = abs(p0[2] - item['initial_height_m']) <= .01
            obj_checks['gravity_displacement'] = p0[2] - p1[2] >= item['min_drop_m']
            bounds = frames[-1]['bounds'][name]; target = item['target_bounds']
            obj_checks['full_bounds_contained'] = all(target['min'][i] <= bounds['min'][i] <= bounds['max'][i] <= target['max'][i] for i in range(3))
            obj_checks['settled_two_seconds'] = stable(frames, motion, duration, 2., .03, .3)
        else:
            for key in ('frozen_initial_height_matches', 'gravity_displacement', 'full_bounds_contained', 'settled_two_seconds'):
                obj_checks[key] = False
        contacts = set()
        for frame in frames:
            for pair in frame.get('contact_pairs', []) if isinstance(frame, dict) else []:
                actors = pair.get('actor_paths') if isinstance(pair, dict) else None
                if isinstance(actors, list) and len(actors) == 2 and type(pair.get('count')) is int and pair['count'] > 0:
                    first = pair.get('first_callback_absolute_physics_step'); last = pair.get('last_callback_absolute_physics_step'); zero = run.get('run_zero_absolute_physics_step')
                    if all(type(s) is int for s in (first, last, zero)) and zero < first <= last <= zero + run.get('actual_physics_steps', 0):
                        contacts.add(frozenset(actors))
        # Optional compact aggregate retains exact actor paths and step bounds.
        for key, record in run.get('body_contact_counts', {}).items():
            actors = key.split('|')
            if len(actors) == 2 and record.get('count', 0) > 0 and type(record.get('first_physics_step')) is int and type(record.get('last_physics_step')) is int and 0 < record['first_physics_step'] <= record['last_physics_step'] <= run.get('actual_physics_steps', 0):
                contacts.add(frozenset(actors))
        obj_checks['specified_support_contact'] = any(frozenset((body, support)) in contacts for body in item['contact_bodies'] for support in item['support_actors'])
        if item.get('required_contact_actors'):
            obj_checks['all_required_actor_contacts'] = all(
                any(frozenset((body,actor)) in contacts for body in item['contact_bodies'])
                for actor in item['required_contact_actors'])
        outcomes[name] = {'checks': obj_checks, 'passed': all(obj_checks.values())}
    checks['all_objects_passed'] = bool(outcomes) and all(item['passed'] for item in outcomes.values())
    return {'schema_version': 1, 'checks': checks, 'objects': outcomes, 'passed': all(checks.values()),
            'scope': 'frozen imported rigid-body gravity, contact, containment and settling diagnostic'}


def verify_run(directory, case_path=None):
    """Require the frozen case and both input and saved-output integrity locks."""
    from ..run_integrity import verify as verify_inputs
    from ..evidence_integrity import verify as verify_evidence
    from ..cache import _sha256
    root = Path(directory)
    lock = json.loads((root / 'run-lock.json').read_text())
    name = lock.get('acceptance_case_file')
    if name != 'acceptance-case.json':
        raise ValueError('rigid smoke requires its frozen JSON acceptance case')
    frozen = root / name
    if _sha256(frozen) != lock.get('acceptance_case_sha256') or (case_path is not None and _sha256(Path(case_path)) != lock.get('acceptance_case_sha256')):
        raise ValueError('rigid smoke acceptance case changed')
    run = json.loads((root / 'result.json').read_text())
    case=json.loads(frozen.read_text())
    result = evaluate(run, case)
    result['checks']['body_bindings_pinned_to_run'] = run.get('body_bindings') == lock.get('body_bindings') and isinstance(lock.get('body_bindings'), dict)
    result['passed'] = bool(result['passed'] and result['checks']['body_bindings_pinned_to_run'])
    if case.get('prepared_manifest_sha256') is not None or case.get('source_ref') is not None:
        from ..physics_binding import validate_asset_binding
        try:
            spec=json.loads((root/'spec.json').read_text())
            for object_id in case['objects']:
                obj=spec['objects'][object_id];binding=obj['asset_binding']
                if case.get('prepared_manifest_sha256') is not None and binding['manifest_sha256']!=case['prepared_manifest_sha256']:
                    raise ValueError('prepared manifest differs from frozen case')
                prepared=validate_asset_binding(binding,require_dynamic=True,asset_path=obj['asset_path'])
                if case.get('source_ref') is not None and prepared.get('source_ref')!=case['source_ref']:
                    raise ValueError('source reference differs from frozen case')
            result['checks']['prepared_selection_pinned_to_case']=True
        except (OSError,ValueError,KeyError,TypeError):
            result['checks']['prepared_selection_pinned_to_case']=False
        result['passed']=bool(result['passed'] and result['checks']['prepared_selection_pinned_to_case'])
    inputs = verify_inputs(root); evidence = verify_evidence(root)
    result.update(input_integrity=inputs, evidence_integrity=evidence, case_pinned_to_run=True)
    result['runtime']={'engine':'physx','isaac_version':lock.get('runtime_version'),
                       'configured_physics_device':lock.get('physics_device'),
                       'physics_scene_readback':run.get('physics_settings'),
                       'physics_dt_s':lock.get('physics_dt_s'),
                       'scope':'frozen runtime configuration and available scene readback; missing historical readback stays null'}
    result['passed'] = bool(result['passed'] and inputs['passed'] and evidence['passed'] and evidence['partial'] is False)
    return result
