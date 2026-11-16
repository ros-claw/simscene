"""Explicit, bounded repairs to a derived USD layer; never edit the source."""
import copy
import math
import re
import struct

from .profiles import PreparationError


def _fail(message):
    raise PreparationError('physics_profile_unsupported', message)


def _path(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 256 or
            value != '.' and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z_][A-Za-z0-9_]*)*', value)):
        _fail('repair paths must be safe relative USD prim paths')
    return value


def _positive(value, label):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 10000:
        _fail(label + ' must be finite, positive and at most 10000')
    return float(value)


def validate_native_repairs(value):
    required={'missing_masses_kg', 'neutralize_drives', 'reason'}
    if not isinstance(value, dict) or not required <= set(value) or set(value)-required-{'material_density_overrides'}:
        _fail('native repairs require missing_masses_kg, neutralize_drives and reason')
    reason = value['reason']
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 1024:
        _fail('native repairs require a bounded reason describing experimental assumptions')
    masses, drives = value['missing_masses_kg'], value['neutralize_drives']
    if not isinstance(masses, dict) or not isinstance(drives, dict) or len(masses) > 16 or len(drives) > 16 or not (masses or drives):
        _fail('native repairs require 1..16 bounded body or joint edits')
    overrides=value.get('material_density_overrides',{})
    if not isinstance(overrides,dict) or len(overrides)>256:
        _fail('material density overrides must be a bounded collider mapping')
    normalized_overrides={}
    for path,entry in overrides.items():
        if not isinstance(entry,dict) or set(entry)!={'material_path','density_kg_m3'}:
            _fail('material density overrides require a material path and measured source density')
        density=entry['density_kg_m3']
        if type(density) not in (int,float) or not math.isfinite(density) or not 0<density<=1e6:
            _fail('source material density must be finite, positive and at most 1000000 kg/m3')
        normalized_overrides[_path(path)]={'material_path':_path(entry['material_path']),
            'density_kg_m3':struct.unpack('f',struct.pack('f',float(density)))[0]}
    return {'missing_masses_kg': {_path(key): _positive(mass, 'missing mass') for key, mass in masses.items()},
            'neutralize_drives': {_path(key): _positive(force, 'neutral drive effort') for key, force in drives.items()},
            'material_density_overrides':normalized_overrides,
            'reason': reason.strip()}


def validate_repair_report(repairs, report):
    """Require every declared assumption to remain visible at package admission."""
    repairs = validate_native_repairs(repairs)
    if (not isinstance(report, dict) or report.get('schema') != 'simscene.native_physics_repairs.v1'
            or report.get('reason') != repairs['reason'] or not isinstance(report.get('masses'), list)
            or not isinstance(report.get('drives'), list)):
        raise ValueError('prepared native repair report is missing or differs from its recipe')
    masses, drives = report['masses'], report['drives']
    def valid_source(source):
        names={'type','stiffness','damping','max_effort','target_position','target_velocity','units'}
        if (not isinstance(source,dict) or set(source)!=names or source['type'] not in ('force','acceleration')
                or source['units']!='original USD drive schema units'):
            return False
        def number_or_sentinel(value):
            return (type(value) in (int,float) and math.isfinite(value)
                    or isinstance(value,dict) and set(value)=={'USD_sentinel'}
                    and value['USD_sentinel'] in ('positive_infinity','negative_infinity','nan'))
        return all(number_or_sentinel(source[name]) for name in names-{'type','units'})
    if (len(masses) != len(repairs['missing_masses_kg'])
            or any(not isinstance(row, dict) or not isinstance(row.get('relative_prim_path'), str)
                   or type(row.get('mass_kg')) not in (int, float) or not math.isfinite(row['mass_kg'])
                   or row.get('source_status') != 'body_mass_not_authored' or row.get('provenance') != 'explicit_experimental_assumption'
                   for row in masses)
            or {row['relative_prim_path']: row['mass_kg'] for row in masses} != repairs['missing_masses_kg']
            or len(drives) != len(repairs['neutralize_drives'])
            or any(not isinstance(row, dict) or not isinstance(row.get('relative_prim_path'), str)
                   or row.get('provenance') != 'explicit_neutral_drive_not_original_behavior'
                   or not valid_source(row.get('source')) or not isinstance(row.get('derived'), dict)
                   or row['derived'].get('type') != 'force' or type(row['derived'].get('max_effort')) not in (int, float)
                   or any(type(row['derived'].get(k)) not in (int, float) or row['derived'][k] != 0.
                          for k in ('stiffness', 'damping', 'target_position', 'target_velocity'))
                   for row in drives)
            or {row['relative_prim_path']: row['derived']['max_effort'] for row in drives} != repairs['neutralize_drives']):
        raise ValueError('prepared native repair report does not match explicit assumptions')
    overrides=report.get('material_density_overrides')
    if (not isinstance(overrides,list) or len(overrides)!=len(repairs['material_density_overrides'])
            or any(not isinstance(row,dict) or not isinstance(row.get('collider_path'),str)
                   or not isinstance(row.get('material_path'),str) or type(row.get('density_kg_m3')) not in (int,float)
                   or row.get('provenance')!='authored_material_density_overridden_by_explicit_body_mass' for row in overrides)
            or {row['collider_path']:{'material_path':row['material_path'],'density_kg_m3':row['density_kg_m3']}
                for row in overrides}!=repairs['material_density_overrides']):
        raise ValueError('prepared native repair report does not match source material density overrides')
    return repairs


