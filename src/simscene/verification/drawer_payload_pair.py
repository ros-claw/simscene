"""Read-only checks for a frozen two-drawer / independent-payload pair.

The case describes a specific prepared cabinet, payload, command schedule and
geometry. Neither declared capabilities nor a rendered clip prove the result.
"""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re

from ..worker.mechanism import _mul, _quaternion, _rotate, _vector, measure_joint


def _normalize(value, root):
    if isinstance(value, dict):
        return {key: _normalize(item, root) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item, root) for item in value]
    if isinstance(value, str) and value.startswith(str(root) + os.sep):
        return '${RUN}/' + value[len(str(root)) + 1:]
    return value


def only_lower_drive_removed(positive, control, expected_commands, positive_root, control_root):
    """Require the same semantic scene with exactly the lower drives omitted."""
    try:
        positive, control = copy.deepcopy(positive), copy.deepcopy(control)
        pc = positive['objects']['cabinet']['mechanism']['commands']
        cc = control['objects']['cabinet']['mechanism']['commands']
        if (not isinstance(expected_commands, list) or pc != expected_commands
                or not any(c.get('joint_id') == 'joint0' for c in pc)
                or not any(c.get('joint_id') == 'joint1' for c in pc)
                or cc != [c for c in pc if c.get('joint_id') != 'joint0']):
            return False
        positive['objects']['cabinet']['mechanism']['commands'] = cc
        for obj in (positive, control):
            for key in ('scene_id', 'revision', 'requests'):
                obj.pop(key, None)
        return _normalize(positive, positive_root) == _normalize(control, control_root)
    except (AttributeError, KeyError, TypeError):
        return False


def payload_corners_local(payload_position, payload_quaternion, drawer_position, drawer_quaternion, bounds):
    """Transform the conservative prepared collider box into drawer coordinates."""
    pp = _vector(payload_position, 3, 'payload position')
    dp = _vector(drawer_position, 3, 'drawer position')
    pq, dq = _quaternion(payload_quaternion), _quaternion(drawer_quaternion)
    lo, hi = _vector(bounds['min'], 3, 'collider minimum'), _vector(bounds['max'], 3, 'collider maximum')
    if any(lo[i] >= hi[i] for i in range(3)):
        raise ValueError('collider bounds must have positive extent')
    inverse = [dq[0], -dq[1], -dq[2], -dq[3]]
    points = []
    for x in (lo[0], hi[0]):
        for y in (lo[1], hi[1]):
            for z in (lo[2], hi[2]):
                world = _rotate(pq, [x, y, z])
                points.append(_rotate(inverse, [world[i] + pp[i] - dp[i] for i in range(3)]))
    return points


def corners_within(corners, bounds):
    lo, hi = _vector(bounds['min'], 3, 'support minimum'), _vector(bounds['max'], 3, 'support maximum')
    if any(lo[i] >= hi[i] for i in range(3)) or len(corners) != 8:
        raise ValueError('invalid support or payload corners')
    return all(all(lo[i] <= _vector(point, 3, 'collider corner')[i] <= hi[i] for i in range(3)) for point in corners)


def moving_contact_steps(frames, payload_body, drawer_body, joint_path, window):
    """Return observed contacts only while the native drawer coordinate changes."""
    _window(frames,window,'lower motion')
    found=[]
    for step in range(max(1,window[0]),window[1]+1):
        current=frames[step]['native_joint_positions'][joint_path]
        previous=frames[step-1]['native_joint_positions'][joint_path]
        if abs(current-previous)<1e-5:
            continue
        if any(set(pair.get('actor_paths',[]))=={payload_body,drawer_body} and pair.get('count',0)>0
               for pair in frames[step].get('contact_pairs',[])):
            found.append(step)
    return found


