"""A class-aware schedule remains reviewable and preserves per-class order."""
import copy,unittest
from simscene.scene import SceneError
from simscene.scene_edits.interleave import interleave

class InterleaveTest(unittest.TestCase):
    def test_reorders_classes_without_mutating_scene_or_intra_class_order(self):
        objects={}
        for index,label in enumerate(('blue','green','red','blue','green','red')):
            objects[f'p{index}']={'kind':'box','dynamic':True,'class_label':label,'spawn_step':1+index*600}
        scene={'objects':objects};before=copy.deepcopy(scene)
        result=interleave(scene,list(objects),['green','blue','red'],900)
        self.assertEqual(scene,before)
        self.assertEqual([item['id'] for item in result['schedule']],['p1','p0','p2','p4','p3','p5'])
        self.assertEqual([item['spawn_step'] for item in result['schedule']],[1,901,1801,2701,3601,4501])
        self.assertEqual([op['id'] for op in result['operations']],['p1','p0','p2','p4','p3','p5'])

    def test_unequal_classes_and_explicit_start(self):
        scene={'objects':{'a':{'kind':'box','dynamic':True,'class_label':'x','spawn_step':1},
                          'b':{'kind':'sphere','dynamic':True,'class_label':'y','spawn_step':10},
                          'c':{'kind':'box','dynamic':True,'class_label':'x','spawn_step':20}}}
        result=interleave(scene,['c','a','b'],['y','x'],30,first_step=7)
        self.assertEqual([(x['id'],x['spawn_step']) for x in result['schedule']],[('b',7),('a',37),('c',67)])

    def test_rejects_collisions_missing_classes_and_oversized_schedule(self):
        scene={'objects':{'a':{'kind':'box','dynamic':True,'class_label':'x','spawn_step':1},
                          'b':{'kind':'box','dynamic':True,'class_label':'y','spawn_step':2},
                          'other':{'kind':'box','dynamic':True,'class_label':'z','spawn_step':11}}}
        with self.assertRaisesRegex(SceneError,'unselected'):interleave(scene,['a','b'],['x','y'],10)
        with self.assertRaisesRegex(SceneError,'exactly'):interleave(scene,['a','b'],['x'],5)
        with self.assertRaisesRegex(SceneError,'maximum'):interleave(scene,['a','b'],['x','y'],72000)
        with self.assertRaises(SceneError):interleave(scene,['a','a'],['x'],5)
