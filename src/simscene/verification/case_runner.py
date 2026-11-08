"""Run a named physical checker with a saved result and a pinned case.

An independently frozen acceptance case and a scene-derived case have different
evidentiary scope even though they use the same physical measurements.
"""
import hashlib,importlib,json
from pathlib import Path

TYPES={'contact':'contact_pick','suction':'suction_pick','moving':'moving_pick','repeated':'repeated_pick','domino':'domino','parallel':'parallel_probe','stream':'stream_probe','mechanism':'mechanism_adapter','passive_network':'passive_network'}
TYPES['rigid_asset_smoke']='rigid_asset_smoke'
TYPES['articulated_asset_smoke']='articulated_asset_smoke'
TYPES['container_asset_smoke']='container_asset_smoke'
TYPES['asset_gallery']='asset_gallery'
TYPES['handoff_chain']='handoff_chain'

def _load(path):
    path=Path(path)
    if path.suffix.lower() in ('.yaml','.yml'):
        import yaml
        try:return yaml.safe_load(path.read_text())
        except yaml.YAMLError as error:raise ValueError(f'invalid YAML: {error}') from error
    return json.loads(path.read_text())

def verify_passive_suite(positive_run, control_runs, case_path=None):
    """Choose an explicit schema authority; its original sealed guards still run."""
    root=Path(positive_run)
    selected=case_path
    if selected is None:
        lock=_load(root/'run-lock.json')
        name=lock.get('acceptance_case_file')
        if name not in ('acceptance-case.json','acceptance-case.yaml','acceptance-case.yml'):
            raise ValueError('a snapshotted passive network case is required')
        selected=root/name
    case=_load(selected)
    if not isinstance(case,dict):raise ValueError('case must be a mapping')
    schema=case.get('schema')
    if schema in ('simscene.passive_network.v1','simscene.passive_network.v2'):
        module_name='passive_network'
    elif schema=='simscene.passive_network.v3':module_name='passive_network_v3'
    else:raise ValueError('unsupported passive network suite schema')
    module=importlib.import_module('.'+module_name,__package__)
    return module.verify_suite(positive_run,control_runs,case_path)

def evaluate(run_path,case_path=None,case_type=None,spec_path=None,mode='positive',reference_run=None):
    directory=Path(run_path) if Path(run_path).is_dir() else None
    lock={}
    if directory and (directory/'run-lock.json').is_file():lock=_load(directory/'run-lock.json')
    allowed=('acceptance-case.json','acceptance-case.yaml','acceptance-case.yml')
    if case_path is None and directory:
        name=lock.get('acceptance_case_file')
        if name in allowed:case_path=directory/name
    if not case_path:raise ValueError('case is required unless the run includes a snapshotted case')
    if lock.get('acceptance_case_sha256') is not None:
        name=lock.get('acceptance_case_file');snapshot=directory/name if name in allowed else None
        if not snapshot or not snapshot.is_file() or hashlib.sha256(snapshot.read_bytes()).hexdigest()!=lock['acceptance_case_sha256'] or hashlib.sha256(Path(case_path).read_bytes()).hexdigest()!=lock['acceptance_case_sha256']:
            raise ValueError("case does not match the run's snapshotted acceptance case")
    case=_load(case_path)
    if not isinstance(case,dict):raise ValueError('case must be a mapping')
    if case_type is None:
        if case.get('schema')=='simscene.rigid_asset_smoke.v1':case_type='rigid_asset_smoke'
        elif case.get('schema')=='simscene.articulated_asset_smoke.v1':case_type='articulated_asset_smoke'
        elif case.get('schema')=='simscene.container_asset_smoke.v1':case_type='container_asset_smoke'
        elif case.get('schema')=='simscene.asset_gallery.v1':case_type='asset_gallery'
        elif case.get('schema')=='simscene.handoff_chain.v1':case_type='handoff_chain'
        elif case.get('schema') in ('simscene.passive_network.v1','simscene.passive_network.v2','simscene.passive_network.v3'):case_type='passive_network'
        elif case.get('schema') in ('simscene.mechanism.v1','simscene.mechanism.v2'):case_type='mechanism'
        elif 'expected_spawn_order' in case and 'objects' in case:case_type='stream'
        elif 'objects' in case:case_type='parallel'
        else:raise ValueError('case type is required when it cannot be inferred')
    if case_type not in TYPES:raise ValueError('unsupported verification case type')
    module_name=TYPES[case_type]
    if case.get('schema')=='simscene.mechanism.v2':
        if case_type!='mechanism':raise ValueError('v2 D6 case requires mechanism verification')
        module_name='mechanism_adapter_v2'
    elif case.get('schema')=='simscene.passive_network.v3':
        if case_type!='passive_network':raise ValueError('v3 D6 case requires passive network verification')
        module_name='passive_network_v3'
    module=importlib.import_module('.'+module_name,__package__)
    if case_type=='handoff_chain':
        if not directory:raise ValueError('handoff verification requires the complete frozen run directory')
        return {**module.verify_run(directory,case_path,mode,reference_directory=reference_run),'case_type':case_type}
    if case_type in ('rigid_asset_smoke','articulated_asset_smoke','container_asset_smoke','asset_gallery'):
        if not directory or mode!='positive' or reference_run is not None:
            raise ValueError('imported asset verification requires a frozen run directory and its own case')
        return {**module.verify_run(directory,case_path),'case_type':case_type}
    if case_type in ('mechanism','passive_network'):
        if not directory:raise ValueError('passive verification requires the complete frozen run directory')
        result=module.verify_run(directory,case_path,mode,reference_run)
        return {**result,'case_type':case_type}
    if mode!='positive' or reference_run is not None:raise ValueError('paired mechanism modes require a mechanism case')
    run=_load(directory/'result.json' if directory else run_path)
    if case_type in ('parallel','stream'):
        spec_path=spec_path or (directory/'spec.json' if directory else None)
        if not spec_path:raise ValueError('spec is required for parallel and stream verification when run is a file')
        result=module.evaluate(run,_load(spec_path),case)
    else:result=module.evaluate(run,case)
    if case.get('collision_policy') is not None:
        if case_type!='stream' or not directory:raise ValueError('collision policy requires a stream run directory and frozen stage')
        from .overlap_audit import evaluate as evaluate_collision
        result['collision_audit']=evaluate_collision(run,_load(spec_path),case,directory/'scene.usda')
        result['passed']=bool(result['passed'] and result['collision_audit']['passed'])
    result['case_type']=case_type
    result['case_pinned_to_run']=bool(lock.get('acceptance_case_sha256'))
    result['archive_ledger_verified']=None
    if lock.get('archive_verified_objects'):
        from .archive_ledger import verify as verify_ledger
        result['archive_ledger_verified']=verify_ledger(directory,run)
        result['passed']=bool(result['passed'] and result['archive_ledger_verified'])
    result['input_integrity']=None
    if lock:
        from ..run_integrity import verify
        result['input_integrity']=verify(directory)
        result['passed']=bool(result['passed'] and result['input_integrity']['passed'])
    result['evidence_integrity']=None
    if directory and (directory/'evidence-lock.json').is_file():
        from ..evidence_integrity import verify as verify_evidence
        result['evidence_integrity']=verify_evidence(directory)
        result['passed']=bool(result['passed'] and result['evidence_integrity']['passed'] and not result['evidence_integrity']['partial'])
    return result
