import json,os,subprocess,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import Mock,patch
from simscene import jobs
from simscene.scene import SceneError

class ReconnectTest(unittest.TestCase):
    def test_live_parent_reports_recorded_signal_from_child(self):
        with tempfile.TemporaryDirectory() as root:
            directory=Path(root)/'run';directory.mkdir()
            process=Mock(pid=12345);process.poll.return_value=241
            (directory/'process-exit.json').write_text(json.dumps({'schema':'simscene.process_exit.v1',
                'run_id':'run','queue_pid':12345,'child_pid':12346,'exit_code':-15}))
            jobs._jobs['signal-test']={'process':process,'directory':directory,'revision':1}
            try:
                result=jobs.status('signal-test')
                self.assertEqual(result['state'],'failed');self.assertEqual(result['exit_code'],-15)
                self.assertFalse(result['exit_code_inferred'])
            finally:jobs._jobs.pop('signal-test',None)

    def test_recovered_jobs_distinguish_recorded_exit_from_inference(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ,{'SIMSCENE_HOME':root}):
            run_id=uuid.uuid4().hex;job_id=uuid.uuid4().hex;pid=99999999
            directory=Path(root)/'runs'/run_id;directory.mkdir(parents=True)
            (directory/'run-lock.json').write_text(json.dumps({'run_id':run_id,'job_id':job_id,'scene_revision':1}))
            (directory/'job.json').write_text(json.dumps({'run_id':run_id,'job_id':job_id,'pid':pid,'identity':None}))
            (directory/'result.json').write_text(json.dumps({'samples':[]}))
            record={'schema':'simscene.process_exit.v1','run_id':run_id,'queue_pid':pid,'child_pid':123,'exit_code':7}
            path=directory/'process-exit.json';path.write_text(json.dumps(record))
            try:
                failed=jobs.status(job_id)
                self.assertEqual(failed['state'],'failed');self.assertEqual(failed['exit_code'],7)
                self.assertFalse(failed['exit_code_inferred'])
                record['exit_code']=0;path.write_text(json.dumps(record))
                observed=jobs.status(job_id)
                self.assertEqual(observed['state'],'completed');self.assertFalse(observed['exit_code_inferred'])
                record['queue_pid']+=1;path.write_text(json.dumps(record))
                inferred=jobs.status(job_id)
                self.assertEqual(inferred['state'],'completed');self.assertTrue(inferred['exit_code_inferred'])
            finally:jobs._jobs.pop(job_id,None)

    def test_live_but_stale_worker_is_reported_as_stalled(self):
        import time
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ,{'SIMSCENE_HOME':root}):
            directory=Path(root)/'run';directory.mkdir();process=subprocess.Popen(['sleep','30'],start_new_session=True)
            jobs._jobs['stale-test']={'process':process,'directory':directory,'revision':1}
            try:
                observation=directory/'latest-observation.json'
                observation.write_text(json.dumps({'physics_steps':3,'simulation_time_s':.05}))
                old=time.time()-301;os.utime(observation,(old,old))
                state=jobs.status('stale-test')
                self.assertEqual(state['state'],'stalled');self.assertIn('no observation',state['stalled_reason'])
                self.assertEqual(jobs.sample('stale-test')['evidence_state'],'stalled')
                (directory/'control-state.json').write_text(json.dumps({'state':'paused'}))
                self.assertEqual(jobs.status('stale-test')['state'],'paused')
            finally:
                jobs._jobs.pop('stale-test',None)
                if process.poll() is None:process.terminate();process.wait(timeout=5)

    def test_queued_job_reports_waiting_and_cooperative_pause(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ,{'SIMSCENE_HOME':root}):
            directory=Path(root)/'run';directory.mkdir()
            process=subprocess.Popen(['sleep','30'],start_new_session=True)
            jobs._jobs['queued-test']={'process':process,'directory':directory,'revision':1}
            try:
                (directory/'gpu-queue.json').write_text(json.dumps({'state':'queued'}))
                self.assertEqual(jobs.status('queued-test')['state'],'queued')
                (directory/'control-state.json').write_text(json.dumps({'state':'paused','request_id':'pause'}))
                self.assertEqual(jobs.status('queued-test')['state'],'paused')
                (directory/'control-state.json').write_text(json.dumps({'state':'running','request_id':'resume'}))
                self.assertEqual(jobs.status('queued-test')['state'],'queued')
                (directory/'gpu-queue.json').write_text(json.dumps({'state':'running'}))
                self.assertEqual(jobs.status('queued-test')['state'],'running')
            finally:
                jobs._jobs.pop('queued-test',None)
                if process.poll() is None:process.terminate();process.wait(timeout=5)

    def test_cancel_is_acknowledged_only_after_worker_exits(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ,{'SIMSCENE_HOME':root}):
            directory=Path(root)/'run';directory.mkdir()
            process=subprocess.Popen(['sleep','30'],start_new_session=True)
            jobs._jobs['live']={'process':process,'directory':directory,'revision':1}
            try:
                requested=jobs.cancel('live')
                self.assertTrue(requested['cancel_requested'])
                process.wait(timeout=5)
                self.assertEqual(jobs.status('live')['state'],'cancelled')
            finally:
                jobs._jobs.pop('live',None)
                if process.poll() is None:process.terminate();process.wait(timeout=5)

    @unittest.skipUnless(Path('/proc/sys/kernel/random/boot_id').is_file(), 'Linux process identity required')
    def test_reconnect_checks_boot_and_process_start_before_reporting_running(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ,{'SIMSCENE_HOME':root}):
            run_id=uuid.uuid4().hex;job_id=uuid.uuid4().hex
            directory=Path(root)/'runs'/run_id;directory.mkdir(parents=True)
            process=subprocess.Popen(['sleep','30'],start_new_session=True)
            try:
                identity=jobs._process_identity(process.pid)
                self.assertIsNotNone(identity)
                (directory/'run-lock.json').write_text(json.dumps({'run_id':run_id,'job_id':job_id,'scene_revision':7,'requested_physics_steps':120}))
                (directory/'latest-observation.json').write_text(json.dumps({'physics_steps':30,'simulation_time_s':.5}))
                meta={'run_id':run_id,'job_id':job_id,'pid':process.pid,'identity':identity}
                (directory/'job.json').write_text(json.dumps(meta))
                status=jobs.status(job_id)
                self.assertEqual(status['state'],'running');self.assertEqual(status['run_id'],run_id)
                self.assertEqual(status['progress']['physics_steps'],30)
                self.assertEqual(status['progress']['requested_physics_steps'],120)
                self.assertIsNotNone(status['last_observation_utc'])
                jobs._jobs.pop(job_id)
                meta['identity']['start_ticks']+=1
                (directory/'job.json').write_text(json.dumps(meta))
                self.assertEqual(jobs.status(job_id)['state'],'failed')
                self.assertIsNone(process.poll())
                jobs._jobs.pop(job_id)
                if hasattr(os,'pidfd_open'):
                    meta['identity']=identity
                    meta['identity']['start_ticks']-=1
                    (directory/'job.json').write_text(json.dumps(meta))
                    self.assertEqual(jobs.status(job_id)['state'],'running')
                    jobs.cancel(job_id);process.wait(timeout=5)
                    self.assertEqual(jobs.status(job_id)['state'],'cancelled')
                    jobs._jobs.pop(job_id)
                (directory/'result.json').write_text(json.dumps({'samples':[], 'requested_physics_steps':120, 'actual_physics_steps':120}))
                result=jobs.status(job_id)
                self.assertEqual(result['state'],'completed');self.assertTrue(result['exit_code_inferred'])
            finally:
                jobs._jobs.pop(job_id,None)
                process.terminate();process.wait(timeout=5)
