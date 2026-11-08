"""Additive geometry-only observation of a recorded box in static halfspaces.

Every original strict sample0 and task step is used. Earliest entry is never
replaced after an escape. This is not stability, cavity-model or physics-suite
acceptance, and does not establish what happened between recorded boundaries.
"""
import argparse
import copy
import datetime
from fractions import Fraction as F
import hashlib
import itertools
import json
import math
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from simscene.verification import mechanism as m,passive_network as p

SCHEMA='simscene.box_halfspace_observation.v2'
MAX_PLANES=32
MAX_STEPS=20_000
MAX_CONTACT_RECORDS=1_000_000
DEPENDENCIES={'mechanism':'ce05b85cd11af946901f77249e6d16208434d5764056c5ba704a97beb4c9f4e8',
              'passive_network':'0ed9160f0225bcba3e621c2b22ce0a36720ca67203cb29330883abfd99a1adc1'}


def require(value,message):
    if not value:raise ValueError(message)


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def canonical_sha(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def dot(a,b):return sum(x*y for x,y in zip(a,b) if x and y)
def sub(a,b):return [x-y for x,y in zip(a,b)]
def cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
def rational(values):return [F(value) for value in values]


def _safe_failure(value):
    if isinstance(value,dict):return {str(k):_safe_failure(v) for k,v in value.items()}
    if isinstance(value,list):return [_safe_failure(v) for v in value]
    if type(value) is float and not math.isfinite(value):return {'unsupported_nonfinite_number':repr(value)}
    return value


def number(value):
    result=float(value)
    require(math.isfinite(result),'represented geometry/margin exceeds finite report range')
    return result


def margin_record(value):
    return {'margin_m_approx':number(value),'exact_rational':str(value),'sign':(value>0)-(value<0)}


def bounded_volume(planes):
    """Exact 3D boundedness, feasibility and full-dimensionality of Nx<=b."""
    require(isinstance(planes,list) and 4<=len(planes)<=MAX_PLANES,'provide 4..32 declared halfspaces')
    prepared=[];identifiers=set()
    for plane in planes:
        require(isinstance(plane,dict) and set(plane)=={'id','normal_world','offset_m'},'invalid halfspace fields')
        require(isinstance(plane['id'],str) and plane['id'] and plane['id'] not in identifiers,'distinct nonempty plane IDs required')
        identifiers.add(plane['id'])
        require(m.vector(plane['normal_world']) and m.finite(plane['offset_m']),'finite halfspace normal/offset required')
        normal=rational(plane['normal_world']);offset=F(plane['offset_m'])
        require(abs(dot(normal,normal)-1)<=F(1,10**12),'plane normal must be unit within 1e-12; no renormalization')
        denominator=math.lcm(offset.denominator,*[v.denominator for v in normal])
        prepared.append({'id':plane['id'],'n':normal,'b':offset,'denominator':denominator,
            'coefficients':[(i,int(value*denominator)) for i,value in enumerate(normal) if value],
            'offset_integer':int(offset*denominator)})
    normals=[plane['n'] for plane in prepared]
    require(any(dot(a,cross(b,c)) for a,b,c in itertools.combinations(normals,3)),
            'unsupported/unbounded volume: normals have rank below three')
    # Full normal rank removes lineality. Every nonzero pointed polyhedral
    # recession cone in R3 has an extreme ray at two independent active planes.
    for first,second in itertools.combinations(normals,2):
        direction=cross(first,second)
        if not any(direction):continue
        for sign in (-1,1):
            candidate=[sign*v for v in direction]
            require(not all(dot(n,candidate)<=0 for n in normals),
                    'unbounded halfspace volume: nonzero recession direction exists')
    vertices=set();triples=0
    for a,b,c in itertools.combinations(prepared,3):
        triples+=1
        determinant=dot(a['n'],cross(b['n'],c['n']))
        if not determinant:continue
        terms=[cross(b['n'],c['n']),cross(c['n'],a['n']),cross(a['n'],b['n'])]
        vertex=tuple((a['b']*terms[0][i]+b['b']*terms[1][i]+c['b']*terms[2][i])/determinant for i in range(3))
        if all(dot(plane['n'],vertex)<=plane['b'] for plane in prepared):vertices.add(vertex)
    require(vertices,'infeasible bounded halfspace volume: no feasible vertices')
    ordered=sorted(vertices);origin=ordered[0];basis=[];full=False
    for vertex in ordered[1:]:
        delta=sub(vertex,origin)
        if not any(delta):continue
        if not basis:basis.append(delta)
        elif len(basis)==1:
            if any(cross(basis[0],delta)):basis.append(delta)
        elif dot(cross(*basis),delta):full=True;break
    require(full,'unsupported degenerate halfspace volume: no three-dimensional interior')
    return {'planes':prepared,'proof':{'bounded':True,'feasible':True,'full_dimensional':True,
        'plane_count':len(planes),'plane_triples_examined':triples,'vertex_count':len(ordered),
        'vertices_world_m_approx':[[number(v) for v in vertex] for vertex in ordered],
        'method':'Exact triple-plane vertices and full-rank recession-cone cross-pair test; no optimizer tolerance.'}}


def prepare(contract):
    fields={'schema','case_sha256','physics_dt_s','box_body_id','receiver_id','box_size_m',
            'box_configuration_sha256','receiver_configuration_sha256','planes','static_review_sha256','geometry_validity_scope'}
    require(isinstance(contract,dict) and set(contract)==fields and contract['schema']==SCHEMA,'expected complete '+SCHEMA)
    require(contract['geometry_validity_scope']=='independently_declared_static_halfspaces','declare static-only geometry validity scope')
    for key in ('case_sha256','box_configuration_sha256','receiver_configuration_sha256','static_review_sha256'):
        value=contract[key];require(isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value),'exact SHA256 required: '+key)
    require(m.finite(contract['physics_dt_s']) and contract['physics_dt_s']>0,'positive finite timestep required')
    require(m.vector(contract['box_size_m']) and min(contract['box_size_m'])>0,'positive finite recorded box dimensions required')
    require(all(isinstance(contract[k],str) and contract[k] for k in ('box_body_id','receiver_id')) and contract['box_body_id']!=contract['receiver_id'],'distinct actual box/receiver IDs required')
    result=bounded_volume(contract['planes'])
    result['half']=[F(v)/2 for v in contract['box_size_m']]
    return result


