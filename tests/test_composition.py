import tempfile,unittest
from simscene.composition import plan_stream
from simscene.scene import SceneStore,SceneError
class StreamPlanTest(unittest.TestCase):
    def test_expands_class_routing_into_atomic_scene_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            store=SceneStore(directory);store.open('s')
            cfg={'experimental':True,'model_directory':'/m','tool_frame':'tcp','tcp_prim':'tcp','target_position':[0,0,1]}
            store.apply('s',0,'robot',[{'op':'add','id':'arm','object':{'kind':'asset','asset_path':'/r.usd','pose_follower':cfg}}])
            wait={'axis':'x','minimum':0,'maximum':1,'max_steps':100}
            routes={'red':{'robot_id':'arm','wait':wait,'slots':[[.2,.3,.4]],'cycle':[{'type':'move','position':'$slot','slot_offset':[0,0,.1]},{'type':'move','object':'$item','offset':[0,0,.2]}]},
                    'blue':{'robot_id':'arm','wait':wait,'cycle':[{'type':'move','object':'$item','offset':[0,0,.4]}]}}
            plan=plan_stream(store.get('s'),'part',['red','blue'],routes,[0,0,.3],[.04,.04,.04],30)
            self.assertEqual([a['spawn_step'] for a in plan['assignments']],[1,31])
            irregular=plan_stream(store.get('s'),'p',['red','blue'],routes,[0,0,.3],[.04,.04,.04],spawn_steps=[3,97])
            self.assertEqual([a['spawn_step'] for a in irregular['assignments']],[3,97])
            with self.assertRaises(SceneError):plan_stream(store.get('s'),'p',['red','blue'],routes,[0,0,.3],[.04,.04,.04],spawn_steps=[97,3])
            self.assertEqual(store.get('s')['revision'],1)
            store.apply('s',1,'stream',plan['operations'])
            scene=store.get('s');sequence=scene['objects']['arm']['pose_follower']['sequence']
            self.assertEqual(sequence[1]['position'],[.2,.3,.5])
            self.assertEqual(sequence[2]['object'],'part0000');self.assertEqual(sequence[4]['object'],'part0001')
            self.assertEqual(sequence[4]['offset'],[0,0,.4])
            with self.assertRaises(SceneError):plan_stream(scene,'again',['red'],routes,[0,0,.3],[.04]*3,30)
    def test_missing_route_fails_before_mutation(self):
        scene={'objects':{}}
        with self.assertRaises(SceneError):plan_stream(scene,'p',['red'],{},[0,0,0],[.1]*3,30)

    def test_stream_preserves_explicit_workspace_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            store=SceneStore(directory);store.open('s')
            cfg={'experimental':True,'model_directory':'/m','tool_frame':'tcp','tcp_prim':'tcp','target_position':[0,0,1]}
            store.apply('s',0,'robot',[{'op':'add','id':'arm','object':{'kind':'asset','asset_path':'/r.usd','pose_follower':cfg}}])
            wait={'axis':'x','minimum':0,'maximum':1,'max_steps':100,'workspace_min':[-1,-1,0],'workspace_max':[2,1,1]}
            route={'red':{'robot_id':'arm','wait':wait,'cycle':[{'type':'track','object':'$item','offset':[0,0,0],'steps':5,'workspace_min':[-1,-1,0],'workspace_max':[2,1,1]}]}}
            plan=plan_stream(store.get('s'),'part',['red'],route,[0,0,.3],[.04]*3,30)
            store.apply('s',1,'stream',plan['operations']);phases=store.get('s')['objects']['arm']['pose_follower']['sequence']
            self.assertEqual(phases[0]['workspace_min'],[-1,-1,0]);self.assertEqual(phases[1]['workspace_max'],[2,1,1])