def max_axis_displacement(frames, body, axis):
    """Measure maximum absolute displacement from the first observed frame."""
    if not isinstance(frames,list) or not frames:
        raise ValueError('a complete observed trajectory is required')
    axis=_vector(axis,3,'world joint axis')
    origin=_vector(frames[0]['positions'][body],3,'initial body position')
    return max(abs(sum((x-y)*direction for x,y,direction in
        zip(_vector(frame['positions'][body],3,'body position'),origin,axis))) for frame in frames)


def _read(root, name):
    path = root / name
    if path.is_symlink() or not path.is_file():
        raise ValueError('required ordinary run file is missing: ' + name)
    value = json.loads(path.read_text(encoding='utf8'))
    if not isinstance(value, dict):
        raise ValueError('run document must be an object: ' + name)
    return value


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _distance(a, b):
    return math.sqrt(sum((x-y)**2 for x, y in zip(a, b)))


def _window(frames, value, name):
    if (not isinstance(value, list) or len(value) != 2
            or any(type(i) is not int for i in value) or not 0 <= value[0] <= value[1] < len(frames)):
        raise ValueError('invalid frozen ' + name + ' window')
    return frames[value[0]:value[1]+1]


def _validate_case(case):
    if (not isinstance(case, dict) or case.get('schema') != 'simscene.drawer_payload_pair.v1'
            or case.get('steps') != 600 or case.get('seed') != 42
            or case.get('physics_device') != 'cpu' or case.get('physics_dt_s') != 1/60):
        raise ValueError('unsupported fixed drawer payload case')
    windows = case.get('windows')
    if not isinstance(windows, dict) or set(windows) != {'reference_step', 'upper_hold', 'lower_hold', 'lower_motion', 'final'}:
        raise ValueError('case requires all frozen measurement windows')
    if type(windows['reference_step']) is not int or not 0 < windows['reference_step'] < 600:
        raise ValueError('invalid payload reference step')
    for name in ('upper_hold', 'lower_hold', 'lower_motion', 'final'):
        _window([None]*601, windows[name], name)
    if windows['final'][1]-windows['final'][0]+1 < 60:
        raise ValueError('final observation requires at least 60 physical steps')
    thresholds = case.get('thresholds')
    limits = {'target_error_m': .01, 'control_displacement_m': .005, 'relative_drift_m': .02,
              'final_joint_error_m': .01, 'table_drift_m': .002, 'tilt_deg': 10.,
              'joint_reconstruction_error_m': .001}
    if not isinstance(thresholds, dict) or set(thresholds) != set(limits) | {'min_drawer_travel_m', 'min_payload_fraction'}:
        raise ValueError('case requires the fixed payload acceptance thresholds')
    for key, maximum in limits.items():
        value = thresholds[key]
        if type(value) not in (int,float) or not math.isfinite(value) or not 0 < value <= maximum:
            raise ValueError('threshold too loose or invalid: ' + key)
    for key, minimum in [('min_drawer_travel_m', .2), ('min_payload_fraction', .8)]:
        value = thresholds[key]
        if type(value) not in (int,float) or not math.isfinite(value) or value < minimum:
            raise ValueError('threshold too loose or invalid: ' + key)
    for key in ('payload_collider_bounds_local', 'support_bounds_local'):
        bounds = case.get(key)
        if not isinstance(bounds, dict) or set(bounds) != {'min', 'max'}:
            raise ValueError('missing frozen geometry bounds: ' + key)
        lo, hi = _vector(bounds['min'],3,key), _vector(bounds['max'],3,key)
        if any(lo[i] >= hi[i] for i in range(3)):raise ValueError('invalid geometry bounds: ' + key)
    height = _vector(case.get('allowed_bottom_z_local'),2,'allowed payload bottom interval')
    if height[0] >= height[1] or height[1]-height[0] > .02:
        raise ValueError('invalid payload bottom height interval')
    if (not isinstance(case.get('positive_commands'),list) or not case['positive_commands']
            or not isinstance(case.get('bindings'),dict)
            or set(case['bindings']) != {'cabinet','box','book_a','book_b'}):
        raise ValueError('missing fixed commands or prepared asset identities')
    for binding in case['bindings'].values():
        if (not isinstance(binding,dict) or not re.fullmatch('[0-9a-f]{64}',str(binding.get('manifest_sha256','')))
                or not isinstance(binding.get('source_ref'),dict)):
            raise ValueError('each prepared asset requires its source and manifest pin')
    commands=case['positive_commands'];by_joint={'joint0':[],'joint1':[]};prior=-1
    for command in commands:
        if not isinstance(command,dict) or command.get('joint_id') not in by_joint:
            raise ValueError('unsupported drawer command')
        trigger=command.get('trigger')
        if (not isinstance(trigger,dict) or set(trigger)!={'type','physics_step'} or trigger.get('type')!='at_step'
                or type(trigger.get('physics_step')) is not int or not 0<=trigger['physics_step']<=600
                or trigger['physics_step']<prior or command.get('position_unit')!='m'
                or command.get('stiffness')!=2000. or command.get('damping')!=100.
                or command.get('max_effort')!=400.):
            raise ValueError('drawer commands differ from the bounded drive protocol')
        prior=trigger['physics_step'];by_joint[command['joint_id']].append(command)
    for key,target in [('joint0',.25),('joint1',.35)]:
        sequence=by_joint[key]
        if (len(sequence)!=3 or [item.get('target_position') for item in sequence]!=[0.,target,0.]
                or sequence[0]['trigger']['physics_step']!=0
                or not 0<sequence[1]['trigger']['physics_step']<sequence[2]['trigger']['physics_step']):
            raise ValueError('each drawer needs exactly one open and one closing command')
        opened,closed=(item['trigger']['physics_step'] for item in sequence[1:])
        hold=windows['lower_hold' if key=='joint0' else 'upper_hold']
        if not opened < hold[0] <= hold[1] < closed:
            raise ValueError('hold window is outside the corresponding driven phase')
        if windows['final'][0] <= closed:
            raise ValueError('final window starts before a drawer is commanded closed')
    open_lower,close_lower=(item['trigger']['physics_step'] for item in by_joint['joint0'][1:])
    if (not windows['reference_step'] < open_lower
            or windows['lower_motion'][0]!=open_lower or windows['lower_motion'][1]>=close_lower
            or windows['lower_motion'][1]<windows['lower_hold'][1]):
        raise ValueError('payload motion window differs from its drive interval')
    return case


