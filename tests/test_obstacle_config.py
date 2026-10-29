"""Reactive obstacle planning accepts only explicit static collision shapes."""
import tempfile
import unittest
from pathlib import Path
from simscene.scene import SceneError,SceneStore

class ObstacleConfigTest(unittest.TestCase):
    def test_validate_obstacle_references_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            store=SceneStore(Path(directory));store.open('s')
            follower={'experimental':True,'model_directory':'/tmp/model','tool_frame':'tcp','tcp_prim':'tcp','target_position':[0,0,1]}
            store.apply('s',0,'base',[{'op':'add','id':'arm','object':{'kind':'asset','asset_path':'/tmp/model.usd','pose_follower':follower}},
                                     {'op':'add','id':'pole','object':{'kind':'box','collision':True,'size':[.1,.1,1]}},
                                     {'op':'add','id':'moving','object':{'kind':'box','dynamic':True}},
                                     {'op':'add','id':'visual','object':{'kind':'box'}}])
            for obstacles,margin in [(['missing'],.01),(['moving'],.01),(['visual'],.01),(['pole','pole'],.01),([{}],.01),(['pole'],.2)]:
                updated=dict(follower,avoid_obstacles=obstacles,obstacle_margin_m=margin)
                with self.subTest(obstacles=obstacles,margin=margin),self.assertRaises(SceneError):
                    store.apply('s',1,'bad',[{'op':'update','id':'arm','changes':{'pose_follower':updated}}])
                self.assertEqual(store.get('s')['revision'],1)
            updated=dict(follower,avoid_obstacles=['pole'],obstacle_margin_m=.01)
            store.apply('s',1,'good',[{'op':'update','id':'arm','changes':{'pose_follower':updated}}])
            self.assertEqual(store.get('s')['objects']['arm']['pose_follower']['avoid_obstacles'],['pole'])
            with self.assertRaises(SceneError):store.apply('s',2,'remove',[{'op':'remove','id':'pole'}])
            self.assertEqual(store.get('s')['revision'],2)

if __name__=='__main__':unittest.main()
