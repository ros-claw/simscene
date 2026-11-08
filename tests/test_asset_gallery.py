"""Synthetic same-run measurements; no physics, SDK or network execution."""
import copy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from simscene.verification import asset_gallery as gallery
from simscene.evidence_integrity import seal
from test_preparation_articulation import smoke_fixture
from test_rigid_asset_smoke import fixture as rigid_fixture


def fixture():
    run,articulated=smoke_fixture();_,rigid=rigid_fixture()
    body=rigid['objects']['item']['motion_body'];run['run_zero_absolute_physics_step']=100
    run['body_bindings']['item']={k:rigid['objects']['item'][k] for k in ('motion_body','contact_bodies','visual_roots')}
    for frame in [run['initial_observation']]+run['samples']:
        z=max(.2,1.-frame['simulation_time_s']*1.6)
        frame['positions'][body]=[0.,0.,z];frame['orientations_wxyz'][body]=[1.,0.,0.,0.]
        frame['bounds']={'item':{'min':[-.1,-.1,z-.1],'max':[.1,.1,z+.1]}}
        frame['contact_pairs']=[]
        actor={20:'/World/ramp',40:'/World/baffle',90:'/World/support'}.get(frame['physics_steps'])
        if actor:frame['contact_pairs'].append({'actor_paths':[body,actor],'count':1,
            'first_callback_absolute_physics_step':100+frame['physics_steps'],
            'last_callback_absolute_physics_step':100+frame['physics_steps']})
    source={'source_id':'fixture-source','asset_id':'selected-probe','revision':'d'*40}
    rigid.update(source_ref=source,prepared_manifest_sha256='a'*64)
    articulated['objects']['valve'].update(prepared_manifest_sha256='b'*64,source_ref=dict(source,asset_id='native-hinge'))
    container=copy.deepcopy(rigid);container['schema']='simscene.container_asset_smoke.v1'
    container['container']={'object_id':'receiver','prepared_manifest_sha256':'c'*64,'source_ref':dict(source,asset_id='open-container'),
        'interior_bounds':{'min':[-.5,-.5,0.],'max':[.5,.5,.5]},
        'opening':{'min_xy':[-.5,-.5],'max_xy':[.5,.5],'z_m':.5}}
    case={'schema':gallery.SCHEMA,'schema_version':1,'components':[
        {'id':'rigid','case':rigid},{'id':'hinge','case':articulated},{'id':'container','case':container}],
        'contact_sequences':[{'id':'ramp-then-baffle','subject_body':body,'actors':['/World/ramp','/World/baffle'],'max_gap_s':.5}]}
    return run,case

def handoff_gallery_fixture():
    from test_handoff_chain import fixture as chain_fixture,spec_fixture
    run,case=fixture();chain,embedded=chain_fixture()
    embedded['steps']=run['actual_physics_steps']
    embedded['prepared_manifest_sha256s']={name:str(i)*64 for i,name in enumerate(embedded['prepared_manifest_sha256s'],1)}
    case['components'][2]['case']['container']['object_id']='probe_receiver'
    frames=[run['initial_observation']]+run['samples'];other=[chain['initial_observation']]+chain['samples']
    for step,frame in enumerate(frames):
        value=other[min(step,len(other)-1)]
        for key in ('positions','orientations_wxyz','bounds'):frame[key].update(copy.deepcopy(value[key]))
        if step<len(other):frame['contact_pairs'].extend(copy.deepcopy(value['contact_pairs']))
    run['body_bindings'].update(chain['body_bindings'])
    case['components'].append({'id':'handoff','case':embedded})
    case['contact_sequences'].append({'id':'ball-guide-receiver','subject_body':embedded['ball_body'],
        'actors':[embedded['guide_actor'],embedded['receiver_floor_actor']],'max_gap_s':.5})
    return run,case,spec_fixture(embedded)



