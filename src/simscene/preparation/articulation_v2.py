"""Conservative static inventory of a native two-coordinate articulation.

This module does not prepare an asset or establish runtime PhysX independence.
Only a directed tree of two single-axis joints and three rigid links is admitted.
"""
import copy
import math

from .articulation import _fail, _finite, canonical_stage


def _relative(root_path, path):
    value = str(path)
    if value != root_path and not value.startswith(root_path + '/'):
        _fail('native articulation path escapes the selected root')
    return value[len(root_path):].lstrip('/')


def _check_rigid_ancestors(prim):
    """Reject unsafe local transforms even when ancestor scales cancel out."""
    from pxr import Usd, UsdGeom

    current = prim
    while current and not current.IsPseudoRoot():
        if any(attr.GetNumTimeSamples() for attr in current.GetAttributes()):
            _fail('native joint/body ancestors cannot have time-sampled attributes')
        xformable = UsdGeom.Xformable(current)
        if xformable:
            matrix = xformable.GetLocalTransformation(Usd.TimeCode.Default())
            if not all(math.isfinite(matrix[i][j]) for i in range(4) for j in range(4)):
                _fail('native joint/body ancestors require finite rigid transforms')
            axes = [matrix.ExtractRotationMatrix().GetRow(i) for i in range(3)]
            if (any(abs(axis.GetLength() - 1.) > 1e-6 for axis in axes)
                    or any(abs(axes[i] * axes[j]) > 1e-6 for i in range(3) for j in range(i))
                    or matrix.GetDeterminant() <= 0):
                _fail('native joint/body ancestors require unit scale, no shear or reflection')
        current = current.GetParent()


