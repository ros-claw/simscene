import json,unittest
from pathlib import Path
from simscene.verification.domino import evaluate
class DominoVerifierTest(unittest.TestCase):
    def test_chain_and_missing_contact(self):
        case=json.loads(Path('tests/fixtures/domino_case.json').read_text())
        run=json.loads(Path('evidence/domino-probe.json').read_text())
        self.assertTrue(evaluate(run,case)['passed'])
        run['contact_counts'].pop('tile2|/World/tile3|')
        self.assertFalse(evaluate(run,case)['passed'])
    def test_missing_observation_fails(self):
        case=json.loads(Path('tests/fixtures/domino_case.json').read_text())
        self.assertFalse(evaluate({},case)['passed'])
