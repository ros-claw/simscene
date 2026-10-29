"""An explicit simulation request ID identifies exactly one saved job."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from simscene import jobs
from simscene.scene import SceneError,SceneStore


class JobIdempotencyTest(unittest.TestCase):
    def test_retries_recover_same_job_even_after_scene_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);runtime=root/'python.sh';runtime.touch()
            with patch.dict(os.environ,{'SIMSCENE_HOME':directory,'SIMSCENE_ISAAC_PYTHON':str(runtime)}):
                store=SceneStore();store.open('scene')
                with patch('simscene.jobs.export_scene',side_effect=lambda scene,path:path.write_text('stage')),patch('simscene.jobs.subprocess.Popen',return_value=Mock(pid=123456789)) as spawn:
                    first=jobs.start('scene',10,17,case={'threshold':.9},request_id='request_a')
                    record=root/'job-requests'/'request_a.json'
                    interrupted=json.loads(record.read_text());interrupted['state']='starting';interrupted.pop('result');record.write_text(json.dumps(interrupted))
                    recovered=jobs.start('scene',10,17,case={'threshold':.9},request_id='request_a')
                    self.assertEqual(recovered['job_id'],first['job_id']);self.assertTrue(recovered['replayed'])
                    store.apply('scene',0,'edit',[{'op':'add','id':'box','object':{'kind':'box'}}])
                    jobs._jobs.pop(first['job_id'],None)
                    repeated=jobs.start('scene',10,17,case={'threshold':.9},request_id='request_a')
                    self.assertEqual(first['job_id'],repeated['job_id']);self.assertEqual(first['run_id'],repeated['run_id'])
                    self.assertFalse(first['replayed']);self.assertTrue(repeated['replayed']);self.assertEqual(spawn.call_count,1)
                    with self.assertRaisesRegex(SceneError,'different job parameters'):
                        jobs.start('scene',11,17,case={'threshold':.9},request_id='request_a')
                    lock=json.loads((root/'runs'/first['run_id']/'run-lock.json').read_text())
                    self.assertEqual(lock['request_id'],'request_a')
                    self.assertEqual(len(lock['request_payload_sha256']),64)
                    interrupted=json.loads(record.read_text());interrupted['state']='starting';interrupted.pop('result');record.write_text(json.dumps(interrupted))
                    (root/'runs'/first['run_id']/'job.json').unlink()
                    with self.assertRaisesRegex(SceneError,'uncertain'):
                        jobs.start('scene',10,17,case={'threshold':.9},request_id='request_a')
                    self.assertEqual(spawn.call_count,1)
                    jobs._jobs.pop(first['job_id'],None)

    def test_changed_case_file_cannot_reuse_the_same_request_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);runtime=root/'python.sh';runtime.touch();case=root/'case.json';case.write_text('{"threshold":0.9}')
            with patch.dict(os.environ,{'SIMSCENE_HOME':directory,'SIMSCENE_ISAAC_PYTHON':str(runtime)}):
                SceneStore().open('scene')
                with patch('simscene.jobs.export_scene',side_effect=lambda scene,path:path.write_text('stage')),patch('simscene.jobs.subprocess.Popen',return_value=Mock(pid=123456789)) as spawn:
                    first=jobs.start('scene',10,case_path=str(case),request_id='request_b')
                    case.write_text('{"threshold":0.8}')
                    with self.assertRaisesRegex(SceneError,'different job parameters'):
                        jobs.start('scene',10,case_path=str(case),request_id='request_b')
                    self.assertEqual(spawn.call_count,1)
                    jobs._jobs.pop(first['job_id'],None)


if __name__=='__main__':unittest.main()
