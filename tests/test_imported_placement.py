import copy,math,tempfile,unittest
from pathlib import Path
from simscene.scene import SceneStore,SceneError,validate
from simscene.placement import measure

class ImportedPlacementTest(unittest.TestCase):
    def test_filtered_geometry_bounds_do_not_import_unrelated_colliders_or_mutate_filters(self):
        from pxr import Usd,UsdPhysics
        from simscene.usd_export import export_scene
        scene={'revision':0,'objects':{
            'roller':{'kind':'cylinder','size':[.2,.2,.4],'position':[1,2,3],
                      'orientation_wxyz':[math.sqrt(.5),0,math.sqrt(.5),0],
                      'collision_exclusions':['floor','other']},
            'floor':{'kind':'box','size':[100,100,.1]},
            'other':{'kind':'box','position':[20,20,20]}}}
        before=copy.deepcopy(scene)
        self.assertEqual(validate(scene),[])
        box=measure(scene,['roller'])['objects']['roller']['world_bounds_m']
        for key,expected in [('min',[.8,1.9,2.9]),('max',[1.2,2.1,3.1])]:
            for actual,value in zip(box[key],expected):self.assertAlmostEqual(actual,value,places=6)
        self.assertEqual(scene,before)
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'actual.usda';export_scene(scene,path)
            stage=Usd.Stage.Open(str(path))
            targets=UsdPhysics.FilteredPairsAPI(stage.GetPrimAtPath('/World/roller')).GetFilteredPairsRel().GetTargets()
            self.assertEqual([str(p) for p in targets],['/World/floor','/World/other'])
            invalid=copy.deepcopy(scene);invalid['objects']['roller']['collision_exclusions']=['missing']
            with self.assertRaisesRegex(SceneError,'collision_exclusions'):
                export_scene(invalid,Path(root)/'invalid.usda')

    def test_filtered_compound_keeps_attached_visual_extent_and_source_bytes(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'visual.usda';self.make_asset(path);source=path.read_bytes()
            scene={'revision':0,'objects':{
                'body-name':{'kind':'compound','position':[2,1,.4],'dynamic':True,
                             'parts':[{'kind':'box','size':[.2,.1,.05]}],
                             'collision_exclusions':['floor']},
                'visual':{'kind':'asset','asset_path':str(path),'asset_physics':'visual_only','asset_lights':'disabled',
                          'position':[.35,0,0],'rigid_attachment':{'body':'body-name'}},
                'floor':{'kind':'box','size':[100,100,.1]}}}
            before=copy.deepcopy(scene)
            self.assertEqual(validate(scene),[])
            box=measure(scene,['body-name'])['objects']['body-name']['world_bounds_m']
            for key,expected in [('min',[1.9,.85,.375]),('max',[2.55,1.15,.5])]:
                for actual,value in zip(box[key],expected):self.assertAlmostEqual(actual,value,places=6)
            self.assertEqual(scene,before);self.assertEqual(path.read_bytes(),source)

    def test_overlap_candidates_expose_shelf_intrusion_but_do_not_call_support_touch_penetration(self):
        scene={'objects':{'tile':{'kind':'box','size':[.012,.08,.18],'position':[-.96,0,.85]},'shelf':{'kind':'box','size':[.5,.36,.03],'position':[-.9,.2,.895]},'deck':{'kind':'box','size':[2,.2,.02],'position':[-.96,0,.75]}}}
        report=measure(scene,['tile','shelf','deck'],True)
        self.assertEqual(len(report['potential_render_bounds_overlaps']),1)
        overlap=report['potential_render_bounds_overlaps'][0]
        self.assertEqual(overlap['ids'],['tile','shelf'])
        self.assertAlmostEqual(overlap['overlap_extent_m'][1],.02)
        scene['objects']['tile']['position'][1]=-.15
        self.assertEqual(measure(scene,['tile','shelf'],True)['potential_render_bounds_overlaps'],[])
        self.assertNotIn('potential_render_bounds_overlaps',measure(scene,['tile']))
    def make_asset(self,path):
        from pxr import Usd,UsdGeom,Gf
        stage=Usd.Stage.CreateNew(str(path));UsdGeom.SetStageUpAxis(stage,'Y');UsdGeom.SetStageMetersPerUnit(stage,.01)
        root=UsdGeom.Xform.Define(stage,'/Part');stage.SetDefaultPrim(root.GetPrim());cube=UsdGeom.Cube.Define(stage,'/Part/visual');cube.CreateSizeAttr(1);cube.AddTranslateOp().Set(Gf.Vec3d(10,5,0));cube.AddScaleOp().Set(Gf.Vec3d(20,10,30));stage.GetRootLayer().Save()
    def test_offset_origin_unit_conversion_rotation_and_explicit_support(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'part.usda';self.make_asset(path)
            s=SceneStore(root);s.open('layout')
            s.apply('layout',0,'create',[{'op':'add','id':'desk','object':{'kind':'box','position':[1,2,1],'size':[2,2,.2],'orientation_wxyz':[math.sqrt(.5),0,0,math.sqrt(.5)]}},
              {'op':'add','id':'part','object':{'kind':'asset','asset_path':str(path),'orientation_wxyz':[math.sqrt(.5),0,0,math.sqrt(.5)]}},
              {'op':'place_on','id':'part','support':'desk','offset_xy':[.2,0]}])
            bound=measure(s.get('layout'),['part'])['objects']['part']['world_bounds_m']
            self.assertAlmostEqual(bound['min'][2],1.1,places=6)
            self.assertAlmostEqual((bound['min'][1]+bound['max'][1])/2,2.2,places=6)
            with self.assertRaisesRegex(SceneError,'explicit support'):
                s.apply('layout',1,'bad',[{'op':'place_on','id':'desk','support':'part'}])
    def test_grid_exclusions_clearance_and_rollback(self):
        with tempfile.TemporaryDirectory() as root:
            s=SceneStore(root);s.open('layout')
            ops=[{'op':'add','id':'table','object':{'kind':'box','size':[1,1,.1],'support_surfaces':{'top':{'min_xy':[-.5,-.5],'max_xy':[.5,.5],'z_m':.05}}}}]
            ops.extend({'op':'add','id':f'p{i}','object':{'kind':'box','size':[.2,.2,.1]}} for i in range(4))
            ops.append({'op':'arrange_grid','ids':['p0','p1','p2','p3'],'support':'table','support_surface':'top','columns':2,'gap_m':.1})
            s.apply('layout',0,'grid',ops);objects=s.get('layout')['objects']
            self.assertAlmostEqual(objects['p3']['position'][0],.15);self.assertAlmostEqual(objects['p3']['position'][1],.15)
            before=s.get('layout')
            with self.assertRaisesRegex(SceneError,'reserved activity'):
                s.apply('layout',1,'blocked',[{'op':'place_on','id':'p0','support':'table','keepout_bounds':[{'min':[-1,-1,0],'max':[1,1,1]}]}])
            self.assertEqual(s.get('layout'),before)
            with self.assertRaisesRegex(SceneError,'exceeds'):
                s.apply('layout',1,'too_large',[{'op':'arrange_grid','ids':['p0','p1','p2','p3'],'support':'table','columns':2,'gap_m':1}])
    def test_explicit_visual_import_preserves_source_and_removes_physics(self):
        from pxr import Usd,UsdGeom,UsdPhysics
        from simscene.usd_export import export_scene
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);source=Usd.Stage.CreateNew(str(root/'source.usda'));UsdGeom.SetStageUpAxis(source,'Z')
            cube=UsdGeom.Cube.Define(source,'/Root');source.SetDefaultPrim(cube.GetPrim());UsdPhysics.CollisionAPI.Apply(cube.GetPrim());UsdPhysics.RigidBodyAPI.Apply(cube.GetPrim());source.GetRootLayer().Save();original=(root/'source.usda').read_bytes()
            obj={'kind':'asset','asset_path':str(root/'source.usda'),'asset_physics':'visual_only','asset_metrics':{'meters_per_unit':1,'reason':'Source has no root unit metadata; metre dimensions independently inspected.'}}
            result=export_scene({'revision':0,'objects':{'prop':obj}},root/'visual.usda');stage=Usd.Stage.Open(result['path']);prim=stage.GetPrimAtPath('/World/prop/Asset')
            self.assertFalse(prim.HasAPI(UsdPhysics.RigidBodyAPI));self.assertFalse(prim.HasAPI(UsdPhysics.CollisionAPI));self.assertEqual(original,(root/'source.usda').read_bytes())