def corners(sample,path,half):
    position=sample.get('positions',{}).get(path);q=sample.get('orientations_wxyz',{}).get(path)
    require(m.vector(position) and m.quaternion(q),'recorded box pose missing/nonfinite/nonunit')
    position=rational(position);w,x,y,z=rational(q);s=w*w+x*x+y*y+z*z
    require(s>0,'zero quaternion')
    rotation=[[(w*w+x*x-y*y-z*z)/s,2*(x*y-w*z)/s,2*(x*z+w*y)/s],
              [2*(x*y+w*z)/s,(w*w-x*x+y*y-z*z)/s,2*(y*z-w*x)/s],
              [2*(x*z-w*y)/s,2*(y*z+w*x)/s,(w*w-x*x-y*y+z*z)/s]]
    result=[]
    for signs in itertools.product((-1,1),repeat=3):
        local=[sign*h for sign,h in zip(signs,half)]
        result.append([p0+dot(row,local) for p0,row in zip(position,rotation)])
    denominator=math.lcm(*(v.denominator for point in result for v in point))
    integer_points=[[int(v*denominator) for v in point] for point in result]
    return result,integer_points,denominator


def corner_margins(integer_points,point_denominator,planes):
    result=[]
    for plane in planes:
        base=plane['offset_integer']*point_denominator
        # Every original corner is tested. Static denominator conversion removes
        # repeated Fraction gcd work, not any geometry or corner/step checks.
        values=[base-sum(coefficient*point[axis] for axis,coefficient in plane['coefficients']) for point in integer_points]
        minimum=min(values);index=values.index(minimum)
        result.append((F(minimum,plane['denominator']*point_denominator),index))
    return result


