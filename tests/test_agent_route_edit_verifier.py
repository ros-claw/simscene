"""The independent edit checker must reject missing or unchanged evidence."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class AgentRouteEditVerifierTest(unittest.TestCase):
    def test_swap_requires_both_changed_ownership_and_a_real_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'state'/'runs').mkdir(parents=True)
            case = root/'pre_registered_case.json'
            shutil.copyfile(ROOT/'tests/fixtures/agent_route_edit_case.json', case)
            (root/'pre_registered_case.sha256').write_text(hashlib.sha256(case.read_bytes()).hexdigest())
            checker = root/'frozen-checker.py'
            shutil.copyfile(ROOT/'experiments/verify_agent_route_edit.py', checker)
            (root/'frozen-checker.sha256').write_text(hashlib.sha256(checker.read_bytes()).hexdigest())
            (root/'exit-code.txt').write_text('0')
            (root/'evaluation-config.json').write_text(json.dumps({'mode':'swap'}))
            objects = {'r':{'class_label':'red'}, 'g':{'class_label':'green'},
                       'arm_a':{'pose_follower':{'sequence':[{'type':'wait_object','object':'r'}]}},
                       'arm_b':{'pose_follower':{'sequence':[{'type':'wait_object','object':'g'}]}}}
            before = {'scene_id':'scene', 'revision':1, 'objects':objects}
            after = json.loads(json.dumps(before)); after['revision'] = 2
            (root/'before.json').write_text(json.dumps(before))
            def report():
                (root/'after.json').write_text(json.dumps(after))
                result = subprocess.run([sys.executable, str(checker), str(root)], text=True, capture_output=True,
                                        env=dict(os.environ, PYTHONPATH=str(ROOT/'src')), check=False)
                self.assertEqual(result.returncode, 1, result.stderr)
                return json.loads(result.stdout)
            unchanged = report()
            self.assertFalse(unchanged['checks']['requested_owners_swapped'])
            self.assertFalse(unchanged['passed'])
            after['objects']['arm_a']['pose_follower']['sequence'][0]['object'] = 'g'
            after['objects']['arm_b']['pose_follower']['sequence'][0]['object'] = 'r'
            swapped = report()
            self.assertTrue(swapped['checks']['requested_owners_swapped'])
            self.assertFalse(swapped['checks']['completed_run_of_edited_revision'])
            self.assertFalse(swapped['passed'])

if __name__ == '__main__':
    unittest.main()
