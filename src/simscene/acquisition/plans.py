"""Immutable selection and preparation plans. Planning starts no converter or physics."""
import fcntl
import hashlib
import json
from pathlib import Path

from ..catalog.config import read as configuration
from ..catalog.models import AssetRef, canonical_json
from ..preparation.profiles import validate_parameters, PROFILE_VERSION, PreparationError
from ..preparation.environment import current_runtime


def payload_hash(value):
    return hashlib.sha256(canonical_json(value, exclude_volatile=False).encode()).hexdigest()


def make_plan(ref, profile_id='visual_prop_v1', parameters=None, target=None, budgets=None,
              *, record=None, runtime=None, config=None):
    from ..catalog.search import resolve_asset
    config = config or configuration()
    ref = AssetRef.from_dict(ref) if isinstance(ref, dict) else ref
    if not isinstance(ref, AssetRef): raise ValueError('asset_ref must be a valid AssetRef')
    ref.validate_selection()
    record = record or resolve_asset(ref, index_directory=config['index_directory'])
    if record.ref != ref: raise ValueError('resolved selection does not match ref')
    budgets = dict(budgets or {})
    allowed = {'download_bytes', 'unpacked_bytes', 'staging_bytes'}
    if set(budgets)-allowed: raise ValueError('unknown acquisition budget')
    for k, default in [('download_bytes', config['asset_download_bytes']),
                       ('unpacked_bytes', config['unpacked_bytes']), ('staging_bytes', config['staging_bytes'])]:
        budgets.setdefault(k, default)
        if type(budgets[k]) is not int or budgets[k] <= 0: raise ValueError('positive integer required: '+k)
    blocking = []; normalized = None
    try: normalized = validate_parameters(profile_id, parameters or {})
    except PreparationError as error: blocking.append({'code':error.code,'detail':str(error)})
    try: runtime = runtime or current_runtime(config=config)
    except ValueError as error:
        code, _, detail = str(error).partition(':')
        code=getattr(error,'code',None) or (code if detail else 'environment_probe_required')
        blocking.append({'code':code,'detail':detail.strip() or str(error)}); runtime = None
    if runtime and target is not None and target != runtime['target']:
        blocking.append({'code':'plan_environment_changed','detail':'requested target differs from observed runtime'})
    license_info = record.license or {'status':'unknown','license':None}
    if license_info.get('status') in ('unknown', 'conflicting'):
        blocking.append({'code':'license_unresolved','detail':'asset license requires source-specific review'})
    elif license_info.get('status')=='restricted':
        blocking.append({'code':'license_restricted','detail':'restricted assets require a source-specific audited usage policy; no blanket grant inferred'})
    availability = record.availability or {}
    if availability.get('gated') or availability.get('private'):
        blocking.append({'code':'source_gated','detail':'no automatic gated/private acquisition'})
    descriptor = availability.get('acquisition') or {}
    if descriptor.get('kind') in {'hf_single_glb','hf_usd_package'} or ref.source_id == 'abo-glb':
        ref.validate_selection(huggingface=True)
        from ..catalog.registry import load_registry
        source = load_registry(config.get('registry_path')).get(ref.source_id)
        if ref.source_id == 'abo-glb' and not descriptor:
            descriptor={'kind':'hf_single_glb','repository':source.repository,'revision':ref.revision,'path':record.entry_path}
        if source.state not in {'audited','enabled'}:
            blocking.append({'code':'source_unavailable','detail':'source has not passed static adapter admission'})
        if descriptor.get('repository') != source.repository or descriptor.get('revision') != ref.revision or descriptor.get('path') != record.entry_path:
            blocking.append({'code':'verification_failed','detail':'acquisition descriptor differs from source selection'})
        if descriptor.get('kind') == 'hf_single_glb':
            descriptor = dict(descriptor,additional_paths=descriptor.get('additional_paths',['LICENSE-CC-BY-4.0.txt']))
        if descriptor.get('kind')=='hf_usd_package' and not descriptor.get('files'):
            blocking.append({'code':'dependency_missing','detail':'native package requires a selected file content pin'})
    if descriptor.get('kind') in {'hf_glb','hf_single_glb'} or ref.source_id == 'abo-glb':
        if runtime and not runtime.get('predecoder_configuration'):
            blocking.append({'code':'unsupported_codec','detail':'standard GLB preparation requires the verified meshopt predecoder; run asset probe after toolchain setup'})
        if ref.source_id == 'abo-glb':
            descriptor = {'kind':'hf_glb','repository':source.repository,'revision':ref.revision,'path':record.entry_path}
    elif ref.source_id == 'nvidia-usd-search':
        descriptor = {'kind':'usd_dependency_closure','asset_url':
                      availability.get('asset_url') or (record.provenance or {}).get('asset_url')}
    elif ref.source_id == 'local-sand3d' and descriptor.get('kind') == 'generated_package':
        if descriptor.get('revision') != ref.revision:
            blocking.append({'code':'verification_failed','detail':'generated content revision differs from selection'})
    elif descriptor.get('kind') == 'http_files':
        if ref.source_id != 'polyhaven' or descriptor.get('source')!='polyhaven':
            blocking.append({'code':'source_unavailable','detail':'HTTP source has no reviewed acquisition adapter'})
        if profile_id!='environment_v1' or descriptor.get('asset_type')!='hdri':
            blocking.append({'code':'physics_profile_unsupported','detail':'selected HTTP files currently prepare only HDRI environment_v1; material maps have no geometry/physics role'})
    elif descriptor.get('kind') != 'hf_usd_package':
        blocking.append({'code':'source_unavailable','detail':'source has no M1 acquisition adapter'})
    estimate = availability.get('estimated_download_bytes')
    if estimate is not None and (type(estimate) is not int or estimate < 0):
        raise ValueError('invalid source download estimate')
    if estimate is not None and estimate > budgets['download_bytes']:
        blocking.append({'code':'budget_exceeded','detail':'known selected file size exceeds transfer budget'})
    payload = {'schema_version':1, 'asset_ref':ref.to_dict(), 'source_snapshot':record.to_dict(),
        'profile_id':profile_id, 'profile_version':PROFILE_VERSION,
        'parameters':normalized if normalized is not None else parameters or {},
        'target':runtime['target'] if runtime else target,
        'toolchain_requirements':runtime['installation'] if runtime else None,
        'converter_selection':runtime['converter'] if runtime else None,
        'converter_environment':runtime.get('predecoder_configuration') if runtime else None,
        'budget_breakdown':budgets,'acquisition':descriptor,'files':[], 'files_complete':False,
        'granularity':availability.get('granularity'), 'estimated_download_bytes':estimate,
        'estimated_unpacked_bytes':None, 'unknown_sizes':True,'runtime_dependencies':[],
        'content_identity':'pending_acquisition_content_lock', 'license_decision':license_info,
        'ready_to_fetch':not blocking,'blocking_reasons':blocking}
    digest = payload_hash(payload); result = dict(payload, plan_id=digest, plan_payload_sha256=digest)
    folder = Path(config['home'])/'asset-plans'; folder.mkdir(parents=True, exist_ok=True)
    with (folder/'.plans.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX); path = folder/(digest+'.json')
        encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n'
        if path.exists():
            if json.loads(path.read_text()) != result: raise ValueError('plan identity collision or modified plan')
        else:
            with path.open('x') as f: f.write(encoded)
    return dict(result, plan_ref=str(path))


def load_plan(plan_id, *, config=None):
    import re
    if not isinstance(plan_id,str) or not re.fullmatch('[0-9a-f]{64}',plan_id):
        raise ValueError('invalid plan_id')
    config = config or configuration(); path = Path(config['home'])/'asset-plans'/(plan_id+'.json')
    plan = json.loads(path.read_text()); payload = dict(plan)
    digest = payload.pop('plan_payload_sha256'); payload.pop('plan_id')
    if digest != plan_id or payload_hash(payload) != digest:
        raise ValueError('verification_failed: immutable plan changed')
    return plan
