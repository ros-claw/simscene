"""Invalid whole-case collision coverage must fail before simulation starts."""
import copy
import unittest
from simscene.verification.collision_preflight import validate

class CollisionPreflightTest(unittest.TestCase):
    def fixture(self):
        follower={'monitor_collisions':True,'self_collision_enabled':True,'diagnose_overlaps':True,'self_collision_exclusions':[['link','finger']]}
        scene={'objects':{'a':{'pose_follower':copy.deepcopy(follower)},'b':{'pose_follower':copy.deepcopy(follower)}}}
        case={'expected_spawn_order':['one','two'],'objects':[{'robot_id':'a'},{'robot_id':'b'}],
              'collision_policy':{'mechanical_pairs':{'a':[['link','finger']],'b':[['finger','link']]},
                                  'allowed_mechanical_contacts':{'a':[],'b':[]},
                                  'grasp_bodies':{'a':['finger'],'b':['finger']}}}
        return scene,case
    def test_complete_case_passes_and_partial_policy_is_rejected(self):
        scene,case=self.fixture();validate(scene,case)
        del case['collision_policy']['grasp_bodies']['b']
        with self.assertRaisesRegex(ValueError,'cover exactly all case robots'):validate(scene,case)
    def test_all_robot_diagnostics_and_exclusions_must_match(self):
        scene,case=self.fixture()
        scene['objects']['b']['pose_follower']['diagnose_overlaps']=False
        with self.assertRaisesRegex(ValueError,'diagnose_overlaps'):validate(scene,case)
        scene,case=self.fixture();case['collision_policy']['mechanical_pairs']['a']=[]
        with self.assertRaisesRegex(ValueError,'self_collision_exclusions'):validate(scene,case)
        scene,case=self.fixture();case['collision_policy']['grasp_bodies']['a']=['a/b']
        with self.assertRaisesRegex(ValueError,'body names'):validate(scene,case)
    def test_optional_without_collision_case(self):
        scene,case=self.fixture();del case['collision_policy'];validate(scene,case)

if __name__=='__main__':unittest.main()
