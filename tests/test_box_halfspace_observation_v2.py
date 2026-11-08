"""Synthetic CPU geometry and real file-lock adversaries, never a physics run."""
import copy
from fractions import Fraction as F
import itertools
import json
import math
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from experiments import box_halfspace_observation_v2 as h
from test_passive_network import seal_fixture


def cube_planes(half=1,angle=0):
    axes=[[math.cos(angle),math.sin(angle),0],[-math.sin(angle),math.cos(angle),0],[0,0,1]]
    return [{'id':f'face_{i}_{sign}','normal_world':[sign*v for v in axis],'offset_m':half}
            for i,axis in enumerate(axes) for sign in (-1,1)]


def fixture(centers=None,quaternions=None,planes=None,size=None):
    centers=centers or [[2,0,0],[0,0,0],[.1,0,0],[0,0,0]]
    quaternions=quaternions or [[1,0,0,0] for _ in centers]
    size=size or [.2,.2,.2];dt=1/60;count=len(centers)-1
    spec={'objects':{'box':{'kind':'box','dynamic':True,'collision':True,'mass_kg':1,'size':size,
                           'position':centers[0],'orientation_wxyz':quaternions[0]},
                     'receiver':{'kind':'box','dynamic':False,'collision':True,'size':[2,2,2],'position':[0,0,0]}},
          'observation':{'sample_interval_steps':1,'strict_start':True,'record_contact_pairs':True}}
    def sample(step):
        return {'physics_steps':step,'simulation_time_s':step*dt,'absolute_physics_step':3+step,
            'absolute_simulation_time_s':.05+step*dt,'positions':{'/World/box':centers[step]},
            'orientations_wxyz':{'/World/box':quaternions[step]},'linear_velocities_m_s':{'/World/box':[0,0,0]},
            'angular_velocities_rad_s':{'/World/box':[0,0,0]},'joints':{},'followers':{},'contact_pairs':[]}
    initial=sample(0)
    reset={'applied':True,'phase':'before_task_start','reset_count':1,'body_ids':['box'],'body_paths':['/World/box'],
        'authored_pose_readback_max_error_m':0,'max_quaternion_error':0,'authored_orientation_readback_max_error_degrees':0,
        'max_linear_speed_m_s':0,'max_angular_speed_rad_s':0,'setters_during_task':False,
        'absolute_physics_step':3,'absolute_simulation_time_s':.05,'before_warmup_absolute_physics_step':0,
        'before_warmup_absolute_simulation_time_s':0,'after_warmup_absolute_physics_step':3,'after_warmup_absolute_simulation_time_s':.05}
    run={'samples':[sample(step) for step in range(1,count+1)],'initial_observation':initial,'initialization_reset':reset,
         'initial_joint_states':{},'run_zero_absolute_physics_step':3,'run_zero_absolute_simulation_time_s':.05,
         'requested_physics_steps':count,'actual_physics_steps':count,'simulation_time_s':count*dt,'seed':42,
         'observation_interval_steps':1,'followers':{},'contacts_truncated':False}
    case={'schema':'synthetic.geometry_case.v1','scope':'Synthetic locks, not a stock physical case or simulation.'}
    contract={'schema':h.SCHEMA,'case_sha256':h.hashlib.sha256(json.dumps(case).encode()).hexdigest(),'physics_dt_s':dt,
        'box_body_id':'box','receiver_id':'receiver','box_size_m':size,
        'box_configuration_sha256':h.canonical_sha(spec['objects']['box']),
        'receiver_configuration_sha256':h.canonical_sha(spec['objects']['receiver']),
        'planes':planes or cube_planes(),'static_review_sha256':'a'*64,
        'geometry_validity_scope':'independently_declared_static_halfspaces'}
    return run,spec,contract,case


