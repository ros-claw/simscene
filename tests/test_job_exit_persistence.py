"""A reattached job must not mistake a crashed worker's result for success."""
import json,os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from simscene import jobs
from simscene.scene import SceneStore

class ExitPersistenceTest(unittest.TestCase):
    def test_reattachment_reads_actual_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);runtime=root/'simulator.sh'
            runtime.write_text('#!/bin/sh\nprintf \'{"samples":[]}\' > "$3"\nexit 7\n');runtime.chmod(0o700)
            with patch.dict(os.environ,{'SIMSCENE_HOME':directory,'SIMSCENE_ISAAC_PYTHON':str(runtime)}):
                SceneStore().open('scene');popen=jobs.subprocess.Popen
                def isolated_queue(command,*args,**kwargs):
                    code='import runpy,sys; m=runpy.run_path(sys.argv[1]); raise SystemExit(m["launch"](sys.argv[2],sys.argv[4:],sys.argv[3]))'
                    return popen([command[0],'-c',code,command[1],command[2],str(root/'lock'),*command[3:]],*args,**kwargs)
                with patch('simscene.jobs.export_scene',side_effect=lambda scene,path:path.write_text('stage')),patch('simscene.jobs.subprocess.Popen',side_effect=isolated_queue):
                    job=jobs.start('scene',10)
                    process=jobs._jobs.pop(job['job_id'])['process']
                    self.assertEqual(process.wait(timeout=5),7)
                    recovered=jobs.status(job['job_id'])
                    self.assertEqual(recovered['state'],'failed')
                    self.assertEqual(recovered['exit_code'],7)
                    self.assertFalse(recovered['exit_code_inferred'])
                    jobs._jobs.pop(job['job_id'],None)

if __name__=='__main__':unittest.main()
