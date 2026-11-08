import copy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from simscene.verification.handoff_chain import evaluate, validate_case, verify_run, verify_selection


def fixture():
    """Synthetic complete telemetry for CPU checker tests, never SDK evidence."""
    tiles=['/World/d0','/World/d1','/World/d2'];source='/World/source_box/Asset/Body';ball='/World/terminal_ball'
    names=['source_box','generated_guide','receiver'];profiles=['rigid_prop_v1','static_fixture_v1','container_v1']
    case={'schema':'simscene.handoff_chain.v1','schema_version':1,'steps':180,'source_object_id':'source_box','source_body':source,
          'ball_object_id':'terminal_ball','ball_body':ball,'tile_object_ids':['d0','d1','d2'],'tiles':tiles,'negative_removed_tile':tiles[1],
          'guide_object_id':'generated_guide','guide_actor':'/World/generated_guide/Asset/Proxy',
          'receiver_object_id':'receiver','receiver_floor_actor':'/World/receiver/Asset/Container/floor',
          'source_min_travel_m':.2,'ball_min_travel_m':.1,'ball_radius_m':.035,
          'initial_vertical_cos_min':.995,'activation_vertical_cos_max':math.cos(.2),'final_vertical_cos_max':.6,
          'target_bounds':{'min':[.4,-.15,0.],'max':[.8,.15,.2]},'trajectory_bounds':{'min':[-.75,-.3,-.01],'max':[1.,.3,.75]},
          'container_floor_tolerance_m':0.,'prepared_manifest_sha256s':dict(zip(names,['a'*64,'b'*64,'c'*64])),
          'source_refs':{n:{'source_id':'cpu-fixture','asset_id':n,'revision':'d'*40} for n in names},'prepared_profiles':dict(zip(names,profiles))}
    frames=[];zero=100
    contacts={8:(source,tiles[0]),18:(tiles[0],tiles[1]),28:(tiles[1],tiles[2]),35:(tiles[2],ball),
              45:(ball,case['guide_actor']),50:(ball,case['receiver_floor_actor'])}
    for step in range(181):
        progress=max(0.,min(1.,(step-35)/10))
        source_position=[-.5+.3*min(1.,step/10),0.,.4]
        ball_position=[.27+.33*progress,0.,.25-(.25-.0357)*progress]
        positions={source:source_position,ball:ball_position};orientations={source:[1.,0.,0.,0.],ball:[1.,0.,0.,0.]}
        bounds={'source_box':{'min':[source_position[0]-.05,-.03,.34],'max':[source_position[0]+.05,.03,.46]},
                'terminal_ball':{'min':[ball_position[0]-.05,-.05,ball_position[2]-.05],'max':[ball_position[0]+.05,.05,ball_position[2]+.05]}}
        for i,path in enumerate(tiles):
            angle=min(math.pi/2,max(0.,(step-(10+i*10)+1)*.12));q=[math.cos(angle/2),0.,math.sin(angle/2),0.]
            positions[path]=[i*.085,0.,.07];orientations[path]=q
            bounds['d'+str(i)]={'min':[i*.085-.01,-.04,0.],'max':[i*.085+.01,.04,.14]}
        frame={'physics_steps':step,'simulation_time_s':step/60,'positions':positions,'orientations_wxyz':orientations,'bounds':bounds,'followers':{}}
        frame['contact_pairs']=[]
        if step in contacts:
            frame['contact_pairs']=[{'actor_paths':list(contacts[step]),'count':1,'first_callback_absolute_physics_step':zero+step,'last_callback_absolute_physics_step':zero+step}]
        frames.append(frame)
    run={'initial_observation':frames[0],'samples':frames[1:],'actual_physics_steps':180,'requested_physics_steps':180,
         'simulation_time_s':3.,'observation_interval_steps':1,'run_zero_absolute_physics_step':zero,'partial':False,
         'samples_truncated':False,'contacts_truncated':False,'contact_geometry_incomplete':False,'followers':{},
         'body_bindings':{'source_box':{'motion_body':source,'profile_id':'rigid_prop_v1'}}}
    return run,case


