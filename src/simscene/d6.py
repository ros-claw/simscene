"""Explicit passive D6 modes and read-only relative-frame observations.

USD LimitAPI low > high means locked; no API means free. Angular ranges
are degrees and form a PhysX pyramid for the two swing axes, not a cone.
There are no drives, springs, setters or task callbacks in this module.
"""
import math
import struct

AXES = ('transX', 'transY', 'transZ', 'rotX', 'rotY', 'rotZ')


def finite_vector(value, count):
    return isinstance(value, (list, tuple)) and len(value) == count and all(type(x) in (int,float) and math.isfinite(x) for x in value)


def measured_pose_valid(position, rotation):
    return (finite_vector(position, 3) and finite_vector(rotation, 4) and
            math.isfinite(math.hypot(*position)) and
            math.isfinite(math.hypot(*rotation)) and abs(math.hypot(*rotation)-1) <= 1e-4)


def applied_schemas(prim):
    # usd-core may not register PhysX plugins. Preserve unknown raw API tokens
    # instead of letting the schema registry silently hide those opinions.
    raw = prim.GetMetadata('apiSchemas')
    return sorted(set(prim.GetAppliedSchemas()) | set(raw.GetAppliedItems() if raw else []))


def resolved_limits(limits):
    """USD LimitAPI attributes have Float type, so compare their actual precision."""
    return {axis: value if isinstance(value, str) else
            [struct.unpack('f', struct.pack('f', v))[0] for v in value]
            for axis, value in limits.items()}


def validate_limits(value):
    if not isinstance(value, dict) or set(value) != set(AXES):
        return ['d6 dof_limits must explicitly specify all six axes']
    errors = []
    for axis, limit in value.items():
        if isinstance(limit, str) and limit in ('free', 'locked'):
            continue
        valid = (isinstance(limit, list) and len(limit) == 2 and
                 all(type(v) in (int, float) and math.isfinite(v) for v in limit) and
                 limit[0] < limit[1])
        if valid and axis.startswith('rot'):
            valid = -180 < limit[0] < limit[1] < 180
        if valid:
            try:
                low, high = resolved_limits({axis: limit})[axis]
                valid = math.isfinite(low) and math.isfinite(high) and low < high
                if axis.startswith('rot'):
                    valid = valid and -180 < low < high < 180
            except (OverflowError, struct.error):
                valid = False
        if not valid:
            errors.append('invalid d6 ' + axis + ': use free, locked, or an ordered finite range; angular ranges must lie inside +/-180 degrees')
    return errors


def author_limits(joint, limits):
    from pxr import UsdPhysics
    errors = validate_limits(limits)
    if errors:
        raise ValueError('; '.join(errors))
    for axis in AXES:
        limit = limits[axis]
        if limit == 'free':
            continue
        api = UsdPhysics.LimitAPI.Apply(joint.GetPrim(), axis)
        low, high = (1., -1.) if limit == 'locked' else limit
        api.CreateLowAttr().Set(low)
        api.CreateHighAttr().Set(high)


def read_limits(prim):
    """Resolved USD limits, not a claim to read native solver impulses/modes."""
    from pxr import UsdPhysics
    values, attributes = {}, {}
    for axis in AXES:
        applied = prim.HasAPI(UsdPhysics.LimitAPI, axis)
        if not applied:
            values[axis] = 'free'
            attributes[axis] = {'applied': False, 'low': None, 'high': None}
            continue
        api = UsdPhysics.LimitAPI(prim, axis)
        low, high = api.GetLowAttr().Get(), api.GetHighAttr().Get()
        def serial(v):
            return v if v is None or math.isfinite(v) else ('nan' if math.isnan(v) else 'inf' if v > 0 else '-inf')
        attributes[axis] = {'applied': True, 'low': serial(low), 'high': serial(high)}
        values[axis] = 'locked' if low is not None and high is not None and low > high else [serial(low), serial(high)]
    schemas = applied_schemas(prim)
    unknown = [s for s in schemas if s.startswith('PhysicsLimitAPI:') and s.split(':', 1)[1] not in AXES]
    time_samples = {a.GetName(): list(a.GetTimeSamples()) for a in prim.GetAttributes() if a.GetNumTimeSamples()}
    return {'dof_limits': values, 'dof_limit_attributes': attributes,
            'unregistered_limit_schemas': unknown,
            'joint_attribute_time_samples': time_samples,
            'resolved_applied_schemas': schemas,
            'dof_limit_scope': 'Resolved loaded USD opinions. Native enforcement requires an actual physical trial.'}


def read_frames(prim):
    from pxr import UsdPhysics
    joint = UsdPhysics.Joint(prim)
    result = {'body_paths': [], 'local_positions_m': [], 'local_rotations_wxyz': []}
    for index in (0, 1):
        result['body_paths'].append([str(v) for v in getattr(joint, 'GetBody'+str(index)+'Rel')().GetTargets()])
        result['local_positions_m'].append(list(getattr(joint, 'GetLocalPos'+str(index)+'Attr')().Get()))
        q = getattr(joint, 'GetLocalRot'+str(index)+'Attr')().Get()
        result['local_rotations_wxyz'].append([q.GetReal(), *q.GetImaginary()])
    result.update(enabled=joint.GetJointEnabledAttr().Get(),
        collision_enabled=joint.GetCollisionEnabledAttr().Get(),
        exclude_from_articulation=joint.GetExcludeFromArticulationAttr().Get())
    return result


