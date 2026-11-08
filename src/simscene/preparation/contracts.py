"""Pure CPU summaries of versioned prepared manifests; no USD or filesystem IO.

The caller verifies the immutable manifest/package before using this view.
References always retain the supplied manifest pin. This function never creates
an identity from a self-hashed replacement file or upgrades runtime evidence.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from ..catalog.models import canonical_json
from .profiles import PROFILE_VERSION, validate_parameters

MAX_SUMMARY_BYTES = 32 * 1024


def _relative_main(value):
    if not isinstance(value, str) or not value or any(c in value for c in ('\\', '%', '?', '#', ':')):
        raise ValueError('invalid prepared main asset path')
    if any(part in ('', '.', '..') for part in value.split('/')):
        raise ValueError('prepared main asset path must stay inside its package')
    path = PurePosixPath(value)
    if path.is_absolute():
        raise ValueError('prepared main asset path must be relative')
    return path


def _digest(value, name):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError(name + ' must be a SHA-256 hex digest')
    return value


def prepared_contract(manifest, *, manifest_path=None, manifest_sha256=None):
    """Return compact PreparedAsset fields, preserving existing compatibility keys.

    Version 1 prepared packages declare metres and Z-up. These are structural
    contract declarations, never evidence of physical runtime verification.
    Missing material observations stay null; an explicitly recorded empty
    runtime dependency inventory is a known zero. Full reports/file inventories
    remain in the manifest behind references instead of expanding this response.
    """
    if not isinstance(manifest, dict) or manifest.get('schema') != 'simscene.prepared_asset.v1':
        raise ValueError('unsupported prepared manifest schema')
    if type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1:
        raise ValueError('unsupported prepared manifest schema_version')
    if type(manifest.get('profile_version')) is not int or manifest['profile_version'] != PROFILE_VERSION:
        raise ValueError('unsupported prepared profile_version')
    identity = _digest(manifest.get('prepared_id'), 'prepared_id')
    main = _relative_main(manifest.get('main'))
    if manifest_sha256 is not None:
        _digest(manifest_sha256, 'manifest_sha256')
    if manifest_path is not None:
        if not isinstance(manifest_path, (str, Path)) or not str(manifest_path):
            raise ValueError('manifest_path must be a path or null')
        current = Path(manifest_path).expanduser().absolute()
        current_path = str(current)
        root = str(current.parent.joinpath(*main.parts))
    else:
        current_path, root = None, None
    profile = manifest.get('profile_id')
    parameters = validate_parameters(profile, manifest.get('parameters'))
    recipe = {'profile_id': profile, 'profile_version': manifest['profile_version'],
              'parameters': parameters}
    recipe_hash = hashlib.sha256(canonical_json(recipe, exclude_volatile=False).encode('utf-8')).hexdigest()

    def reference(pointer):
        return {'manifest_path': current_path, 'manifest_sha256': manifest_sha256,
                'json_pointer': pointer}

    body_map = manifest.get('body_map', {})
    if not isinstance(body_map, dict):
        raise ValueError('prepared body_map must be an object')
    source_manifest = manifest.get('source_manifest_sha256', manifest.get('source_manifest_hash'))
    if source_manifest is not None:
        _digest(source_manifest, 'source_manifest_hash')
    runtime = deepcopy(manifest.get('runtime_validation', {'status': 'unknown'}))
    if not isinstance(runtime, dict) or not isinstance(runtime.get('status'), str):
        raise ValueError('runtime_validation must retain an explicit status')
    dependencies = manifest.get('runtime_dependencies')
    if dependencies is not None and not isinstance(dependencies, list):
        raise ValueError('runtime_dependencies must be a recorded list or null')
    dependency_count = len(dependencies) if dependencies is not None else None
    # Existing v1 manifests have inspection.json, but no inline material counts.
    # Reading that file here would violate this pure summary boundary. A future
    # producer may explicitly persist an inspected count in material_report.
    observed_materials = manifest.get('material_report')
    material_count = observed_materials.get('inspected_material_count') if isinstance(observed_materials, dict) else None
    if material_count is not None and (type(material_count) is not int or material_count < 0):
        raise ValueError('inspected_material_count must be a nonnegative integer or null')
    material_report = {'inspected_material_count': material_count,
                       'material_evidence': 'inspected' if material_count is not None else 'unknown',
                       'runtime_dependency_count': dependency_count,
                       'runtime_dependency_evidence': 'inspected' if dependency_count is not None else 'unknown'}
    mass = parameters.get('mass_kg') if profile == 'rigid_prop_v1' else None
    collision_applied = profile in {'rigid_prop_v1', 'static_fixture_v1', 'container_v1', 'articulated_prop_v1'}
    collision_method = parameters.get('collision_method')
    approximate = collision_applied and collision_method in {'convex_hull', 'box_proxy'}
    physics_report = {'collision_method': collision_method, 'collision_applied': collision_applied,
                      'mass_assumption_kg': mass, 'experimental_mass': mass is not None,
                      'experimental_material': profile == 'rigid_prop_v1' or (profile == 'static_fixture_v1' and collision_method == 'box_proxy'),
                      'collision_approximation': approximate,
                      'collision_report_ref': reference('/collision_report') if manifest.get('collision_report') is not None else None,
                      'mass_assumption_note_ref': reference('/parameters/mass_note') if mass is not None else None,
                      'runtime_validation': deepcopy(runtime)}
    warnings = []
    if approximate:
        warnings.append('collision_approximation:' + collision_method)
    if dependencies and any(isinstance(item, dict) and
                            (item.get('kind') == 'target_runtime_mdl' or str(item.get('asset', '')).lower().endswith('.mdl'))
                            for item in dependencies):
        warnings.append('runtime_mdl_dependency_requires_target_environment')
    if mass is not None:
        warnings.append('experimental_mass_assumption_not_manufacturer_data')
    if material_count is None:
        warnings.append('material_count_unknown')
    if runtime['status'] not in {'runtime_verified', 'verified', 'pass'}:
        warnings.append('physical_runtime_validation_not_verified')
    derived = reference('/files')
    derived['selector'] = {'exclude_prefixes': ['source/', 'licenses/']}
    derived['inventory_scope'] = 'complete_package_apply_selector_for_derived_files'
    result = {'schema_version': 1, 'prepared_handle': identity, 'root': root,
              'manifest_path': current_path, 'manifest_sha256': manifest_sha256,
              'profile_id': profile, 'recipe_hash': recipe_hash,
              'toolchain': deepcopy(manifest.get('toolchain')), 'target': deepcopy(manifest.get('target')),
              'source_manifest_hash': source_manifest,
              'derived_files': derived,
              'metrics': {'meters_per_unit': 1.0, 'up_axis': 'Z',
                          'basis': 'prepared_schema_v1_declaration', 'bounds': deepcopy(manifest.get('bounds'))},
              'bounds': deepcopy(manifest.get('bounds')), 'body_map': deepcopy(body_map),
              'material_report': material_report, 'physics_report': physics_report,
              'warnings': warnings, 'runtime_validation': runtime}
    if profile=='articulated_prop_v1':
        result['joint_map']=deepcopy(manifest.get('joint_map',{}))
    if profile=='container_v1':
        result['physics_report']['container_report_ref']=reference('/container_report')
    canonical_json(result, exclude_volatile=False)  # Validate finite JSON before presentation.
    if max(len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')),
           len(json.dumps(result, ensure_ascii=True, allow_nan=False).encode('utf-8'))) > MAX_SUMMARY_BYTES:
        raise ValueError('prepared summary exceeds its bounded response size; request full manifest details')
    return result
