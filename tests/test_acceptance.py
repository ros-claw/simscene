import json,tempfile,unittest
from pathlib import Path
from simscene.verification.acceptance import evaluate, _resources

class AcceptanceTest(unittest.TestCase):
    def test_formal_collision_policy_cannot_be_widened_by_case(self):
        case=json.loads(Path('tests/fixtures/three_arm_stream60_audited_case.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'case.json';path.write_text(json.dumps(case))
            self.assertTrue(evaluate([],directory,path)['checks']['fixed_collision_policy'])
            case['collision_policy']['mechanical_pairs']['franka'].append(['panda_link1','panda_link7'])
            path.write_text(json.dumps(case))
            self.assertFalse(evaluate([],directory,path)['checks']['fixed_collision_policy'])

    def test_small_record_and_missing_runs_cannot_be_formal_acceptance(self):
        case='tests/fixtures/three_arm_stream_case.json'
        report=evaluate(['missing1','missing2','missing3'],'missing4',case)
        self.assertFalse(report['passed'])
        self.assertFalse(report['checks']['fixed_case_shape'])
        self.assertFalse(report['checks']['all_runs_readable'])
        self.assertEqual(len(report['errors']),4)

    def test_ten_minute_resource_record_requires_complete_bounded_samples(self):
        samples=[{'physics_steps':n,'rss_bytes':100,'gpu_process_memory_bytes':200} for n in range(0,36001,3600)]
        self.assertTrue(_resources({'actual_physics_steps':36000,'resources':samples}))
        missing=[dict(x) for x in samples];missing[5]['gpu_process_memory_bytes']=None
        self.assertFalse(_resources({'actual_physics_steps':36000,'resources':missing}))
        self.assertFalse(_resources({'actual_physics_steps':36000,'resources':samples[:-1]}))
        self.assertFalse(_resources({'actual_physics_steps':36000,'resources':samples[:2]+samples[3:]}))
