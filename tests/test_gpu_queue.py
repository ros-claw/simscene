"""Two launched jobs must not enter the simulated GPU section together."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]


class GPUQueueTest(unittest.TestCase):
    def test_child_retains_queue_lock_if_wrapper_is_killed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);lock=root/'lock';lock.mkdir(mode=0o700)
            source='from simscene.worker.gpu_queue import launch; import sys; raise SystemExit(launch(sys.argv[1],sys.argv[3:],sys.argv[2]))'
            env=dict(os.environ,PYTHONPATH=os.pathsep.join([str(ROOT/'src'),str(ROOT)]))
            def child(name,duration):
                folder=root/name;folder.mkdir();state=folder/'queue.json';state.write_text('{"state":"queued"}')
                marker=folder/'started'
                program='from pathlib import Path; import sys,time; Path(sys.argv[1]).write_text("started"); time.sleep(float(sys.argv[2]))'
                return subprocess.Popen([sys.executable,'-c',source,str(state),str(lock),sys.executable,'-c',program,str(marker),str(duration)],env=env),marker
            first,marker=child('first',1.0)
            second=None
            try:
                end=time.monotonic()+5
                while not marker.exists() and time.monotonic()<end:time.sleep(.02)
                self.assertTrue(marker.exists())
                first.kill();first.wait(timeout=3)
                second,other=child('second',.05)
                time.sleep(.2)
                self.assertFalse(other.exists(),'orphaned simulator must still own the queue lock')
                self.assertEqual(second.wait(timeout=4),0)
                self.assertTrue(other.exists())
            finally:
                if first.poll() is None:first.kill();first.wait()
                if second is not None and second.poll() is None:second.kill();second.wait()

    def test_real_child_exit_is_persisted_before_wrapper_exits(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run=root/'run';run.mkdir();lock=root/'lock';lock.mkdir(mode=0o700)
            state=run/'gpu-queue.json';state.write_text('{"state":"queued"}')
            source='from simscene.worker.gpu_queue import launch; import sys; raise SystemExit(launch(sys.argv[1],sys.argv[3:],sys.argv[2]))'
            env=dict(os.environ,PYTHONPATH=os.pathsep.join([str(ROOT/'src'),str(ROOT)]))
            process=subprocess.Popen([sys.executable,'-c',source,str(state),str(lock),sys.executable,'-c','raise SystemExit(7)'],env=env)
            self.assertEqual(process.wait(timeout=5),7)
            record=json.loads((run/'process-exit.json').read_text())
            self.assertEqual(record['schema'],'simscene.process_exit.v1')
            self.assertEqual(record['run_id'],'run')
            self.assertEqual(record['queue_pid'],process.pid)
            self.assertEqual(record['exit_code'],7)

    def test_jobs_serialize_and_a_queued_job_can_be_cancelled(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);lock=root/'lock';lock.mkdir(mode=0o700)
            def child(name,duration):
                folder=root/name;folder.mkdir();state=folder/'queue.json';state.write_text('{"state":"queued"}')
                marker=folder/'started'
                command=[sys.executable,'-c','from pathlib import Path; import sys,time; Path(sys.argv[1]).write_text(str(time.time_ns())); time.sleep(float(sys.argv[2]))',str(marker),str(duration)]
                source='from simscene.worker.gpu_queue import launch; import sys; launch(sys.argv[1],sys.argv[3:],sys.argv[2])'
                env=dict(os.environ,PYTHONPATH=os.pathsep.join([str(ROOT/'src'),str(ROOT)]))
                process=subprocess.Popen([sys.executable,'-c',source,str(state),str(lock),*command],env=env)
                return process,state,marker
            def until(predicate):
                end=time.monotonic()+5
                while time.monotonic()<end:
                    if predicate():return
                    time.sleep(.02)
                self.fail('timed out waiting for queue state')
            first,s1,m1=child('first',1.0)
            try:
                until(m1.exists)
                second,s2,m2=child('second',.1)
                try:
                    time.sleep(.2)
                    self.assertEqual(json.loads(s2.read_text())['state'],'queued')
                    self.assertFalse(m2.exists())
                    (s2.parent/'control-request.json').write_text(json.dumps({'action':'pause','request_id':'pause'}))
                    until(lambda:(s2.parent/'control-state.json').exists())
                    self.assertEqual(json.loads((s2.parent/'control-state.json').read_text())['state'],'paused')
                    first.wait(timeout=3);time.sleep(.2)
                    self.assertFalse(m2.exists())
                    (s2.parent/'control-request.json').write_text(json.dumps({'action':'resume','request_id':'resume'}))
                    until(m2.exists);second.wait(timeout=3)
                    third,s3,m3=child('third',.05)
                    try:
                        until(m3.exists);third.wait(timeout=3)
                        self.assertEqual(json.loads(s3.read_text())['state'],'running')
                        self.assertGreater(int(m3.read_text()),int(m1.read_text()))
                    finally:
                        if third.poll() is None:third.kill();third.wait()
                    active,_,active_marker=child('active',1.0)
                    try:
                        until(active_marker.exists)
                        queued,_,queued_marker=child('queued',.1)
                        try:
                            time.sleep(.2);self.assertFalse(queued_marker.exists())
                            queued.terminate();queued.wait(timeout=3)
                            self.assertFalse(queued_marker.exists())
                        finally:
                            if queued.poll() is None:queued.kill();queued.wait()
                    finally:
                        if active.poll() is None:active.terminate();active.wait()
                finally:
                    if second.poll() is None:second.kill();second.wait()
            finally:
                if first.poll() is None:first.kill();first.wait()


if __name__=='__main__':
    unittest.main()
