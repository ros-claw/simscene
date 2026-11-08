import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
class CliTest(unittest.TestCase):
    def test_import_preserves_strict_observation_and_capture_configuration(self):
        from simscene.scene import SceneStore
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'scene.json';state=root/'state'
            scene={'objects':{'box':{'kind':'box','size':[.1]*3}},'observation':{'sample_interval_steps':1,'strict_start':True,'record_contact_pairs':True},'presentation':{'profile':'technical_showcase_1080p','capture':{'anti_aliasing':'dlaa'}}}
            source.write_text(json.dumps(scene));result=subprocess.run([sys.executable,'-m','simscene.cli','import-scene','--spec',str(source),'--scene','imported'],env=dict(os.environ,PYTHONPATH='src',SIMSCENE_HOME=str(state)),capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            imported=SceneStore(state).get('imported')
            self.assertEqual(imported['observation'],scene['observation'])
            self.assertEqual(imported['presentation'],scene['presentation'])
    def test_run_uses_shared_job_api_and_waits(self):
        import contextlib,io
        from unittest.mock import patch
        from simscene.cli import main
        with patch.object(sys,'argv',['simscene','run','--scene','example','--steps','3']),patch('simscene.jobs.start',return_value={'job_id':'j'}) as start,patch('simscene.jobs.status',return_value={'state':'completed','result':{'task_status':'unverified'}}),contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(),0)
            start.assert_called_once_with('example',3,None,None,False,False,request_id=None)
            self.assertEqual(json.loads(output.getvalue())['state'],'completed')

    def test_build_yaml_and_verify_observed_domino(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);spec=root/'scene.yaml';spec.write_text('objects:\n  cube:\n    kind: box\n    size: [0.1, 0.1, 0.1]\n')
            env=dict(os.environ,PYTHONPATH='src')
            result=subprocess.run([sys.executable,'-m','simscene.cli','build','--spec',str(spec),'--output',str(root/'scene.usda')],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr);self.assertTrue((root/'scene.usda').is_file())
            env['SIMSCENE_HOME']=str(root/'state')
            imported=subprocess.run([sys.executable,'-m','simscene.cli','import-scene','--spec',str(spec),'--scene','test'],env=env,capture_output=True,text=True)
            self.assertEqual(imported.returncode,0,imported.stderr)
            again=subprocess.run([sys.executable,'-m','simscene.cli','import-scene','--spec',str(spec),'--scene','test'],env=env,capture_output=True,text=True)
            self.assertEqual(again.returncode,1)
            verify=subprocess.run([sys.executable,'-m','simscene.cli','verify','--type','domino','--run','evidence/domino-probe.json','--case','tests/fixtures/domino_case.json'],env=env,capture_output=True,text=True)
            self.assertEqual(verify.returncode,0,verify.stderr);self.assertTrue(json.loads(verify.stdout)['passed'])
    def test_invalid_yaml_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'bad.yaml';path.write_text('bad: [')
            result=subprocess.run([sys.executable,'-m','simscene.cli','build','--spec',str(path),'--output',str(Path(directory)/'scene.usda')],env=dict(os.environ,PYTHONPATH='src'),capture_output=True,text=True)
            self.assertEqual(result.returncode,1);self.assertIn('invalid YAML',result.stderr)

    def test_verify_directory_uses_the_frozen_case_and_saved_spec(self):
        import hashlib,shutil
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            shutil.copyfile('evidence/three-arm-stream3.json',root/'result.json')
            result_path=root/'result.json';record=json.loads(result_path.read_text());record['images']={};result_path.write_text(json.dumps(record))
            shutil.copyfile('evidence/three-arm-stream3-spec.json',root/'spec.json')
            spec=root/'spec.json';data=json.loads(spec.read_text());data['objects']={k:v for k,v in data['objects'].items() if v.get('kind')!='asset'};spec.write_text(json.dumps(data))
            case=root/'acceptance-case.json'
            shutil.copyfile('tests/fixtures/three_arm_stream_case.json',case)
            for name,contents in [('scene.usda','#usda 1.0'),('asset-lock.json','{}'),('runtime-lock.json','{}'),('python.sh','launcher')]:
                (root/name).write_text(contents)
            digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
            lock={'acceptance_case_file':case.name,'acceptance_case_sha256':digest(case),'runtime_python':str(root/'python.sh'),'runtime_python_sha256':digest(root/'python.sh')}
            for name,key in [('spec.json','spec_sha256'),('scene.usda','stage_sha256'),('asset-lock.json','asset_lock_sha256'),('runtime-lock.json','runtime_lock_sha256')]:lock[key]=digest(root/name)
            (root/'run-lock.json').write_text(json.dumps(lock))
            from simscene.evidence_integrity import seal
            seal(root)
            command=[sys.executable,'-m','simscene.cli','verify','--run',str(root)]
            env=dict(os.environ,PYTHONPATH='src')
            result=subprocess.run(command,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue(json.loads(result.stdout)['passed'])
            spec=root/'spec.json';original=spec.read_text();spec.write_text(original+' ')
            result=subprocess.run(command,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,1)
            self.assertFalse(json.loads(result.stdout)['input_integrity']['passed'])
            spec.write_text(original)
            original=result_path.read_text();result_path.write_text(original+' ')
            result=subprocess.run(command,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,1)
            self.assertFalse(json.loads(result.stdout)['evidence_integrity']['passed'])
            result_path.write_text(original)
            case.write_text('{}')
            result=subprocess.run(command,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,1)
            self.assertIn('does not match',result.stderr)

    def test_configure_saves_runtime_without_claiming_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Path(directory)/'python.sh';runtime.write_text('runtime')
            env=dict(os.environ,PYTHONPATH='src',XDG_CONFIG_HOME=directory)
            result=subprocess.run([sys.executable,'-m','simscene.cli','configure','--isaac-python',str(runtime)],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['status'],'configured_not_registered_or_installed')
