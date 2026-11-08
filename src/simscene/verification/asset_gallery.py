"""One frozen heterogeneous run, with original component evidence checkers.

Ordered contacts establish observed temporal order only. They do not establish
necessary causality; that requires a separately frozen negative experiment.
"""
import json
import math
from pathlib import Path
import re

from . import rigid_asset_smoke as rigid
from . import articulated_asset_smoke as articulated
from . import container_asset_smoke as container
from . import handoff_chain as handoff

SCHEMA = 'simscene.asset_gallery.v1'
MODULES = {rigid.SCHEMA:rigid, articulated.SCHEMA:articulated, container.SCHEMA:container, handoff.SCHEMA:handoff}
MAX_CASE_BYTES = 256 * 1024


def _id(value):
    return isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}',value) is not None


def _selection(value):
    from ..catalog.models import AssetRef
    if not isinstance(value,dict) or not re.fullmatch(r'[0-9a-f]{64}',str(value.get('prepared_manifest_sha256',''))):
        raise ValueError('gallery selection requires an exact prepared manifest SHA-256')
    ref=value.get('source_ref')
    try:
        selected=AssetRef.from_dict(ref)
        selected.validate_selection(huggingface=selected.source_id in ('abo-glb','gso-glb','usdcraft'))
        if selected.revision.lower() in ('unknown','main','master','latest','head'):
            raise ValueError('mutable or unknown source revision')
    except (ValueError,TypeError,KeyError,AttributeError) as error:
        raise ValueError('gallery selection requires an explicit pinned source_ref') from error


def _handoff_selections(case):
    roles=[(case['source_object_id'],'rigid_prop_v1',True),
           (case['guide_object_id'],'static_fixture_v1',False),
           (case['receiver_object_id'],'container_v1',False)]
    names={name for name,_,_ in roles}
    if len(names)!=3 or any(not isinstance(case.get(key),dict) or set(case[key])!=names
            for key in ('prepared_manifest_sha256s','source_refs','prepared_profiles')):
        raise ValueError('gallery handoff requires three exact prepared object selections')
    result=[]
    for name,profile,dynamic in roles:
        if case['prepared_profiles'][name]!=profile:raise ValueError('gallery handoff prepared profile differs')
        expected={'prepared_manifest_sha256':case['prepared_manifest_sha256s'][name],'source_ref':case['source_refs'][name]}
        _selection(expected);result.append((name,expected,profile,dynamic))
    return result


def validate_case(case):
    if (not isinstance(case,dict) or case.get('schema')!=SCHEMA or type(case.get('schema_version')) is not int
            or case['schema_version']!=1 or set(case)-{'schema','schema_version','components','contact_sequences'}):
        raise ValueError('unsupported asset gallery case')
    try:
        if len(json.dumps(case,allow_nan=False).encode())>MAX_CASE_BYTES: raise ValueError('gallery case too large')
    except (ValueError,TypeError,RecursionError) as error:
        raise ValueError('gallery case must be bounded finite JSON') from error
    components=case.get('components');claimed=set();subjects=set()
    if not isinstance(components,list) or not 0<len(components)<=16:
        raise ValueError('gallery requires one to sixteen components')
    for component in components:
        if not isinstance(component,dict) or set(component)!={'id','case'} or not _id(component['id']) or component['id'] in claimed:
            raise ValueError('invalid or duplicate gallery component ID')
        claimed.add(component['id']);embedded=component['case']
        module=MODULES.get(embedded.get('schema')) if isinstance(embedded,dict) else None
        if module is None: raise ValueError('unsupported gallery component schema')
        module.validate_case(embedded)
        if embedded['schema']=='simscene.handoff_chain.v1':
            _handoff_selections(embedded)
            subjects.update([embedded['source_body'],embedded['ball_body'],*embedded['tiles']])
        elif module is articulated:
            for item in embedded['objects'].values():
                _selection(item);subjects.add(item['child_body'])
                if item.get('parent_body'): subjects.add(item['parent_body'])
        else:
            _selection(embedded)
            subjects.update(item['motion_body'] for item in embedded['objects'].values())
            if module is container:
                _selection(embedded['container'])
                if embedded['container']['object_id'] in embedded['objects']:
                    raise ValueError('container and probe must be distinct objects')
    sequences=case.get('contact_sequences',[])
    if not isinstance(sequences,list) or len(sequences)>16: raise ValueError('invalid gallery contact sequences')
    for sequence in sequences:
        if (not isinstance(sequence,dict) or set(sequence)!={'id','subject_body','actors','max_gap_s'}
                or not _id(sequence['id']) or sequence['id'] in claimed):
            raise ValueError('invalid or duplicate gallery sequence ID')
        claimed.add(sequence['id']);actors=sequence['actors'];gap=sequence['max_gap_s']
        if (sequence['subject_body'] not in subjects or not rigid._actor(sequence['subject_body'])
                or not isinstance(actors,list) or not 2<=len(actors)<=32
                or any(not rigid._actor(a) or a==sequence['subject_body'] for a in actors)
                or type(gap) not in (int,float) or not math.isfinite(gap) or gap<=0):
            raise ValueError('invalid gallery contact sequence actors or finite gap')
    return case