class GalleryTests(unittest.TestCase):
    def test_three_original_checkers_share_one_unmodified_run_and_embedded_cases(self):
        run,case=fixture();oldrun=copy.deepcopy(run);oldcase=copy.deepcopy(case)
        with (patch.object(gallery.rigid,'verify_run',side_effect=AssertionError('no component run directories')),
             patch.object(gallery.articulated,'verify_run',side_effect=AssertionError('no component run directories')),
             patch.object(gallery.container,'verify_run',side_effect=AssertionError('no component run directories'))):
            result=gallery.evaluate(run,case)
        self.assertTrue(result['passed'],result)
        self.assertEqual(set(result['components']),{'rigid','hinge','container'})
        self.assertEqual(result['contact_sequences']['ramp-then-baffle']['callback_physics_steps'],[20,40])
        self.assertIn('necessary causality',result['scope'])
        self.assertFalse(result['case_pinned_to_run'])
        self.assertEqual(run,oldrun);self.assertEqual(case,oldcase)

    def test_strict_bounded_finite_and_explicit_source_selection_contract(self):
        _,case=fixture()
        mutations=[lambda c:c.update(schema_version=True),lambda c:c.update(actions=[]),
            lambda c:c['components'].append(copy.deepcopy(c['components'][0])),
            lambda c:c['components'][0].update(extra='ignored'),
            lambda c:c['components'][0]['case'].pop('source_ref'),
            lambda c:c['components'][0]['case'].update(prepared_manifest_sha256='not-sha'),
            lambda c:c['components'][1]['case']['objects']['valve']['source_ref'].update(revision='main'),
            lambda c:c['components'][2]['case']['container'].pop('source_ref'),
            lambda c:c['contact_sequences'][0].update(max_gap_s=float('nan')),
            lambda c:c['contact_sequences'][0].update(subject_body='/World/unmapped'),
            lambda c:c['contact_sequences'][0].update(actors=['/World/ramp']),
            lambda c:c['contact_sequences'][0].update(id='rigid'),
            lambda c:c.update(components=[dict(c['components'][0],id=str(i)) for i in range(17)])]
        for mutation in mutations:
            value=copy.deepcopy(case);mutation(value)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):gallery.validate_case(value)

    def test_truncation_missing_frames_wrong_body_and_individual_physical_failure_reject(self):
        run,case=fixture()
        for key in ('partial','samples_truncated','contacts_truncated','contact_geometry_incomplete'):
            bad=copy.deepcopy(run);bad[key]=True
            with self.subTest(key=key):self.assertFalse(gallery.evaluate(bad,case)['passed'])
        bad=copy.deepcopy(run);del bad['samples'][100]
        self.assertFalse(gallery.evaluate(bad,case)['passed'])
        bad=copy.deepcopy(run);bad['body_bindings']['item']['motion_body']='/World/imposter'
        self.assertFalse(gallery.evaluate(bad,case)['passed'])
        bad=copy.deepcopy(run);bad['samples'][-1]['bounds']['item']['max'][0]=2.
        self.assertFalse(gallery.evaluate(bad,case)['passed'])

    def test_contact_order_gap_exact_paths_and_no_future_callbacks(self):
        run,case=fixture()
        case['contact_sequences'][0]['actors'].reverse()
        self.assertFalse(gallery.evaluate(run,case)['passed'])
        run,case=fixture();case['contact_sequences'][0]['max_gap_s']=.1
        self.assertFalse(gallery.evaluate(run,case)['passed'])
        run,case=fixture();run['samples'][39]['contact_pairs'][0]['actor_paths'][1]='/World/baffle/Fake'
        self.assertFalse(gallery.evaluate(run,case)['passed'])
        run,case=fixture();pair=run['samples'][39]['contact_pairs'][0]
        pair.update(first_callback_absolute_physics_step=160,last_callback_absolute_physics_step=160)
        self.assertFalse(gallery.evaluate(run,case)['passed'])

    def test_sequence_uses_later_actual_contact_when_earliest_cannot_meet_gap(self):
        run,case=fixture();sequence=case['contact_sequences'][0];sequence['max_gap_s']=.1
        body=sequence['subject_body']
        run['samples'][37]['contact_pairs']=[{'actor_paths':[body,'/World/ramp'],'count':1,
            'first_callback_absolute_physics_step':138,'last_callback_absolute_physics_step':138}]
        result=gallery.evaluate(run,case)
        self.assertTrue(result['passed'])
        self.assertEqual(result['contact_sequences']['ramp-then-baffle']['callback_physics_steps'],[38,40])

    def test_fourth_component_uses_same_full_run_and_original_handoff_evaluator(self):
        run,case,_=handoff_gallery_fixture();unchanged=copy.deepcopy(case)
        with patch.object(gallery.handoff,'evaluate',wraps=gallery.handoff.evaluate) as called:
            result=gallery.evaluate(run,case)
        self.assertTrue(result['passed'],result)
        self.assertEqual(len(result['components']),4)
        self.assertIs(called.call_args.args[0],run)
        self.assertIs(called.call_args.args[1],case['components'][-1]['case'])
        self.assertEqual(case,unchanged)
        self.assertEqual(result['contact_sequences']['ball-guide-receiver']['callback_physics_steps'],[45,50])
        wrong=copy.deepcopy(run);wrong['samples'][44]['contact_pairs']=[]
        self.assertFalse(gallery.evaluate(wrong,case)['passed'])

    def test_handoff_gallery_pins_all_sources_and_actual_receiver_geometry(self):
        run,case,spec=handoff_gallery_fixture();embedded=case['components'][-1]['case']
        refs={'item':case['components'][0]['case']['source_ref'],
              'valve':case['components'][1]['case']['objects']['valve']['source_ref'],
              'probe_receiver':case['components'][2]['case']['container']['source_ref']}
        manifests={}
        for name,profile,digest in [('item','rigid_prop_v1','a'*64),('valve','articulated_prop_v1','b'*64),('probe_receiver','container_v1','c'*64)]:
            spec['objects'][name]={'kind':'asset','dynamic':name!='probe_receiver','asset_path':'/fixture/'+name+'/main.usda',
                'asset_binding':{'manifest_path':'/fixture/'+name+'/manifest.json','manifest_sha256':digest}}
            manifests[name]={'profile_id':profile,'source_ref':refs[name]}
        for name,profile in embedded['prepared_profiles'].items():
            if name==embedded['source_object_id']:body={'main':{'relative_prim_path':'Body','collider_relative_prim_paths':['Body/Mesh']}}
            elif name==embedded['guide_object_id']:body={'main':{'relative_prim_path':'Proxy','collider_relative_prim_paths':['Proxy']}}
            else:body={'main':{'relative_prim_path':'Container','collider_relative_prim_paths':['Container/floor']}}
            manifests[name]={'profile_id':profile,'source_ref':embedded['source_refs'][name],'body_map':body,
                'parameters':{'container_proxy':{'interior_bounds':{'min':[-.2,-.15,0.],'max':[.2,.15,.2]}}}}
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name,value in [('result.json',run),('spec.json',spec),('acceptance-case.json',case)]:
                (root/name).write_text(json.dumps(value))
            (root/'run-lock.json').write_text(json.dumps({'acceptance_case_file':'acceptance-case.json',
                'acceptance_case_sha256':hashlib.sha256((root/'acceptance-case.json').read_bytes()).hexdigest(),'body_bindings':run['body_bindings']}))
            seal(root)
            def manifest(binding,**kwargs):return manifests[Path(binding['manifest_path']).parent.name]
            with patch('simscene.physics_binding.validate_asset_binding',side_effect=manifest),patch('simscene.run_integrity.verify',return_value={'passed':True}) as inputs:
                self.assertTrue(gallery.verify_run(root)['passed'])
                self.assertEqual(inputs.call_count,1)
                original=copy.deepcopy(manifests['generated_guide'])
                manifests['generated_guide']['source_ref']={'source_id':'imposter','asset_id':'guide','revision':'d'*40}
                result=gallery.verify_run(root)
                self.assertFalse(result['passed']);self.assertFalse(result['checks']['all_prepared_selections_pinned'])
                manifests['generated_guide']=original
                spec['objects']['terminal_ball']['size']=[.08]*3
                (root/'spec.json').write_text(json.dumps(spec))
                result=gallery.verify_run(root)
                self.assertFalse(result['passed']);self.assertIn('uniform sphere',result['errors'][0])

    def test_handoff_requires_exact_actual_object_pin_maps_and_declared_profiles(self):
        source={'source_id':'gso-glb','asset_id':'source_box','revision':'d'*40}
        case={'source_object_id':'unit-source','guide_object_id':'unit-guide','receiver_object_id':'unit-receiver',
            'prepared_manifest_sha256s':{'unit-source':'a'*64,'unit-guide':'b'*64,'unit-receiver':'c'*64},
            'source_refs':{'unit-source':source,'unit-guide':dict(source,source_id='local-sand3d',asset_id='guide_plate_v1'),
                'unit-receiver':dict(source,source_id='local-sand3d',asset_id='open_receiver_v1')},
            'prepared_profiles':{'unit-source':'rigid_prop_v1','unit-guide':'static_fixture_v1','unit-receiver':'container_v1'}}
        selections=gallery._handoff_selections(case)
        self.assertEqual([row[0] for row in selections],['unit-source','unit-guide','unit-receiver'])
        self.assertEqual([row[3] for row in selections],[True,False,False])
        for mutation in (lambda c:c['source_refs'].pop('unit-receiver'),
                lambda c:c['source_refs'].update(receiver=source),
                lambda c:c['source_refs']['unit-source'].update(revision='main'),
                lambda c:c['prepared_manifest_sha256s'].update({'unit-guide':'wrong'}),
                lambda c:c['prepared_profiles'].update({'unit-guide':'visual_prop_v1'})):
            bad=copy.deepcopy(case);mutation(bad)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):gallery._handoff_selections(bad)

    def persist(self,root):
        run,case=fixture();objects={};manifests={}
        for name,digest,profile,source in [('item','a'*64,'rigid_prop_v1',case['components'][0]['case']['source_ref']),
            ('valve','b'*64,'articulated_prop_v1',case['components'][1]['case']['objects']['valve']['source_ref']),
            ('receiver','c'*64,'container_v1',case['components'][2]['case']['container']['source_ref'])]:
            objects[name]={'kind':'asset','dynamic':name!='receiver','asset_path':str(root/(name+'.usda')),
                'asset_binding':{'manifest_path':str(root/(name+'-manifest.json')),'manifest_sha256':digest}}
            manifests[str(root/(name+'-manifest.json'))]={'profile_id':profile,'source_ref':source}
        for name,value in [('spec.json',{'objects':objects}),('result.json',run),('acceptance-case.json',case)]:
            (root/name).write_text(json.dumps(value))
        lock={'acceptance_case_file':'acceptance-case.json','acceptance_case_sha256':hashlib.sha256((root/'acceptance-case.json').read_bytes()).hexdigest(),
            'body_bindings':run['body_bindings']}
        (root/'run-lock.json').write_text(json.dumps(lock));seal(root)
        return manifests

    def test_whole_case_locks_once_all_selections_and_no_case_rewrites(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);manifests=self.persist(root)
            before={p.name:p.read_bytes() for p in root.iterdir()}
            def bound(binding,**kwargs):return manifests[binding['manifest_path']]
            with (patch('simscene.physics_binding.validate_asset_binding',side_effect=bound) as bindings,
                 patch('simscene.run_integrity.verify',return_value={'passed':True}) as inputs,
                 patch('simscene.evidence_integrity.verify',wraps=__import__('simscene.evidence_integrity',fromlist=['verify']).verify) as evidence):
                result=gallery.verify_run(root)
            self.assertTrue(result['passed'],result)
            self.assertEqual(inputs.call_count,1);self.assertEqual(evidence.call_count,1)
            self.assertEqual(bindings.call_count,3)
            self.assertEqual(before,{p.name:p.read_bytes() for p in root.iterdir()})

    def test_same_caller_case_hash_and_source_profile_manifest_and_body_locks_reject(self):
        for change in ('source','profile','manifest','body','extra_body','evidence','input','partial_evidence'):
            with self.subTest(change=change),TemporaryDirectory() as tmp:
                root=Path(tmp);manifests=self.persist(root)
                if change=='source':manifests[str(root/'valve-manifest.json')]['source_ref']={'wrong':'selection'}
                if change=='profile':manifests[str(root/'receiver-manifest.json')]['profile_id']='rigid_prop_v1'
                if change=='manifest':
                    spec=json.loads((root/'spec.json').read_text());spec['objects']['item']['asset_binding']['manifest_sha256']='f'*64
                    (root/'spec.json').write_text(json.dumps(spec))
                if change in ('body','extra_body'):
                    run=json.loads((root/'result.json').read_text())
                    if change=='body':run['body_bindings']['item']['motion_body']='/World/substitute'
                    else:run['body_bindings']['uncovered']={}
                    (root/'result.json').write_text(json.dumps(run));seal(root)
                if change=='evidence':(root/'result.json').write_text((root/'result.json').read_text()+' ')
                with patch('simscene.physics_binding.validate_asset_binding',side_effect=lambda b,**kw:manifests[b['manifest_path']]),patch('simscene.run_integrity.verify',return_value={'passed':change!='input'}):
                    if change=='partial_evidence':
                        with patch('simscene.evidence_integrity.verify',return_value={'passed':True,'partial':True}):result=gallery.verify_run(root)
                    else:result=gallery.verify_run(root)
                self.assertFalse(result['passed'])
        with TemporaryDirectory() as tmp:
            root=Path(tmp);self.persist(root);other=root/'different.json';other.write_text('{}')
            with self.assertRaisesRegex(ValueError,'whole frozen run case'):gallery.verify_run(root,other)
            (root/'acceptance-case.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'whole frozen run case'):gallery.verify_run(root)


if __name__=='__main__':unittest.main()
