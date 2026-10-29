"""Case proposals retain explicit destinations and reject ambiguous routes."""
import json
from pathlib import Path
import tempfile
import unittest
from simscene.scene_edits.stream_case import plan_case
from simscene.scene import SceneError


class StreamCaseTest(unittest.TestCase):
    def test_builds_per_item_physical_checks_from_explicit_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); f = root/'f'; u = root/'u'; f.mkdir(); u.mkdir()
            (f/'profile.json').write_text(json.dumps({'model':'franka_panda'}))
            (u/'profile.json').write_text(json.dumps({'model':'ur10_short_suction'}))
            def follower(model, item):
                return {'monitor_collisions':True,'model_directory':str(model),'sequence':[
                    {'type':'wait_object','object':item},{'type':'track','object':item},
                    {'type':'track','object':item,'gripper_value':0},{'type':'move','object':item},
                    {'type':'move','position':[0,0,1]},{'type':'move','position':[0,0,.5]},
                    {'type':'gripper','value':1},{'type':'move','position':[0,0,1]},
                    {'type':'move','position':[0,0,1]}]}
            scene={'objects':{'belt':{'kind':'box','conveyor':{'direction':[1,0,0],'speed_m_s':.03}},
                 'bin':{'kind':'box'}, 'f':{'pose_follower':follower(f,'a')}, 'u':{'pose_follower':follower(u,'b')},
                 'a':{'kind':'box','dynamic':True,'spawn_step':1,'class_label':'red','position':[0,0,0]},
                 'b':{'kind':'box','dynamic':True,'spawn_step':601,'class_label':'blue','position':[0,0,0]}}}
            bins={'red':{'min':[0,0,0],'max':[1,1,1]},'blue':{'min':[2,0,0],'max':[3,1,1],'pass_x':[1]}}
            result=plan_case(scene,'belt',bins,['belt','bin'])
            self.assertEqual(result['case']['expected_spawn_order'],['a','b'])
            self.assertEqual(result['case']['objects'][0]['lift_phase'],3)
            self.assertEqual(result['case']['objects'][1]['held_phases'],[3,4,5])
            self.assertEqual(result['case']['objects'][1]['bin_min'],[2,0,0])
            self.assertIn('not independent',result['scope'])
            with self.assertRaises(SceneError):
                plan_case(scene,'belt',{'red':bins['red']},['belt','bin'])
            scene['objects']['belt']['conveyor']['direction']=[0,1,0]
            with self.assertRaises(SceneError):
                plan_case(scene,'belt',bins,['belt','bin'])


if __name__ == '__main__':
    unittest.main()