def _contact_sequence(run,sequence):
    """Use only actual callback endpoint steps, never interpolate an aggregate."""
    try:
        total=run['actual_physics_steps'];zero=run['run_zero_absolute_physics_step'];duration=run['simulation_time_s']
        if type(total) is not int or total<=0 or type(zero) is not int or type(duration) not in (int,float) or not math.isfinite(duration) or duration<=0:
            raise ValueError('invalid measured physics timeline')
        dt=duration/total
        if not math.isfinite(dt) or dt<=0: raise ValueError('invalid measured physics step duration')
        frames=[run['initial_observation']]+run['samples']
        for frame in frames:
            step=frame['physics_steps'];time=frame['simulation_time_s']
            if type(step) is not int or not 0<=step<=total or type(time) not in (int,float) or not math.isfinite(time) or abs(time-step*dt)>1e-6:
                raise ValueError('contact sequence timeline inconsistent')
        observed={actor:set() for actor in sequence['actors']}
        for frame in frames:
            for pair in frame.get('contact_pairs',[]):
                actors=pair.get('actor_paths');first=pair.get('first_callback_absolute_physics_step');last=pair.get('last_callback_absolute_physics_step')
                if (not isinstance(actors,list) or len(actors)!=2 or type(pair.get('count')) is not int or pair['count']<=0
                        or type(first) is not int or type(last) is not int or not zero<first<=last<=zero+total):continue
                # A frame cannot report a callback that had not happened yet.
                if last>zero+frame['physics_steps']:continue
                if sequence['subject_body'] not in actors:continue
                actor=actors[1] if actors[0]==sequence['subject_body'] else actors[0]
                if actor in observed: observed[actor].update((first-zero,last-zero))
        # Keep all feasible histories: greedy earliest can fail a max-gap chain
        # that a later initial contact satisfies. Endpoints cap states by steps.
        states={step:[step] for step in observed[sequence['actors'][0]]}
        for actor in sequence['actors'][1:]:
            following={}
            for step in sorted(observed[actor]):
                prior=[history for last,history in states.items() if 0<(step-last)*dt<=sequence['max_gap_s']+1e-9]
                if prior:following[step]=min(prior)+[step]
            states=following
        history=min(states.values()) if states else []
        return {'passed':bool(history),'actor_paths':sequence['actors'],'subject_body':sequence['subject_body'],
                'callback_physics_steps':history,'contact_times_s':[step*dt for step in history],
                'scope':'observed strict temporal contact order only; necessary causality untested'}
    except (KeyError,ValueError,TypeError,AttributeError) as error:
        return {'passed':False,'errors':[str(error)],'scope':'contact order unavailable; necessary causality untested'}


def evaluate(run,case):
    """Read one measurement mapping; never relabel or rewrite component cases."""
    validate_case(case)
    components={component['id']:MODULES[component['case']['schema']].evaluate(run,component['case']) for component in case['components']}
    sequences={item['id']:_contact_sequence(run,item) for item in case.get('contact_sequences',[])}
    checks={'all_components_passed':all(value.get('passed') is True for value in components.values()),
            'all_contact_sequences_passed':all(value.get('passed') is True for value in sequences.values())}
    return {'schema_version':1,'passed':all(checks.values()),'checks':checks,'components':components,
            'contact_sequences':sequences,'case_pinned_to_run':False,
            'scope':'one-run heterogeneous component observations; contact order does not establish necessary causality'}


