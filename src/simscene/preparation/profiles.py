"""Strict, CPU-only preparation recipes. Values describe experiments, not products."""
import copy
import hashlib
import json
import math

PROFILE_VERSION = 1
PROFILES = frozenset({'visual_prop_v1', 'static_fixture_v1', 'rigid_prop_v1', 'articulated_prop_v1', 'container_v1', 'environment_v1'})

class PreparationError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _fail(message):
    raise PreparationError('physics_profile_unsupported', message)


def number(value, name, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _fail(f'{name} must be finite numeric')
    if positive and value <= 0 or nonnegative and value < 0:
        _fail(f'{name} is out of range')
    return float(value)


def vector(value, length, name, *, positive=False):
    if not isinstance(value, (list, tuple)) or len(value) != length:
        _fail(f'{name} requires {length} values')
    return [number(v, name, positive=positive) for v in value]


def validate_parameters(profile, parameters):
    if profile=='environment_v1':
        from .environment_layer import validate_environment_parameters
        return validate_environment_parameters(parameters)
    if profile not in PROFILES:
        _fail(f'unsupported profile: {profile}')
    if not isinstance(parameters, dict):
        _fail('parameters must be an object')
    p = copy.deepcopy(parameters)
    allowed = {'source_physics_policy','scale_mode','target_longest_extent_m','mass_kg','mass_note',
               'collision_method','static_friction','dynamic_friction','restitution','ccd',
               'proxy_tolerance_m','support_surfaces','static_proxy','container_proxy'}
    if set(p) - allowed:
        _fail(f'unknown parameters: {sorted(set(p)-allowed)}')
    if p.get('source_physics_policy') not in {'preserve_valid','replace_visual_only','reject_if_physics'}:
        _fail('source_physics_policy is required')
    p.setdefault('scale_mode', 'preserve')
    if p['scale_mode'] not in {'preserve','fit_longest'}:
        _fail('scale_mode must be preserve or fit_longest')
    if p['scale_mode'] == 'fit_longest':
        p['target_longest_extent_m'] = number(p.get('target_longest_extent_m'), 'target_longest_extent_m', positive=True)
    elif p.get('target_longest_extent_m') is not None:
        _fail('target_longest_extent_m applies only to fit_longest')
    p.pop('target_longest_extent_m', None) if p.get('target_longest_extent_m') is None else None
    if 'proxy_tolerance_m' not in p:
        _fail('proxy_tolerance_m is required')
    p['proxy_tolerance_m'] = number(p['proxy_tolerance_m'], 'proxy_tolerance_m', positive=True)
    for name, default in [('static_friction',.6),('dynamic_friction',.5),('restitution',.05)]:
        p[name] = number(p.get(name,default), name, nonnegative=True)
    if p['dynamic_friction'] > p['static_friction'] or p['restitution'] > 1:
        _fail('dynamic friction must not exceed static; restitution must be <=1')
    p.setdefault('ccd', profile == 'rigid_prop_v1')
    if type(p['ccd']) is not bool:
        _fail('ccd must be bool')
    p.setdefault('collision_method', 'convex_hull' if profile == 'rigid_prop_v1' else 'preserve')
    if p['collision_method'] not in {'preserve','convex_hull','box_proxy'}:
        _fail('invalid collision_method')
    if profile in {'articulated_prop_v1','container_v1'}:
        if p['scale_mode'] != 'preserve':
            _fail('M2 physical profiles cannot rescale native physics or declared metric container geometry')
        if profile == 'articulated_prop_v1':
            if 'container_proxy' in p:
                _fail('container_proxy applies only to container_v1')
            if p['source_physics_policy'] != 'preserve_valid' or p['collision_method'] != 'preserve':
                _fail('articulated profile requires preserve_valid native physics/collision')
        else:
            if p['source_physics_policy'] != 'replace_visual_only' or p['collision_method'] != 'box_proxy':
                _fail('container profile requires explicit opening-preserving wall proxies and replace_visual_only')
            from .container import validate_container
            validate_container(p.get('container_proxy'))
    elif 'container_proxy' in p:
        _fail('container_proxy applies only to container_v1')
    if profile == 'rigid_prop_v1':
        if p['source_physics_policy'] != 'reject_if_physics':
            _fail('M1 rigid requires reject_if_physics')
        if p['collision_method'] != 'convex_hull':
            _fail('M1 rigid supports measured mesh convex_hull only; box proxy is static-only')
        p['mass_kg'] = number(p.get('mass_kg'), 'mass_kg', positive=True)
        if not isinstance(p.get('mass_note'), str) or not p['mass_note'].strip():
            _fail('rigid requires explicit experimental mass_note')
    elif any(k in p for k in ('mass_kg','mass_note')):
        _fail('mass parameters apply only to rigid')
    if profile == 'static_fixture_v1':
        if p['collision_method'] not in {'preserve','box_proxy'}:
            _fail('static supports preserve or explicit box_proxy')
        from simscene.placement import validate_surfaces
        try:
            validate_surfaces(p.get('support_surfaces'))
        except ValueError as error:
            _fail(str(error))
        if p['collision_method'] == 'box_proxy':
            if p['source_physics_policy'] != 'replace_visual_only':
                _fail('box_proxy requires replace_visual_only to prevent duplicate physics')
            proxy = p.get('static_proxy')
            if not isinstance(proxy, dict) or set(proxy) != {'size_m','position_m','orientation_wxyz'}:
                _fail('static_proxy requires measured size_m, position_m, orientation_wxyz')
            proxy['size_m'] = vector(proxy['size_m'],3,'proxy size',positive=True)
            proxy['position_m'] = vector(proxy['position_m'],3,'proxy position')
            proxy['orientation_wxyz'] = vector(proxy['orientation_wxyz'],4,'proxy orientation')
            if abs(sum(v*v for v in proxy['orientation_wxyz'])-1) > 1e-6:
                _fail('proxy quaternion must be normalized')
        elif p['source_physics_policy'] != 'preserve_valid':
            _fail('preserve static collision requires preserve_valid')
    elif any(k in p for k in ('support_surfaces','static_proxy')):
        _fail('support_surfaces/static_proxy apply only to static')
    return p


def source_identity(acquired, closure_sha256):
    """Keep attribution distinct even when two selections contain identical mesh bytes."""
    payload={'closure_sha256':closure_sha256,'source_manifest_sha256':acquired.get('manifest_sha256',acquired.get('source_manifest_hash')),
             'source_ref':acquired.get('source_ref',acquired.get('asset_ref')),'license':acquired.get('license','unknown'),
             'provenance':acquired.get('provenance')}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def preparation_key(source_sha256, profile, parameters, target, converter):
    """Exclude storage locations and job identity; retain source and runtime identity."""
    if not isinstance(source_sha256,str) or len(source_sha256)!=64 or any(c not in '0123456789abcdef' for c in source_sha256):
        raise PreparationError('verification_failed','source SHA256 required')
    payload = {'source_sha256':source_sha256,'profile':profile,'profile_version':PROFILE_VERSION,
               'parameters':validate_parameters(profile,parameters),'target':target,'converter':converter}
    try:
        data=json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    except (ValueError,TypeError) as error:
        raise PreparationError('verification_failed','identity must contain finite JSON') from error
    return hashlib.sha256(data).hexdigest()
