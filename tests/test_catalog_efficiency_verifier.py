import json
import math
from pathlib import Path
import tempfile
import unittest
from experiments.catalog_efficiency_verifier import equal, physical, structural, projected_visibility, evaluate, source_checks


class EfficiencyVerifierTests(unittest.TestCase):
    def fixture(self):
        spec={'objects':{'ball':{'kind':'sphere','size':[.06]*3,'position':[0,0,.3],'dynamic':True,'collision':True,'mass_kg':.12},'support':{'kind':'box','dynamic':False,'collision':True}}}
        acceptance={'steps':120,'physics_hz':60,'seed':42,'payloads':{'ball':{'target_bounds':{'min':[-1,-1,-.005],'max':[1,1,1]},'support_object_ids':['support'],'min_drop_m':.1,'settle_seconds':1}}}
        frames=[]
        for step in range(121):
            z=max(.03,.3-.027*step)
            frames.append({'physics_steps':step,'simulation_time_s':step/60,'positions':{'/World/ball':[0,0,z]},'orientations_wxyz':{'/World/ball':[1,0,0,0]},'contact_pairs':[{'actor_paths':['/World/ball','/World/support'],'count':1}] if step==10 else []})
        run={'initial_observation':frames[0],'samples':frames[1:],'actual_physics_steps':120,'requested_physics_steps':120,'simulation_time_s':2,'seed':42,'followers':{},'contacts_truncated':False,'contact_geometry_incomplete':False}
        return spec,acceptance,run

    def test_legacy_missing_new_flags_uses_actual_full_trajectory(self):
        spec,acceptance,run=self.fixture();checks,bodies=physical(run,spec,acceptance)
        self.assertTrue(all(checks.values()),(checks,bodies));self.assertNotIn('partial',run)
        run['samples']=run['samples'][:-1]
        checks,_=physical(run,spec,acceptance);self.assertFalse(checks['complete_cadence'])

    def test_floor_contact_settling_and_truncation_fail_independently(self):
        for failure in ('floor','contact','settling','partial'):
            spec,acceptance,run=self.fixture()
            if failure=='floor':run['samples'][-1]['positions']['/World/ball'][2]=-.2
            if failure=='contact':
                for frame in run['samples']:frame['contact_pairs']=[]
            if failure=='settling':run['samples'][-1]['positions']['/World/ball'][0]=.1
            if failure=='partial':run['partial']=True
            checks,_=physical(run,spec,acceptance);self.assertFalse(all(checks.values()),failure)

    def test_no_analytic_bounds_for_nonuniform_sphere(self):
        spec,acceptance,run=self.fixture();spec['objects']['ball']['size'][0]=.1
        with self.assertRaises(ValueError):physical(run,spec,acceptance)

    def test_exact_physical_actor_set_and_mass(self):
        spec,_,_=self.fixture();acceptance={'required_objects':{'ball':{'kind':'sphere','mass_kg':.12},'support':{'kind':'box'}},'dynamic_object_ids':['ball']}
        with tempfile.TemporaryDirectory() as temporary:
            self.assertTrue(all(structural(spec,acceptance,Path(temporary)).values()))
            spec['objects']['ball']['mass_kg']=.13;self.assertFalse(all(structural(spec,acceptance,Path(temporary)).values()))
            spec['objects']['ball']['mass_kg']=.12;spec['objects']['extra']={'kind':'box'}
            self.assertFalse(structural(spec,acceptance,Path(temporary))['exact_physical_actor_ids'])

    def test_warm_edit_only_exact_direction_and_distance(self):
        spec,_,_=self.fixture();acceptance={'required_objects':{'ball':{'kind':'sphere'},'support':{'kind':'box'}},'dynamic_object_ids':['ball'],'seed_scene':'seed.json','edit':{'object_id':'ball','delta_m':[.02,0,0]}}
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'seed.json').write_text(json.dumps(spec));spec['objects']['ball']['position'][0]=.02
            self.assertTrue(structural(spec,acceptance,root)['frozen_physical_recipe'])
            spec['objects']['support']['collision']=False
            self.assertFalse(structural(spec,acceptance,root)['frozen_physical_recipe'])
        self.assertFalse(equal(True,1));self.assertTrue(equal(.12,.120000000001))

    def test_actual_pixels_and_projection_not_model_visibility_flag(self):
        from PIL import Image,ImageDraw
        spec={'objects':{'camera':{'camera':{'focal_length_mm':35,'horizontal_aperture_mm':36}},'ball':{'kind':'sphere','size':[.1]*3}}}
        frame={'cameras':{'camera':{'position':[0,0,0],'orientation_wxyz':[1,0,0,0]}},'positions':{'/World/ball':[0,0,-1]}}
        image=Image.new('RGB',(200,100),(30,30,30));ImageDraw.Draw(image).ellipse((90,40,110,60),fill=(200,10,10))
        rule={'ball':{'dominant_channels':[0],'minimum_radius_px':5}}
        self.assertTrue(projected_visibility(image,frame,spec,'camera',rule))
        self.assertFalse(projected_visibility(Image.new('RGB',(200,100),(30,30,30)),frame,spec,'camera',rule))
        frame['positions']['/World/ball'][0]=3
        self.assertFalse(projected_visibility(image,frame,spec,'camera',rule))

    def test_claimed_capability_gap_requires_missing_implementation_and_tool(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);work=root/'work';work.mkdir();package=root/'package/server/vendor/simscene';package.mkdir(parents=True)
            (work/'submission.json').write_text(json.dumps({'capability_gap':True}))
            (package/'mcp_server.py').write_text('@server.tool()\ndef scene_open():pass\n')
            acceptance={'schema':'simscene.catalog_efficiency_acceptance.v1','task_id':'glb-rigid','group':'B','required_capability_tools':['asset_prepare'],'required_capability_files':['preparation/glb_convert.py'],'capability_requirement':'actual pinned GLB conversion plus explicit prepared rigid binding'}
            path=root/'acceptance.json';path.write_text(json.dumps(acceptance))
            result=evaluate('glb-rigid',work,root/'state',root/'package',path);self.assertTrue(result['capability_gap_verified']);self.assertFalse(result['passed'])
            (package/'mcp_server.py').write_text('@threaded_tool()\ndef asset_prepare():pass\n')
            self.assertFalse(evaluate('glb-rigid',work,root/'state',root/'package',path)['capability_gap_verified'])

    def test_missing_workbench_cannot_pass_source_subset(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'asset-lock.json').write_text('{}')
            self.assertEqual(source_checks(root,{'objects':{}},{'source_objects':{'workbench':{'required_file_sha256':['a'*64]}}}),{'workbench':False})

    def test_seed_remapping_preserves_source_and_hash_records(self):
        import shutil
        from experiments.eval_catalog_efficiency import remap_seed_metadata
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'source';source.mkdir();cache=source/'cache'/'a';cache.mkdir(parents=True)
            original={'root':'${CACHE_ROOT}/a/model.usda','files':[{'path':'model.usda','sha256':'a'*64}],
                      'source':'https://example.invalid/${CACHE_ROOT}/original'}
            (cache/'simscene-lock.json').write_text(json.dumps(original));(cache/'model.usda').write_text('#usda 1.0')
            (source/'seed-scene.json').write_text(json.dumps({'objects':{'a':{'asset_path':'${TASK_ROOT}/asset.usda'}}}))
            output=root/'output';work=output/'work';work.mkdir(parents=True);shutil.copytree(source,work/'task');shutil.copytree(source/'cache',output/'cache')
            receipts=remap_seed_metadata(source,output,work)
            remapped=json.loads((output/'cache/a/simscene-lock.json').read_text())
            self.assertEqual(remapped['root'],str(output/'cache/a/model.usda'));self.assertEqual(remapped['source'],original['source']);self.assertEqual(remapped['files'],original['files'])
            self.assertEqual(json.loads((cache/'simscene-lock.json').read_text()),original)
            self.assertEqual(len(receipts),2);self.assertTrue(json.loads((output/'seed-remapping.json').read_text())['source_inventory_unchanged'])

    def test_prelaunch_reservation_is_distinct_from_attempted_physics(self):
        from experiments.catalog_efficiency_verifier import attempted_runs
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);runs=root/'runs';(runs/'incomplete').mkdir(parents=True);(runs/'launched').mkdir()
            (runs/'incomplete/spec.json').write_text('{}');(runs/'launched/job.json').write_text('{}')
            self.assertEqual(attempted_runs(root),{'launched'})
