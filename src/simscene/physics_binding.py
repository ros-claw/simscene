"""Validate prepared file closures and resolve explicit imported body paths."""
import json
import re
from pathlib import Path, PurePosixPath
from .cache import _sha256


def _relative(value, *, allow_root=False):
    if allow_root and value in ('', '.'):
        return ''
    if not isinstance(value, str) or not value or value.startswith('/') or '\\' in value or '%' in value:
        raise ValueError('invalid relative prepared path')
    if any(p in ('', '.', '..') for p in value.split('/')) or any(c in value for c in ('?', '#', ':')):
        raise ValueError('unsafe relative prepared path')
    return PurePosixPath(value).as_posix()


def _no_symlinks(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('prepared package contains a symlink')


def validate_asset_binding(binding, *, require_dynamic=False, asset_path=None):
    """Return a prepared manifest only after its complete closure is verified."""
    if not isinstance(binding, dict) or set(binding) != {'manifest_path', 'manifest_sha256'}:
        raise ValueError('asset_binding requires manifest_path and manifest_sha256')
    if not isinstance(binding['manifest_path'], str) or not binding['manifest_path']:
        raise ValueError('invalid prepared manifest path')
    manifest_path = Path(binding['manifest_path']).expanduser().absolute()
    _no_symlinks(manifest_path)
    if not re.fullmatch(r'[0-9a-f]{64}', str(binding['manifest_sha256'])):
        raise ValueError('invalid prepared manifest hash')
    if not manifest_path.is_file() or manifest_path.stat().st_size > 16 * 1024**2 or _sha256(manifest_path) != binding['manifest_sha256']:
        raise ValueError('prepared manifest is missing or changed')
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('schema_version') != 1 or manifest.get('schema') != 'simscene.prepared_asset.v1':
        raise ValueError('unsupported prepared manifest schema')
    root = manifest_path.parent
    files = manifest.get('files')
    if not isinstance(files, list) or not 0 < len(files) <= 4096:
        raise ValueError('invalid prepared file closure')
    names = set()
    for item in files:
        name = _relative(item['path'])
        if name in names or name == manifest_path.name:
            raise ValueError('duplicate or recursive prepared manifest file')
        names.add(name)
        path = root / name; _no_symlinks(path)
        size = item.get('size_bytes', item.get('size'))
        if type(size) is not int or size < 0 or not re.fullmatch(r'[0-9a-f]{64}', str(item.get('sha256', ''))):
            raise ValueError('invalid prepared file record')
        if not path.is_file() or path.stat().st_size != size or _sha256(path) != item['sha256']:
            raise ValueError('prepared dependency is missing or changed: ' + name)
    actual = set()
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('prepared package contains a symlink')
        if path.is_file() and path != manifest_path:
            actual.add(path.relative_to(root).as_posix())
    if actual != names:
        raise ValueError('prepared manifest does not cover its complete package')
    main = _relative(manifest.get('main'))
    if main not in names or manifest.get('default_prim') != '/Asset':
        raise ValueError('prepared default prim or entry file is invalid')
    if asset_path is not None and Path(asset_path).expanduser().absolute() != root / main:
        raise ValueError('scene asset_path does not match its prepared binding')
    body_map = manifest.get('body_map', {})
    if not isinstance(body_map, dict):
        raise ValueError('invalid prepared body map')
    seen = set()
    for local_id, entry in body_map.items():
        if not isinstance(local_id, str) or not local_id or not isinstance(entry, dict):
            raise ValueError('invalid prepared local body')
        relative = _relative(entry.get('relative_prim_path'), allow_root=True)
        if relative in seen:
            raise ValueError('duplicate prepared body mapping')
        seen.add(relative)
        for key in ('visual_relative_prim_paths', 'collider_relative_prim_paths'):
            values = entry.get(key, [])
            if not isinstance(values, list) or len(values) != len(set(values)):
                raise ValueError('invalid prepared visual/collider paths')
            for value in values:
                _relative(value, allow_root=True)
    if manifest.get('profile_id') == 'articulated_prop_v1':
        report=manifest.get('articulation_report')
        if not isinstance(report,dict) or report.get('body_map') != body_map or report.get('joint_map') != manifest.get('joint_map'):
            raise ValueError('articulated prepared maps must match the inspected immutable graph')
        from .worker.mechanism import validate_binding
        joints={}
        for local_id,entry in manifest.get('joint_map',{}).items():
            rel=_relative(entry.get('relative_prim_path'),allow_root=True)
            parent=entry.get('parent_body_id');child=entry.get('child_body_id')
            if child not in body_map or parent is not None and parent not in body_map:
                raise ValueError('prepared joint references an undeclared body')
            joints[local_id]=dict(entry,joint_path='/World/validation/'+rel,parent_body='/World/validation/'+body_map[parent]['relative_prim_path'] if parent else None,child_body='/World/validation/'+body_map[child]['relative_prim_path'])
        validate_binding({'joints':joints})
    if require_dynamic and manifest.get('profile_id') != 'articulated_prop_v1':
        if manifest.get('profile_id') != 'rigid_prop_v1' or set(body_map) != {'main'} or body_map['main'].get('role') != 'rigid':
            raise ValueError('dynamic imported assets require a prepared rigid_prop_v1 main body')
        if not all(body_map['main'].get(key) for key in ('visual_relative_prim_paths', 'collider_relative_prim_paths')):
            raise ValueError('dynamic prepared asset lacks visual/collider mapping')
    return manifest


def resolve_body_bindings(stage, spec):
    """Resolve final selected-stage paths without guessing from actor prefixes."""
    from pxr import Usd, UsdPhysics, UsdGeom, UsdUtils
    result = {}; claimed = set()
    for object_id, obj in spec.get('objects', {}).items():
        binding = obj.get('asset_binding')
        if not binding:
            if obj.get('kind') == 'asset' and obj.get('dynamic'):
                raise ValueError('dynamic imported asset requires a prepared binding')
            continue
        if obj.get('kind') != 'asset':
            raise ValueError('prepared binding is only valid for assets')
        dynamic = obj.get('dynamic') is True
        manifest = validate_asset_binding(binding, require_dynamic=dynamic, asset_path=obj.get('asset_path'))
        if not dynamic:
            continue
        package = Path(binding['manifest_path']).expanduser().absolute().parent
        known = {entry['path'] for entry in manifest['files']}
        source_stage = Usd.Stage.Open(str(package / manifest['main']))
        if (not source_stage or not source_stage.GetDefaultPrim() or str(source_stage.GetDefaultPrim().GetPath()) != '/Asset'
                or not source_stage.HasAuthoredMetadata('metersPerUnit') or abs(UsdGeom.GetStageMetersPerUnit(source_stage) - 1.) > 1e-9
                or not source_stage.HasAuthoredMetadata('upAxis') or UsdGeom.GetStageUpAxis(source_stage) != UsdGeom.Tokens.z):
            raise ValueError('prepared rigid source must author /Asset, meters and Z-up')
        layers, assets, unresolved = UsdUtils.ComputeAllDependencies(str(package / manifest['main']))
        if unresolved:
            raise ValueError('prepared USD dependency closure is unresolved')
        for value in [layer.realPath or layer.identifier for layer in layers] + list(assets):
            dependency = Path(str(value))
            if not dependency.is_absolute():
                dependency = package / dependency
            try:
                relative = dependency.resolve().relative_to(package.resolve()).as_posix()
            except ValueError as error:
                raise ValueError('prepared USD dependency escapes its hashed package') from error
            if relative not in known:
                raise ValueError('prepared USD dependency is outside the hashed file closure')
        if obj.get('pose_follower') or obj.get('asset_physics') == 'visual_only':
            raise ValueError('prepared dynamic bodies cannot use a follower or visual-only override')
        base = '/World/' + object_id.replace('-', '_') + '/Asset'
        anchor = stage.GetPrimAtPath(base)
        if not anchor or not anchor.IsActive():
            raise ValueError('prepared asset instance is missing')
        if manifest['profile_id']=='articulated_prop_v1':
            from .preparation.articulation import resolve_instance
            result[object_id]=resolve_instance(stage,anchor,manifest)
            for motion in result[object_id]['motion_bodies']:
                if motion in claimed:raise ValueError('duplicate prepared motion body')
                claimed.add(motion)
            continue
        entry = manifest['body_map']['main']
        def absolute(relative):
            relative = _relative(relative, allow_root=True)
            path = base + ('/' + relative if relative else '')
            prim = stage.GetPrimAtPath(path)
            if not prim or not prim.IsActive():
                raise ValueError('prepared mapped prim is missing: ' + path)
            return path, prim
        motion, body = absolute(entry['relative_prim_path'])
        if motion in claimed or not body.HasAPI(UsdPhysics.RigidBodyAPI) or not UsdPhysics.RigidBodyAPI(body).GetRigidBodyEnabledAttr().Get():
            raise ValueError('missing, disabled or duplicate prepared rigid body')
        claimed.add(motion)
        matrix = UsdGeom.Xformable(body).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        axes = [matrix.ExtractRotationMatrix().GetRow(i) for i in range(3)]
        if any(abs(axis.GetLength() - 1.) > 1e-6 for axis in axes) or any(abs(axes[i] * axes[j]) > 1e-6 for i in range(3) for j in range(i)) or matrix.GetDeterminant() < 0:
            raise ValueError('prepared rigid-body ancestors have unsafe scale or shear')
        visuals = [absolute(p)[0] for p in entry['visual_relative_prim_paths']]
        colliders = []
        for relative in entry['collider_relative_prim_paths']:
            path, prim = absolute(relative)
            if not prim.HasAPI(UsdPhysics.CollisionAPI) or not UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Get():
                raise ValueError('prepared collider is missing or disabled')
            colliders.append(path)
        if any(path != motion and not path.startswith(motion + '/') for path in visuals + colliders):
            raise ValueError('prepared visuals and colliders must belong to the mapped motion body')
        bodies = []; actual_colliders = []
        for prim in Usd.PrimRange(anchor):
            if prim.HasAPI(UsdPhysics.ArticulationRootAPI) or prim.IsA(UsdPhysics.Joint):
                raise ValueError('articulated prepared asset is unsupported')
            if prim.HasAPI(UsdPhysics.RigidBodyAPI):
                bodies.append(str(prim.GetPath()))
            if prim.HasAPI(UsdPhysics.CollisionAPI) and UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Get():
                actual_colliders.append(str(prim.GetPath()))
            if any(attr.GetNumTimeSamples() for attr in prim.GetAttributes()):
                raise ValueError('animated prepared rigid asset is unsupported')
        if bodies != [motion]:
            raise ValueError('prepared rigid body closure does not match the stage')
        if set(actual_colliders) != set(colliders):
            raise ValueError('prepared collider closure does not match the stage')
        result[object_id] = {'local_body_id': 'main', 'profile_id': manifest['profile_id'],
                             'motion_body': motion, 'contact_bodies': [motion],
                             'visual_roots': visuals, 'collider_paths': colliders}
    return result
