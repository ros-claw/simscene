import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

class StaticVerifierTest(unittest.TestCase):
    def test_missing_contact_or_release_cannot_pass(self):
        record={'samples':[{'phase':'close','step':0,'cube':[0,0,.32]}, {'phase':'lift','step':0,'cube':[0,0,.45]}, {'phase':'retract','step':0,'cube':[.28,-.5,.32]}, {'phase':'retract','step':60,'cube':[.28,-.5,.32]}], 'contact_counts':{}}
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'run.json';path.write_text(json.dumps(record))
            result=subprocess.run([sys.executable,'experiments/verify_static_place.py',str(path),'tests/fixtures/rs007l_static_case.json'],capture_output=True,text=True,check=True)
            checks=json.loads(result.stdout)
            self.assertFalse(checks['passed'])
            self.assertFalse(checks['checks']['left_contact_in_lift'])
            self.assertFalse(checks['checks']['fingers_retracted'])
