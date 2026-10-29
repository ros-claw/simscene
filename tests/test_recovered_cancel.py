"""A recovered cancellation must stop a launcher and its child process."""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch
from simscene import jobs


@unittest.skipUnless(hasattr(os,'pidfd_open') and hasattr(signal,'pidfd_send_signal'),'Linux pidfd required')
class RecoveredCancelTest(unittest.TestCase):
    def test_reattached_cancel_stops_the_entire_worker_group(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run_id=uuid.uuid4().hex;job_id=uuid.uuid4().hex;run=root/'runs'/run_id;run.mkdir(parents=True)
            process=subprocess.Popen(['bash','-c','python3 -c "import time; time.sleep(20)" || true'],start_new_session=True)
            try:
                child=None;deadline=time.monotonic()+3
                while time.monotonic()<deadline and child is None:
                    result=subprocess.run(['pgrep','-P',str(process.pid)],capture_output=True,text=True)
                    if result.stdout.strip():child=int(result.stdout.splitlines()[0])
                    else:time.sleep(.02)
                self.assertIsNotNone(child)
                identity=jobs._process_identity(process.pid)
                (run/'job.json').write_text(json.dumps({'run_id':run_id,'job_id':job_id,'pid':process.pid,'identity':identity}))
                (run/'run-lock.json').write_text(json.dumps({'run_id':run_id,'job_id':job_id,'scene_revision':0}))
                with patch.dict(os.environ,{'SIMSCENE_HOME':directory}):
                    jobs.cancel(job_id);process.wait(timeout=3)
                    def alive(pid):
                        try:
                            raw=Path('/proc',str(pid),'stat').read_text();state=raw[raw.rfind(')')+2:].split()[0]
                            return state not in ('Z','X')
                        except OSError:return False
                    end=time.monotonic()+3
                    while alive(child) and time.monotonic()<end:time.sleep(.02)
                    self.assertFalse(alive(child))
                    self.assertEqual(jobs.status(job_id)['state'],'cancelled')
                    jobs._jobs.pop(job_id,None)
            finally:
                try:os.killpg(process.pid,signal.SIGTERM)
                except ProcessLookupError:pass
                if process.poll() is None:process.kill();process.wait()


if __name__=='__main__':unittest.main()
