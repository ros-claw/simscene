"""The suction checker must honor the case's explicitly named obstacles."""
import json
from pathlib import Path
import unittest
from simscene.verification.suction_pick import evaluate


class SuctionObstacleTest(unittest.TestCase):
    def test_custom_obstacle_contact_is_forbidden(self):
        case=json.loads(Path('tests/fixtures/ur10_suction_static_case.json').read_text())
        case['forbidden_environment_paths']=['/World/custom_box']
        robot=case['robot_id']
        contact='/World/'+robot+'/Asset/ee_link|/World/custom_box|'+robot+':1'
        run={'robot_contacts':{contact:{'count':1}},'monitored_robot_ids':[robot],'contacts_truncated':False}
        report=evaluate(run,case)
        self.assertFalse(report['checks']['no_robot_belt_table_or_bin_contact'])
        self.assertIn(contact,report['forbidden_contacts'])


if __name__ == '__main__':
    unittest.main()
