"""Read-only admission and observation identity of an explicit D6 cord model.

This does not replace the old rope slack/contact/control or action-clock tests.
Hard angular limits are a model definition, not calibrated fibre elasticity.
Observed twist excursions are reported separately. Overall swing is never
substituted for the two pyramid coordinates or advertised as an SDK getter.
"""
import math

from ..d6 import AXES, resolved_limits, validate_limits, relative_observation, measured_pose_valid, finite_vector
from . import mechanism as legacy

MODEL = 'passive_d6_limited'


def _qmul(a, b):
    w,x,y,z = a;v,i,j,k = b
    return [w*v-x*i-y*j-z*k,w*i+x*v+y*k-z*j,
            w*j-x*k+y*v+z*i,w*k+x*j-y*i+z*v]


def _inverse(q):
    n = sum(x*x for x in q)
    return [q[0]/n, *[-v/n for v in q[1:]]]


def _frame(sample, loaded, index):
    targets = loaded['body_paths'][index]
    p, q = [0.,0.,0.], [1.,0.,0.,0.]
    if targets:
        p = sample['positions'][targets[0]]
        q = sample['orientations_wxyz'][targets[0]]
        if not measured_pose_valid(p,q):
            raise ValueError('invalid same-sample native endpoint pose')
    offset = legacy.rotate(q, loaded['local_positions_m'][index])
    return [a+b for a,b in zip(p, offset)], _qmul(q, loaded['local_rotations_wxyz'][index])