def _geometry(root, case, result):
    """Check authored colliders, independently of the render bounding boxes."""
    from pxr import Usd, UsdGeom, UsdPhysics
    from ..physics_binding import validate_asset_binding
    spec = _read(root, 'spec.json')
    stage = Usd.Stage.Open(str(root/'scene.usda'))
    if stage is None:raise ValueError('frozen stage cannot be opened')
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render,
                          UsdGeom.Tokens.proxy, UsdGeom.Tokens.guide], False, True)
    for role, expected in case['bindings'].items():
        obj = spec['objects'][role]
        binding = obj.get('asset_binding', {})
        if binding.get('manifest_sha256') != expected.get('manifest_sha256'):
            raise ValueError('prepared manifest differs from case: '+role)
        manifest = validate_asset_binding(binding, require_dynamic=True, asset_path=obj['asset_path'])
        if manifest.get('source_ref') != expected.get('source_ref'):
            raise ValueError('prepared source differs from case: '+role)
        if obj.get('dynamic') is not True or any(k in obj for k in ('rigid_attachment','pose_follower','kinematic')):
            raise ValueError('a carried or table prop is not an independent dynamic asset: '+role)
    body = result['body_bindings']['box']['motion_body']
    payload = stage.GetPrimAtPath(body)
    rb = UsdPhysics.RigidBodyAPI(payload)
    disable = payload.GetAttribute('physxRigidBody:disableGravity')
    if (not payload or not rb or rb.GetRigidBodyEnabledAttr().Get() is False
            or rb.GetKinematicEnabledAttr().Get() is True or (disable and disable.Get() is True)):
        raise ValueError('payload must be an enabled nonkinematic rigid body with gravity')
    paths = result['body_bindings']['box']['collider_paths']
    if not isinstance(paths,list) or len(paths)!=1:raise ValueError('expected one pinned payload collider')
    collider = stage.GetPrimAtPath(paths[0]); api = UsdPhysics.CollisionAPI(collider)
    if (not collider or not api or api.GetCollisionEnabledAttr().Get() is False
            or UsdPhysics.MeshCollisionAPI(collider).GetApproximationAttr().Get() != 'convexHull'):
        raise ValueError('payload convex-hull collider is missing or disabled')
    bounds = cache.ComputeRelativeBound(collider,payload).ComputeAlignedRange()
    if bounds.IsEmpty():raise ValueError('payload collider has no geometric bounds')
    actual = {'min':list(bounds.GetMin()),'max':list(bounds.GetMax())}
    for key in ('min','max'):
        if any(abs(actual[key][i]-case['payload_collider_bounds_local'][key][i])>1e-6 for i in range(3)):
            raise ValueError('payload collider geometry differs from frozen case')
    lower_path=result['body_bindings']['cabinet']['bodies']['link1']['motion_body']
    lower=stage.GetPrimAtPath(lower_path)
    named={}
    for name in ('box_bottom','box_left','box_right','box_back','inner_front_rail'):
        prim=stage.GetPrimAtPath(lower_path+'/Collisions/'+name+'/Geom')
        api=UsdPhysics.CollisionAPI(prim)
        if not prim or prim.GetTypeName()!='Cube' or not api or api.GetCollisionEnabledAttr().Get() is False:
            raise ValueError('required separate lower drawer collider is missing: '+name)
        bound=cache.ComputeRelativeBound(prim,lower).ComputeAlignedRange()
        if bound.IsEmpty():raise ValueError('drawer collider has no measured bounds: '+name)
        named[name]={'min':list(bound.GetMin()),'max':list(bound.GetMax())}
    usable={'min':[named['box_left']['max'][0], named['inner_front_rail']['max'][1]],
            'max':[named['box_right']['min'][0], named['box_back']['min'][1]]}
    declared=case['support_bounds_local']
    if any(declared['min'][i]<usable['min'][i]-1e-6 or declared['max'][i]>usable['max'][i]+1e-6 for i in range(2)):
        raise ValueError('frozen support extends outside actual drawer walls')
    floor=named['box_bottom']['max'][2]
    bottom=case['allowed_bottom_z_local']
    if not bottom[0] <= floor <= bottom[1] or floor-bottom[0]>.01 or bottom[1]-floor>.01:
        raise ValueError('frozen payload height interval is inconsistent with actual floor')
    return actual


