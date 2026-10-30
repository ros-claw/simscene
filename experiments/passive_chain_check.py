"""Independent checker for recorded passive contact networks; no scene repair.

Case identity, contact edges and receiving bounds must be frozen before formal
runs. Timed spawning is permitted only for the one initial trigger. Contact
order and downstream motion provide evidence, not a general proof of causation;
paired removal controls are required for the challenge's causal claim.
"""
import argparse
import json
import math
from pathlib import Path


def path(name):
    return '/World/' + name.replace('-', '_')


def finite_vector(value, n):
    return isinstance(value, list) and len(value) == n and all(type(x) in (int, float) and math.isfinite(x) for x in value)


def vertical_cos(q):
    if not finite_vector(q, 4) or abs(sum(v*v for v in q)-1) > .01:
        return None
    return 1-2*(q[1]*q[1]+q[2]*q[2])


def validate_case(case):
    required = {'schema', 'trigger_id', 'bodies', 'edges', 'receiver'}
    if not isinstance(case, dict) or not required <= set(case) or case['schema'] != 'simscene.passive_chain.v1':
        raise ValueError('invalid passive-chain case')
    bodies = case['bodies']
    if not isinstance(bodies, dict) or len(bodies) < 3 or case['trigger_id'] not in bodies:
        raise ValueError('case requires trigger and downstream bodies')
    for name, body in bodies.items():
        if not isinstance(name, str) or not name or body.get('kind') not in ('sphere', 'tile'):
            raise ValueError('invalid passive body')
    edges = case['edges']
    if not isinstance(edges, list) or not edges or any(not isinstance(e, list) or len(e) != 2 or e[0] not in bodies or e[1] not in bodies or e[0] == e[1] for e in edges):
        raise ValueError('invalid contact edges')
    if len({tuple(e) for e in edges}) != len(edges):
        raise ValueError('duplicate contact edges')
    reached = {case['trigger_id']}
    remaining = set(bodies) - reached
    while remaining:
        next_nodes = {b for a, b in edges if a in reached} & remaining
        if not next_nodes:
            raise ValueError('all passive bodies must be reachable from trigger')
        reached |= next_nodes
        remaining -= next_nodes
    # Reject cycles, which could otherwise hide impossible temporal ordering.
    pending = set(bodies)
    while pending:
        roots = {n for n in pending if not any(b == n and a in pending for a, b in edges)}
        if not roots:
            raise ValueError('contact network must be acyclic')
        pending -= roots
    receiver = case['receiver']
    if receiver.get('body_id') not in bodies or not receiver.get('collider_ids') or not finite_vector(receiver.get('min'), 3) or not finite_vector(receiver.get('max'), 3) or any(a >= b for a, b in zip(receiver['min'], receiver['max'])):
        raise ValueError('invalid receiver')
    return case


def contact_first(run, first, second):
    stamps = []
    for key, value in run.get('contact_counts', {}).items():
        parts = key.split('|')
        if len(parts) < 2:
            continue
        if (parts[0] == first and parts[1] == path(second)) or (parts[0] == second and parts[1] == path(first)):
            step = value.get('first_physics_step')
            if value.get('count', 0) > 0 and type(step) is int and step >= 0:
                stamps.append(step)
    return min(stamps) if stamps else None