def configuration(run, spec):
    """Compare source D6 declarations and complete same-sample observations."""
    wanted = {n:o['joint'] for n,o in spec['objects'].items()
              if o.get('kind') == 'joint' and o.get('joint',{}).get('type') == 'd6'}
    result = {'passed': True, 'joint_count': len(wanted), 'joints': {},
              'scope': __doc__, 'SDK_joint_getter_claimed': False,
              'pyramid_coordinate_bound_certificate_claimed': False,
              'twist_excess_is_diagnostic': True}
    if not wanted:
        return result
    records = run.get('mechanism_configuration',{}).get('joints',[])
    task = run.get('samples',[])
    initial = run.get('initial_observation',{})
    count = run.get('actual_physics_steps')
    result['checks'] = {
        'loaded_joint_inventory_unique':isinstance(records,list) and all(isinstance(v,dict) and isinstance(v.get('path'),str) for v in records),
        'strict_complete_sequential_sample_coverage':isinstance(initial,dict) and initial.get('physics_steps') == 0 and type(count) is int and count > 0 and count == run.get('requested_physics_steps') and isinstance(task,list) and len(task) == count and all(isinstance(s,dict) and type(s.get('physics_steps')) is int and s['physics_steps'] == i for i,s in enumerate(task,1)),
    }
    if result['checks']['loaded_joint_inventory_unique']:
        result['checks']['loaded_joint_inventory_unique'] = len({v['path'] for v in records}) == len(records)
    if not all(result['checks'].values()):
        result['passed'] = False
        return result
    actual = {v['path']:v for v in records}
    samples = [initial] + task
    for name, cfg in wanted.items():
        checks = {};detail = {'checks':checks,'maximum_tensor_anchor_difference_m':0.,
            'maximum_tensor_relative_q_difference':0.,'maximum_principal_twist_excess_degrees':0.,
            'maximum_overall_swing_angle_degrees':0.,'first_invalid_sample_step':None}
        result['joints'][name] = detail
        try:
            limits = cfg.get('dof_limits')
            checks['valid_explicit_source_limits'] = not validate_limits(limits)
            if not checks['valid_explicit_source_limits']:
                raise ValueError('invalid source six-axis declaration')
            expected = resolved_limits(limits);raw = {}
            for axis, value in expected.items():
                low, high = (None,None) if value == 'free' else (1.,-1.) if value == 'locked' else value
                raw[axis] = {'applied':value != 'free','low':low,'high':high}
            loaded = actual[legacy.path(name)]
            checks['loaded_typed_D6_and_modes'] = loaded['type'] == 'PhysicsJoint' and loaded['dof_limits'] == expected and loaded['dof_limit_attributes'] == raw
            required_apis = {'PhysicsLimitAPI:'+a for a,v in expected.items() if v != 'free'}
            schemas = loaded['resolved_applied_schemas']
            checks['ordinary_passive_static_joint'] = (loaded['exclude_from_articulation'] is True and
                loaded['drives'] == [] and loaded['drive_attributes'] == [] and
                loaded['joint_attribute_time_samples'] == {} and loaded['unregistered_limit_schemas'] == [] and
                isinstance(schemas,list) and len(schemas)==len(set(schemas)) and
                required_apis <= set(schemas) <= required_apis | {'PhysxJointAPI'})
            checks['complete_loaded_frame_shapes'] = all(isinstance(loaded[k],list) and len(loaded[k])==2 for k in ('body_paths','local_positions_m','local_rotations_wxyz')) and all(
                isinstance(loaded['body_paths'][i],list) and len(loaded['body_paths'][i]) <= 1 and
                measured_pose_valid(loaded['local_positions_m'][i],loaded['local_rotations_wxyz'][i]) for i in (0,1))
            checks['loaded_relationships_and_flags'] = all(loaded['body_paths'][i] == loaded['body'+str(i)] ==
                ([legacy.path(cfg['body'+str(i)])] if cfg.get('body'+str(i)) else []) for i in (0,1)) and loaded['enabled'] is cfg.get('enabled',True) and loaded['collision_enabled'] is cfg.get('collision_enabled',False)
            # Canonical raw frame precision is Float, just as LimitAPI bounds.
            import struct
            f32 = lambda vs:[struct.unpack('f',struct.pack('f',v))[0] for v in vs]
            checks['loaded_local_frames_match'] = all(loaded['local_positions_m'][i] == f32(cfg.get('local_pos'+str(i),[0,0,0])) and
                loaded['local_rotations_wxyz'][i] == f32(cfg.get('local_rot'+str(i)+'_wxyz',[1,0,0,0])) for i in (0,1))
            checks['same_sample_tensor_frames_complete'] = bool(samples) and spec.get('observation',{}).get('strict_start') is True
            for sample in samples:
                try:
                    state = sample['joints'][name]
                    if not isinstance(state,dict) or not all(finite_vector(state.get(key),size) for key,size in (
                            ('anchor0_world_m',3),('anchor1_world_m',3),('relative_rotation_wxyz',4),('translation_in_frame0_m',3))):
                        raise ValueError('incomplete finite D6 observation')
                    p0,q0 = _frame(sample,loaded,0);p1,q1 = _frame(sample,loaded,1)
                    local = legacy.rotate(_inverse(q0), legacy.sub(p1,p0))
                    relative = _qmul(_inverse(q0),q1)
                    measure = relative_observation(local,relative,expected)
                    point_error = max(math.dist(p0,state['anchor0_world_m']),math.dist(p1,state['anchor1_world_m']))
                    qa,qb = measure['relative_rotation_wxyz'],state['relative_rotation_wxyz']
                    q_error = min(math.dist(qa,qb),math.dist([-v for v in qa],qb))
                    valid = (state.get('pose_source') == 'same_sample_PhysX_rigid_body_tensors' and
                        state.get('drive_present') is False and state.get('type') == 'd6' and
                        state.get('enabled') is cfg.get('enabled',True) and point_error <= 1e-6 and q_error <= 1e-6 and
                        math.dist(local,state['translation_in_frame0_m']) <= 1e-6 and
                        legacy.finite(state.get('anchor_error_m')) and
                        legacy.finite(state.get('frame_separation_m')) and
                        abs(measure['frame_separation_m']-state['frame_separation_m']) <= 1e-6 and
                        abs(measure['anchor_error_m']-state['anchor_error_m']) <= 1e-6 and
                        legacy.finite(state.get('twist_x_degrees')) and legacy.finite(state.get('swing_angle_degrees')) and
                        abs(measure['swing_angle_degrees']-state['swing_angle_degrees']) <= 1e-5 and
                        measure['twist_x_degrees'] is not None and
                        abs((measure['twist_x_degrees']-state['twist_x_degrees']+180)%360-180) <= 1e-5)
                    detail['maximum_tensor_anchor_difference_m'] = max(detail['maximum_tensor_anchor_difference_m'],point_error)
                    detail['maximum_tensor_relative_q_difference'] = max(detail['maximum_tensor_relative_q_difference'],q_error)
                    detail['maximum_overall_swing_angle_degrees'] = max(detail['maximum_overall_swing_angle_degrees'],measure['swing_angle_degrees'])
                    twist = measure['twist_x_degrees'];limit = expected['rotX']
                    if twist is not None and limit != 'free':
                        low,high = (0.,0.) if limit == 'locked' else limit
                        detail['maximum_principal_twist_excess_degrees'] = max(detail['maximum_principal_twist_excess_degrees'], max(low-twist,twist-high,0.))
                except (KeyError,TypeError,ValueError,IndexError,ZeroDivisionError,AttributeError,OverflowError):
                    valid = False
                if not valid:
                    checks['same_sample_tensor_frames_complete'] = False
                    if detail['first_invalid_sample_step'] is None:detail['first_invalid_sample_step'] = sample.get('physics_steps')
        except (KeyError,TypeError,ValueError,IndexError,OverflowError,AttributeError) as error:
            checks['complete_valid_declaration'] = False;detail['error'] = str(error)
        detail['passed'] = all(checks.values())
        result['passed'] = result['passed'] and detail['passed']
    return result


