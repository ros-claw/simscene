"""Regression for an explicit suction lift requirement."""
import copy
import json
from pathlib import Path
import unittest
from simscene.verification.suction_pick import evaluate


class SuctionLiftTest(unittest.TestCase):
    def test_lift_uses_measured_object_height_and_fails_closed(self):
        case=json.loads(Path('tests/fixtures/ur10_suction_static_case.json').read_text())
        case.update(tracking_phase=0, held_phases=[2], release_phase=3,
                    evidence_per_item=True, minimum_lift_m=.08)
        path=case['part_path']; robot=case['robot_id']
        samples=[]
        for step,z in [(10,.3),(15,.3),(20,.3),(25,.35),(30,.42),(35,.42)]:
            samples.append({'physics_steps':step,'simulation_time_s':step/60,
                            'positions':{path:[0,0,z]},'orientations_wxyz':{},
                            'followers':{robot:{'sequence_index':2,'suction':{'gripped':[path]}}}})
        run={'samples':samples,'followers':{robot:{'transitions':[{'index':i,'physics_step':i*10} for i in range(1,6)]}},
             'robot_contacts':{},'monitored_robot_ids':[robot],'contacts_truncated':False}
        self.assertTrue(evaluate(run,case)['checks']['lifted'])
        flat=copy.deepcopy(run)
        for frame in flat['samples']:frame['positions'][path][2]=.3
        self.assertFalse(evaluate(flat,case)['checks']['lifted'])
        flat['followers'][robot]['transitions']=[]
        self.assertFalse(evaluate(flat,case)['checks']['lifted'])


if __name__ == '__main__':
    unittest.main()