def _native_value(value):
    """Keep USD values JSON-safe, including authored infinity sentinels."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        return {'USD_sentinel': 'nan' if math.isnan(value) else
                'positive_infinity' if value > 0 else 'negative_infinity'}
    if hasattr(value, 'GetReal'):
        return [_native_value(float(value.GetReal())),
                *[_native_value(float(v)) for v in value.GetImaginary()]]
    try:
        return [_native_value(v) for v in value]
    except TypeError:
        _fail('unsupported native physics attribute value')


def _raw_attributes(prim):
    return {attr.GetName(): _native_value(attr.Get()) for attr in prim.GetAttributes()
            if attr.HasAuthoredValueOpinion()
            and attr.GetName().startswith(('physics:', 'physx', 'drive:'))}


def _schemas(prim):
    metadata = prim.GetMetadata('apiSchemas')
    return [str(value) for value in metadata.GetAppliedItems()] if metadata else []


def _joint_frames(joint):
    result = {}
    for suffix in ('0', '1'):
        position = getattr(joint, 'GetLocalPos' + suffix + 'Attr')().Get()
        rotation = getattr(joint, 'GetLocalRot' + suffix + 'Attr')().Get()
        result['local_pos' + suffix + '_m'] = _finite(position, 'joint local position')
        if rotation is None:
            _fail('missing native joint local rotation')
        q = _finite([rotation.GetReal(), *rotation.GetImaginary()], 'joint local rotation')
        if abs(sum(value * value for value in q) - 1.) > 1e-5:
            _fail('native joint local rotation must be normalized')
        result['local_rot' + suffix + '_wxyz'] = q
    return result


def _endpoints(joint, bodies):
    endpoints = []
    for relationship in (joint.GetBody0Rel(), joint.GetBody1Rel()):
        targets = list(relationship.GetTargets())
        if len(targets) > 1 or targets and str(targets[0]) not in bodies:
            _fail('native joint endpoint must resolve to one preserved rigid body or world')
        endpoints.append(str(targets[0]) if targets else None)
    return endpoints


def _require_enabled(joint):
    if joint.GetJointEnabledAttr().Get() is not True:
        _fail('native joint is disabled')
    if joint.GetExcludeFromArticulationAttr().Get() is not False:
        _fail('native joint is excluded from the articulation')


def _drive(prim, instance):
    from pxr import UsdPhysics

    schemas = _schemas(prim)
    drives = [s for s in schemas if s.startswith('PhysicsDriveAPI:')]
    if any(s != 'PhysicsDriveAPI:' + instance for s in drives):
        _fail('native joint has an unsupported multiaxis drive')
    if not drives:
        return None
    drive = UsdPhysics.DriveAPI(prim, instance)
    kind = str(drive.GetTypeAttr().Get())
    if kind not in ('force', 'acceleration'):
        _fail('native joint has an unsupported drive type')
    values = {}
    for key, suffix in [('stiffness', 'Stiffness'), ('damping', 'Damping'),
                        ('max_force', 'MaxForce'), ('target_position', 'TargetPosition'),
                        ('target_velocity', 'TargetVelocity')]:
        try:
            value = float(getattr(drive, 'Get' + suffix + 'Attr')().Get())
        except (TypeError, ValueError):
            _fail('native drive has a missing parameter')
        if not math.isfinite(value) and not (key == 'max_force' and value == math.inf):
            _fail('native drive contains a nonfinite value')
        if key in ('stiffness', 'damping', 'max_force') and value < 0:
            _fail('native drive contains a negative gain or effort')
        values[key] = _native_value(value)
    return dict(values, instance=instance, type=kind, units='native_USD_schema_units',
                authored_attributes=sorted(a.GetName() for a in prim.GetAttributes()
                    if a.GetName().startswith('drive:' + instance + ':') and a.HasAuthoredValueOpinion()))


def _body_properties(prim):
    from pxr import UsdPhysics

    rigid = UsdPhysics.RigidBodyAPI(prim)
    if rigid.GetRigidBodyEnabledAttr().Get() is not True or rigid.GetKinematicEnabledAttr().Get() is not False:
        _fail('native links must be enabled nonkinematic rigid bodies')
    _check_rigid_ancestors(prim)
    mass = UsdPhysics.MassAPI(prim)
    if not mass or not mass.GetMassAttr().HasAuthoredValueOpinion():
        _fail('native link lacks explicit mass')
    value = _finite([mass.GetMassAttr().Get()], 'mass', positive=True)[0]
    diagonal_value = mass.GetDiagonalInertiaAttr().Get()
    center_value = mass.GetCenterOfMassAttr().Get()
    orientation = mass.GetPrincipalAxesAttr().Get()
    if diagonal_value is None or center_value is None or orientation is None:
        _fail('native link mass properties cannot be blocked')
    diagonal = list(diagonal_value)
    if diagonal == [0., 0., 0.]:
        inertia = None
    else:
        inertia = _finite(diagonal, 'diagonal inertia', positive=True)
        if max(inertia) > sum(inertia) - max(inertia) + 1e-8:
            _fail('native link inertia violates principal moment triangle inequality')
    center = list(center_value)
    center = None if center == [-math.inf] * 3 else _finite(center, 'center of mass')
    orientation = [orientation.GetReal(), *orientation.GetImaginary()]
    orientation = None if orientation == [0.] * 4 else _finite(orientation, 'inertia principal axes')
    if orientation is not None and abs(sum(v * v for v in orientation) - 1.) > 1e-5:
        _fail('native inertia principal axes must be normalized')
    return {'mass_kg': value, 'diagonal_inertia_kg_m2': inertia,
            'center_of_mass_local_m': center, 'principal_axes_wxyz': orientation,
            'inertia_provenance': ('engine_computes_from_preserved_native_colliders_and_authored_mass'
                                   if inertia is None else 'preserved_native_USD_authored_inertia'),
            'physics_provenance': 'preserved_native_USD_authored_values'}


def inspect_articulation_v2(stage, root=None):
    """Return a stable static graph report; raise PreparationError if unsupported.

    Link and joint IDs are generated by sorted source-relative path. The report
    describes two candidate joint coordinates, not a runtime DOF measurement.
    """
    from pxr import Usd, UsdGeom, UsdPhysics

    canonical_stage(stage)
    if not math.isfinite(UsdGeom.GetStageMetersPerUnit(stage)):
        _fail('native articulated physics requires finite metres and Z-up')
    mass_units = UsdPhysics.GetStageKilogramsPerUnit(stage)
    if not math.isfinite(mass_units) or abs(mass_units - 1.) > 1e-9:
        _fail('native articulated physics requires kilogramsPerUnit=1')
    root = root or stage.GetDefaultPrim()
    if not root:
        _fail('native articulated source requires a default prim')
    root_path = str(root.GetPath())
    prims = list(Usd.PrimRange(root))
    bodies, colliders, moving, fixed, articulation_roots = {}, {}, [], [], []
    for prim in prims:
        if any(attr.GetNumTimeSamples() for attr in prim.GetAttributes()):
            _fail('native articulated time-sampled attributes are unsupported')
        schemas = _schemas(prim)
        tokens = [prim.GetTypeName(), *schemas, *(p.GetName() for p in prim.GetProperties())]
        if any(marker in token.lower() for token in tokens for marker in ('mimic', 'gear', 'tendon', 'coupl')):
            _fail('native coupling, mimic, gear or tendon is unsupported')
        if any(s.startswith('PhysicsLimitAPI:') for s in schemas):
            _fail('native multi-axis limit schema is unsupported')
        if prim.HasAPI(UsdPhysics.ArticulationRootAPI):
            articulation_roots.append(str(prim.GetPath()))
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            bodies[str(prim.GetPath())] = _body_properties(prim)
        if prim.HasAPI(UsdPhysics.CollisionAPI):
            if not UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Get():
                _fail('disabled native collider cannot qualify an articulated link')
            owner = prim
            while owner and not owner.HasAPI(UsdPhysics.RigidBodyAPI):
                owner = owner.GetParent()
            owner_path = str(owner.GetPath()) if owner else None
            if owner_path is not None:
                _relative(root_path, owner_path)
            colliders.setdefault(owner_path, []).append(str(prim.GetPath()))
        if prim.IsA(UsdPhysics.Joint):
            _check_rigid_ancestors(prim)
            if prim.IsA(UsdPhysics.FixedJoint):
                fixed.append(prim)
            elif prim.IsA(UsdPhysics.RevoluteJoint) or prim.IsA(UsdPhysics.PrismaticJoint):
                moving.append(prim)
            else:
                _fail('native multi-axis or unsupported joint type')
        elif 'joint' in prim.GetTypeName().lower():
            _fail('unrecognized native joint type')
    # Constraints outside the selected root must not silently connect into the
    # inspected graph; unrelated scene joints remain outside this inventory.
    for prim in stage.Traverse():
        path = str(prim.GetPath())
        if path == root_path or path.startswith(root_path + '/'):
            continue
        tokens = [prim.GetTypeName(), *_schemas(prim), *(p.GetName() for p in prim.GetProperties())]
        is_constraint = (prim.IsA(UsdPhysics.Joint) or 'joint' in prim.GetTypeName().lower()
                         or any(marker in token.lower() for token in tokens
                                for marker in ('mimic', 'gear', 'tendon', 'coupl')))
        if is_constraint:
            for relationship in prim.GetRelationships():
                for target in relationship.GetTargets():
                    target_path = str(target.GetPrimPath())
                    if target_path == root_path or target_path.startswith(root_path + '/'):
                        _fail('native articulation has a constraint outside the selected root')
    if len(bodies) != 3 or len(moving) != 2 or len(fixed) > 1:
        _fail('two-DOF profile requires three rigid links, two scalar joints and at most one world fixed joint')
    for path in bodies:
        parent = stage.GetPrimAtPath(path).GetParent()
        while parent and not parent.IsPseudoRoot():
            if str(parent.GetPath()) in bodies:
                _fail('nested native rigid bodies are unsupported')
            parent = parent.GetParent()
        if not colliders.get(path):
            _fail('native articulated link lacks enabled collision')
    paths = sorted(bodies)
    ids = {path: 'link' + str(index) for index, path in enumerate(paths)}
    body_map = {ids[path]: dict(bodies[path], relative_prim_path=_relative(root_path, path), role='rigid',
                               visual_relative_prim_paths=[_relative(root_path, path)],
                               collider_relative_prim_paths=sorted(_relative(root_path, p) for p in colliders[path]))
                for path in paths}
    incoming = {path: 0 for path in paths}
    edges, joint_map = {}, {}
    for index, prim in enumerate(sorted(moving, key=lambda item: str(item.GetPath()))):
        joint = UsdPhysics.Joint(prim)
        _require_enabled(joint)
        parent, child = _endpoints(joint, bodies)
        if parent is None or child is None or parent == child:
            _fail('moving joint must connect two distinct preserved rigid links')
        incoming[child] += 1
        edges.setdefault(parent, []).append(child)
        angular = prim.IsA(UsdPhysics.RevoluteJoint)
        typed = UsdPhysics.RevoluteJoint(prim) if angular else UsdPhysics.PrismaticJoint(prim)
        if not typed.GetAxisAttr().HasAuthoredValueOpinion() or typed.GetAxisAttr().Get() not in ('X', 'Y', 'Z'):
            _fail('native joint requires an explicitly authored X, Y or Z axis')
        if not typed.GetLowerLimitAttr().HasAuthoredValueOpinion() or not typed.GetUpperLimitAttr().HasAuthoredValueOpinion():
            _fail('native joint requires authored finite limits')
        limits = _finite([typed.GetLowerLimitAttr().Get(), typed.GetUpperLimitAttr().Get()], 'joint limits')
        if limits[0] >= limits[1]:
            _fail('native joint requires ordered nonlocked limits')
        if angular:
            limits = [math.radians(value) for value in limits]
        native_drive = _drive(prim, 'angular' if angular else 'linear')
        entry = {'relative_prim_path': _relative(root_path, prim.GetPath()),
                 'parent_body_id': ids[parent], 'child_body_id': ids[child],
                 'type': 'revolute' if angular else 'prismatic', 'axis': str(typed.GetAxisAttr().Get()),
                 'limits': limits, 'position_unit': 'rad' if angular else 'm',
                 'joint_enabled': True, 'exclude_from_articulation': False,
                 'drive': native_drive, 'passive': native_drive is None,
                 'native_authored_attributes': _raw_attributes(prim),
                 'native_attribute_units': 'preserved_USD_schema_units',
                 'physics_provenance': 'preserved_native_USD_joint_not_synthesized'}
        entry.update(_joint_frames(joint))
        joint_map['joint' + str(index)] = entry
    roots = [path for path, count in incoming.items() if count == 0]
    if len(roots) != 1 or any(count > 1 for count in incoming.values()):
        _fail('native articulation requires one root and one incoming joint per nonroot link')
    graph_root = roots[0]
    visited, pending = set(), [graph_root]
    while pending:
        current = pending.pop()
        if current in visited:
            _fail('native articulation graph contains a cycle')
        visited.add(current)
        pending.extend(edges.get(current, []))
    if visited != set(paths):
        _fail('native articulation graph must be connected and acyclic')
    fixed_map = {}
    for prim in fixed:
        joint = UsdPhysics.Joint(prim)
        _require_enabled(joint)
        if any(schema.startswith('PhysicsDriveAPI:') for schema in _schemas(prim)):
            _fail('world fixed joint cannot have a drive')
        if _endpoints(joint, bodies) != [None, graph_root]:
            _fail('only one world-to-root fixed joint is supported')
        entry = {'relative_prim_path': _relative(root_path, prim.GetPath()), 'type': 'fixed',
                 'parent_body_id': None, 'child_body_id': ids[graph_root], 'drive': None,
                 'joint_enabled': True, 'exclude_from_articulation': False,
                 'native_authored_attributes': _raw_attributes(prim)}
        entry.update(_joint_frames(joint))
        fixed_map['fixed0'] = entry
    if len(articulation_roots) != 1:
        _fail('native articulation requires one explicit articulation root')
    declared_root = articulation_roots[0]
    valid_root = (declared_root == graph_root or graph_root.startswith(declared_root + '/')
                  or fixed and declared_root == str(fixed[0].GetPath()))
    if not valid_root:
        _fail('native articulation root does not identify the graph root')
    return {'schema': 'simscene.articulation_inspection.v2', 'schema_version': 2,
            'body_map': body_map, 'joint_map': joint_map, 'root_body_id': ids[graph_root],
            'fixed_joint_paths': sorted(_relative(root_path, p.GetPath()) for p in fixed),
            'fixed_joint_map': fixed_map,
            'articulation_root_paths': [_relative(root_path, declared_root)],
            'static_collider_paths': sorted(_relative(root_path, p) for p in colliders.get(None, [])),
            'scope': 'static native tree with two candidate coordinates; not runtime DOF or independence verification'}


def runtime_joint(entry):
    """Convert a supported native force drive to the existing SI contract."""
    result=copy.deepcopy(entry);drive=entry.get('drive')
    if drive is None:return result
    effort=drive.get('max_force');stiffness=drive.get('stiffness');damping=drive.get('damping')
    target=drive.get('target_position');velocity=drive.get('target_velocity')
    if (drive.get('type')!='force' or any(type(v) not in (int,float) or not math.isfinite(v)
            for v in (effort,stiffness,damping,target,velocity)) or effort<=0 or stiffness<0 or damping<0):
        _fail('two-DOF runtime requires a finite native force drive or no drive')
    angular=entry['type']=='revolute';gain=180/math.pi if angular else 1.;position=math.pi/180 if angular else 1.
    result['drive']={'stiffness':stiffness*gain,'damping':damping*gain,'max_effort':effort,
        'target_position':target*position,'target_velocity':velocity*position,
        'provenance':'preserved_native_force_drive_normalized_to_SI'}
    return result


def verify_source_graph_v2(package,manifest):
    """Compare a preserved source and its prepared physical graph and geometry."""
    from pathlib import Path
    from pxr import Usd
    from .articulation import _verify_physical_prims
    package=Path(package);source_root=manifest.get('source_root')
    candidates=[item['path'] for item in manifest.get('files',[])
                if item.get('path','').startswith('source/') and item.get('sha256')==manifest.get('source_sha256')]
    if source_root is not None:
        if source_root not in candidates:_fail('two-DOF source root differs from its hashed snapshot')
        candidates=[source_root]
    if len(candidates)!=1:_fail('two-DOF source snapshot must identify one native USD root')
    source=Usd.Stage.Open(str(package/candidates[0]));prepared=Usd.Stage.Open(str(package/manifest['main']))
    if not source or not prepared:_fail('two-DOF source or prepared USD could not be opened')
    graph=inspect_articulation_v2(source)
    def wrap(path):return 'Native'+('/'+path if path else '')
    for entry in graph['body_map'].values():
        entry['relative_prim_path']=wrap(entry['relative_prim_path'])
        for key in ('visual_relative_prim_paths','collider_relative_prim_paths'):
            entry[key]=[wrap(p) for p in entry[key]]
    for mapping in ('joint_map','fixed_joint_map'):
        for entry in graph[mapping].values():entry['relative_prim_path']=wrap(entry['relative_prim_path'])
    for key in ('fixed_joint_paths','articulation_root_paths','static_collider_paths'):
        graph[key]=[wrap(p) for p in graph[key]]
    if graph!=manifest.get('articulation_report'):_fail('two-DOF prepared graph differs from its source')
    _verify_physical_prims(source,prepared)
    return True


def resolve_instance_v2(stage,anchor,manifest):
    """Resolve and re-inspect a single composed two-coordinate native tree."""
    from pxr import Gf,Usd,UsdGeom
    actual=inspect_articulation_v2(stage,anchor);expected=manifest['articulation_report']
    # A documented instance placement transforms only the world end of a fixed
    # anchor. Compare all other fixed-joint properties and the complete tree.
    comparable=copy.deepcopy(actual)
    matrix=UsdGeom.Xformable(anchor).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    rotation=matrix.RemoveScaleShear().ExtractRotationQuat()
    for key,fixed in comparable['fixed_joint_map'].items():
        previous=expected['fixed_joint_map'].get(key,{})
        if not previous:_fail('loaded two-DOF world anchor is not in the prepared graph')
        source_position=Gf.Vec3d(*previous['local_pos0_m'])
        source_q=previous['local_rot0_wxyz'];source_quat=Gf.Quatd(source_q[0],Gf.Vec3d(*source_q[1:]))
        expected_position=matrix.Transform(source_position);expected_quat=rotation*source_quat
        actual_position=fixed['local_pos0_m'];actual_quat=fixed['local_rot0_wxyz']
        wanted_q=[expected_quat.GetReal(),*expected_quat.GetImaginary()]
        if (max(abs(actual_position[i]-expected_position[i]) for i in range(3))>1e-5
                or min(max(abs(actual_quat[i]-wanted_q[i]) for i in range(4)),
                       max(abs(actual_quat[i]+wanted_q[i]) for i in range(4)))>1e-5):
            _fail('loaded two-DOF world anchor differs from its instance placement')
        for field in ('local_pos0_m','local_rot0_wxyz'):
            if field in previous:fixed[field]=previous[field]
        attrs=fixed.get('native_authored_attributes',{});old=previous.get('native_authored_attributes',{})
        for field in ('physics:localPos0','physics:localRot0'):
            if field in old:attrs[field]=old[field]
            else:attrs.pop(field,None)
    if comparable!=expected:_fail('loaded two-DOF articulation differs from its prepared graph')
    base=str(anchor.GetPath())
    def path(relative):return base+('/'+relative if relative else '')
    bodies={name:{'motion_body':path(entry['relative_prim_path']),'role':entry['role'],
        'visual_roots':[path(p) for p in entry['visual_relative_prim_paths']],
        'collider_paths':[path(p) for p in entry['collider_relative_prim_paths']]}
        for name,entry in actual['body_map'].items()}
    joints={name:dict(runtime_joint(entry),joint_path=path(entry['relative_prim_path']),
        parent_body=bodies[entry['parent_body_id']]['motion_body'],child_body=bodies[entry['child_body_id']]['motion_body'])
        for name,entry in actual['joint_map'].items()}
    result={'profile_id':'articulated_prop_v2','bodies':bodies,'joints':joints,
        'root_body':bodies[actual['root_body_id']]['motion_body'],
        'motion_bodies':[entry['motion_body'] for entry in bodies.values()],
        'contact_bodies':[entry['motion_body'] for entry in bodies.values()],
        'visual_roots':list(dict.fromkeys(p for entry in bodies.values() for p in entry['visual_roots'])),
        'collider_paths':[p for entry in bodies.values() for p in entry['collider_paths']]+[path(p) for p in actual['static_collider_paths']],
        'articulation_roots':[path(p) for p in actual['articulation_root_paths']]}
    from ..worker.mechanism import validate_binding
    validate_binding(result)
    return result