def _metrics(result, case, positive):
    frames=[result.get('initial_observation'),*result.get('samples',[])]
    zero=result.get('run_zero_absolute_physics_step');absolute=result.get('run_zero_absolute_simulation_time_s')
    if (result.get('actual_physics_steps') != case['steps'] or result.get('requested_physics_steps') != case['steps']
            or result.get('partial') is not False or result.get('samples_truncated') is not False
            or result.get('seed') != case['seed']
            or result.get('observation_interval_steps') != 1 or len(frames) != case['steps']+1
            or type(zero) is not int or type(absolute) not in (int,float) or not math.isfinite(absolute)):
        raise ValueError('run lacks a complete per-step physical timeline')
    for index, frame in enumerate(frames):
        if (not isinstance(frame,dict) or frame.get('physics_steps') != index
                or frame.get('absolute_physics_step') != zero+index
                or type(frame.get('simulation_time_s')) not in (int,float) or not math.isfinite(frame['simulation_time_s'])
                or abs(frame['simulation_time_s']-index/60)>1e-6
                or type(frame.get('absolute_simulation_time_s')) not in (int,float) or not math.isfinite(frame['absolute_simulation_time_s'])
                or abs(frame['absolute_simulation_time_s']-absolute-index/60)>1e-5):
            raise ValueError('run contains a missing or inconsistent physical sample')
    if result.get('followers') != {} or result.get('task_status') not in ('unverified','completed'):
        raise ValueError('unexpected follower or failed task in physical run')
    for phase in ('before_warmup','after_run'):
        settings=result['physics_settings'][phase]
        if (settings.get('requested_device')!='cpu' or settings.get('enable_gpu_dynamics') is not False
                or settings.get('request_matches_observation') is not True
                or abs(settings.get('authored_time_steps_per_second',0)-60)>1e-5
                or settings.get('gravity_magnitude_m_s2',0)<=0):
            raise ValueError('actual physics settings differ from frozen case')
    cb=result['body_bindings']['cabinet'];pb=result['body_bindings']['box']
    if cb.get('profile_id')!='articulated_prop_v2' or set(cb.get('joints',{}))!={'joint0','joint1'}:
        raise ValueError('run is not the pinned two-joint articulation')
    lower,upper=cb['joints']['joint0'],cb['joints']['joint1']
    body=pb['motion_body'];drawer=lower['child_body'];parent=lower['parent_body']
    if (lower['type']!='prismatic' or upper['type']!='prismatic'
            or lower['joint_path']==upper['joint_path'] or lower['child_body']==upper['child_body']):
        raise ValueError('drawer joint bindings are not two independent prismatic coordinates')
    if body in cb.get('motion_bodies',[]) or pb.get('profile_id')!='rigid_prop_v1':
        raise ValueError('payload is not an independent rigid body')
    previous={};max_q_error=0.
    for frame in frames:
        if frame.get('native_joint_measurement_source')!='PhysX_articulation_tensor_DOF_readback_SI':
            raise ValueError('native joint tensor source is missing')
        for key,joint in cb['joints'].items():
            measured=measure_joint(joint,frame,previous.get(key),physics_step=frame['physics_steps'],
                                   physics_dt_s=case['physics_dt_s'],require_unique_initial=True)
            native=frame['native_joint_positions'][joint['joint_path']]
            if type(native) not in (int,float) or not math.isfinite(native):raise ValueError('invalid native joint position')
            max_q_error=max(max_q_error,abs(native-measured['position']))
            if not joint['limits'][0]-.001 <= native <= joint['limits'][1]+.001:
                raise ValueError('actual joint exceeded native limits')
            previous[key]=measured
    if max_q_error>case['thresholds']['joint_reconstruction_error_m']:
        raise ValueError('native joint positions disagree with same-step rigid body poses')
    commands=case['positive_commands'] if positive else [c for c in case['positive_commands'] if c['joint_id']!='joint0']
    events=frames[-1]['mechanisms']['cabinet']['command_events']
    if len(events)!=len(commands):raise ValueError('actual command event count differs from the frozen schedule')
    for index,(event,command) in enumerate(zip(events,commands)):
        drive=event.get('drive_readback',{})
        if (event.get('command_index')!=index or event.get('joint_id')!=command['joint_id']
                or event.get('physics_step')!=command['trigger']['physics_step']
                or event.get('trigger')!=command['trigger'] or event.get('cause')!='declared_at_step_schedule'
                or event.get('target_position')!=command['target_position']
                or any(abs(drive.get(field,float('inf'))-command[key])>1e-4 for field,key in
                       [('target_position','target_position'),('stiffness','stiffness'),('damping','damping'),('max_force','max_effort')])):
            raise ValueError('actual drive event differs from the frozen schedule')
    windows=case['windows'];reference=frames[windows['reference_step']]
    pq=_quaternion(reference['orientations_wxyz'][parent])
    frame_rot=_mul(pq,lower['local_rot0_wxyz'])
    local_axis=[0.,0.,0.];local_axis[('X','Y','Z').index(lower['axis'])]=1.
    axis=_rotate(frame_rot,local_axis)
    base=_vector(reference['positions'][body],3,'reference payload position')
    def coordinate(frame):return frame['native_joint_positions'][lower['joint_path']]
    def payload_travel(frame):
        position=_vector(frame['positions'][body],3,'payload position')
        return sum((position[i]-base[i])*axis[i] for i in range(3))
    def relative(frame):
        pos=_vector(frame['positions'][body],3,'payload position');dp=_vector(frame['positions'][drawer],3,'drawer position')
        dq=_quaternion(frame['orientations_wxyz'][drawer]);inv=[dq[0],-dq[1],-dq[2],-dq[3]]
        return _rotate(inv,[pos[i]-dp[i] for i in range(3)])
    lh=_window(frames,windows['lower_hold'],'lower hold');uh=_window(frames,windows['upper_hold'],'upper hold')
    final=_window(frames,windows['final'],'final')
    lower0=coordinate(frames[0]);upper0=frames[0]['native_joint_positions'][upper['joint_path']]
    qref=coordinate(reference);base_rel=relative(reference)
    lower_hold=[coordinate(f) for f in lh];upper_hold=[f['native_joint_positions'][upper['joint_path']] for f in uh]
    payload_hold=[payload_travel(f) for f in lh]
    points=[payload_corners_local(f['positions'][body],f['orientations_wxyz'][body],
             f['positions'][drawer],f['orientations_wxyz'][drawer],case['payload_collider_bounds_local']) for f in lh+final]
    supported=all(corners_within(p,case['support_bounds_local']) and
                  case['allowed_bottom_z_local'][0] <= min(x[2] for x in p) <= case['allowed_bottom_z_local'][1] for p in points)
    refq=_quaternion(reference['orientations_wxyz'][body]);tilts=[]
    for f in final:
        q=_quaternion(f['orientations_wxyz'][body]);dot=abs(sum(a*b for a,b in zip(q,refq)))
        tilts.append(math.degrees(2*math.acos(max(-1.,min(1.,dot)))))
    drift={}
    for name in ('book_a','book_b'):
        path=result['body_bindings'][name]['motion_body'];origin=_vector(final[0]['positions'][path],3,'table prop')
        drift[name]=max(_distance(_vector(f['positions'][path],3,'table prop'),origin) for f in final)
    contacts=moving_contact_steps(frames,body,drawer,lower['joint_path'],windows['lower_motion'])
    t=case['thresholds']
    check={'upper_reached':all(abs(q-.35)<=t['target_error_m'] for q in upper_hold),
           'lower_closed':all(abs(coordinate(f)-lower0)<=t['final_joint_error_m'] for f in final),
           'upper_closed':all(abs(f['native_joint_positions'][upper['joint_path']]-upper0)<=t['final_joint_error_m'] for f in final),
           'payload_supported':supported,'payload_tilt':max(tilts)<=t['tilt_deg'],
           'table_props_stable':all(v<=t['table_drift_m'] for v in drift.values())}
    if positive:
        check.update(lower_reached=all(abs(q-.25)<=t['target_error_m'] for q in lower_hold),
                     payload_followed=all(q-qref>=t['min_drawer_travel_m'] and p>=t['min_payload_fraction']*(q-qref)
                                          for q,p in zip(lower_hold,payload_hold)),
                     payload_relative_drift=max(_distance(relative(f),base_rel) for f in lh)<=t['relative_drift_m'],
                     actual_payload_drawer_contact=bool(contacts))
    else:
        check.update(lower_undriven_stationary=max(abs(coordinate(f)-lower0) for f in frames)<=t['control_displacement_m'],
                     payload_undriven_stationary=max_axis_displacement(frames,body,axis)<=t['control_displacement_m'])
    return {'checks':check,'lower_hold_minmax_m':[min(lower_hold),max(lower_hold)],
            'upper_hold_minmax_m':[min(upper_hold),max(upper_hold)],
            'payload_hold_displacement_minmax_m':[min(payload_hold),max(payload_hold)],
            'payload_relative_hold_drift_m':max(_distance(relative(f),base_rel) for f in lh),
            'final_table_drift_m':drift,'final_payload_tilt_deg':max(tilts),
            'full_run_drawer_displacement_max_m':max(abs(coordinate(f)-lower0) for f in frames),
            'full_run_payload_displacement_max_m':max_axis_displacement(frames,body,axis),
            'native_pose_max_error_m':max_q_error,'actual_contact_samples':len(contacts),
            'contact_geometry_incomplete':result.get('contact_geometry_incomplete')}


