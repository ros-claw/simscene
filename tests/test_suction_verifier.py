import json,unittest
from pathlib import Path
from simscene.verification.suction_pick import evaluate
class SuctionVerifierTest(unittest.TestCase):
    def test_missing_evidence_never_passes(self):
        case=json.loads(Path('tests/fixtures/ur10_suction_static_case.json').read_text())
        result=evaluate({},case)
        self.assertFalse(result['passed']);self.assertFalse(result['checks']['suction_acquired_target']);self.assertFalse(result['checks']['no_robot_belt_table_or_bin_contact'])