def annotate_repaired_graph(graph, repairs):
    """Label and check repaired values in a graph relative to the /Asset wrapper.

    The graph is independently re-inspected when a scene is composed. It must
    still have the declared values; these annotations never create physics.
    """
    repairs = validate_native_repairs(repairs)
    result = copy.deepcopy(graph)
    bodies = result['body_map']; joints = result['joint_map']
    def wrapped(name):
        return 'Native' + ('' if name == '.' else '/' + name)
    def same_float32(actual, requested):
        return (type(actual) in (int, float) and math.isfinite(actual)
                and actual == struct.unpack('f', struct.pack('f', requested))[0])
    for name, mass in repairs['missing_masses_kg'].items():
        matches = [body for body in bodies.values() if body.get('relative_prim_path') == wrapped(name)]
        if len(matches) != 1 or not same_float32(matches[0].get('mass_kg'), mass):
            raise ValueError('prepared native repair report does not match mapped body mass')
        overridden={wrapped(path) for path in repairs['material_density_overrides']}
        affects=bool(overridden.intersection(matches[0].get('collider_relative_prim_paths',[])))
        matches[0]['physics_provenance'] = ('native_link_with_explicit_experimental_mass_overriding_source_material_density'
                                             if affects else 'native_link_with_explicit_experimental_mass')
        if matches[0].get('diagonal_inertia_kg_m2') is None:
            matches[0]['inertia_provenance'] = 'engine_computes_from_native_colliders_and_experimental_mass'
    for name, effort in repairs['neutralize_drives'].items():
        matches = [joint for joint in joints.values() if joint.get('relative_prim_path') == wrapped(name)]
        drive = matches[0].get('drive') if len(matches) == 1 else None
        if (not isinstance(drive, dict) or not same_float32(drive.get('max_effort'), effort)
                or any(drive.get(key) != 0. for key in ('stiffness', 'damping', 'target_position', 'target_velocity'))):
            raise ValueError('prepared native repair report does not match mapped neutral drive')
        drive['provenance'] = 'explicit_neutral_drive_not_original_behavior'
        matches[0]['native_attribute_units'] = 'derived_USD_schema_units; normalized limits/frames/drive also recorded separately'
    result['scope'] = 'inspected derived graph with explicit repairs; source graph and runtime validation are separate'
    return result


