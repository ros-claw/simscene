"""Conservative admission and inventory of an existing native single-DOF joint.

No physical schema is added or removed here. Noncanonical units/frames are
unsupported: scaling a parent is not a valid joint/inertia conversion.
"""
import math
from .profiles import PreparationError


def _fail(message):
    raise PreparationError('physics_profile_unsupported', message)


def canonical_stage(stage):
    from pxr import UsdGeom
    if (not stage.HasAuthoredMetadata('metersPerUnit') or abs(UsdGeom.GetStageMetersPerUnit(stage)-1.) > 1e-9
            or not stage.HasAuthoredMetadata('upAxis') or UsdGeom.GetStageUpAxis(stage) != UsdGeom.Tokens.z):
        _fail('native articulated physics requires authored metres and Z-up; joint/inertia conversion unsupported')


def _finite(values, name, positive=False):
    try:
        values = [float(v) for v in values]
    except (TypeError, ValueError):
        _fail('missing native ' + name)
    if not all(math.isfinite(v) and (not positive or v > 0) for v in values):
        _fail('invalid native ' + name)
    return values


def _rigid_frame(prim):
    from pxr import Usd, UsdGeom
    matrix = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    axes = [matrix.ExtractRotationMatrix().GetRow(i) for i in range(3)]
    if (any(abs(axis.GetLength()-1.) > 1e-6 for axis in axes)
            or any(abs(axes[i]*axes[j]) > 1e-6 for i in range(3) for j in range(i))
            or matrix.GetDeterminant() < 0):
        _fail('native joint/body ancestors require unit scale, no shear or reflection')


