import copy,json,unittest
from pathlib import Path
from simscene.verification.parallel_probe import evaluate
class ParallelVerifierTest(unittest.TestCase):
    def test_real_run_and_unsafe_or_missing_evidence(self):
        run=json.loads(Path('evidence/three-arm-probe-v5.json').read_text())
        spec=json.loads(Path('evidence/three-arm-probe-v5-spec.json').read_text())
        case=json.loads(Path('tests/fixtures/three_arm_probe_case.json').read_text())
        self.assertTrue(evaluate(run,spec,case)['passed'])
        altered=copy.deepcopy(spec);altered['objects']['part_f']['class_label']='red'
        self.assertFalse(evaluate(run,altered,case)['passed'])
        altered=copy.deepcopy(run);altered['robot_contacts']['/World/franka/Asset/panda_hand|/World/ur10/Asset/ee_link|franka:3']={'count':1}
        self.assertFalse(evaluate(altered,spec,case)['passed'])
        altered=copy.deepcopy(run)
        for frame in altered['samples']:frame.pop('orientations_wxyz',None)
        self.assertFalse(evaluate(altered,spec,case)['passed'])
