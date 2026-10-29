import copy
import json
import unittest
from pathlib import Path
from simscene.verification.repeated_pick import evaluate

class RepeatedVerifierTest(unittest.TestCase):
    def test_missing_evidence_fails_closed(self):
        case=json.loads(Path('tests/fixtures/rs007l_repeated_case.json').read_text())
        self.assertFalse(evaluate({},case)['passed'])

    def test_actual_record_and_negative_controls(self):
        case=json.loads(Path('tests/fixtures/rs007l_repeated_case.json').read_text())
        run=json.loads(Path('evidence/rs007l-repeated-probe-v2.json').read_text())
        self.assertTrue(evaluate(run,case)['passed'])
        multi=copy.deepcopy(run)
        multi['contact_counts']={key+',other_arm:8':value for key,value in multi['contact_counts'].items()}
        self.assertTrue(evaluate(multi,case)['passed'])
        bad=copy.deepcopy(run);bad['spawn_events'][0]['class_label']='blue'
        self.assertFalse(evaluate(bad,case)['passed'])
        bad=copy.deepcopy(run);bad['robot_contacts']['/World/arm/Asset/finger|/World/belt|arm:2']={'count':1}
        self.assertFalse(evaluate(bad,case)['passed'])
        bad=copy.deepcopy(run)
        bad['samples']=[s for s in bad['samples'] if not 895<=s['physics_steps']<=905]
        self.assertFalse(evaluate(bad,case)['passed'])