def locked_fixture(root,**kwargs):
    run,spec,contract,case=fixture(**kwargs);directory=root/'run';directory.mkdir()
    seal_fixture(directory,run,spec,case)
    lock=json.loads((directory/'run-lock.json').read_text());lock['created_at_utc']='2021-01-01T00:00:00Z'
    (directory/'run-lock.json').write_text(json.dumps(lock))
    case_path=root/'case.json';case_path.write_text(json.dumps(case))
    review=root/'static-review.md';review.write_text('Synthetic STATIC halfspace declaration. This does not assert actual receiver equivalence.\n')
    contract['static_review_sha256']=h.sha(review)
    contract_path=root/'contract.json';contract_path.write_text(json.dumps(contract,indent=2))
    freeze=root/'freeze.json';freeze.write_text(json.dumps({'schema':'simscene.box_halfspace_freeze.v1',
        'frozen_at_utc':'2020-01-01T00:00:00Z','files_sha256':{str(p.resolve()):h.sha(p) for p in (case_path,review,contract_path,Path(h.__file__))}},indent=2))
    return directory,case_path,contract_path,review,freeze,h.sha(directory/'run-lock.json'),h.sha(directory/'evidence-lock.json')


class HalfspaceGeometryTest(unittest.TestCase):
    def test_earliest_entry_all_steps_and_all_corners(self):
        run,spec,contract,_=fixture();before=copy.deepcopy((run,spec,contract))
        result=h.evaluate(run,spec,contract)
        self.assertTrue(result['geometry_query_complete']);self.assertTrue(result['membership_supplement_passed'])
        self.assertEqual(result['first_complete_entry']['physics_steps'],1)
        self.assertEqual([row['physics_steps'] for row in result['steps']],[0,1,2,3])
        self.assertEqual(result['corner_plane_tests'],4*8*6)
        self.assertTrue(all(len(row['corners_world_m_approx'])==8 for row in result['steps']))
        self.assertFalse(result['file_integrity_verified']);self.assertFalse(result['stability_assessed'])
        self.assertFalse(result['formal_house_accepted']);self.assertEqual((run,spec,contract),before)

    def test_escape_and_later_reentry_cannot_replace_earliest_entry(self):
        run,spec,contract,_=fixture(centers=[[2,0,0],[0,0,0],[1.2,0,0],[0,0,0]])
        result=h.evaluate(run,spec,contract)
        self.assertTrue(result['geometry_query_complete']);self.assertFalse(result['membership_supplement_passed'])
        self.assertEqual(result['first_complete_entry']['physics_steps'],1);self.assertEqual(result['escape_steps'],[2])
        margin=result['minimum_face_margins_after_entry']['face_0_1']
        self.assertEqual(margin['physics_steps'],2);self.assertEqual(margin['sign'],-1)
        self.assertAlmostEqual(margin['margin_m_approx'],-.3)
        self.assertTrue(result['steps'][3]['whole_box_member'])

    def test_initial_boundary_entry_is_not_discarded(self):
        run,spec,contract,_=fixture(centers=[[0,0,0],[2,0,0],[0,0,0]])
        result=h.evaluate(run,spec,contract)
        self.assertEqual(result['first_complete_entry']['physics_steps'],0)
        self.assertEqual(result['escape_steps'],[1]);self.assertFalse(result['membership_supplement_passed'])

    def test_tilted_box_center_inside_is_insufficient(self):
        q=[math.cos(math.pi/8),0,0,math.sin(math.pi/8)]
        run,spec,contract,_=fixture(centers=[[2,0,0],[0,0,0],[0,0,0],[0,0,0]],
            quaternions=[[1,0,0,0],q,[1,0,0,0],q],planes=cube_planes(.5),size=[.8,.8,.8])
        result=h.evaluate(run,spec,contract)
        self.assertTrue(result['geometry_query_complete']);self.assertFalse(result['steps'][1]['whole_box_member'])
        self.assertEqual(result['first_complete_entry']['physics_steps'],2)
        self.assertEqual(result['escape_steps'],[3])

    def test_tilted_receiver_and_box_are_both_respected(self):
        run,spec,contract,_=fixture(centers=[[2,0,0],[.4,.4,0],[0,0,0]],planes=cube_planes(.5,math.pi/4),size=[.1,.1,.1])
        result=h.evaluate(run,spec,contract)
        self.assertFalse(result['steps'][1]['whole_box_member']);self.assertEqual(result['first_complete_entry']['physics_steps'],2)
        q=[math.cos(math.pi/8),0,0,math.sin(math.pi/8)]
        run,spec,contract,_=fixture(centers=[[2,0,0],[0,0,0]],quaternions=[[1,0,0,0],q],planes=cube_planes(.5,math.pi/4),size=[.8,.8,.8])
        self.assertTrue(h.evaluate(run,spec,contract)['membership_supplement_passed'])

    def test_no_inside_tolerance_hides_one_frame_escape(self):
        run,spec,contract,_=fixture(centers=[[2,0,0],[0,0,0],[.90000000000001,0,0],[0,0,0]])
        result=h.evaluate(run,spec,contract)
        self.assertEqual(result['escape_steps'],[2]);self.assertFalse(result['membership_supplement_passed'])
        self.assertEqual(result['steps'][2]['sign'],-1)
        self.assertLess(F(result['steps'][2]['exact_rational']),0)

    def test_integer_corner_cache_matches_naive_fraction_for_all_corners(self):
        generator=random.Random(20261101);planes=cube_planes(angle=.43);prepared=h.bounded_volume(planes)
        half=[F(.1),F(.07),F(.04)]
        for _ in range(25):
            q=[generator.uniform(-1,1) for _ in range(4)];norm=math.hypot(*q);q=[v/norm for v in q]
            sample={'positions':{'/World/box':[generator.uniform(-2,2) for _ in range(3)]},'orientations_wxyz':{'/World/box':q}}
            points,integers,denominator=h.corners(sample,'/World/box',half)
            cached=h.corner_margins(integers,denominator,prepared['planes'])
            for plane,(actual,index) in zip(prepared['planes'],cached):
                naive=[plane['b']-h.dot(plane['n'],point) for point in points]
                self.assertEqual(actual,min(naive));self.assertEqual(naive[index],actual)
            sample['orientations_wxyz']['/World/box']=[-v for v in q]
            self.assertEqual(h.corners(sample,'/World/box',half)[0],points)

    def test_unbounded_infeasible_flat_and_malformed_volumes_fail_closed(self):
        malformed=[cube_planes()[:-1],cube_planes()+[{'id':'conflict','normal_world':[1,0,0],'offset_m':-2}],
            [{**p,'offset_m':0 if p['id'].startswith('face_2') else 1} for p in cube_planes()],
            [{'id':str(i),'normal_world':[1,0,0],'offset_m':1} for i in range(4)],
            [{'id':str(i),'normal_world':[0,0,0],'offset_m':1} for i in range(4)],
            [{**p,'normal_world':[float('nan'),0,0]} for p in cube_planes()],
            [{**p,'offset_m':float('inf')} for p in cube_planes()],
            [{'id':str(i),'normal_world':[1,0,0],'offset_m':1} for i in range(33)]]
        for planes in malformed:
            with self.subTest(planes=planes):
                run,spec,contract,_=fixture(planes=planes);result=h.evaluate(run,spec,contract)
                self.assertFalse(result['geometry_query_complete']);self.assertFalse(result['membership_supplement_passed']);self.assertTrue(result['errors'])
                json.dumps(result,allow_nan=False)
        # An unbounded epigraph can have four affinely independent vertices.
        a=1/math.sqrt(3)
        planes=cube_planes()[:4]+[{'id':'floor','normal_world':[0,0,-1],'offset_m':0},
                                {'id':'slope','normal_world':[a,a,-a],'offset_m':a}]
        with self.assertRaisesRegex(ValueError,'unbounded'):h.bounded_volume(planes)

    def test_bounded_tetrahedron_is_supported_without_six_opposite_planes(self):
        a=1/math.sqrt(3)
        planes=[{'id':f'lower_{i}','normal_world':[-1 if j==i else 0 for j in range(3)],'offset_m':0} for i in range(3)]
        planes.append({'id':'upper','normal_world':[a,a,a],'offset_m':a})
        volume=h.bounded_volume(planes)
        self.assertTrue(volume['proof']['full_dimensional']);self.assertEqual(volume['proof']['vertex_count'],4)

    def test_missing_reordered_rebased_or_inconsistent_clock_rejected(self):
        for mode in ('missing','reordered','duplicate','rebased','absolute','relative','no_t0','no_velocity','pose_missing'):
            with self.subTest(mode=mode):
                run,spec,contract,_=fixture()
                if mode=='missing':run['samples'].pop(1)
                if mode=='reordered':run['samples'].reverse()
                if mode=='duplicate':run['samples'][1]['physics_steps']=1
                if mode=='rebased':
                    for sample in run['samples']:sample['physics_steps']+=10
                if mode=='absolute':run['samples'][1]['absolute_physics_step']+=1
                if mode=='relative':run['samples'][1]['simulation_time_s']+=.01
                if mode=='no_t0':run.pop('initial_observation')
                if mode=='no_velocity':run['samples'][1].pop('linear_velocities_m_s')
                if mode=='pose_missing':run['samples'][1]['positions'].clear()
                result=h.evaluate(run,spec,contract)
                self.assertFalse(result['geometry_query_complete']);self.assertFalse(result['membership_supplement_passed'])

    def test_static_root_dimension_scope_and_step_budgets_are_bound(self):
        for mutation in ('moving_receiver','conveyor','wrong_size','changed_root','time_gate','budget'):
            with self.subTest(mutation=mutation):
                run,spec,contract,_=fixture()
                if mutation=='moving_receiver':spec['objects']['receiver']['dynamic']=True
                if mutation=='conveyor':spec['objects']['receiver']['conveyor']={'speed':1}
                if mutation=='wrong_size':contract['box_size_m']=[.19,.2,.2]
                if mutation=='changed_root':spec['objects']['receiver']['position']=[.2,0,0]
                if mutation=='time_gate':contract['start_step']=2
                if mutation=='budget':
                    with patch.object(h,'MAX_STEPS',2):result=h.evaluate(run,spec,contract)
                else:result=h.evaluate(run,spec,contract)
                self.assertFalse(result['geometry_query_complete'])

    def test_membership_does_not_establish_stability_or_modeled_cavity(self):
        run,spec,contract,_=fixture(centers=[[2,0,0],[.7,0,0],[-.7,0,0],[.7,0,0]])
        result=h.evaluate(run,spec,contract)
        self.assertTrue(result['membership_supplement_passed']);self.assertFalse(result['stability_assessed'])
        self.assertEqual(result['modeled_receiver_equivalence'],'not_established_by_this_helper')
        self.assertEqual(result['between_step_continuity'],'not_established');self.assertFalse(result['formal_house_accepted'])

    def test_actual_callback_first_contact_keeps_original_counter_boundary(self):
        run,spec,contract,_=fixture()
        sample=run['samples'][1];absolute=sample['absolute_physics_step']
        record={'body_ids':['box','receiver'],'actor_paths':['/World/box','/World/receiver/part_0/Shape'],
            'collider_paths':['/World/box','/World/receiver/part_0/Shape'],'count':1,
            'first_callback_absolute_physics_step':absolute-1,'last_callback_absolute_physics_step':absolute-1,'minimum_separation_m':0}
        sample['contact_pairs']=[record];run['contacts']={'first':{'physics_step':1}}
        result=h.evaluate(run,spec,contract);contact=result['contact_observation']
        self.assertTrue(contact['complete']);self.assertEqual(contact['first_contact']['observation_step'],2)
        self.assertEqual(contact['first_contact']['raw_callbacks'][0],record)
        run['samples'][0].pop('contact_pairs');result=h.evaluate(run,spec,contract)
        self.assertTrue(result['geometry_query_complete']);self.assertFalse(result['contact_observation']['complete'])
        self.assertIsNone(result['contact_observation']['first_contact'])
        self.assertEqual(result['contact_observation']['first_observed_available_contact']['observation_step'],2)

    def test_unknown_callback_or_callback_budget_never_invents_first_contact(self):
        for mutation in ('actor','counter','unknown_field','budget'):
            with self.subTest(mutation=mutation):
                run,spec,contract,_=fixture();sample=run['samples'][0]
                record={'body_ids':['box','receiver'],'actor_paths':['/World/box','/World/receiver'],
                    'collider_paths':['/World/box','/World/receiver'],'count':1,
                    'first_callback_absolute_physics_step':4,'last_callback_absolute_physics_step':4}
                sample['contact_pairs']=[record]
                if mutation=='actor':record['actor_paths'][1]='/World/something_else'
                if mutation=='counter':record['last_callback_absolute_physics_step']=5
                if mutation=='unknown_field':record['unevaluated']=float('nan')
                if mutation=='budget':
                    with patch.object(h,'MAX_CONTACT_RECORDS',0):result=h.evaluate(run,spec,contract)
                else:result=h.evaluate(run,spec,contract)
                self.assertTrue(result['geometry_query_complete']);self.assertFalse(result['contact_observation']['complete'])
                self.assertIsNone(result['contact_observation']['first_contact']);json.dumps(result,allow_nan=False)