def inspect_articulation(stage, root=None):
    """Return complete body/joint maps, expressed relative to an existing root."""
    from pxr import Usd, UsdPhysics
    canonical_stage(stage)
    root = root or stage.GetDefaultPrim()
    if not root:
        _fail('native articulated source requires a default prim')
    prims = list(Usd.PrimRange(root));root_path = str(root.GetPath())
    def relative(path):
        value = str(path)
        if value != root_path and not value.startswith(root_path + '/'):
            _fail('native joint endpoints escape the selected default prim')
        return value[len(root_path):].lstrip('/')
    bodies = {};colliders = {};joints = [];fixed = []
    for prim in prims:
        if any(a.GetNumTimeSamples() for a in prim.GetAttributes()):
            _fail('native articulated time-sampled attributes are unsupported')
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            api = UsdPhysics.RigidBodyAPI(prim)
            if not api.GetRigidBodyEnabledAttr().Get() or api.GetKinematicEnabledAttr().Get():
                _fail('native articulated links must be enabled nonkinematic rigid bodies')
            _rigid_frame(prim)
            mass = UsdPhysics.MassAPI(prim)
            if not mass or not mass.GetMassAttr().HasAuthoredValueOpinion():
                _fail('native articulated link lacks explicit mass')
            value = _finite([mass.GetMassAttr().Get()], 'mass', positive=True)[0]
            diagonal = list(mass.GetDiagonalInertiaAttr().Get())
            auto = diagonal == [0.,0.,0.]
            if auto:
                inertia = None
            else:
                inertia = _finite(diagonal, 'diagonal inertia', positive=True)
                if max(inertia) > sum(inertia)-max(inertia)+1e-8:
                    _fail('native link inertia violates principal moment triangle inequality')
            native_com = list(mass.GetCenterOfMassAttr().Get())
            com = None if native_com == [-math.inf]*3 else _finite(native_com, 'center of mass')
            q = mass.GetPrincipalAxesAttr().Get()
            native_orientation = [q.GetReal(), *q.GetImaginary()]
            orientation = None if native_orientation == [0.]*4 else _finite(native_orientation, 'inertia principal axes')
            if orientation is not None and abs(sum(v*v for v in orientation)-1) > 1e-5:
                _fail('native inertia principal axes must be normalized')
            bodies[str(prim.GetPath())] = {'mass_kg': value, 'diagonal_inertia_kg_m2': inertia,
                'center_of_mass_local_m': com, 'principal_axes_wxyz': orientation,
                'inertia_provenance': 'engine_computes_from_preserved_native_colliders_and_authored_mass' if auto else 'preserved_native_USD_authored_inertia',
                'physics_provenance': 'preserved_native_USD_authored_values'}
        if prim.HasAPI(UsdPhysics.CollisionAPI):
            if not UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Get():
                _fail('disabled native collider cannot qualify an articulated link')
            body = prim
            while body and not body.HasAPI(UsdPhysics.RigidBodyAPI):
                body = body.GetParent()
            colliders.setdefault(str(body.GetPath()) if body else None, []).append(str(prim.GetPath()))
        if prim.IsA(UsdPhysics.Joint):
            if prim.IsA(UsdPhysics.FixedJoint):
                fixed.append(prim)
            elif prim.IsA(UsdPhysics.RevoluteJoint) or prim.IsA(UsdPhysics.PrismaticJoint):
                joints.append(prim)
            else:
                _fail('native joint type is unsupported; single hinge/slider only')
    if len(joints) != 1 or not 1 <= len(bodies) <= 2 or len(fixed) > 1:
        _fail('articulated profile supports exactly one native hinge/slider and at most two links plus one world fixed joint')
    body_map = {};ids = {}
    for index, (path, properties) in enumerate(sorted(bodies.items())):
        if not colliders.get(path):
            _fail('native articulated link lacks enabled collision')
        local_id = 'link' + str(index);ids[path] = local_id
        body_map[local_id] = dict(properties, relative_prim_path=relative(path), role='rigid',
            visual_relative_prim_paths=[relative(path)], collider_relative_prim_paths=[relative(p) for p in colliders[path]])
    if colliders.get(None):
        body_map['static'] = {'relative_prim_path':'', 'role':'static', 'visual_relative_prim_paths':[''],
                             'collider_relative_prim_paths':[relative(p) for p in colliders[None]]}
    prim = joints[0];api = UsdPhysics.Joint(prim)
    if not api.GetJointEnabledAttr().Get():
        _fail('native joint is disabled')
    endpoints = []
    for rel in (api.GetBody0Rel(), api.GetBody1Rel()):
        values = list(rel.GetTargets())
        if len(values) > 1 or values and str(values[0]) not in bodies:
            _fail('native joint endpoint must resolve to one preserved rigid link or world')
        endpoints.append(str(values[0]) if values else None)
    if endpoints[1] is None or endpoints[0] == endpoints[1] or set(bodies) != set(p for p in endpoints if p):
        _fail('native hinge/slider must connect exactly its preserved links with an explicit child')
    for fixed_prim in fixed:
        fixed_api = UsdPhysics.Joint(fixed_prim)
        a = list(fixed_api.GetBody0Rel().GetTargets());b = list(fixed_api.GetBody1Rel().GetTargets())
        if a or b != ([stage.GetPrimAtPath(endpoints[0]).GetPath()] if endpoints[0] else []) or not fixed_api.GetJointEnabledAttr().Get():
            _fail('only an enabled world-to-parent fixed joint is supported')
    is_angular = prim.IsA(UsdPhysics.RevoluteJoint)
    typed = UsdPhysics.RevoluteJoint(prim) if is_angular else UsdPhysics.PrismaticJoint(prim)
    if not typed.GetLowerLimitAttr().HasAuthoredValueOpinion() or not typed.GetUpperLimitAttr().HasAuthoredValueOpinion():
        _fail('native joint requires authored finite limits')
    if not typed.GetAxisAttr().HasAuthoredValueOpinion():
        _fail('native joint requires an explicitly authored axis')
    limits = _finite([typed.GetLowerLimitAttr().Get(), typed.GetUpperLimitAttr().Get()], 'joint limits')
    if is_angular:
        limits = [math.radians(v) for v in limits]
    drive_instance = 'angular' if is_angular else 'linear'
    drives = [s for s in prim.GetAppliedSchemas() if s.startswith('PhysicsDriveAPI:')]
    if any(s != 'PhysicsDriveAPI:' + drive_instance for s in drives):
        _fail('native joint has unsupported coupled/multiaxis drive')
    drive = None
    if drives:
        native = UsdPhysics.DriveAPI(prim, drive_instance)
        if native.GetTypeAttr().Get() != 'force':
            _fail('native acceleration drive is unsupported')
        gain = 180/math.pi if is_angular else 1.
        values = _finite([native.GetStiffnessAttr().Get(), native.GetDampingAttr().Get(), native.GetMaxForceAttr().Get()], 'drive parameters')
        drive = {'stiffness': values[0]*gain, 'damping': values[1]*gain, 'max_effort': values[2],
                 'target_position': float(native.GetTargetPositionAttr().Get()) * (math.pi/180 if is_angular else 1),
                 'target_velocity': float(native.GetTargetVelocityAttr().Get()) * (math.pi/180 if is_angular else 1),
                 'provenance': 'preserved_native_force_drive_normalized_to_SI'}
    native_attributes={}
    for attr in prim.GetAttributes():
        if not attr.HasAuthoredValueOpinion() or not attr.GetName().startswith(('physics:','physx','drive:')):continue
        value=attr.Get()
        if hasattr(value,'GetReal'):value=[float(value.GetReal()),*[float(v) for v in value.GetImaginary()]]
        elif not isinstance(value,(str,bool,int,float,type(None))):value=list(value)
        if isinstance(value,float) and not math.isfinite(value):value={'USD_sentinel':'positive_infinity' if value>0 else 'negative_infinity'}
        native_attributes[attr.GetName()]=value
    joint = {'native_authored_attributes':native_attributes,'native_attribute_units':'preserved_USD_schema_units; normalized limits/frames/drive also recorded separately', 'relative_prim_path':relative(prim.GetPath()), 'type':'revolute' if is_angular else 'prismatic',
             'parent_body_id':ids.get(endpoints[0]), 'child_body_id':ids[endpoints[1]], 'axis':str(typed.GetAxisAttr().Get()),
             'limits':limits, 'position_unit':'rad' if is_angular else 'm', 'passive':drive is None, 'drive':drive,
             'local_pos0_m':_finite(api.GetLocalPos0Attr().Get(), 'joint local position'),
             'local_pos1_m':_finite(api.GetLocalPos1Attr().Get(), 'joint local position'),
             'physics_provenance':'preserved_native_USD_joint_not_synthesized'}
    for suffix, attr in [('0',api.GetLocalRot0Attr()),('1',api.GetLocalRot1Attr())]:
        q=attr.Get();joint['local_rot'+suffix+'_wxyz']=_finite([q.GetReal(),*q.GetImaginary()], 'joint frame')
    from ..worker.mechanism import validate_binding
    runtime = dict(joint, joint_path='/World/inspection/Joint', parent_body='/World/inspection/Parent' if endpoints[0] else None,
                   child_body='/World/inspection/Child')
    try:
        validate_binding({'joints':{'main':runtime}})
    except ValueError as error:
        _fail(str(error))
    return {'body_map':body_map, 'joint_map':{'main':joint},
            'fixed_joint_paths':[relative(p.GetPath()) for p in fixed],
            'articulation_root_paths':[relative(p.GetPath()) for p in prims if p.HasAPI(UsdPhysics.ArticulationRootAPI)],
            'scope':'inspected native source graph; no runtime validation claimed'}


