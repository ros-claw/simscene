import json
import unittest
from pathlib import Path
from simscene.verification.contact_pick import evaluate

class ContactVerifierTest(unittest.TestCase):
    def setUp(self):
        self.case=json.loads(Path('tests/fixtures/franka_static_case.json').read_text())

    def test_missing_evidence_fails(self):
        result=evaluate({},self.case)
        self.assertFalse(result['passed'])
        self.assertFalse(result['checks']['left_lift_contact'])
        self.assertFalse(result['checks']['no_forbidden_robot_environment_contact'])

    def test_zero_length_phase_cannot_establish_contact(self):
        follower={'transitions':[{'index':1,'physics_step':20},{'index':2,'physics_step':20}]}
        result=evaluate({'followers':{'arm':follower}},self.case)
        self.assertFalse(result['checks']['left_lift_contact'])
        self.assertFalse(result['checks']['right_lift_contact'])

    def test_invalid_open_direction_cannot_prove_release(self):
        self.case['open_direction']='unknown'
        result=evaluate({'followers':{'arm':{'gripper_joint_position':0.04}}},self.case)
        self.assertFalse(result['checks']['opened'])
