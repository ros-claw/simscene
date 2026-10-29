"""A collision proposal is explicit, model-bound and does not edit the scene."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from simscene.scene import SceneError
from simscene.scene_edits.collision_audit import propose
from simscene.verification.acceptance import COLLISION_POLICY

class CollisionAuditProposalTest(unittest.TestCase):
    def scene(self):
        def robot(path):
            return {'kind':'asset', 'asset_path':path, 'pose_follower':{'experimental':True,
                    'model_directory':'/tmp/model', 'tool_frame':'tcp', 'tcp_prim':'tcp',
                    'target_position':[0,0,1], 'sequence':[]}}
        return {'objects':{'arm':robot('/assets/Kawasaki/RS007L/rs007l_onrobot_rg2.usd'),
                           'panda':robot('/assets/FrankaRobotics/FrankaPanda/franka.usd')}}
    def test_proposes_model_specific_exclusions_without_mutation(self):
        scene = self.scene(); original = copy.deepcopy(scene)
        result = propose(scene, ['arm','panda'])
        self.assertEqual(scene, original)
        self.assertEqual(result['collision_policy']['mechanical_pairs']['arm'], COLLISION_POLICY['mechanical_pairs']['kawasaki'])
        self.assertEqual(result['collision_policy']['mechanical_pairs']['panda'], [])
        self.assertEqual(result['collision_policy']['allowed_mechanical_contacts']['panda'], COLLISION_POLICY['allowed_mechanical_contacts']['franka'])
        for op in result['operations']:
            follower = op['changes']['pose_follower']
            self.assertTrue(follower['monitor_collisions'] and follower['self_collision_enabled'] and follower['diagnose_overlaps'])
            self.assertEqual(follower['sequence'], [])
        result['collision_policy']['mechanical_pairs']['arm'].clear()
        self.assertEqual(len(COLLISION_POLICY['mechanical_pairs']['kawasaki']), 6)
        scene['objects']['panda2'] = copy.deepcopy(scene['objects']['panda'])
        repeated = propose(scene, ['panda','panda2'])
        self.assertEqual(set(repeated['collision_policy']['grasp_bodies']), {'panda','panda2'})
    def test_unknown_duplicate_and_malformed_models_fail_closed(self):
        scene = self.scene()
        for ids in ([], ['arm','arm'], [{}], ['missing']):
            with self.subTest(ids=ids), self.assertRaises(SceneError): propose(scene, ids)
        scene['objects']['arm']['asset_path'] = '/some/other/robot.usd'
        with self.assertRaises(SceneError): propose(scene, ['arm'])

    def test_flattened_download_uses_matching_generated_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); asset=root/'flat'/'franka.usd';asset.parent.mkdir();asset.touch()
            profile=root/'profile';profile.mkdir()
            (profile/'profile.json').write_text(json.dumps({'model':'franka_panda','asset_path':str(asset)}))
            scene=self.scene();scene['objects']['panda']['asset_path']=str(asset)
            scene['objects']['panda']['pose_follower']['model_directory']=str(profile)
            proposal=propose(scene,['panda'])
            self.assertEqual(proposal['collision_policy']['grasp_bodies']['panda'],['panda_leftfinger','panda_rightfinger'])
            (profile/'profile.json').write_text(json.dumps({'model':'franka_panda','asset_path':str(root/'different.usd')}))
            with self.assertRaises(SceneError):propose(scene,['panda'])

if __name__ == '__main__': unittest.main()
