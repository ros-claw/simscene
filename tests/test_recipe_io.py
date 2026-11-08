"""Portable recipe bindings and CLI imports: CPU fixtures, no SDK/network calls."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from simscene.recipes import io
from simscene.preparation.profiles import validate_parameters,PROFILE_VERSION
from simscene.catalog.models import AssetRecord,AssetRef
from experiments import export_scene_recipe as exporter
from experiments import apply_scene_recipe as applier
from experiments import acquire_recipe_assets as acquirer


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepared(root):
    root.mkdir();(root/'source').mkdir()
    (root/'source/item.glb').write_bytes(b'source geometry fixture')
    source_file={'path':'item.glb','size_bytes':(root/'source/item.glb').stat().st_size,'sha256':digest(root/'source/item.glb')}
    ref=AssetRef('abo-glb','fixture','b'*40).to_dict()
    record=AssetRecord(AssetRef.from_dict(ref),'Fixture',format='glb',entry_path='item.glb',
        license={'status':'known','license':'CC-BY-4.0'},availability={'acquisition':{'kind':'hf_single_glb','repository':'codepawl/abo-glb','revision':'b'*40,'path':'item.glb'}},
        provenance={'source_location':'https://huggingface.co/codepawl/abo-glb'}).to_dict()
    acquired={'root':'/old/developer/cache/item.glb','source_ref':ref,'files':[source_file],'metadata':record}
    (root/'source/acquired.json').write_text(json.dumps(acquired))
    (root/'main.usda').write_text('#usda 1.0\n(defaultPrim = "Asset"\n metersPerUnit = 1\n upAxis = "Z")\ndef Xform "Asset" { def Xform "Body" { def Xform "Visual" {} } }\n')
    manifest={'schema':'simscene.prepared_asset.v1','schema_version':1,'prepared_id':'c'*64,'profile_id':'rigid_prop_v1',
        'profile_version':PROFILE_VERSION,'parameters':validate_parameters('rigid_prop_v1',{'mass_kg':.12,'mass_note':'explicit fixture assumption','source_physics_policy':'reject_if_physics','proxy_tolerance_m':.002}),
        'target':{'engine':'physx','isaac_version':'fixture','usd_version':'fixture','platform':'linux'},'toolchain':{'backend':'fixture','version':'1'},
        'source_ref':ref,'source_sha256':source_file['sha256'],'source_closure_sha256':'d'*64,'source_manifest_sha256':'e'*64,
        'root':'/old/private/prepared','asset_path':'/old/private/main.usda','main':'main.usda','default_prim':'/Asset',
        'body_map':{'main':{'role':'rigid','relative_prim_path':'Body','visual_relative_prim_paths':['Body/Visual'],'collider_relative_prim_paths':['Body/Visual']}},
        'runtime_validation':{'status':'not_run','physical_steps':0},
        'files':[{'path':str(p.relative_to(root)),'size_bytes':p.stat().st_size,'sha256':digest(p)} for p in sorted(root.rglob('*')) if p.is_file()]}
    path=root/'manifest.json';path.write_text(json.dumps(manifest))
    binding={'asset_path':str(root/'main.usda'),'asset_binding':{'manifest_path':str(path),'manifest_sha256':digest(path)}}
    return manifest,acquired,binding


class RecipeIOTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.manifest,self.acquired,self.binding=prepared(self.root/'package')
        self.selection=io.prepared_selection(self.manifest,self.acquired,manifest_sha256=self.binding['asset_binding']['manifest_sha256'])

    def test_prepared_export_has_no_private_paths_and_old_pin_is_informational(self):
        value=json.dumps(self.selection);self.assertNotIn('/old/',value);self.assertNotIn(str(self.root),value)
        self.assertEqual(self.selection['source_files'][0]['path'],'item.glb')
        self.assertIn('informational',self.selection['previous_preparation']['scope'])
        changed=copy.deepcopy(self.selection);changed['previous_preparation']['manifest_sha256']='f'*64
        self.assertEqual(io.validate_rebuilt(changed,self.binding)['prepared_id'],'c'*64)

    def test_portable_apply_injects_exact_current_binding_and_retains_legacy_strings(self):
        recipe={'operations':[{'op':'add','id':'item','object':{'kind':'asset','dynamic':True,'asset_role':'payload'}},
            {'op':'add','id':'table','object':{'kind':'asset','asset_path':'asset://legacy'}}]}
        old=copy.deepcopy(recipe)
        operations=io.resolve_operations(recipe,{'payload':self.binding,'legacy':{'root':'/local/native.usda'}},selections={'payload':self.selection})
        self.assertEqual(operations[0]['object'],dict(kind='asset',dynamic=True,**self.binding))
        self.assertEqual(operations[1]['object']['asset_path'],'/local/native.usda');self.assertEqual(recipe,old)
        with self.assertRaises(ValueError):io.resolve_operations(recipe,{'payload':self.binding},selections=None)
        forged=copy.deepcopy(recipe);forged['operations'][0]['object']['asset_path']='old.usda'
        with self.assertRaises(ValueError):io.resolve_operations(forged,{'payload':self.binding},selections={'payload':self.selection})

    def test_source_profile_target_toolchain_and_complete_closure_are_mandatory(self):
        for key,value in [('source_sha256','f'*64),('profile_version',99),('target',{}),('toolchain',{}),('source_ref',dict(self.selection['source_ref'],asset_id='imposter'))]:
            bad=copy.deepcopy(self.selection);bad[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):io.validate_rebuilt(bad,self.binding)
        (self.root/'package/source/item.glb').write_bytes(b'tampered')
        with self.assertRaises(ValueError):io.validate_rebuilt(self.selection,self.binding)

    def test_exporter_handles_prepared_snapshot_and_leaves_legacy_schema(self):
        run=self.root/'run';run.mkdir()
        spec={'objects':{'item':dict(kind='asset',dynamic=True,**self.binding),'floor':{'kind':'box','size':[1,1,.1]}}}
        (run/'spec.json').write_text(json.dumps(spec));(run/'run-lock.json').write_text('{}')
        (run/'asset-lock.json').write_text(json.dumps({'item':{'kind':'prepared_snapshot','manifest_sha256':self.binding['asset_binding']['manifest_sha256']}}))
        with patch.object(exporter,'inputs',return_value={'passed':True}),patch.object(exporter,'outputs',return_value={'passed':True}):
            exporter.export(run,self.root/'export')
        recipe=json.loads((self.root/'export/recipe.json').read_text());lock=json.loads((self.root/'export/assets.lock.json').read_text())
        self.assertEqual(lock['schema'],io.SCHEMA);self.assertEqual(recipe['operations'][0]['object']['asset_role'],'item')
        self.assertNotIn('asset_binding',recipe['operations'][0]['object']);self.assertNotIn('/old/',json.dumps(lock))
        (run/'spec.json').write_text(json.dumps({'objects':{'floor':{'kind':'box'}}}));(run/'asset-lock.json').write_text('{}')
        with patch.object(exporter,'inputs',return_value={'passed':True}),patch.object(exporter,'outputs',return_value={'passed':True}):exporter.export(run,self.root/'legacy')
        self.assertEqual(json.loads((self.root/'legacy/assets.lock.json').read_text())['schema'],'simscene.selected_assets.v1')

    def test_generated_export_records_only_trusted_intent_and_rejects_arbitrary_code(self):
        from simscene.generation.sand3d import COMMIT
        manifest=copy.deepcopy(self.manifest);acquired=copy.deepcopy(self.acquired)
        manifest['source_ref']=dict(manifest['source_ref'],source_id='local-sand3d',asset_id='guide_plate_v1')
        acquired['source_ref']=manifest['source_ref']
        manifest['provenance']={'generator':'sand3d','reviewed_commit':COMMIT,'identity':{
            'recipe_id':'guide_plate_v1','parameters':{},'seed':0,'template_sha256':'1'*64,
            'toolchain':{'python':'/private/runtime/python','reviewed_commit':COMMIT,'observed':{'sand3d_commit':COMMIT,'python_version':[3,11,0]}}}}
        selection=io.prepared_selection(manifest,acquired,manifest_sha256='a'*64)
        self.assertEqual(selection['generation']['seed'],0);self.assertNotIn('/private/',json.dumps(selection))
        manifest['provenance']['identity']['recipe_id']='exec_program'
        with self.assertRaises(ValueError):io.prepared_selection(manifest,acquired,manifest_sha256='a'*64)

    def test_legacy_snapshot_export_retains_v1_payload_and_asset_uri(self):
        run=self.root/'legacy-run';(run/'assets'/('a'*64)).mkdir(parents=True)
        source='https://example.invalid/selected.usd'
        metadata={'source':source,'package_sha256':'a'*64,'files':[{'path':'selected.usd','size':3,'sha256':'b'*64}],
            'license':'unknown','dependency_status':'resolved'}
        (run/'assets'/('a'*64)/'simscene-lock.json').write_text(json.dumps(metadata))
        (run/'spec.json').write_text(json.dumps({'objects':{'table':{'kind':'asset','asset_path':str(run/'assets'/('a'*64)/'selected.usd')}}}))
        (run/'asset-lock.json').write_text(json.dumps({'table':{'kind':'snapshot','source':source,'package_sha256':'a'*64}}))
        (run/'run-lock.json').write_text('{}')
        with patch.object(exporter,'inputs',return_value={'passed':True}),patch.object(exporter,'outputs',return_value={'passed':True}):exporter.export(run,self.root/'legacy-selected')
        lock=json.loads((self.root/'legacy-selected/assets.lock.json').read_text())
        self.assertEqual(lock,{'schema':'simscene.selected_assets.v1','assets':{'table':dict(metadata,provider='usd-search')}})
        recipe=json.loads((self.root/'legacy-selected/recipe.json').read_text())
        self.assertEqual(recipe['operations'][0]['object']['asset_path'],'asset://table')
        self.assertNotIn('schema',recipe)

    def test_selected_legacy_submembers_export_rebuild_and_apply_without_changing_source_lock(self):
        run=self.root/'member-run';package=run/'assets'/('a'*64);(package/'origin').mkdir(parents=True)
        for name,data in [('full.usda',b'full packing table including decorations'),('bare.usda',b'bare table'),('other.usda',b'other selected member')]:
            (package/'origin'/name).write_bytes(data)
        files=[{'path':p.relative_to(package).as_posix(),'size':p.stat().st_size,'sha256':digest(p)} for p in sorted((package/'origin').iterdir())]
        source='https://example.invalid/packing_table.usd'
        metadata={'source':source,'package_sha256':'a'*64,'root':'/old/cache/'+('a'*64)+'/origin/full.usda',
            'files':files,'license':'unknown','dependency_status':'resolved'}
        lock_path=package/'simscene-lock.json';lock_path.write_text(json.dumps(metadata));original=lock_path.read_bytes()
        scene={'objects':{'table':{'kind':'asset','asset_path':str(package/'origin/bare.usda')},
            'other':{'kind':'asset','asset_path':str(package/'origin/other.usda')},
            'table_again':{'kind':'asset','asset_path':str(package/'origin/bare.usda')}}}
        (run/'spec.json').write_text(json.dumps(scene));(run/'run-lock.json').write_text('{}')
        (run/'asset-lock.json').write_text(json.dumps({name:{'kind':'snapshot','source':source,'package_sha256':'a'*64} for name in scene['objects']}))
        with patch.object(exporter,'inputs',return_value={'passed':True}),patch.object(exporter,'outputs',return_value={'passed':True}):exporter.export(run,self.root/'member-export')
        lock=json.loads((self.root/'member-export/assets.lock.json').read_text());recipe=json.loads((self.root/'member-export/recipe.json').read_text())
        self.assertEqual(lock['schema'],io.SCHEMA);self.assertEqual(set(lock['assets']),{'table','other'})
        self.assertEqual(lock['assets']['table']['selected_member'],{'path':'origin/bare.usda','sha256':digest(package/'origin/bare.usda')})
        self.assertEqual([o['object']['asset_path'] for o in recipe['operations']],['asset://table','asset://other','asset://table'])
        acquired=dict(metadata,root=str(package/'origin/full.usda'))
        with patch('simscene.cache.AssetCache') as cache:
            cache.return_value.acquire.return_value=acquired
            catalog=acquirer.acquire(lock,run/'assets')
        self.assertEqual(catalog['table']['root'],str(package/'origin/bare.usda'))
        self.assertEqual(catalog['other']['root'],str(package/'origin/other.usda'))
        self.assertEqual(acquired['root'],str(package/'origin/full.usda'))
        self.assertEqual(lock_path.read_bytes(),original)
        operations=io.resolve_operations(recipe,catalog,selections=lock['assets'])
        self.assertEqual(operations[0]['object']['asset_path'],str(package/'origin/bare.usda'))
        self.assertNotIn('/old/cache/',json.dumps(lock))

    def test_selected_member_rejects_traversal_hash_drift_unlisted_files_and_symlinks(self):
        package=self.root/'legacy-member';package.mkdir();(package/'root.usda').write_bytes(b'full')
        (package/'bare.usda').write_bytes(b'bare')
        files=[{'path':p.name,'size':p.stat().st_size,'sha256':digest(p)} for p in package.iterdir()]
        acquired={'root':str(package/'root.usda'),'files':files}
        selection={'selected_member':{'path':'bare.usda','sha256':digest(package/'bare.usda')}}
        self.assertEqual(io.resolve_member(selection,acquired,package)['root'],str(package/'bare.usda'))
        for path in ('../bare.usda','/bare.usda','sub/../bare.usda','%2e%2e/bare.usda','bare.usda?token=x','bare.usda\n'):
            bad=copy.deepcopy(selection);bad['selected_member']['path']=path
            with self.subTest(path=path),self.assertRaises(ValueError):io.resolve_member(bad,acquired,package)
        bad=copy.deepcopy(selection);bad['selected_member']['sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'source closure'):io.resolve_member(bad,acquired,package)
        bad=copy.deepcopy(selection);bad['selected_member']['path']='unlisted.usda'
        with self.assertRaisesRegex(ValueError,'source closure'):io.resolve_member(bad,acquired,package)
        (package/'bare.usda').write_bytes(b'drift')
        with self.assertRaisesRegex(ValueError,'changed'):io.resolve_member(selection,acquired,package)
        (package/'bare.usda').unlink();outside=self.root/'outside.usda';outside.write_bytes(b'bare');(package/'bare.usda').symlink_to(outside)
        with self.assertRaisesRegex(ValueError,'changed'):io.resolve_member(selection,acquired,package)

    def test_legacy_failed_bytes_counted_and_capacity_not_transfer_limit(self):
        from simscene.acquisition.transfer import current_budget
        files=[{'path':'fixture.usda','size':4,'sha256':'a'*64}]
        lock={'schema':'simscene.selected_assets.v1','assets':{'first':{'provider':'usd-search','source':'https://example.invalid/one','files':files},
            'second':{'provider':'usd-search','source':'https://example.invalid/two','files':files}}}
        limits=[]
        def fetch(source):
            budget=current_budget();limits.append(budget.download_limit)
            budget.actual_download_bytes+=7 if source.endswith('one') else 4
            if source.endswith('two'):raise ValueError('ordinary texture 404 after partial bytes')
            return {'root':'/cache/fixture.usda','files':files}
        with patch('simscene.cache.AssetCache') as cache:
            cache.return_value.acquire.side_effect=fetch
            with self.assertRaises(acquirer.RecipeAcquireError) as error:
                acquirer.acquire(lock,self.root/'cache',max_bytes=999,download_bytes=20,asset_download_bytes=15,catalog_output=self.root/'legacy-cost.json')
        self.assertEqual(limits,[15,13]);self.assertEqual(error.exception.report['actual_download_bytes'],11)
        self.assertEqual(cache.call_args.args[2],999)
        self.assertEqual(list(error.exception.catalog),['first'])

    def test_new_registered_generated_template_exports_without_hardcoded_recipe_list(self):
        from simscene.generation.sand3d import COMMIT
        manifest=copy.deepcopy(self.manifest);acquired=copy.deepcopy(self.acquired)
        manifest['source_ref']=dict(manifest['source_ref'],source_id='local-sand3d',asset_id='open_receiver_v1')
        acquired['source_ref']=manifest['source_ref']
        manifest['provenance']={'generator':'sand3d','reviewed_commit':COMMIT,'identity':{
            'recipe_id':'open_receiver_v1','parameters':{'interior_width_m':.3},'seed':0,'template_sha256':'1'*64,
            'toolchain':{'reviewed_commit':COMMIT,'python':'/private/configured/python','observed':{'sand3d_commit':COMMIT}}}}
        result=io.prepared_selection(manifest,acquired,manifest_sha256='a'*64)
        self.assertEqual(result['generation']['recipe_id'],'open_receiver_v1')
        self.assertEqual(result['generation']['parameters']['interior_width_m'],.3)
        self.assertNotIn('/private/',json.dumps(result))

    def test_script_imports_never_parse_cli_or_launch(self):
        with patch('argparse.ArgumentParser.parse_args',side_effect=AssertionError('import parsed CLI')),patch('subprocess.Popen',side_effect=AssertionError('import launched')):
            for name in ('apply_scene_recipe','acquire_recipe_assets','export_scene_recipe'):
                path=Path(__file__).parents[1]/'experiments'/(name+'.py')
                spec=importlib.util.spec_from_file_location('isolated_'+name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

    def test_durable_rebuild_uses_plan_receipt_status_and_checks_source(self):
        result={'root':self.binding['asset_path'],**self.binding['asset_binding'],'actual_download_bytes':7}
        config={'home':str(self.root/'state'),'asset_cache_directory':str(self.root/'cache')}
        with (patch('simscene.acquisition.plans.make_plan',return_value={'ready_to_fetch':True,'plan_id':'p'}) as plan,
            patch('simscene.preparation.jobs.start',return_value={'job_id':'prep-fixture'}) as start,
            patch('simscene.preparation.jobs.status',side_effect=[{'state':'queued'},{'state':'completed','result':result,'actual_download_bytes':7}]),patch.object(acquirer.time,'sleep')):
            catalog=acquirer.acquire({'schema':io.SCHEMA,'assets':{'payload':self.selection}},self.root/'cache',config=config,catalog_output=self.root/'catalog.json')
        self.assertEqual(catalog['payload'],self.binding)
        self.assertEqual(plan.call_args.args[4]['download_bytes'],512*1024**2)
        self.assertEqual(plan.call_args.kwargs['config']['asset_cache_capacity_bytes'],4*1024**3)
        self.assertTrue(start.call_args.args[1].startswith('recipe-prepare-'))
        report=json.loads((self.root/'catalog.json.report.json').read_text());self.assertEqual(report['actual_download_bytes'],7)
        self.assertIn('new case',report['physical_verification'])

    def test_failed_preparation_cost_retained_no_future_or_retry(self):
        record={'state':'failed','error':'texture missing','actual_download_bytes':23}
        with patch('simscene.acquisition.plans.make_plan',return_value={'ready_to_fetch':True,'plan_id':'p'}),patch('simscene.preparation.jobs.start',return_value={'job_id':'prep-fixture'}) as start,patch('simscene.preparation.jobs.status',return_value=record):
            with self.assertRaises(acquirer.RecipeAcquireError) as error:
                acquirer.acquire({'schema':io.SCHEMA,'assets':{'payload':self.selection}},self.root/'cache',config={},catalog_output=self.root/'failed.json')
        self.assertEqual(start.call_count,1);self.assertEqual(error.exception.report['actual_download_bytes'],23)
        self.assertEqual(json.loads((self.root/'failed.json.report.json').read_text())['roles'][0]['state'],'failed')


if __name__=='__main__':unittest.main()
