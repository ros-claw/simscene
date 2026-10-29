"""Exercise real queue processes, pause/resume, and job status without Isaac."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from simscene import jobs
from simscene.scene import SceneStore


class JobQueueIntegrationTest(unittest.TestCase):
    def test_queued_pause_does_not_hold_the_simulator_slot(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);runtime=root/'fake-python.sh'
            runtime.write_text('#!/bin/sh\nsleep 0.7\nprintf \'{"samples":[],"requested_physics_steps":10,"actual_physics_steps":10}\' > "$3"\n');runtime.chmod(0o700)
            with patch.dict(os.environ,{'SIMSCENE_HOME':directory,'SIMSCENE_ISAAC_PYTHON':str(runtime)}):
                SceneStore().open('scene');started=[]
                # Run the unchanged queue wrapper with an isolated test lock,
                # so a real simulation can be active during this CPU test.
                popen = jobs.subprocess.Popen
                def isolated_queue(command, *args, **kwargs):
                    source = 'import runpy,sys; m=runpy.run_path(sys.argv[1]); m["launch"](sys.argv[2],sys.argv[4:],sys.argv[3])'
                    wrapped = [command[0], '-c', source, command[1], command[2], str(root/'lock'), *command[3:]]
                    return popen(wrapped, *args, **kwargs)
                def wait_for(job,states,timeout=8):
                    end=time.monotonic()+timeout
                    while time.monotonic()<end:
                        state=jobs.status(job['job_id'])['state']
                        if state in states:return state
                        time.sleep(.03)
                    self.fail(f'job did not reach {states}: {state}')
                try:
                    with patch('simscene.jobs.export_scene',side_effect=lambda scene,path:path.write_text('stage')), patch('simscene.jobs.subprocess.Popen',side_effect=isolated_queue):
                        first=jobs.start('scene',10,request_id='one');started.append(first)
                        wait_for(first,{'running'})
                        second=jobs.start('scene',10,request_id='two');started.append(second)
                        wait_for(second,{'queued'})
                        jobs.set_paused(second['job_id'],True);wait_for(second,{'paused'})
                        wait_for(first,{'completed'})
                        third=jobs.start('scene',10,request_id='three');started.append(third)
                        wait_for(third,{'running','completed'});wait_for(third,{'completed'})
                        self.assertEqual(jobs.status(second['job_id'])['state'],'paused')
                        jobs.set_paused(second['job_id'],False);wait_for(second,{'completed'})
                    states=[json.loads((root/'runs'/job['run_id']/'gpu-queue.json').read_text()) for job in (first,third,second)]
                    self.assertTrue(all(item['state']=='running' for item in states))
                    self.assertLess(states[0]['started_unix_ns'],states[1]['started_unix_ns'])
                    self.assertLess(states[1]['started_unix_ns'],states[2]['started_unix_ns'])
                finally:
                    for job in started:
                        data=jobs._jobs.pop(job['job_id'],None)
                        if data and data['process'].poll() is None:
                            os.killpg(data['process'].pid,15);data['process'].wait(timeout=3)


if __name__=='__main__':unittest.main()
