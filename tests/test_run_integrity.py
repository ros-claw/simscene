import hashlib,json,tempfile,unittest
from pathlib import Path
from simscene.run_integrity import verify

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
class RunIntegrityTest(unittest.TestCase):
    def test_worker_snapshot_detects_changes_and_unrecorded_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);runtime=root/'python.sh';runtime.write_text('launcher')
            (root/'spec.json').write_text('{"objects":{}}');(root/'scene.usda').write_text('#usda 1.0')
            (root/'asset-lock.json').write_text('{}');(root/'runtime-lock.json').write_text('{}')
            code=root/'runtime'/'simscene'/'worker'/'isaac_run.py';code.parent.mkdir(parents=True);code.write_text('original')
            lock={'runtime_python':str(runtime),'runtime_python_sha256':sha(runtime),'worker_code_sha256':{'worker/isaac_run.py':sha(code)}}
            for file,key in [('spec.json','spec_sha256'),('scene.usda','stage_sha256'),('asset-lock.json','asset_lock_sha256'),('runtime-lock.json','runtime_lock_sha256')]:lock[key]=sha(root/file)
            (root/'run-lock.json').write_text(json.dumps(lock))
            self.assertTrue(verify(root)['checks']['worker_code_snapshot'])
            extra=code.parent/'injected.py';extra.write_text('unexpected')
            self.assertFalse(verify(root)['checks']['worker_code_snapshot'])
            extra.unlink();code.write_text('changed')
            self.assertFalse(verify(root)['checks']['worker_code_snapshot'])

    def test_unlocked_scene_asset_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);runtime=root/'python.sh';runtime.write_text('launcher')
            (root/'spec.json').write_text(json.dumps({'objects':{'unlocked':{'kind':'asset','asset_path':'/missing.usd'}}}))
            (root/'scene.usda').write_text('#usda 1.0');(root/'asset-lock.json').write_text('{}');(root/'runtime-lock.json').write_text('{}')
            lock={'runtime_python':str(runtime),'runtime_python_sha256':sha(runtime)}
            for file,key in [('spec.json','spec_sha256'),('scene.usda','stage_sha256'),('asset-lock.json','asset_lock_sha256'),('runtime-lock.json','runtime_lock_sha256')]:lock[key]=sha(root/file)
            (root/'run-lock.json').write_text(json.dumps(lock))
            result=verify(root)
            self.assertFalse(result['passed']);self.assertFalse(result['checks']['asset_lock_coverage'])

    def test_detects_changed_run_inputs_and_external_asset(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);asset=root/'external.usd';asset.write_text('original')
            runtime=root/'python.sh';runtime.write_text('launcher')
            (root/'spec.json').write_text(json.dumps({'objects':{'asset':{'kind':'asset','asset_path':str(asset)}}}));(root/'scene.usda').write_text('#usda 1.0')
            (root/'asset-lock.json').write_text(json.dumps({'asset':{'kind':'external','path':str(asset),'files':[{'path':str(asset),'size':asset.stat().st_size,'sha256':sha(asset)}]}}))
            (root/'runtime-lock.json').write_text('{}')
            lock={'runtime_python':str(runtime),'runtime_python_sha256':sha(runtime)}
            for file,key in [('spec.json','spec_sha256'),('scene.usda','stage_sha256'),('asset-lock.json','asset_lock_sha256'),('runtime-lock.json','runtime_lock_sha256')]:lock[key]=sha(root/file)
            (root/'acceptance-case.json').write_text('{"threshold":0.9}')
            lock['acceptance_case_file']='acceptance-case.json';lock['acceptance_case_sha256']=sha(root/'acceptance-case.json')
            (root/'run-lock.json').write_text(json.dumps(lock))
            self.assertTrue(verify(root)['passed'])
            (root/'acceptance-case.json').write_text('{"threshold":0.1}')
            self.assertFalse(verify(root)['checks']['acceptance_case'])
            asset.write_text('modified')
            result=verify(root);self.assertFalse(result['passed']);self.assertFalse(result['checks']['asset:asset'])
            (root/'scene.usda').write_text('changed')
            self.assertFalse(verify(root)['checks']['scene.usda'])