def _pin_selection(spec,name,expected,profile,*,dynamic,validated):
    from ..physics_binding import validate_asset_binding
    obj=spec['objects'][name];binding=obj['asset_binding']
    if obj.get('kind')!='asset' or obj.get('dynamic',False) is not dynamic:
        raise ValueError('gallery object kind/dynamic mode differs: '+name)
    if binding['manifest_sha256']!=expected['prepared_manifest_sha256']:
        raise ValueError('gallery prepared manifest differs from selected object: '+name)
    # A single manifest closure may be shared by multiple actual instances.
    key=(binding['manifest_path'],binding['manifest_sha256'],obj['asset_path'],dynamic)
    if key not in validated:
        validated[key]=validate_asset_binding(binding,require_dynamic=dynamic,asset_path=obj['asset_path'])
    manifest=validated[key]
    if manifest.get('profile_id')!=profile or manifest.get('source_ref')!=expected['source_ref']:
        raise ValueError('gallery profile or source selection differs: '+name)


def verify_run(directory,case_path=None):
    """Verify the whole frozen case and whole input/evidence locks exactly once."""
    from ..cache import _sha256
    from ..run_integrity import verify as verify_inputs
    from ..evidence_integrity import verify as verify_evidence
    root=Path(directory)
    for name in ('run-lock.json','acceptance-case.json','spec.json','result.json'):
        if (root/name).is_symlink():raise ValueError('gallery requires ordinary frozen run files')
    lock=json.loads((root/'run-lock.json').read_text());frozen=root/'acceptance-case.json'
    expected=lock.get('acceptance_case_sha256')
    if (lock.get('acceptance_case_file')!='acceptance-case.json' or not isinstance(expected,str)
            or _sha256(frozen)!=expected or case_path is not None and _sha256(Path(case_path))!=expected):
        raise ValueError('gallery acceptance case differs from whole frozen run case')
    case=json.loads(frozen.read_text());validate_case(case)
    run=json.loads((root/'result.json').read_text());result=evaluate(run,case)
    checks=result['checks'];checks['all_body_bindings_pinned_to_run']=(isinstance(lock.get('body_bindings'),dict)
        and bool(lock['body_bindings']) and run.get('body_bindings')==lock['body_bindings'])
    checks['all_prepared_selections_pinned']=False;errors=[]
    try:
        spec=json.loads((root/'spec.json').read_text());validated={}
        for component in case['components']:
            embedded=component['case'];module=MODULES[embedded['schema']]
            if embedded['schema']=='simscene.handoff_chain.v1':
                for name,expected,profile,dynamic in _handoff_selections(embedded):
                    if dynamic and name not in lock.get('body_bindings',{}):
                        raise ValueError('gallery handoff source body not in frozen run bindings: '+name)
                    _pin_selection(spec,name,expected,profile,dynamic=dynamic,validated=validated)
                if module.verify_selection(spec,embedded) is not True:
                    raise ValueError('gallery handoff geometry selection not verified')
                continue
            for name,item in embedded['objects'].items():
                if name not in lock.get('body_bindings',{}):raise ValueError('gallery component body not in frozen run bindings: '+name)
                _pin_selection(spec,name,item if module is articulated else embedded,
                               'articulated_prop_v1' if module is articulated else 'rigid_prop_v1',dynamic=True,validated=validated)
            if module is container:
                selected=embedded['container']
                _pin_selection(spec,selected['object_id'],selected,'container_v1',dynamic=False,validated=validated)
        checks['all_prepared_selections_pinned']=True
    except (OSError,ValueError,KeyError,TypeError,AttributeError) as error:errors.append(str(error))
    try: inputs=verify_inputs(root)
    except (OSError,ValueError,KeyError,TypeError) as error:inputs={'passed':False,'errors':[str(error)]}
    try:evidence=verify_evidence(root)
    except (OSError,ValueError,KeyError,TypeError) as error:evidence={'passed':False,'partial':None,'errors':[str(error)]}
    result.update(input_integrity=inputs,evidence_integrity=evidence,case_pinned_to_run=True,errors=errors)
    result['passed']=bool(all(checks.values()) and inputs.get('passed') is True and evidence.get('passed') is True and evidence.get('partial') is False)
    return result