def _contact_scan(run,spec,body,receiver):
    complete=spec.get('observation',{}).get('record_contact_pairs') is True and run.get('contacts_truncated') is False
    errors=[];first=None;visited=0
    known={n for n,o in spec['objects'].items() if o.get('kind') in ('box','sphere','cylinder','capsule','compound') and (o.get('dynamic') or o.get('collision'))}
    for sample in run['samples']:
        pairs=sample.get('contact_pairs')
        if not isinstance(pairs,list):complete=False;errors.append({'step':sample['physics_steps'],'error':'per-step callbacks unavailable'});continue
        for record in pairs:
            visited+=1
            if visited>MAX_CONTACT_RECORDS:
                return {'complete':False,'first_contact':None,'first_observed_available_contact':first,'error':'contact record budget exceeded','records_examined':visited-1}
            valid=isinstance(record,dict)
            if valid:
                required={'body_ids','actor_paths','collider_paths','count','first_callback_absolute_physics_step','last_callback_absolute_physics_step'}
                valid=required<=set(record)<=required|{'minimum_separation_m'}
            if valid:
                ids,actors,colliders=(record.get(key) for key in ('body_ids','actor_paths','collider_paths'))
                valid=all(isinstance(v,list) and len(v)==2 for v in (ids,actors,colliders)) and all(isinstance(n,str) and n in known for n in ids)
            if valid:
                valid=all(isinstance(a,str) and (a==m.path(n) or a.startswith(m.path(n)+'/')) and (c is None or isinstance(c,str) and (c==m.path(n) or c.startswith(m.path(n)+'/'))) for n,a,c in zip(ids,actors,colliders))
                first_abs,last_abs=record.get('first_callback_absolute_physics_step'),record.get('last_callback_absolute_physics_step')
                valid=valid and type(record.get('count')) is int and record['count']>0 and type(first_abs) is int and type(last_abs) is int and sample['absolute_physics_step']-1<=first_abs<=last_abs<=sample['absolute_physics_step']
                valid=valid and ('minimum_separation_m' not in record or m.finite(record['minimum_separation_m']))
            if not valid:complete=False;errors.append({'step':sample['physics_steps'],'error':'invalid raw callback record'});continue
            if set(ids)=={body,receiver} and (first is None or first['observation_step']==sample['physics_steps']):
                if first is None:first={'observation_step':sample['physics_steps'],'simulation_time_s':sample['simulation_time_s'],
                    'absolute_physics_step':sample['absolute_physics_step'],'absolute_simulation_time_s':sample['absolute_simulation_time_s'],'raw_callbacks':[]}
                first['raw_callbacks'].append(copy.deepcopy(record))
    return {'complete':complete,'first_contact':first if complete else None,'first_observed_available_contact':first,
        'errors':errors,'records_examined':visited,'scope':'First task app-update observation with actual callback data; original callback counters retained, never a synthetic activation/continuous contact time. Aggregate first/last contacts are ignored.'}