def validate_loaded(prim, cfg):
    """Check the complete authoring declaration without claiming SDK forces."""
    actual = {**read_limits(prim), **read_frames(prim)}
    def f32(values):
        return [struct.unpack('f', struct.pack('f', v))[0] for v in values]
    expected_frames = {
        'body_paths': [['/World/'+cfg['body'+str(i)].replace('-', '_')] if cfg.get('body'+str(i)) else [] for i in (0, 1)],
        'local_positions_m': [f32(cfg.get('local_pos'+str(i), [0, 0, 0])) for i in (0, 1)],
        'local_rotations_wxyz': [f32(cfg.get('local_rot'+str(i)+'_wxyz', [1, 0, 0, 0])) for i in (0, 1)],
        'enabled': cfg.get('enabled', True), 'collision_enabled': cfg.get('collision_enabled', False),
        'exclude_from_articulation': True}
    expected_limits = resolved_limits(cfg['dof_limits'])
    expected_raw = {}
    for axis, value in expected_limits.items():
        applied = value != 'free'
        low, high = (None, None) if not applied else (1., -1.) if value == 'locked' else value
        expected_raw[axis] = {'applied': applied, 'low': low, 'high': high}
    allowed_properties = {'physics:'+name for name in ('localPos0', 'localPos1', 'localRot0', 'localRot1',
        'jointEnabled', 'collisionEnabled', 'excludeFromArticulation')}
    allowed_properties |= {'limit:'+axis+':physics:'+end for axis, value in expected_limits.items()
        if value != 'free' for end in ('low', 'high')}
    extras = [a.GetName() for a in prim.GetAttributes() if a.HasAuthoredValueOpinion() and a.GetName() not in allowed_properties]
    allowed_apis = {'PhysicsLimitAPI:'+axis for axis, value in expected_limits.items() if value != 'free'}
    # PhysxJointAPI may be applied by the backend; authored extension settings
    # (projection, friction, armature, etc.) are still rejected as undeclared.
    unexpected_apis = [v for v in applied_schemas(prim) if v not in allowed_apis | {'PhysxJointAPI'}]
    if (prim.GetTypeName() != 'PhysicsJoint' or actual['dof_limits'] != expected_limits or
            actual['dof_limit_attributes'] != expected_raw or actual['unregistered_limit_schemas'] or
            actual['joint_attribute_time_samples'] or any(actual[k] != v for k,v in expected_frames.items()) or
            extras or unexpected_apis):
        raise RuntimeError('D6 loaded declaration differs or contains animation/undeclared physics: '+str(prim.GetPath()))
    return {**actual, 'undeclared_authored_attributes': extras, 'unexpected_applied_schemas': unexpected_apis}


def relative_observation(translation, rotation, limits):
    """Observe J=frame0^-1*frame1; keep its complete quaternion.

    Twist is about joint X. Swing angle is overall tilt, not either pyramid
    coordinate and must not be compared against individual rotY/rotZ ranges.
    """
    if not finite_vector(translation, 3) or not finite_vector(rotation, 4):
        raise ValueError('D6 relative frame requires a finite 3-vector and unit quaternion')
    q = [float(v) for v in rotation]
    length = math.hypot(*q)
    if not math.isfinite(length) or abs(length-1) > 1e-4 or not math.isfinite(math.hypot(*translation)):
        raise ValueError('D6 relative frame requires a bounded vector and unit quaternion')
    if validate_limits(limits):
        raise ValueError('D6 relative frame requires valid resolved limits')
    limits = resolved_limits(limits)
    q = [v/length for v in q]
    if q[0] < 0:
        q = [-v for v in q]
    w, x, y, z = q
    twist_norm = math.hypot(w, x)
    twist = math.degrees(2*math.atan2(x, w)) if twist_norm > 1e-12 else None
    swing = math.degrees(2*math.acos(min(1., twist_norm)))
    errors = []
    for axis, coordinate in zip(AXES[:3], translation):
        limit = limits[axis]
        if limit == 'free':
            errors.append(0.)
        elif limit == 'locked':
            errors.append(coordinate)
        else:
            errors.append(coordinate-min(limit[1], max(limit[0], coordinate)))
    return {'translation_in_frame0_m': [float(v) for v in translation],
            'relative_rotation_wxyz': q, 'twist_x_degrees': twist,
            'swing_angle_degrees': swing,
            'anchor_error_m': math.hypot(*errors),
            'frame_separation_m': math.hypot(*translation),
            'coordinate_scope': 'Measured relative joint frames; twist/swing decomposition is not global Euler angles. Overall swing is not either pyramid coordinate. Twist is undefined at a 180-degree swing.'}
