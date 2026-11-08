"""Open-container passage and retention checks on actual imported probe bounds."""
import json
from pathlib import Path
from . import rigid_asset_smoke as rigid

SCHEMA='simscene.container_asset_smoke.v1'


def validate_case(case):
    if not isinstance(case,dict) or case.get('schema')!=SCHEMA or case.get('schema_version')!=1:
        raise ValueError('unsupported container asset smoke case')
    rigid.validate_case(dict(case,schema=rigid.SCHEMA))
    container=case.get('container')
    if (not isinstance(container,dict) or not isinstance(container.get('object_id'),str)
            or not isinstance(container.get('prepared_manifest_sha256'),str)
            or not rigid._bounds(container.get('interior_bounds'))):
        raise ValueError('container smoke requires frozen prepared container and interior bounds')
    opening=container.get('opening')
    if (not isinstance(opening,dict) or not rigid._numbers(opening.get('min_xy'),2)
            or not rigid._numbers(opening.get('max_xy'),2) or not rigid._numbers([opening.get('z_m')],1)
            or any(a>=b for a,b in zip(opening['min_xy'],opening['max_xy']))):
        raise ValueError('container smoke requires a frozen upward opening')
    return case


def evaluate(run,case):
    validate_case(case)
    result=rigid.evaluate(run,dict(case,schema=rigid.SCHEMA))
    try:
        frames=[run['initial_observation']]+run['samples'];opening=case['container']['opening'];inside=case['container']['interior_bounds']
        for name,outcome in result['objects'].items():
            checks=outcome['checks'];bounds=[frame['bounds'][name] for frame in frames]
            checks['initial_full_probe_above_opening']=bounds[0]['min'][2]>opening['z_m']
            traversing=[b for b in bounds if b['min'][2]<=opening['z_m']<=b['max'][2]]
            checks['full_probe_passed_opening']=bool(traversing) and bounds[-1]['max'][2]<opening['z_m'] and all(
                opening['min_xy'][i]<=b['min'][i]<=b['max'][i]<=opening['max_xy'][i] for b in traversing for i in (0,1))
            final=bounds[-1]
            checks['full_probe_retained_inside_cavity']=all(inside['min'][i]<=final['min'][i]<=final['max'][i]<=inside['max'][i] for i in range(3))
            outcome['passed']=all(checks.values())
        result['checks']['all_objects_passed']=bool(result['objects']) and all(o['passed'] for o in result['objects'].values())
        result['passed']=all(result['checks'].values())
    except (KeyError,ValueError,TypeError,AttributeError):
        result['passed']=False;result['checks']['valid_container_measurements']=False
    result['scope']='frozen upward opening passage, full-bounds retention, direct support contact and settling; explicit measured container geometry'
    return result


def verify_run(directory,case_path=None):
    from ..cache import _sha256
    from ..physics_binding import validate_asset_binding
    from ..run_integrity import verify as verify_inputs
    from ..evidence_integrity import verify as verify_evidence
    root=Path(directory);lock=json.loads((root/'run-lock.json').read_text())
    if lock.get('acceptance_case_file')!='acceptance-case.json':raise ValueError('container smoke requires frozen JSON case')
    frozen=root/'acceptance-case.json';expected=lock.get('acceptance_case_sha256')
    if _sha256(frozen)!=expected or case_path is not None and _sha256(Path(case_path))!=expected:raise ValueError('container smoke case changed')
    run=json.loads((root/'result.json').read_text());case=json.loads(frozen.read_text());result=evaluate(run,case)
    pinned=False
    try:
        spec=json.loads((root/'spec.json').read_text());obj=spec['objects'][case['container']['object_id']]
        manifest=validate_asset_binding(obj['asset_binding'],asset_path=obj['asset_path'])
        pinned=manifest['profile_id']=='container_v1' and obj['asset_binding']['manifest_sha256']==case['container']['prepared_manifest_sha256']
    except (OSError,KeyError,ValueError,TypeError):pass
    result['checks']['prepared_container_pinned']=pinned
    result['checks']['probe_bindings_pinned']=run.get('body_bindings')==lock.get('body_bindings') and isinstance(lock.get('body_bindings'),dict)
    inputs=verify_inputs(root);evidence=verify_evidence(root)
    result.update(input_integrity=inputs,evidence_integrity=evidence,case_pinned_to_run=True)
    result['passed']=bool(all(result['checks'].values()) and inputs['passed'] and evidence['passed'] and evidence['partial'] is False)
    return result
