"""Generation admission, identity, acquisition and reconnects without Blender."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from simscene.catalog.models import stable_hash
from simscene.generation import jobs
from simscene.generation.sand3d import COMMIT, generate_asset, parameters, sha
from simscene.generation.acquisition import acquire_generated


class GenerationContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.config={'home':str(self.root/'state'),'index_directory':str(self.root/'index')}
        self.runtime={'schema_version':1,'python':'/isolated/python','reviewed_commit':COMMIT,
                      'observed':{'sand3d_commit':COMMIT,'sand3d_fingerprint':'fixed'}}

    def backend(self, task, python, folder):
        self.assertEqual(task['recipe_id'],'guide_plate_v1')
        self.assertEqual(python,'/isolated/python')
        Path(task['output']).write_text('#usda 1.0\n'+str(task['parameters']['length_m']))
        Path(task['runtime_output']).write_text(json.dumps(task['expected_runtime']))

    def generated(self, name='first', value=None):
        with patch('simscene.generation.sand3d._run',side_effect=self.backend):
            return generate_asset('guide_plate_v1',value or {},self.runtime,output_directory=self.root/name,config=self.config)

    def test_template_parameters_reject_remote_program_and_nonfinite_before_launch(self):
        for recipe,value in [('https://remote/program.py',{}),('guide_plate_v1',{'program':'print(1)'}),
                             ('guide_plate_v1',{'length_m':True}),('guide_plate_v1',{'width_m':float('nan')}),
                             ('guide_plate_v1',{'length_m':.05,'width_m':.02,'thickness_m':.04})]:
            with self.subTest(recipe=recipe,value=value), self.assertRaises(ValueError):parameters(recipe,value)

    def test_open_receiver_has_bounded_explicit_cavity_parameters(self):
        value=parameters('open_receiver_v1',{'interior_width_m':.6})
        self.assertEqual(value['interior_width_m'],.6)
        self.assertEqual(value['interior_depth_m'],.3)
        for invalid in ({'program':'exec(1)'},{'wall_thickness_m':True},{'interior_height_m':float('inf')},{'floor_thickness_m':0}):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):parameters('open_receiver_v1',invalid)

    def test_rebuild_identity_changed_dimension_and_real_selected_acquisition(self):
        a=self.generated();b=self.generated('second');c=self.generated('changed',{'length_m':.7})
        self.assertEqual(a['asset_ref'],b['asset_ref']);self.assertNotEqual(a['asset_ref'],c['asset_ref'])
        self.assertEqual(a['physics_status'],'not_prepared')
        from simscene.catalog.store import CatalogStore
        from simscene.catalog.models import AssetRef
        record=CatalogStore(self.config['index_directory']).get(AssetRef.from_dict(a['asset_ref']))
        plan={'asset_ref':a['asset_ref'],'acquisition':record.availability['acquisition'],
              'budget_breakdown':{'staging_bytes':1000,'unpacked_bytes':1000},'license_decision':record.license,'source_snapshot':record.to_dict()}
        private=self.root/'job';private.mkdir()
        acquired=acquire_generated(plan,self.config,private)
        self.assertEqual(acquired['actual_download_bytes'],0)
        self.assertEqual(Path(acquired['root']).parent,private/'source')
        self.assertEqual(sha(acquired['root']),record.provenance['identity']['output_sha256'])
        Path(a['generated_manifest_path']).write_text('{}')
        with self.assertRaisesRegex(ValueError,'manifest missing or changed'):acquire_generated(plan,self.config)
        self.assertTrue(Path(acquired['root']).is_file())

    def test_unreviewed_runtime_and_existing_output_fail_without_execution(self):
        with patch('simscene.generation.sand3d._run') as run:
            runtime=deepcopy(self.runtime);runtime['reviewed_commit']='other'
            with self.assertRaisesRegex(ValueError,'runtime_unavailable'):
                generate_asset('guide_plate_v1',{},runtime,output_directory=self.root/'never',config=self.config)
            self.assertFalse((self.root/'never').exists());run.assert_not_called()
            (self.root/'existing').mkdir()
            with self.assertRaises(FileExistsError):
                generate_asset('guide_plate_v1',{},self.runtime,output_directory=self.root/'existing',config=self.config)
            run.assert_not_called()

    def test_durable_request_replay_conflict_and_uncertain_launch_never_restart(self):
        runtime=self.root/'runtime.json';runtime.write_text(json.dumps(self.runtime));self.config['generation_runtime']=str(runtime)
        with patch('simscene.generation.jobs.subprocess.Popen') as launch,patch('simscene.jobs._process_identity',return_value={'start_ticks':123}):
            launch.return_value.pid=999
            first=jobs.start('guide_plate_v1',{},'same',config=self.config)
            second=jobs.start('guide_plate_v1',{},'same',config=self.config)
            self.assertEqual(first['job_id'],second['job_id']);self.assertTrue(second['replayed']);self.assertEqual(launch.call_count,1)
            with self.assertRaisesRegex(ValueError,'different job parameters'):
                jobs.start('guide_plate_v1',{'length_m':.6},'same',config=self.config)
            root=jobs.directory(first['job_id'],config=self.config)
            (root/'launch.json').unlink()
            self.assertEqual(jobs.status(first['job_id'],config=self.config)['state'],'uncertain')
            again=jobs.start('guide_plate_v1',{},'same',config=self.config)
            self.assertEqual(again['job_id'],first['job_id']);self.assertEqual(launch.call_count,1)

    def test_unknown_missing_runtime_cancel_and_failed_result_remain_explicit(self):
        with self.assertRaisesRegex(ValueError,'runtime_unavailable'):
            jobs.start('guide_plate_v1',{},config=self.config)
        job_id='gen-'+'a'*32;root=jobs.directory(job_id,config=self.config);root.mkdir(parents=True)
        (root/'job.json').write_text(json.dumps({'job_id':job_id,'type':'asset_generation','state':'failed','error':'real failure'}))
        result=jobs.cancel(job_id,config=self.config)
        self.assertEqual(result['state'],'failed');self.assertTrue(result['completion_confirmed']);self.assertFalse((root/'cancel-request.json').exists())


if __name__=='__main__':unittest.main()
