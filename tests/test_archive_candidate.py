import copy,json,unittest
from pathlib import Path
from simscene.verification.archive_candidate import evaluate_item,validate_case

class ArchiveCandidateTest(unittest.TestCase):
    def test_case_must_cover_all_workpieces_and_keep_physical_thresholds(self):
        spec=json.loads(Path('evidence/three-arm-stream9-hover-v3-spec.json').read_text())
        case=json.loads(Path('tests/fixtures/three_arm_stream9_hover_case.json').read_text())
        validate_case(spec,case)
        bad=copy.deepcopy(case);bad['objects'].pop()
        with self.assertRaises(ValueError):validate_case(spec,bad)
        bad=copy.deepcopy(case);bad['common']['max_linear_velocity_m_s']=2
        with self.assertRaises(ValueError):validate_case(spec,bad)
        bad=copy.deepcopy(case);bad['objects'][0]['class_label']='other'
        with self.assertRaises(ValueError):validate_case(spec,bad)

    def test_real_recorded_pick_passes_and_forged_terminal_pose_fails(self):
        run=json.loads(Path('evidence/three-arm-stream3.json').read_text())
        spec=json.loads(Path('evidence/three-arm-stream3-spec.json').read_text())
        case=json.loads(Path('tests/fixtures/three_arm_stream_case.json').read_text())
        item=next(x for x in case['objects'] if x['part_id']=='part0002');item['evidence_per_item']=True
        frame=next(s for s in run['samples'] if s['simulation_time_s']>=run['simulation_time_s']-2)
        run['samples']=[s for s in run['samples'] if s['physics_steps']<=frame['physics_steps']]
        run['simulation_time_s']=frame['simulation_time_s']
        event={'part_id':item['part_id'],'class_label':item['class_label'],'terminal_state':'correct','physics_step':frame['physics_steps'],'simulation_time_s':frame['simulation_time_s'],'position':frame['positions'][item['part_path']],'bounds':run['bounds'][item['part_id']]}
        result=evaluate_item(run,spec,case,item,event)
        self.assertTrue(result['passed'],[k for k,v in result['checks'].items() if not v])
        event['bounds']['max'][0]+=1
        self.assertFalse(evaluate_item(run,spec,case,item,event)['checks']['terminal_observation_matches_geometry'])