def evaluate(run, spec, case, mode='positive', removed_id=None):
    validate_case(case)
    if mode not in ('positive', 'no_trigger', 'broken_link'):
        raise ValueError('invalid chain control mode')
    trigger = case['trigger_id']
    if mode == 'no_trigger':
        removed_id = trigger
    if mode == 'broken_link' and (removed_id not in case['bodies'] or removed_id == trigger):
        raise ValueError('broken-link control requires a downstream removed body')
    objects = spec.get('objects', {})
    expected = set(case['bodies']) - ({removed_id} if mode != 'positive' else set())
    samples = run.get('samples', [])
    steps = [s.get('physics_steps') for s in samples]
    timeline_ok = bool(samples) and all(type(s) is int for s in steps) and all(a < b for a, b in zip(steps, steps[1:]))
    max_gap = max((b-a for a, b in zip(steps, steps[1:])), default=0) if timeline_ok else 10**9
    scheduled = {n for n, obj in objects.items() if obj.get('spawn_step', 0) > 0}
    dynamic = {n for n, obj in objects.items() if obj.get('dynamic')}
    allowed_spawn = set() if mode == 'no_trigger' else {trigger}
    trigger_step = objects.get(trigger, {}).get('spawn_step', case.get('trigger_step', 60))
    checks = {
        'completed_duration': run.get('actual_physics_steps', 0) == run.get('requested_physics_steps') and run.get('actual_physics_steps', 0) > 0,
        'observed_time_order': timeline_ok and max_gap <= case.get('maximum_sample_gap_steps', 5),
        'contacts_not_truncated': run.get('contacts_truncated') is False,
        'exact_dynamic_roles': dynamic == expected,
        'role_shapes_match': all(objects.get(n,{}).get('kind') == ('box' if case['bodies'][n]['kind']=='tile' else 'sphere') for n in expected),
        'only_initial_trigger_scheduled': scheduled == allowed_spawn and trigger_step >= case.get('minimum_trigger_step', 60),
        'no_active_drives': not run.get('followers') and all(not obj.get('pose_follower') and not obj.get('conveyor') for obj in objects.values()),
        'imported_assets_are_passive_visuals': all(obj.get('asset_physics') == 'visual_only' for obj in objects.values() if obj.get('kind') == 'asset'),
        'spawn_evidence_matches': len(run.get('spawn_events', [])) == len(allowed_spawn) and {e.get('id') for e in run.get('spawn_events', [])} == allowed_spawn and all(e.get('physics_step') == trigger_step for e in run.get('spawn_events', [])),
    }
    nodes = {}
    for name in expected:
        body = case['bodies'][name]
        observations = [(s['physics_steps'], s.get('positions', {}).get(path(name)), s.get('orientations_wxyz', {}).get(path(name))) for s in samples]
        valid = [(t, p, q) for t, p, q in observations if finite_vector(p, 3) and vertical_cos(q) is not None]
        initial = objects.get(name, {}).get('position', [0, 0, 0])
        activation = None
        for t, position, q in valid:
            if name == trigger:
                active = t >= trigger_step
            elif body['kind'] == 'tile':
                active = vertical_cos(q) <= body.get('activation_cos_max', .98) or math.dist(position, initial) >= body.get('activation_distance_m', .015)
            else:
                active = math.dist(position[:2], initial[:2]) >= body.get('activation_distance_m', .025)
            if active:
                activation = t
                break
        before = [(t, p, q) for t, p, q in valid if t < trigger_step]
        quiet = name == trigger or bool(before) and all(math.dist(p, initial) <= case.get('initial_position_tolerance_m', .015) and (body['kind'] != 'tile' or vertical_cos(q) >= .98) for _, p, q in before)
        if body['kind'] == 'tile':
            final_ok = bool(valid and vertical_cos(valid[-1][2]) <= case.get('final_tile_cos_max', .5))
        else:
            final_ok = bool(valid)
        nodes[name] = {'observed':bool(valid) and len(valid) == sum(1 for t, p, q in observations if name != trigger or t > trigger_step), 'quiet_before_trigger':quiet, 'activation_step':activation, 'final_state_ok':final_ok}
    checks['all_expected_bodies_observed'] = bool(nodes) and all(n['observed'] for n in nodes.values())
    checks['downstream_initially_quiet'] = all(n['quiet_before_trigger'] for n in nodes.values())
    edges = {}
    for a, b in case['edges']:
        if a not in expected or b not in expected:
            continue
        stamp = contact_first(run, a, b)
        ta = trigger_step if a == trigger else nodes[a]['activation_step']
        tb = nodes[b]['activation_step']
        valid = stamp is not None and ta is not None and tb is not None and stamp > trigger_step and ta <= stamp + max_gap and stamp <= tb + max_gap
        edges[a+'->'+b] = {'first_contact_step':stamp, 'source_activation_step':ta, 'target_activation_step':tb, 'ordered':valid}
    receiver = case['receiver'];end = receiver['body_id']
    tail_steps = case.get('terminal_stability_steps', 120)
    tail = [s.get('positions', {}).get(path(end)) for s in samples if s.get('physics_steps', 0) >= run.get('actual_physics_steps', 0)-tail_steps]
    terminal_size = objects.get(end, {}).get('size', [0, 0, 0]);radius = max(terminal_size)/2
    tail_valid = bool(tail) and all(finite_vector(p, 3) for p in tail)
    contained = tail_valid and all(all(receiver['min'][i]+radius-.002 <= p[i] <= receiver['max'][i]-radius+.002 for i in range(3)) for p in tail)
    span = max((math.dist(a, b) for a in tail for b in tail), default=math.inf) if tail_valid else math.inf
    receiver_contact = any(contact_first(run, end, other) is not None for other in receiver['collider_ids'])
    if mode == 'positive':
        checks['all_required_activated'] = all(n['activation_step'] is not None for n in nodes.values())
        checks['all_tiles_finally_tipped'] = all(n['final_state_ok'] for n in nodes.values())
        checks['every_handoff_ordered'] = bool(edges) and all(e['ordered'] for e in edges.values())
        checks['terminal_received_and_settled'] = bool(contained and span <= case.get('terminal_max_motion_m', .005) and receiver_contact and tail_steps >= 60 and run.get('actual_physics_steps', 0)-steps[0] >= tail_steps) if steps else False
    else:
        downstream = set(case['bodies']) - {trigger}
        if mode == 'broken_link':
            downstream = {removed_id}
            while True:
                new = downstream | {b for a, b in case['edges'] if a in downstream}
                if new == downstream:break
                downstream = new
            downstream.discard(removed_id)
        checks['control_really_removed_body'] = removed_id not in objects
        checks['downstream_did_not_activate'] = bool(downstream) and all(nodes[n]['activation_step'] is None for n in downstream)
        checks['terminal_not_received'] = not contained and not receiver_contact
    return {'passed':all(checks.values()), 'mode':mode, 'checks':checks, 'bodies':nodes, 'edges':edges, 'receiver':{'contained_entire_tail':bool(contained), 'terminal_motion_m':span if math.isfinite(span) else None, 'contact':receiver_contact}, 'scope':'Recorded contact order and measured passive motion; causal claim requires paired no-trigger and broken-link controls.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run');parser.add_argument('case');parser.add_argument('--mode', default='positive', choices=['positive','no_trigger','broken_link']);parser.add_argument('--removed-id');parser.add_argument('--output')
    args = parser.parse_args();root = Path(args.run).resolve()
    case_path = Path(args.case);case = json.loads(case_path.read_text())
    from simscene.run_integrity import verify as inputs
    from simscene.evidence_integrity import verify as outputs
    report = evaluate(json.loads((root/'result.json').read_text()),json.loads((root/'spec.json').read_text()),case,args.mode,args.removed_id)
    report['input_integrity'] = inputs(root);report['output_integrity'] = outputs(root)
    lock = json.loads((root/'run-lock.json').read_text())
    import hashlib
    report['case_pinned_to_run'] = lock.get('acceptance_case_sha256') == hashlib.sha256(case_path.read_bytes()).hexdigest()
    report['passed'] = bool(report['passed'] and report['case_pinned_to_run'] and report['input_integrity']['passed'] and report['output_integrity']['passed'] and not report['output_integrity']['partial'])
    text = json.dumps(report,indent=2,allow_nan=False)
    if args.output:Path(args.output).write_text(text+'\n')
    print(text);return 0 if report['passed'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