class HalfspaceFileProofTest(unittest.TestCase):
    def test_actual_input_output_lock_checks_and_original_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=locked_fixture(Path(tmp));result=h.verify(*args)
            self.assertTrue(result['file_integrity_verified'],result['errors']);self.assertTrue(result['membership_supplement_passed'])
            hashes=result['provenance']['original_files_sha256']
            self.assertEqual(hashes['result.json'],h.sha(args[0]/'result.json'));self.assertEqual(hashes['acceptance-case.json'],h.sha(args[1]))
            self.assertFalse(result['formal_house_accepted']);self.assertFalse(result['stability_assessed'])

    def test_tampered_original_or_static_files_rejected_without_exemptions(self):
        for target in ('result.json','spec.json','evidence-lock.json','run-lock.json','acceptance-case.json',
                       'scene.usda','asset-lock.json','runtime/simscene/worker/isaac_run.py','contract','review','case','freeze'):
            with self.subTest(target=target),tempfile.TemporaryDirectory() as tmp:
                args=locked_fixture(Path(tmp));root,case,contract,review,freeze=args[:5]
                file={'contract':contract,'review':review,'case':case,'freeze':freeze}.get(target,root/target)
                file.write_bytes(file.read_bytes()+b'\n')
                if target=='freeze':
                    # Formatting-only freeze change is itself hashed/reported;
                    # changing its code/contract pin, rather than whitespace, fails.
                    value=json.loads(file.read_text());value['files_sha256'][str(Path(h.__file__).resolve())]='0'*64
                    file.write_text(json.dumps(value))
                result=h.verify(*args)
                self.assertFalse(result['file_integrity_verified'])

    def test_post_job_freeze_and_changed_during_read_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=locked_fixture(Path(tmp));freeze=args[4]
            value=json.loads(freeze.read_text());value['frozen_at_utc']='2022-01-01T00:00:00Z';freeze.write_text(json.dumps(value))
            self.assertFalse(h.verify(*args)['file_integrity_verified'])
        with tempfile.TemporaryDirectory() as tmp:
            args=locked_fixture(Path(tmp));original=h.p._read_locked
            def changing(*values,**kw):
                data=original(*values,**kw);(args[0]/'result.json').write_bytes((args[0]/'result.json').read_bytes()+b'\n');return data
            with patch.object(h.p,'_read_locked',side_effect=changing):result=h.verify(*args)
            self.assertFalse(result['file_integrity_verified'])

    def test_step_budget_and_original_pin_fail_before_large_json_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=locked_fixture(Path(tmp))
            with patch.object(h.p,'_read_locked',side_effect=AssertionError('must not read oversized original')):
                with patch.object(h,'MAX_STEPS',2):result=h.verify(*args)
            self.assertFalse(result['geometry_query_complete']);self.assertFalse(result['file_integrity_verified'])
            bad=(*args[:5],'0'*64,args[6])
            with patch.object(h.p,'_read_locked',side_effect=AssertionError('must reject custody mismatch first')):
                self.assertFalse(h.verify(*bad)['file_integrity_verified'])

    def test_new_cli_rejects_escape_and_keeps_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);args=locked_fixture(root,centers=[[2,0,0],[0,0,0],[1.2,0,0],[0,0,0]])
            argv=[sys.executable,str(Path(h.__file__).resolve())]
            for name,value in zip(('run','case','contract','static-review','freeze','run-lock-sha256','evidence-lock-sha256'),args):argv.extend(['--'+name,str(value)])
            output=root/'observation.json';argv.extend(['--output',str(output)])
            completed=subprocess.run(argv,text=True,capture_output=True)
            self.assertEqual(completed.returncode,1,completed.stderr)
            result=json.loads(output.read_text());self.assertTrue(result['geometry_query_complete']);self.assertFalse(result['membership_supplement_passed'])
            self.assertEqual(result['first_complete_entry']['physics_steps'],1);self.assertEqual(result['escape_steps'],[2])
            original=output.read_bytes();subprocess.run(argv,text=True,capture_output=True);self.assertEqual(output.read_bytes(),original)


if __name__=='__main__':unittest.main()