def verify_pair(positive_directory, control_directory, case_path=None):
    """Verify two same-case, same-runtime runs and one causal intervention."""
    report = {'schema': 'simscene.drawer_payload_pair_report.v1', 'passed': False,
              'checks': {}, 'errors': [], 'metrics': {},
              'scope': 'Specific frozen pair; actual contact callbacks do not certify absence of all penetration.'}
    try:
        from ..run_integrity import verify as verify_inputs
        from ..evidence_integrity import verify as verify_outputs
        p,c=Path(positive_directory).resolve(),Path(control_directory).resolve()
        if p==c:raise ValueError('positive and control must be distinct runs')
        pl,cl=_read(p,'run-lock.json'),_read(c,'run-lock.json')
        pc,cc=_read(p,'acceptance-case.json'),_read(c,'acceptance-case.json')
        case=_validate_case(pc)
        digest=_sha(p/'acceptance-case.json')
        if (pc!=cc or _sha(c/'acceptance-case.json')!=digest or pl.get('acceptance_case_sha256')!=digest
                or cl.get('acceptance_case_sha256')!=digest or case_path is not None and _sha(case_path)!=digest):
            raise ValueError('the two runs do not use the same frozen case')
        keys=('runtime_version','runtime_python_sha256','queue_launcher_python_sha256','worker_code_sha256',
              'seed','physics_device','physics_dt_s','requested_physics_steps','gpu_selection')
        if (pl.get('run_id')==cl.get('run_id') or any(key not in pl or pl.get(key)!=cl.get(key) for key in keys)
                or pl['seed']!=case['seed'] or pl['physics_device']!=case['physics_device']
                or pl['physics_dt_s']!=case['physics_dt_s'] or pl['requested_physics_steps']!=case['steps']):
            raise ValueError('run identities, worker, runtime, seed, device or steps differ')
        pi,ci,pe,ce=verify_inputs(p),verify_inputs(c),verify_outputs(p),verify_outputs(c)
        if any(x.get('passed') is not True for x in (pi,ci,pe,ce)) or pe.get('partial') is not False or ce.get('partial') is not False:
            raise ValueError('run inputs or evidence did not pass integrity checks')
        ps,cs=_read(p,'spec.json'),_read(c,'spec.json')
        if not only_lower_drive_removed(ps,cs,case['positive_commands'],p,c):
            raise ValueError('control is not exactly the positive scene without lower drive commands')
        pr,cr=_read(p,'result.json'),_read(c,'result.json')
        if pr.get('body_bindings')!=cr.get('body_bindings'):
            raise ValueError('run body or joint mappings differ')
        _geometry(p,case,pr);_geometry(c,case,cr)
        positive,control=_metrics(pr,case,True),_metrics(cr,case,False)
        report['metrics']={'positive':positive,'control':control}
        report['checks']={'same_frozen_case':True,'same_runtime_and_seed':True,
                          'input_and_output_integrity':True,'only_lower_drive_removed':True,
                          'actual_geometry_and_bindings':True,
                          **{'positive_'+k:v for k,v in positive['checks'].items()},
                          **{'control_'+k:v for k,v in control['checks'].items()}}
        report['passed']=all(value is True for value in report['checks'].values())
    except Exception as error:
        report['errors'].append(type(error).__name__ + ': ' + str(error))
    return report