def spec_fixture(case):
    objects={}
    for name,profile in case['prepared_profiles'].items():
        objects[name]={'kind':'asset','asset_path':'/fixture/'+name+'/main.usda',
                       'asset_binding':{'manifest_path':'/fixture/'+name+'/manifest.json','manifest_sha256':case['prepared_manifest_sha256s'][name]},
                       'dynamic':profile=='rigid_prop_v1'}
    objects['receiver']['position']=[.6,0.,0.]
    objects['terminal_ball']={'kind':'sphere','size':[.07]*3,'dynamic':True,'collision':True}
    for name in case['tile_object_ids']:objects[name]={'kind':'box','size':[.018,.08,.14],'dynamic':True,'collision':True}
    return {'objects':objects,'observation':{'sample_interval_steps':1,'strict_start':True,'record_contact_pairs':True}}


def negative(run,case):
    run=copy.deepcopy(run)
    for frame in [run['initial_observation']]+run['samples']:
        for key in ('positions','orientations_wxyz'):frame[key].pop('/World/d1')
        frame['bounds'].pop('d1');frame['orientations_wxyz']['/World/d2']=[1.,0.,0.,0.]
        frame['positions'][case['ball_body']]=copy.deepcopy(run['initial_observation']['positions'][case['ball_body']])
        frame['contact_pairs']=[p for p in frame['contact_pairs'] if set(p['actor_paths'])=={case['source_body'],'/World/d0'}]
    return run


