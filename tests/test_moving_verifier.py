import json,unittest
from pathlib import Path
from simscene.verification.moving_pick import evaluate

class MovingVerifierTest(unittest.TestCase):
    def test_missing_evidence_fails(self):
        case=json.loads(Path('tests/fixtures/rs007l_moving_case.json').read_text())
        result=evaluate({'followers':{'arm':{'sequence_index':7,'sequence_length':7,'sequence_error':None}},'samples':[]},case)
        self.assertFalse(result['passed'])
        self.assertFalse(result['checks']['contained'])
        self.assertFalse(result['checks']['belt_motion_observed'])
        self.assertFalse(result['checks']['contacts_complete'])