def _record_value(value):
    if isinstance(value, float) and not math.isfinite(value):
        return {'USD_sentinel': 'positive_infinity' if value > 0 else 'negative_infinity' if value < 0 else 'nan'}
    if value is None or type(value) in (bool, int, float):
        return value
    return str(value)


def apply_native_repairs(stage, repairs):
    """Apply only requested missing masses and neutral drives to a derived layer.

    Validate every proposed edit before writing anything. The caller must pass
    a private derived stage, then run normal graph admission and hash both the
    immutable source closure and the repaired output separately.
    """
    from pxr import Usd, UsdPhysics, UsdShade
    from .articulation import canonical_stage
    repairs = validate_native_repairs(repairs)
    canonical_stage(stage)
    root = stage.GetDefaultPrim()
    if not root:
        _fail('native repairs require a default prim')
    prims = list(Usd.PrimRange(root))
    if any(prim.IsInstance() or prim.IsInstanceable() for prim in prims):
        _fail('native repairs do not support instanced prims')
    root_path = str(root.GetPath())

    def relative(prim):
        path = str(prim.GetPath())
        return '.' if path == root_path else path[len(root_path) + 1:]

    bodies = {relative(prim): prim for prim in prims if prim.HasAPI(UsdPhysics.RigidBodyAPI)}
    missing = set()
    for name, prim in bodies.items():
        mass = UsdPhysics.MassAPI(prim)
        attr = mass.GetMassAttr() if mass else None
        if not attr or not attr.HasAuthoredValueOpinion():
            missing.add(name)
            ancestor=prim.GetParent()
            while ancestor and not ancestor.IsPseudoRoot():
                if (ancestor.HasAPI(UsdPhysics.MassAPI)
                        and UsdPhysics.MassAPI(ancestor).GetDensityAttr().HasAuthoredValueOpinion()):
                    _fail('cannot add body mass over inherited authored density')
                ancestor=ancestor.GetParent()
            # A parent mass takes precedence over explicit descendant mass or
            # density in USD. Refuse to silently erase those authored inputs.
            for descendant in Usd.PrimRange(prim):
                owner=descendant
                while owner and not owner.HasAPI(UsdPhysics.RigidBodyAPI):
                    owner=owner.GetParent()
                if owner != prim or not descendant.HasAPI(UsdPhysics.MassAPI):
                    continue
                child_mass=UsdPhysics.MassAPI(descendant)
                if (child_mass.GetDensityAttr().HasAuthoredValueOpinion() or
                        descendant != prim and child_mass.GetMassAttr().HasAuthoredValueOpinion()):
                    _fail('cannot add missing body mass when descendant mass or density is explicitly authored')
        else:
            _positive(attr.Get(), 'authored source mass')
    requested_masses = repairs['missing_masses_kg']
    if not bodies or set(requested_masses) != missing:
        _fail('missing_masses_kg must name exactly every body without an authored mass; existing masses cannot be overwritten')

    # Even with no body mass, a bound physics material may supply a source
    # density. A body mass takes precedence; require explicit per-collider
    # acknowledgment of that behavioral change, including inherited bindings.
    material_overrides={}
    for name in sorted(missing):
        body=bodies[name]
        for prim in Usd.PrimRange(body):
            if not prim.HasAPI(UsdPhysics.CollisionAPI):continue
            owner=prim
            while owner and not owner.HasAPI(UsdPhysics.RigidBodyAPI):owner=owner.GetParent()
            if owner != body:continue
            material,_=UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial('physics')
            if not material or not material.GetPrim().HasAPI(UsdPhysics.MaterialAPI):continue
            density=UsdPhysics.MaterialAPI(material.GetPrim()).GetDensityAttr()
            if not density.HasAuthoredValueOpinion():continue
            material_path=str(material.GetPath())
            if material_path != root_path and not material_path.startswith(root_path+'/'):
                _fail('physics material density outside the selected source root is unsupported')
            number=density.Get()
            if type(number) not in (int,float) or not math.isfinite(number) or number<=0:
                _fail('authored physics material density must be finite and positive')
            material_overrides[relative(prim)]={'material_path':relative(material.GetPrim()),'density_kg_m3':float(number)}
    if material_overrides != repairs['material_density_overrides']:
        _fail('explicit material density overrides must exactly match source collider/material bindings')

    joints = {relative(prim): prim for prim in prims if prim.IsA(UsdPhysics.Joint)}
    requested_drives = repairs['neutralize_drives']
    if not set(requested_drives) <= set(joints):
        _fail('neutralize_drives must name existing native joints')
    pending_drives = []
    for name, prim in joints.items():
        if prim.IsA(UsdPhysics.RevoluteJoint):
            instance = 'angular'
        elif prim.IsA(UsdPhysics.PrismaticJoint):
            instance = 'linear'
        else:
            if name in requested_drives:
                _fail('only native hinge or slider drives can be neutralized')
            continue
        schemas = [schema for schema in prim.GetAppliedSchemas() if schema.startswith('PhysicsDriveAPI:')]
        if any(schema != 'PhysicsDriveAPI:' + instance for schema in schemas):
            _fail('coupled or multiaxis source drives are unsupported')
        if name in requested_drives and not schemas:
            _fail('a neutralized drive must already exist in the source')
        if not schemas:
            continue
        drive = UsdPhysics.DriveAPI(prim, instance)
        get = lambda name: getattr(drive, 'Get' + name + 'Attr')().Get()
        source = {'type': _record_value(get('Type')), 'stiffness': _record_value(get('Stiffness')),
                  'damping': _record_value(get('Damping')), 'max_effort': _record_value(get('MaxForce')),
                  'target_position': _record_value(get('TargetPosition')), 'target_velocity': _record_value(get('TargetVelocity')),
                  'units': 'original USD drive schema units'}
        fields = [get(field) for field in ('Stiffness', 'Damping', 'MaxForce', 'TargetPosition', 'TargetVelocity')]
        supported = (get('Type') == 'force' and all(type(v) in (int, float) and math.isfinite(v) for v in fields)
                     and fields[0] >= 0 and fields[1] >= 0 and fields[2] > 0)
        if name not in requested_drives:
            if not supported:
                _fail('unsupported source drive must be explicitly neutralized')
            continue
        if supported:
            _fail('source drive is already supported; preserve it rather than neutralizing it')
        pending_drives.append((name, prim, instance, source, requested_drives[name]))

    masses = []
    for name, value in requested_masses.items():
        UsdPhysics.MassAPI.Apply(bodies[name]).CreateMassAttr(value)
        masses.append({'relative_prim_path': name, 'source_status': 'body_mass_not_authored', 'mass_kg': value,
                       'provenance': 'explicit_experimental_assumption'})
    drives = []
    for name, prim, instance, source, maximum in pending_drives:
        drive = UsdPhysics.DriveAPI.Apply(prim, instance)
        drive.CreateTypeAttr('force')
        drive.CreateStiffnessAttr(0.)
        drive.CreateDampingAttr(0.)
        drive.CreateMaxForceAttr(maximum)
        drive.CreateTargetPositionAttr(0.)
        drive.CreateTargetVelocityAttr(0.)
        drives.append({'relative_prim_path': name, 'instance': instance, 'source': source,
                       'derived': {'type': 'force', 'stiffness': 0., 'damping': 0., 'max_effort': maximum,
                                   'target_position': 0., 'target_velocity': 0.},
                       'provenance': 'explicit_neutral_drive_not_original_behavior'})
    return {'schema': 'simscene.native_physics_repairs.v1', 'reason': repairs['reason'],
            'masses': masses, 'drives': drives,
            'material_density_overrides':[{'collider_path':path,**item,
                'provenance':'authored_material_density_overridden_by_explicit_body_mass'}
                for path,item in sorted(material_overrides.items())],
            'scope': 'Only the derived layer is edited; source values and original drive behavior are not asserted for the repair.'}