def rope_source(spec, case):
    """Read-only structural admission before any outcome is available."""
    from ..d6 import validate_limits
    links = set(case['rope']['segment_ids']);ordered = case['rope']['joint_ids']
    objects = spec['objects'];internal = ordered[1:-1]
    checks = {'model_explicitly_declared':case.get('rope_joint_model') == MODEL,
        'strict_tensor_observation_requested':case.get('require_strict_initial_state') is True and spec.get('observation',{}).get('strict_start') is True}
    checks['initial_dynamic_colliding_longitudinal_capsules'] = bool(links) and all(
        (obj:=objects.get(name,{})).get('kind') == 'capsule' and obj.get('dynamic') is True and
        obj.get('collision') is True and not obj.get('spawn_step',0) and legacy.positive_mass(obj) and
        legacy.vector(obj.get('size')) and min(obj['size']) > 0 and abs(obj['size'][0]-obj['size'][1]) <= 1e-9 and
        obj['size'][2] >= obj['size'][0] and measured_pose_valid(obj.get('position',[0,0,0]),obj.get('orientation_wxyz',[1,0,0,0]))
        for name in links)
    checks['all_D6_are_declared_internal_rope_joints'] = {n for n,o in objects.items() if o.get('kind') == 'joint' and o.get('joint',{}).get('type') == 'd6'} == set(internal)
    checks['only_declared_chain_joints_touch_capsules'] = not [n for n,o in objects.items() if o.get('kind') == 'joint' and
        set((o.get('joint',{}).get('body0'),o.get('joint',{}).get('body1'))) & links and n not in ordered]
    checks['all_internal_D6_lock_translation_and_bound_rotation'] = bool(internal)
    checks['explicit_longitudinal_material_frames'] = bool(internal)
    for name in internal:
        cfg = objects.get(name,{}).get('joint',{});limits = cfg.get('dof_limits',{})
        checks['all_internal_D6_lock_translation_and_bound_rotation'] &= (cfg.get('type') == 'd6' and not validate_limits(limits) and
            all(limits.get(a) == 'locked' for a in AXES[:3]) and all(isinstance(limits.get(a),list) for a in AXES[3:]) and
            cfg.get('body0') in links and cfg.get('body1') in links and cfg.get('enabled',True) is True)
        for i in (0,1):
            q = cfg.get('local_rot'+str(i)+'_wxyz')
            valid = legacy.quaternion(q) and legacy.dot(legacy.rotate(q,[1,0,0]),[0,0,1]) >= 1-1e-6
            checks['explicit_longitudinal_material_frames'] &= bool(valid)
    return {'passed':all(checks.values()),'checks':checks,'scope':__doc__}


def rope_model(run, spec, case):
    """Admit one material-axis D6 chain; preserve all old numerical tests."""
    source = rope_source(spec,case);checks = dict(source['checks'])
    metadata = configuration(run,spec)
    checks['complete_passive_loaded_D6_tensor_observations'] = metadata['passed']
    return {'passed':all(checks.values()),'checks':checks,'configuration':metadata,'scope':__doc__}