def _observe(run,spec,contract,prepared):
    result={'schema':SCHEMA,'helper_sha256':sha(__file__),'observation_scope':'untrusted_in_memory_geometry_only',
        'file_integrity_verified':False,'geometry_query_complete':False,'membership_supplement_passed':False,
        'first_complete_entry':None,'escape_steps':[],'minimum_face_margins_after_entry':{},'steps':[],
        'stability_assessed':False,'physics_acceptance':'not_assessed','formal_house_accepted':False,
        'modeled_receiver_equivalence':'not_established_by_this_helper','between_step_continuity':'not_established',
        'volume_proof':prepared['proof'],'errors':[],
        'corner_order':'lexicographic signs (-1,+1) for local X,Y,Z',
        'arithmetic':'Exact rational quaternion rotation divided by its recorded squared norm; shared-denominator integer plane tests of every corner, with zero inside tolerance.',
        'geometry_validity_scope':contract['geometry_validity_scope']}
    try:
        require(isinstance(run.get('samples'),list) and 0<len(run['samples'])<=MAX_STEPS,'unsupported step budget: 1..20000 full original task samples required')
        body,receiver=contract['box_body_id'],contract['receiver_id'];objects=spec['objects']
        obj,container=objects.get(body,{}),objects.get(receiver,{})
        require(obj.get('kind')=='box' and obj.get('dynamic') is True and obj.get('collision') is True and not obj.get('spawn_step',0),'box must be an initially present physical dynamic box')
        require(obj.get('size')==contract['box_size_m'],'box dimensions differ from the original declared physical box')
        require(container.get('kind') in ('box','sphere','cylinder','capsule','compound') and not container.get('dynamic') and container.get('collision') is True and not any(container.get(k) for k in ('spawn_step','pose_follower','conveyor')),'receiver must be authored static collision geometry')
        require(canonical_sha(obj)==contract['box_configuration_sha256'] and canonical_sha(container)==contract['receiver_configuration_sha256'],'physical root configurations differ from static declaration')
        dt=contract['physics_dt_s'];clock=m.timeline(run,spec,dt);strict=m.strict_initial_state(run,spec,{'require_strict_initial_state':True},dt)
        result['timeline']=clock;result['strict_initial_state']=strict
        require(clock['passed'] and strict['passed'],'complete original per-step relative/absolute clock and measured strict t0 required')
        first=None;minima={};escapes=[];tests=0;previous=None
        for sample in itertools.chain((run['initial_observation'],),run['samples']):
            points,integers,denominator=corners(sample,m.path(body),prepared['half'])
            margins=corner_margins(integers,denominator,prepared['planes']);tests+=8*len(margins)
            inside=all(value>=0 for value,index in margins)
            worst=min(range(len(margins)),key=lambda i:margins[i][0])
            row={key:sample[key] for key in ('physics_steps','simulation_time_s','absolute_physics_step','absolute_simulation_time_s')}
            row.update(whole_box_member=inside,corners_world_m_approx=[[number(v) for v in point] for point in points],
                worst_plane_id=prepared['planes'][worst]['id'],worst_corner_index=margins[worst][1],**margin_record(margins[worst][0]))
            result['steps'].append(row)
            if inside and first is None:
                first={key:row[key] for key in ('physics_steps','simulation_time_s','absolute_physics_step','absolute_simulation_time_s')}
                first['preceding_original_boundary']=previous
            if first is not None:
                if not inside:escapes.append(sample['physics_steps'])
                for plane,(value,index) in zip(prepared['planes'],margins):
                    if plane['id'] not in minima or value<minima[plane['id']]['value']:
                        minima[plane['id']]={'value':value,'record':{'physics_steps':sample['physics_steps'],'corner_index':index,
                            'corner_world_m_approx':[number(v) for v in points[index]],**margin_record(value)}}
            previous={key:sample[key] for key in ('physics_steps','simulation_time_s','absolute_physics_step','absolute_simulation_time_s')}
        result.update(geometry_query_complete=True,first_complete_entry=first,escape_steps=escapes,
            minimum_face_margins_after_entry={name:value['record'] for name,value in minima.items()},
            membership_supplement_passed=first is not None and not escapes,
            original_boundaries_examined=len(result['steps']),corner_plane_tests=tests,
            contact_observation=_contact_scan(run,spec,body,receiver))
    except (ValueError,TypeError,KeyError,AttributeError,IndexError,ArithmeticError,MemoryError) as error:
        result['errors'].append({'type':type(error).__name__,'reason':str(error)})
    return result if result['geometry_query_complete'] else _safe_failure(result)


def evaluate(run,spec,contract):
    """Untrusted in-memory geometry only; file provenance is not certified."""
    try:return _observe(run,spec,contract,prepare(contract))
    except (ValueError,TypeError,KeyError,AttributeError,IndexError,ArithmeticError,MemoryError) as error:
        return {'schema':SCHEMA,'geometry_query_complete':False,'membership_supplement_passed':False,
            'file_integrity_verified':False,'stability_assessed':False,'formal_house_accepted':False,
            'errors':[{'type':type(error).__name__,'reason':str(error)}]}


def _date(value):
    result=datetime.datetime.fromisoformat(value.replace('Z','+00:00'))
    require(result.tzinfo is not None,'timezone-aware freeze/run times required')
    return result