class HandoffTests(unittest.TestCase):
    def test_complete_contacts_order_bounds_and_settling_pass(self):
        run,case=fixture();result=evaluate(run,case)
        self.assertTrue(result['passed'],result)
        self.assertEqual(result['measurements']['ball_activation_step'],39)
        self.assertIn('exact_rotation_invariant',result['measurements']['sphere_bounds_method'])
        # USD's rotated bounding cube can overestimate sphere extent. The
        # exact sphere geometry remains contained using measured center/radius.
        run['samples'][-1]['bounds']['terminal_ball']['min'][2]=-.02
        self.assertTrue(evaluate(run,case)['passed'])

    def test_missing_middle_requires_upstream_progress_and_quiet_downstream(self):
        run,case=fixture();control=negative(run,case)
        self.assertTrue(evaluate(control,case,'missing_middle')['passed'])
        control['samples'][50]['orientations_wxyz']['/World/d2']=[math.sqrt(.5),0.,math.sqrt(.5),0.]
        self.assertFalse(evaluate(control,case,'missing_middle')['passed'])
        control=negative(run,case)
        for frame in [control['initial_observation']]+control['samples']:frame['orientations_wxyz']['/World/d0']=[1.,0.,0.,0.]
        self.assertFalse(evaluate(control,case,'missing_middle')['passed'])

    def test_timer_or_prefix_contacts_and_out_of_order_handoff_fail(self):
        for mutation in ('prefix','timer','order','early_ball','guide_initial_only','future_callback'):
            run,case=fixture()
            if mutation=='prefix':run['samples'][7]['contact_pairs'][0]['actor_paths'][0]=case['source_body']+'/Other'
            elif mutation=='timer':run['samples'][7]['contact_pairs']=[]
            elif mutation=='order':run['samples'][17]['contact_pairs'][0]['first_callback_absolute_physics_step']=run['samples'][17]['contact_pairs'][0]['last_callback_absolute_physics_step']=125
            elif mutation=='early_ball':run['samples'][10]['positions'][case['ball_body']][0]=.5
            elif mutation=='future_callback':run['samples'][7]['contact_pairs'][0]['first_callback_absolute_physics_step']=run['samples'][7]['contact_pairs'][0]['last_callback_absolute_physics_step']=109
            else:
                pair=run['samples'][44]['contact_pairs'].pop();pair['first_callback_absolute_physics_step']=pair['last_callback_absolute_physics_step']=102;run['samples'][1]['contact_pairs'].append(pair)
            with self.subTest(mutation=mutation):self.assertFalse(evaluate(run,case)['passed'])

    def test_partial_missing_steps_unbounded_source_and_uncaught_sphere_are_failures(self):
        for mutation in ('partial','samples_truncated','contacts_truncated','contact_geometry_incomplete','missing','escape','receiver','sphere','wrongbody'):
            run,case=fixture()
            if mutation in ('partial','samples_truncated','contacts_truncated','contact_geometry_incomplete'):run[mutation]=True
            elif mutation=='missing':del run['samples'][10]
            elif mutation=='escape':run['samples'][10]['bounds']['source_box']['max'][1]=1.
            elif mutation=='receiver':run['samples'][49]['contact_pairs']=[]
            elif mutation=='sphere':run['samples'][-1]['positions'][case['ball_body']][0]=.79
            else:run['body_bindings']['source_box']['motion_body']='/World/source_box'
            with self.subTest(mutation=mutation):self.assertFalse(evaluate(run,case)['passed'])

    def test_unrelated_declared_cabinet_drive_allowed_chain_control_is_not(self):
        run,case=fixture()
        for frame in [run['initial_observation']]+run['samples']:frame['mechanisms']={'cabinet':{'runtime_targets':{'main':1.}}}
        self.assertTrue(evaluate(run,case)['passed'])
        run['samples'][1]['mechanisms']['terminal_ball']={}
        self.assertFalse(evaluate(run,case)['passed'])
        run,case=fixture();run['followers']={'robot':{}}
        self.assertFalse(evaluate(run,case)['passed'])

    def test_schema_requires_all_source_pins_distinct_actors_and_interior_control(self):
        for mutation in ('pin','profile','actor','control','radius','target'):
            _,case=fixture()
            if mutation=='pin':case['prepared_manifest_sha256s'].pop('receiver')
            elif mutation=='profile':case['prepared_profiles']['receiver']='rigid_prop_v1'
            elif mutation=='actor':case['tiles'][1]=case['tiles'][0]
            elif mutation=='control':case['negative_removed_tile']=case['tiles'][0]
            elif mutation=='radius':case['ball_radius_m']=.1
            else:case['target_bounds']['max'][0]=2.
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):validate_case(case)

    def test_selection_pins_exact_source_profile_sphere_and_receiver_geometry(self):
        _,case=fixture();spec=spec_fixture(case)
        def manifest(binding,**kwargs):
            name=Path(binding['manifest_path']).parent.name;profile=case['prepared_profiles'][name]
            if name=='source_box':body={'main':{'relative_prim_path':'Body','collider_relative_prim_paths':['Body/Mesh']}}
            elif name=='generated_guide':body={'main':{'relative_prim_path':'Proxy','collider_relative_prim_paths':['Proxy']}}
            else:body={'main':{'relative_prim_path':'Container','collider_relative_prim_paths':['Container/floor']}}
            return {'profile_id':profile,'source_ref':case['source_refs'][name],'body_map':body,
                    'parameters':{'container_proxy':{'interior_bounds':{'min':[-.2,-.15,0.],'max':[.2,.15,.2]}}}}
        with patch('simscene.physics_binding.validate_asset_binding',side_effect=manifest):
            self.assertTrue(verify_selection(spec,case))
            for mutation in ('source','radius','cavity','guide','missing'):
                s=copy.deepcopy(spec);c=copy.deepcopy(case)
                if mutation=='source':c['source_refs']['source_box']['revision']='e'*40
                elif mutation=='radius':s['objects']['terminal_ball']['size']=[.08]*3
                elif mutation=='cavity':c['target_bounds']['max'][0]=.81
                elif mutation=='missing':s['objects'].pop('d0')
                else:c['guide_actor']+='/Other'
                with self.subTest(mutation=mutation),self.assertRaises(ValueError):verify_selection(s,c)

    def test_saved_locks_case_hash_and_only_middle_deleted_control(self):
        from simscene.evidence_integrity import seal
        run,case=fixture();control=negative(run,case);spec=spec_fixture(case)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);positive=root/'positive';negative_root=root/'negative';positive.mkdir();negative_root.mkdir()
            for directory,record in ((positive,run),(negative_root,control)):
                selected=copy.deepcopy(spec)
                if directory==negative_root:selected['objects'].pop('d1')
                (directory/'spec.json').write_text(json.dumps(selected));(directory/'result.json').write_text(json.dumps(record))
                (directory/'acceptance-case.json').write_text(json.dumps(case));digest=hashlib.sha256((directory/'acceptance-case.json').read_bytes()).hexdigest()
                lock={'acceptance_case_file':'acceptance-case.json','acceptance_case_sha256':digest,'body_bindings':record['body_bindings'],
                      'physics_device':'cpu','physics_dt_s':1/60,'runtime_version':'CPU-fixture','requested_physics_steps':180,'seed':None}
                (directory/'run-lock.json').write_text(json.dumps(lock));(directory/'runtime').mkdir();(directory/'runtime/worker.py').write_text('# frozen CPU fixture\n');seal(directory)
            with patch('simscene.verification.handoff_chain._selection',return_value=True),patch('simscene.run_integrity.verify',return_value={'passed':True}):
                self.assertTrue(verify_run(positive)['passed'])
                self.assertTrue(verify_run(negative_root,mode='missing_middle',reference_directory=positive)['passed'])
                changed_spec=json.loads((negative_root/'spec.json').read_text());changed_spec['presentation']={'profile':'changed'}
                (negative_root/'spec.json').write_text(json.dumps(changed_spec))
                self.assertFalse(verify_run(negative_root,mode='missing_middle',reference_directory=positive)['passed'])
                changed_spec.pop('presentation');(negative_root/'spec.json').write_text(json.dumps(changed_spec))
                (negative_root/'runtime/worker.py').write_text('# changed\n')
                self.assertFalse(verify_run(negative_root,mode='missing_middle',reference_directory=positive)['passed'])
                (positive/'result.json').write_text(json.dumps(dict(run,seed=1)))
                self.assertFalse(verify_run(positive)['passed'])
            (positive/'acceptance-case.json').write_text(json.dumps(dict(case,steps=181)))
            with self.assertRaisesRegex(ValueError,'changed'):verify_run(positive)

    def test_embedded_gallery_control_pins_whole_document_and_requires_unambiguous_component(self):
        from simscene.evidence_integrity import seal
        from simscene.verification.handoff_chain import _component
        run,case=fixture();control=negative(run,case);spec=spec_fixture(case)
        document={'schema':'simscene.asset_gallery.v1','schema_version':1,'components':[{'id':'transfer','case':case}],'contact_sequences':[]}
        with tempfile.TemporaryDirectory() as tmp:
            positive=Path(tmp)/'positive';negative_root=Path(tmp)/'negative'
            for directory,record in ((positive,run),(negative_root,control)):
                directory.mkdir();selected=copy.deepcopy(spec)
                if directory==negative_root:selected['objects'].pop('d1')
                (directory/'spec.json').write_text(json.dumps(selected));(directory/'result.json').write_text(json.dumps(record))
                (directory/'acceptance-case.json').write_text(json.dumps(document))
                digest=hashlib.sha256((directory/'acceptance-case.json').read_bytes()).hexdigest()
                (directory/'run-lock.json').write_text(json.dumps({'acceptance_case_file':'acceptance-case.json','acceptance_case_sha256':digest,'body_bindings':record['body_bindings']}))
                (directory/'runtime').mkdir();(directory/'runtime/worker.py').write_text('# identical\n');seal(directory)
            with patch('simscene.verification.handoff_chain._selection',return_value=True),patch('simscene.run_integrity.verify',return_value={'passed':True}):
                result=verify_run(positive);self.assertTrue(result['passed']);self.assertEqual(result['embedded_component_id'],'transfer')
                self.assertTrue(verify_run(negative_root,mode='missing_middle',reference_directory=positive)['passed'])
                with self.assertRaisesRegex(ValueError,'unambiguous'):verify_run(positive,component_id='wrong')
                # An external standalone component file cannot replace the
                # pinned whole gallery document even if its payload matches.
                path=Path(tmp)/'component.json';path.write_text(json.dumps(case))
                with self.assertRaisesRegex(ValueError,'changed'):verify_run(positive,case_path=path)
        duplicate=copy.deepcopy(document);duplicate['components'].append({'id':'transfer2','case':copy.deepcopy(case)})
        with self.assertRaisesRegex(ValueError,'unambiguous'):_component(duplicate,None)
        self.assertEqual(_component(duplicate,'transfer2')[1],'transfer2')

    def test_render_only_control_requires_frozen_opt_in_and_keeps_physics_exact(self):
        from simscene.verification.handoff_chain import _render_comparison
        _,case=fixture();p=spec_fixture(case);n=copy.deepcopy(p)
        p['objects']['overview']={'kind':'camera','position':[1.,2.,3.],'camera':{'resolution':[960,540]}}
        before=copy.deepcopy(p);after=copy.deepcopy(n)
        strict=_render_comparison(before,after,case,[])
        self.assertEqual(strict['objects'],{});self.assertNotEqual(before,after)
        case['control_render_policy']='allow_static_render_differences'
        before=copy.deepcopy(p);after=copy.deepcopy(n)
        with patch('simscene.verification.handoff_chain._render_schema_proof',return_value=True):
            proof=_render_comparison(before,after,case,[])
        self.assertTrue(proof['checked_no_physics_schemas']);self.assertIn('overview',proof['objects']);self.assertEqual(before,after)
        before=copy.deepcopy(p);after=copy.deepcopy(n);after['objects']['d0']['mass_kg']=.5
        with patch('simscene.verification.handoff_chain._render_schema_proof',return_value=True):_render_comparison(before,after,case,[])
        self.assertNotEqual(before,after)
        # Camera disguise cannot remove a physical chain actor from comparison.
        before=copy.deepcopy(p);after=copy.deepcopy(n);before['objects']['d0']={'kind':'camera'};after['objects'].pop('d0')
        with patch('simscene.verification.handoff_chain._render_schema_proof',return_value=True):_render_comparison(before,after,case,[])
        self.assertIn('d0',before['objects'])
        with patch('simscene.verification.handoff_chain._render_schema_proof',return_value=False):
            proof=_render_comparison(copy.deepcopy(p),copy.deepcopy(n),case,[])
        self.assertFalse(proof['checked_no_physics_schemas'])

    def test_render_delta_usd_subtree_with_collider_is_not_render_only(self):
        from simscene.verification.handoff_chain import _render_schema_proof
        try:from pxr import Usd,UsdGeom,UsdPhysics
        except ImportError:self.skipTest('CPU OpenUSD required')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);stage=Usd.Stage.CreateNew(str(root/'scene.usda'));UsdGeom.Xform.Define(stage,'/World')
            camera=UsdGeom.Camera.Define(stage,'/World/overview');stage.GetRootLayer().Save()
            self.assertTrue(_render_schema_proof([root],['overview']))
            UsdPhysics.CollisionAPI.Apply(camera.GetPrim());stage.GetRootLayer().Save()
            self.assertFalse(_render_schema_proof([root],['overview']))
