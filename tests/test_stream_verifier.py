import json,unittest
import copy
from pathlib import Path
from simscene.verification.stream_probe import evaluate
class StreamVerifierTest(unittest.TestCase):
    def test_upstream_routing_record_and_negative_control(self):
        case=json.loads(Path('tests/fixtures/three_arm_stream_case.json').read_text())
        run=json.loads(Path('evidence/three-arm-stream3.json').read_text())
        spec=json.loads(Path('evidence/three-arm-stream3-spec.json').read_text())
        result=evaluate(run,spec,case)
        self.assertTrue(result['passed']);self.assertEqual(result['ledger']['correct'],3)
        run['robot_contacts']['/World/kawasaki/Asset/left_inner_finger|/World/part0000|kawasaki:0']={'count':1}
        result=evaluate(run,spec,case)
        self.assertFalse(result['passed']);self.assertFalse(result['checks']['no_wrong_robot_contact'])

    def test_missing_run_cannot_pass_or_invent_success(self):
        case=json.loads(Path('tests/fixtures/three_arm_stream_case.json').read_text())
        result=evaluate({}, {'objects':{}},case)
        self.assertFalse(result['passed']);self.assertEqual(result['ledger']['generated'],0)
        self.assertIsNone(result['ledger']['success_rate'])
    def test_wrong_robot_proximity_is_not_reported_as_physical_contact(self):
        case=json.loads(Path('tests/fixtures/three_arm_stream_case.json').read_text())
        run=json.loads(Path('evidence/three-arm-stream3.json').read_text())
        spec=json.loads(Path('evidence/three-arm-stream3-spec.json').read_text())
        key='/World/kawasaki/Asset/left_inner_finger|/World/part0000|kawasaki:0'
        run['contact_geometry_incomplete']=False
        run['robot_contacts'][key]={'count':1,'minimum_separation_m':.004}
        checked=evaluate(run,spec,case)
        self.assertTrue(checked['checks']['no_wrong_robot_contact'])
        self.assertIn(key,checked['wrong_robot_proximity'])
        for separation in (0.,-.001,None):
            run['robot_contacts'][key]['minimum_separation_m']=separation
            self.assertFalse(evaluate(run,spec,case)['checks']['no_wrong_robot_contact'])
        run['robot_contacts'][key]['minimum_separation_m']=.004
        run['contact_geometry_incomplete']=True
        self.assertFalse(evaluate(run,spec,case)['checks']['no_wrong_robot_contact'])
        run['robot_contacts'].pop(key)
        pair='/World/kawasaki/Asset/link1|/World/franka/Asset/panda_link1|kawasaki:0,franka:0'
        run['contact_geometry_incomplete']=False
        run['robot_contacts'][pair]={'count':1,'minimum_separation_m':.002}
        near=evaluate(run,spec,case)
        self.assertTrue(near['checks']['no_arm_arm_contact'])
        self.assertIn(pair,near['cross_arm_proximity'])
        run['robot_contacts'][pair]['minimum_separation_m']=0.
        self.assertFalse(evaluate(run,spec,case)['checks']['no_arm_arm_contact'])
    def test_duplicate_spawn_is_invalid(self):
        case=json.loads(Path('tests/fixtures/three_arm_stream_case.json').read_text())
        run={'spawn_events':[{'id':'part0000'},{'id':'part0000'}]}
        result=evaluate(run,{'objects':{}},case)
        self.assertFalse(result['passed']);self.assertIsNone(result['ledger']['success_rate'])
        self.assertEqual(result['ledger']['failed_or_unfinished'],2)
    def test_a_second_object_with_same_class_does_not_define_a_wrong_bin(self):
        case=json.loads(Path('tests/fixtures/three_arm_stream9_case.json').read_text())
        run={'spawn_events':[{'id':'part0002','class_label':'red'}],
             'bounds':{'part0002':{'min':[.1,-.81,.30],'max':[.14,-.77,.34]}}}
        result=evaluate(run,{'objects':{}},case)
        self.assertEqual(result['ledger']['wrong_bin'],0)
        self.assertEqual(result['ledger']['objects'][0]['state'],'failed_or_unfinished')

    def test_thresholds_require_each_arm_and_parallel_activity(self):
        case=json.loads(Path('tests/fixtures/three_arm_stream_case.json').read_text())
        case['acceptance_thresholds']={'overall_success_rate':.9,'per_robot_success_rate':.85,'minimum_parallel_steps':1}
        run=json.loads(Path('evidence/three-arm-stream3.json').read_text())
        spec=json.loads(Path('evidence/three-arm-stream3-spec.json').read_text())
        result=evaluate(run,spec,case)
        self.assertTrue(result['checks']['minimum_overall_success_rate'])
        self.assertTrue(result['checks']['minimum_per_robot_success_rate'])
        self.assertFalse(result['checks']['simultaneous_cycles_observed'])
        self.assertFalse(result['passed'])
        for item in case['objects']:
            transitions=run['followers'][item['robot_id']]['transitions']
            for event in transitions:
                if event['index']==item['tracking_phase']:event['physics_step']=1000
                if event['index']==item['release_phase']+1:event['physics_step']=1100
        overlapping=evaluate(run,spec,case)
        self.assertEqual(overlapping['parallel_steps'],[1000,1100])
        self.assertTrue(overlapping['checks']['simultaneous_cycles_observed'])
        run['spawn_events'][0]['class_label']='red'
        self.assertFalse(evaluate(run,spec,case)['checks']['spawn_classes_match'])

    def test_archived_object_requires_actual_terminal_observation(self):
        case=json.loads(Path('tests/fixtures/three_arm_stream_case.json').read_text())
        run=json.loads(Path('evidence/three-arm-stream3.json').read_text())
        spec=json.loads(Path('evidence/three-arm-stream3-spec.json').read_text())
        part='part0002';path='/World/'+part
        next(item for item in case['objects'] if item['part_id']==part)['evidence_per_item']=True
        frame=next(s for s in run['samples'] if s['simulation_time_s']>=run['simulation_time_s']-2)
        run['archived_objects']={part:{'part_id':part,'class_label':'red','terminal_state':'correct','physics_step':frame['physics_steps'],'simulation_time_s':frame['simulation_time_s'],'position':frame['positions'][path], 'bounds':run['bounds'][part]}}
        for sample in run['samples']:
            if sample['physics_steps']>frame['physics_steps']:
                sample['positions'].pop(path,None);sample.get('orientations_wxyz',{}).pop(path,None)
        run['positions'].pop(path,None);run['bounds'].pop(part,None)
        result=evaluate(run,spec,case)
        self.assertTrue(result['objects'][part]['passed'])
        self.assertTrue(result['passed'])
        bad=copy.deepcopy(run);bad['archived_objects'][part]['position']=[100,100,100]
        self.assertFalse(evaluate(bad,spec,case)['objects'][part]['checks']['archive_matches_observation'])
        bad=copy.deepcopy(run);bad['archived_objects'][part]['physics_step']=1
        self.assertFalse(evaluate(bad,spec,case)['objects'][part]['passed'])