def verify(directory,case_path,contract_path,review_path,freeze_path,original_run_lock_sha256,original_evidence_lock_sha256):
    """Full sealed originals and a pre-job static contract, never edited data."""
    root=Path(directory).resolve();paths=[Path(v).resolve() for v in (case_path,contract_path,review_path,freeze_path)]
    case_path,contract_path,review_path,freeze_path=paths
    failure={'schema':SCHEMA,'geometry_query_complete':False,'membership_supplement_passed':False,'file_integrity_verified':False,'stability_assessed':False,'formal_house_accepted':False,'errors':[]}
    try:
        require(sha(m.__file__)==DEPENDENCIES['mechanism'] and sha(p.__file__)==DEPENDENCIES['passive_network'],'frozen reader/clock kernel changed')
        expected_locks={'run-lock.json':original_run_lock_sha256,'evidence-lock.json':original_evidence_lock_sha256}
        require(all(isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value) for value in expected_locks.values()),'provide independently retained original lock SHA256 values')
        require(all(sha(root/name)==value for name,value in expected_locks.items()),'original run/evidence lock bytes differ from retained SHA256 values')
        external={str(path):sha(path) for path in (case_path,contract_path,review_path,freeze_path)}
        contract=json.loads(contract_path.read_text());prepared=prepare(contract)
        require(sha(case_path)==contract['case_sha256'] and sha(review_path)==contract['static_review_sha256'],'original case/static-review bytes differ from contract')
        freeze=json.loads(freeze_path.read_text())
        require(freeze.get('schema')=='simscene.box_halfspace_freeze.v1','independent static binding freeze required')
        pinned=freeze.get('files_sha256',{})
        require(all(pinned.get(str(path))==sha(path) for path in (case_path,contract_path,review_path,Path(__file__).resolve())),'static freeze must pin exact case/contract/review/helper bytes')
        lock=json.loads((root/'run-lock.json').read_text())
        require(_date(freeze['frozen_at_utc'])<_date(lock['created_at_utc']),'static binding must precede original job snapshot')
        require(type(lock.get('requested_physics_steps')) is int and 0<lock['requested_physics_steps']<=MAX_STEPS,'unsupported original step budget')
        require(lock.get('physics_dt_s')==contract['physics_dt_s'],'original locked timestep differs from declaration')
        require(lock.get('acceptance_case_file') in ('acceptance-case.json','acceptance-case.yaml','acceptance-case.yml'),'invalid original snapshotted case filename')
        names=('run-lock.json','evidence-lock.json','spec.json','result.json',lock['acceptance_case_file'])
        before={name:sha(root/name) for name in names}
        def mapping_case(value):require(isinstance(value,dict),'original case must parse as a mapping; its physics semantics remain the stock checker responsibility')
        data=p._read_locked(root,case_path,case_validator=mapping_case)
        require(data['passed'],'original full input/output locks or worker/case proof failed')
        evidence=json.loads((root/'evidence-lock.json').read_text())
        require(before['result.json']==evidence['artifacts']['result.json']['sha256'] and before['spec.json']==data['lock']['spec_sha256'],'recorded original result/spec hashes differ')
        result=_observe(data['run'],data['spec'],contract,prepared)
        require(all(sha(root/name)==value for name,value in before.items()),'original run files changed during observation')
        require(all(sha(Path(name))==value for name,value in external.items()),'static contract/case/review/freeze changed during observation')
        result.update(file_integrity_verified=True,observation_scope='sealed_original_run_geometry_only',
            provenance={'original_files_sha256':before,'external_files_sha256':external,
                        'independently_retained_original_lock_sha256':expected_locks,
                        'helper_sha256':sha(__file__),'input_output_proof':data['integrity'],
                        'local_freeze_chronology':'Exact local recorded bytes/dates, not an external timestamp signature.',
                        'physical_case_semantics':'Not certified by this geometry helper; the original stock/v3 suite remains authoritative.'})
        return result
    except (OSError,ValueError,TypeError,KeyError,AttributeError,IndexError,ArithmeticError,MemoryError) as error:
        failure['errors'].append({'type':type(error).__name__,'reason':str(error)})
        return failure


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('run','case','contract','static-review','freeze','run-lock-sha256','evidence-lock-sha256','output'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args();root=Path(args.run).resolve();output=Path(args.output).resolve()
    require(not output.is_relative_to(root),'write reports outside the sealed original run')
    result=verify(root,args.case,args.contract,args.static_review,args.freeze,args.run_lock_sha256,args.evidence_lock_sha256)
    with output.open('x') as stream:json.dump(result,stream,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({key:result[key] for key in ('geometry_query_complete','membership_supplement_passed','file_integrity_verified','stability_assessed','formal_house_accepted')}))
    return 0 if result['geometry_query_complete'] and result['membership_supplement_passed'] and result['file_integrity_verified'] else 1


if __name__=='__main__':raise SystemExit(main())