def transform_world_anchors(stage, root):
    """Move world-end joint frames with an instance, without touching source files."""
    from pxr import Usd,UsdGeom,UsdPhysics,Gf
    matrix=UsdGeom.Xformable(root).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    rotation=matrix.RemoveScaleShear().ExtractRotationQuat()
    records=[]
    for prim in Usd.PrimRange(root):
        if not prim.IsA(UsdPhysics.Joint):continue
        api=UsdPhysics.Joint(prim)
        for index in (0,1):
            if getattr(api,'GetBody'+str(index)+'Rel')().GetTargets():continue
            position_attr=getattr(api,'GetLocalPos'+str(index)+'Attr')()
            rotation_attr=getattr(api,'GetLocalRot'+str(index)+'Attr')()
            p=position_attr.Get();q=rotation_attr.Get()
            world_p=matrix.Transform(Gf.Vec3d(p));world_q=rotation*Gf.Quatd(q.GetReal(),Gf.Vec3d(q.GetImaginary()))
            position_attr.Set(Gf.Vec3f(world_p));rotation_attr.Set(Gf.Quatf(world_q.GetReal(),Gf.Vec3f(world_q.GetImaginary())))
            records.append({'joint_path':str(prim.GetPath()),'world_endpoint':index,
                            'local_position_source_m':list(p),'world_position_instance_m':list(world_p),
                            'scope':'rigid instance placement applied to world-end joint frame; source untouched'})
    return records


def resolve_instance(stage, anchor, manifest):
    """Verify final loaded graph and return explicit body and joint bindings."""
    from ..worker.mechanism import validate_binding
    actual=inspect_articulation(stage,anchor)
    expected=manifest['articulation_report']
    # World-frame values may differ due to documented rigid instance placement.
    for key in ('body_map','fixed_joint_paths','articulation_root_paths'):
        if actual[key]!=expected[key]:
            _fail('loaded native articulated graph/properties differ from prepared package: '+key)
    source=expected['joint_map']['main'];loaded=actual['joint_map']['main']
    for key in source:
        if source['parent_body_id'] is None and key in {'local_pos0_m','local_rot0_wxyz'}:continue
        expected_value=source[key];actual_value=loaded[key]
        if source['parent_body_id'] is None and key=='native_authored_attributes':
            omit={'physics:localPos0','physics:localRot0'}
            expected_value={k:v for k,v in expected_value.items() if k not in omit}
            actual_value={k:v for k,v in actual_value.items() if k not in omit}
        if expected_value!=actual_value:
            _fail('loaded native joint differs from prepared package: '+key)
    base=str(anchor.GetPath())
    def path(relative):return base+('/'+relative if relative else '')
    bodies={local_id:{'motion_body':path(entry['relative_prim_path']), 'role':entry['role'],
                      'visual_roots':[path(p) for p in entry['visual_relative_prim_paths']],
                      'collider_paths':[path(p) for p in entry['collider_relative_prim_paths']]}
            for local_id,entry in actual['body_map'].items()}
    joints={}
    for joint_id,entry in actual['joint_map'].items():
        joints[joint_id]=dict(entry,joint_path=path(entry['relative_prim_path']),
            parent_body=bodies[entry['parent_body_id']]['motion_body'] if entry['parent_body_id'] else None,
            child_body=bodies[entry['child_body_id']]['motion_body'])
    result={'profile_id':'articulated_prop_v1','bodies':bodies,'joints':joints,
            'motion_bodies':[entry['motion_body'] for entry in bodies.values() if entry['role']=='rigid'],
            'contact_bodies':[entry['motion_body'] for entry in bodies.values() if entry['role']=='rigid'],
            'visual_roots':list(dict.fromkeys(p for entry in bodies.values() for p in entry['visual_roots'])),
            'collider_paths':[p for entry in bodies.values() for p in entry['collider_paths']],
            'articulation_roots':[path(p) for p in actual['articulation_root_paths']]}
    validate_binding(result)
    return result
