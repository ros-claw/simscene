import tempfile
import unittest
from unittest.mock import patch
from simscene import jobs
from simscene.assets import SearchError
from simscene.scene import SceneStore, SceneError

class JobTests(unittest.TestCase):
    def test_incompatible_phase_speed_is_rejected_before_worker_launch(self):
        from pathlib import Path
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);model=root/'model';model.mkdir();runtime=root/'python.sh';runtime.touch()
            (model/'robot.urdf').write_text('urdf');(model/'robot.xrdf').write_text('xrdf')
            (model/'rmp_flow.yaml').write_text('rmp_params:\n  joint_velocity_cap_rmp:\n    velocity_damping_region: 0.35\n')
            asset=root/'asset.usd';asset.write_text('usd')
            config={'experimental':True,'model_directory':str(model),'tool_frame':'tcp','tcp_prim':'tcp','target_position':[0,0,1],
                    'max_joint_speed':.5,'sequence':[{'type':'move','position':[0,0,1],'rmp_max_joint_speed':.3}]}
            with patch.dict('os.environ',{'SIMSCENE_HOME':str(root),'SIMSCENE_ISAAC_PYTHON':str(runtime)}):
                store=SceneStore();store.open('scene');store.apply('scene',0,'robot',[{'op':'add','id':'robot','object':{'kind':'asset','asset_path':str(asset),'pose_follower':config}}])
                with patch('simscene.jobs._lock_external_asset',return_value={'kind':'external'}),patch('simscene.jobs.subprocess.Popen',return_value=Mock()) as launch:
                    with self.assertRaisesRegex(SceneError,'below its damping region'):
                        jobs.start('scene',120)
                    launch.assert_not_called()

    def test_external_usd_lock_hashes_root_and_referenced_layer(self):
        from pathlib import Path
        from pxr import Usd,UsdGeom
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            child=Usd.Stage.CreateNew(str(root/'child.usda'))
            child.SetDefaultPrim(UsdGeom.Xform.Define(child,'/Child').GetPrim());child.GetRootLayer().Save()
            stage=Usd.Stage.CreateNew(str(root/'root.usda'));prim=UsdGeom.Xform.Define(stage,'/Root').GetPrim()
            stage.SetDefaultPrim(prim);prim.GetReferences().AddReference('./child.usda');stage.GetRootLayer().Save()
            lock=jobs._lock_external_asset(root/'root.usda')
            self.assertEqual({Path(item['path']).name for item in lock['files']},{'root.usda','child.usda'})
            self.assertTrue(all(len(item['sha256'])==64 for item in lock['files']))
            self.assertEqual(lock['kind'],'external')

    def test_cached_assets_are_verified_and_copied_for_a_run(self):
        import hashlib, json
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            root=Path(root); digest='a'*64; package=root/'cache'/digest
            package.mkdir(parents=True); data=b'USD data'
            (package/'model.usda').write_bytes(data)
            metadata={'source':'https://example.com/model.usda','package_sha256':digest,
                      'files':[{'path':'model.usda','size':len(data),'sha256':hashlib.sha256(data).hexdigest()}],
                      'dependency_status':'resolved_locally'}
            (package/'simscene-lock.json').write_text(json.dumps(metadata))
            scene={'objects':{'a':{'kind':'asset','asset_path':str(package/'model.usda')},
                              'b':{'kind':'asset','asset_path':str(package/'model.usda')}}}
            run=root/'run';run.mkdir()
            records=jobs._snapshot_cached_assets(scene,run)
            (package/'model.usda').write_text('corrupted after snapshot')
            self.assertEqual(Path(scene['objects']['a']['asset_path']).read_bytes(),data)
            self.assertEqual(scene['objects']['a']['asset_path'],scene['objects']['b']['asset_path'])
            self.assertEqual(records['a']['kind'],'snapshot')
            with self.assertRaises(SearchError):
                jobs._snapshot_cached_assets({'objects':{'x':{'kind':'asset','asset_path':str(package/'model.usda')}}},root/'other')

    def test_distinct_caches_with_same_archive_hash_are_not_conflated(self):
        import hashlib,json
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);digest='b'*64;paths=[]
            for index in range(2):
                package=root/f'cache{index}'/digest;package.mkdir(parents=True)
                data=f'dependency version {index}'.encode();(package/'root.usd').write_bytes(data)
                (package/'simscene-lock.json').write_text(json.dumps({'source':'https://example.com/a.usd','package_sha256':digest,'files':[{'path':'root.usd','size':len(data),'sha256':hashlib.sha256(data).hexdigest()}]}))
                paths.append(package/'root.usd')
            run=root/'run';run.mkdir()
            scene={'objects':{f'a{i}':{'kind':'asset','asset_path':str(path)} for i,path in enumerate(paths)}}
            jobs._snapshot_cached_assets(scene,run)
            self.assertNotEqual(scene['objects']['a0']['asset_path'],scene['objects']['a1']['asset_path'])
            self.assertNotEqual(Path(scene['objects']['a0']['asset_path']).read_bytes(),Path(scene['objects']['a1']['asset_path']).read_bytes())

    def test_missing_runtime_and_bad_steps(self):
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {'SIMSCENE_HOME':root, 'XDG_CONFIG_HOME':root}, clear=True):
            SceneStore().open('s')
            with self.assertRaises(SceneError): jobs.start('s', 0)
            with self.assertRaises(SceneError): jobs.start('s', 120, -1)
            with self.assertRaises(SceneError): jobs.start('s', 120)

    def test_archive_requires_a_pinned_case_before_worker_launch(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            runtime=Path(root)/'python.sh';runtime.write_text('runtime')
            with patch.dict('os.environ',{'SIMSCENE_HOME':root,'SIMSCENE_ISAAC_PYTHON':str(runtime)}):
                SceneStore().open('s')
                with self.assertRaisesRegex(SceneError,'requires a pinned stream case'):
                    jobs.start('s',120,archive_verified_objects=True)
                self.assertFalse((Path(root)/'runs').exists())

    def test_download_failure_is_reported(self):
        with patch('simscene.cache.AssetCache.acquire', side_effect=RuntimeError('network failed')):
            job = jobs.acquire_start('https://example.com/a.usd')['job_id']
            try: jobs._downloads[job].result(timeout=5)
            except RuntimeError: pass
            result = jobs.status(job)
            self.assertEqual(result['state'], 'failed')
            self.assertIn('network failed', result['error'])

    def test_huggingface_job_reports_acquisition_failures(self):
        with patch('simscene.huggingface_cache.acquire',side_effect=RuntimeError('unavailable')):
            job=jobs.huggingface_acquire_start('org/repo','a'*40,'root.usd')['job_id']
            try:jobs._downloads[job].result(timeout=5)
            except RuntimeError:pass
            self.assertEqual(jobs.status(job)['state'],'failed')
            self.assertIn('unavailable',jobs.status(job)['error'])

    def test_incomplete_zero_exit_run_is_failed_with_observable_result(self):
        import json
        from pathlib import Path
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)
            (p/'result.json').write_text(json.dumps({'requested_physics_steps':15000,'actual_physics_steps':12074,
                'task_status':'failed','followers':{'ur10':{'sequence_error':'wait_object phase 1 timed out'}},'samples':[]}))
            jobs._jobs['incomplete-test']={'directory':p,'revision':1,'process':Mock(poll=Mock(return_value=0))}
            try:
                result=jobs.status('incomplete-test')
                self.assertEqual(result['state'],'failed')
                self.assertIn('12074 of 15000',result['failure_reason'])
                self.assertEqual(result['result']['followers']['ur10']['sequence_error'],'wait_object phase 1 timed out')
                self.assertEqual(result['result_file'],str(p/'result.json'))
            finally:del jobs._jobs['incomplete-test']

    def test_malformed_result_is_reported_failed(self):
        import json
        from pathlib import Path
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);(p/'result.json').write_text(json.dumps([]))
            jobs._jobs['invalid-result-test']={'directory':p,'revision':1,'process':Mock(poll=Mock(return_value=0))}
            try:
                result=jobs.status('invalid-result-test')
                self.assertEqual(result['state'],'failed')
                self.assertIsNone(result['result'])
                self.assertIn('not an object',result['failure_reason'])
            finally:del jobs._jobs['invalid-result-test']

    def test_result_cannot_claim_a_shorter_request_than_the_locked_run(self):
        import json
        from pathlib import Path
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)
            (p/'run-lock.json').write_text(json.dumps({'requested_physics_steps':15000}))
            (p/'result.json').write_text(json.dumps({'requested_physics_steps':12000,'actual_physics_steps':12000}))
            jobs._jobs['incorrect-request-test']={'directory':p,'revision':1,'process':Mock(poll=Mock(return_value=0))}
            try:
                result=jobs.status('incorrect-request-test')
                self.assertEqual(result['state'],'failed')
                self.assertIn('locked 15000',result['failure_reason'])
            finally:del jobs._jobs['incorrect-request-test']

    def test_status_bounds_samples_and_observation(self):
        import json
        from pathlib import Path
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as root:
            p=Path(root); (p/'result.json').write_text(json.dumps({'samples':[{'physics_steps':1},{'physics_steps':2}], 'images':{}}))
            jobs._jobs['test']={'directory':p,'revision':1,'process':Mock(poll=Mock(return_value=0))}
            try:
                result=jobs.status('test')
                self.assertEqual(result['result']['sample_count'],2)
                self.assertNotIn('samples',result['result'])
                self.assertEqual(jobs.sample('test')['physics_steps'],2)
                with self.assertRaises(SceneError): jobs.sample('test', 2)
            finally: del jobs._jobs['test']

    def test_large_contact_reports_are_paged(self):
        import json
        from pathlib import Path
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)
            (p/'result.json').write_text(json.dumps({'contact_counts':{f'pair-{i}':{'count':i} for i in range(250)},'robot_contacts':{},'contacts_truncated':False}))
            jobs._jobs['page-test']={'directory':p,'revision':1,'process':Mock(poll=Mock(return_value=0))}
            try:
                result=jobs.status('page-test')['result']
                self.assertEqual(result['contact_counts_total'],250)
                self.assertEqual(len(result['contact_counts']),100)
                self.assertTrue(result['contact_counts_excerpted'])
                page=jobs.contacts_page('page-test',offset=200,limit=100)
                self.assertEqual(len(page['contacts']),50)
                self.assertIsNone(page['next_offset'])
                self.assertFalse(page['contacts_truncated'])
                with self.assertRaises(SceneError):jobs.contacts_page('page-test',limit=1000)
            finally:del jobs._jobs['page-test']

    def test_video_chunks_are_bounded_and_confined_to_run(self):
        import base64, json
        from pathlib import Path
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as other:
            p=Path(root);video=p/'camera.mp4';video.write_bytes(b'abcdefgh')
            result={'videos':{'view':{'path':str(video)}}}
            (p/'result.json').write_text(json.dumps(result))
            jobs._jobs['video-test']={'directory':p,'revision':1,'process':Mock(poll=Mock(return_value=0))}
            try:
                page=jobs.video_chunk('video-test','view',2,3)
                self.assertEqual(base64.b64decode(page['data_base64']),b'cde')
                self.assertEqual(page['next_offset'],5)
                with self.assertRaises(SceneError):jobs.video_chunk('video-test','view',0,262145)
                outside=Path(other)/'outside.mp4';outside.write_bytes(b'x')
                result['videos']['view']['path']=str(outside);(p/'result.json').write_text(json.dumps(result))
                with self.assertRaises(SceneError):jobs.video_chunk('video-test','view')
            finally:del jobs._jobs['video-test']

    def test_running_job_exposes_latest_observation_and_enabled_preview(self):
        import json
        from pathlib import Path
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)
            (p/'spec.json').write_text(json.dumps({'objects':{'view':{'kind':'camera','preview_fps':2},'hidden':{'kind':'camera'}}}))
            (p/'latest-observation.json').write_text(json.dumps({'physics_steps':30}))
            (p/'camera_view_live.png').write_bytes(b'png')
            jobs._jobs['live-test']={'directory':p,'revision':1,'process':Mock(poll=Mock(return_value=None))}
            try:
                self.assertEqual(jobs.sample('live-test')['physics_steps'],30)
                self.assertEqual(jobs.camera_image('live-test','view'),str(p/'camera_view_live.png'))
                with self.assertRaises(SceneError):jobs.camera_image('live-test','hidden')
                with self.assertRaises(SceneError):jobs.sample('live-test',0)
            finally:del jobs._jobs['live-test']

    def test_pause_and_resume_requests_are_atomic_and_report_acknowledged_state(self):
        import json
        from pathlib import Path
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);jobs._jobs['control-test']={'directory':p,'revision':1,'process':Mock(poll=Mock(return_value=None))}
            try:
                request=jobs.set_paused('control-test',True)
                self.assertEqual(json.loads((p/'control-request.json').read_text())['request_id'],request['request_id'])
                (p/'control-state.json').write_text(json.dumps({'state':'paused','request_id':request['request_id']}))
                self.assertEqual(jobs.status('control-test')['state'],'paused')
                self.assertEqual(jobs.set_paused('control-test',False)['requested'],'resume')
            finally:del jobs._jobs['control-test']

    def test_failed_job_exposes_only_saved_partial_evidence(self):
        import json
        from pathlib import Path
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);(p/'latest-observation.json').write_text(json.dumps({'physics_steps':42}))
            video=p/'partial.mp4';video.write_bytes(b'partial')
            partial=p/'partial-result.json';partial.write_text(json.dumps({'partial':True,'videos':{'view':{'path':str(video)}}}))
            jobs._jobs['failed-test']={'directory':p,'revision':1,'process':Mock(poll=Mock(return_value=1))}
            try:
                result=jobs.status('failed-test')
                self.assertEqual(result['state'],'failed');self.assertEqual(result['partial_result_file'],str(partial))
                self.assertEqual(jobs.sample('failed-test')['physics_steps'],42)
                self.assertTrue(jobs.video_chunk('failed-test','view')['partial'])
            finally:del jobs._jobs['failed-test']

    def test_control_files_are_snapshotted(self):
        from pathlib import Path
        import json
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as root:
            model=Path(root)/'model';model.mkdir()
            for name in ('robot.urdf','robot.xrdf','rmp_flow.yaml'): (model/name).write_text('original '+name)
            executable=Path(root)/'python.sh';executable.touch()
            with patch.dict('os.environ',{'SIMSCENE_HOME':root,'SIMSCENE_ISAAC_PYTHON':str(executable),'SIMSCENE_PHYSICS_DEVICE':'cpu','CUDA_VISIBLE_DEVICES':'2'}):
                s=SceneStore();s.open('s')
                cfg={'experimental':True,'model_directory':str(model),'tool_frame':'tcp','tcp_prim':'tcp','target_position':[0,0,1],'gripper_urdf':str(model/'robot.urdf'),'gripper_joint':'finger','sequence':[{'type':'gripper','value':0,'steps':10}]}
                asset=Path(root)/'asset.usda';asset.write_text('#usda 1.0\n')
                acceptance=Path(root)/'case.json';acceptance.write_text('{"threshold": 0.9}')
                s.apply('s',0,'setup',[{'op':'add','id':'robot','object':{'kind':'asset','asset_path':str(asset),'pose_follower':cfg}}])
                with patch('simscene.jobs._lock_external_asset',return_value={'kind':'external'}),patch('simscene.jobs.export_scene',side_effect=lambda scene,path:path.write_text('stage')),patch('simscene.jobs.subprocess.Popen',return_value=Mock(pid=123456789)) as launch:
                    job=jobs.start('s',10,17,str(acceptance),True)
                    self.assertIn('--continue-on-controller-error',launch.call_args.args[0])
                run=Path(root)/'runs'/job['run_id']; spec=json.loads((run/'spec.json').read_text())
                snap=Path(spec['objects']['robot']['pose_follower']['model_directory'])
                (model/'robot.xrdf').write_text('changed')
                self.assertEqual((snap/'robot.xrdf').read_text(),'original robot.xrdf')
                self.assertEqual(spec['objects']['robot']['pose_follower']['gripper_urdf'],str(snap/'robot.urdf'))
                self.assertIn('robot.xrdf',json.loads((run/'runtime-lock.json').read_text())['robot']['files_sha256'])
                lock=json.loads((run/'run-lock.json').read_text())
                code=run/'runtime'/'simscene'/'worker'/'isaac_run.py'
                self.assertTrue(code.is_file())
                self.assertIn('worker/isaac_run.py',lock['worker_code_sha256'])
                self.assertIn(str(code),launch.call_args.args[0])
                self.assertIn(str(run/'runtime'/'simscene'/'worker'/'gpu_queue.py'),launch.call_args.args[0])
                self.assertNotEqual(job['job_id'],job['run_id'])
                self.assertEqual(lock['job_id'],job['job_id'])
                self.assertEqual(lock['run_id'],job['run_id'])
                self.assertEqual(lock['scene_revision'],1)
                self.assertEqual(lock['requested_physics_steps'],10)
                self.assertEqual(lock['seed'],17)
                self.assertEqual(lock['physics_device'],'cpu')
                self.assertTrue(lock['continue_on_controller_error'])
                self.assertEqual(lock['gpu_selection']['cuda_visible_devices'],'2')
                acceptance.write_text('{"threshold": 0.1}')
                self.assertEqual(json.loads((run/lock['acceptance_case_file']).read_text())['threshold'],.9)
                self.assertEqual(len(lock['spec_sha256']),64)
                del jobs._jobs[job['job_id']]
