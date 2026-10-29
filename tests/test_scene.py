import tempfile
import unittest
from simscene.scene import SceneStore, SceneError

class SceneTest(unittest.TestCase):
    def test_phase_soft_speed_cap_requires_global_default(self):
        from simscene.scene import validate
        follower={'experimental':True,'model_directory':'/models','tool_frame':'tcp','tcp_prim':'hand','target_position':[0,0,0],
                  'max_joint_speed':.5,'sequence':[{'type':'move','position':[0,0,0],'rmp_max_joint_speed':.3}]}
        scene={'objects':{'arm':{'kind':'asset','asset_path':'/tmp/arm.usd','pose_follower':follower}}}
        self.assertFalse(validate(scene))
        del follower['max_joint_speed']
        self.assertTrue(any('requires a global max_joint_speed' in issue['message'] for issue in validate(scene)))
        follower['max_joint_speed']=.5;follower['sequence'][0]['rmp_max_joint_speed']=float('nan')
        self.assertTrue(any('rmp_max_joint_speed' in issue['message'] for issue in validate(scene)))

    def test_invalid_tracking_workspace_is_rejected(self):
        from simscene.scene import validate
        follower={'experimental':True,'model_directory':'/m','tool_frame':'tcp','tcp_prim':'hand','target_position':[0,0,0],
                  'sequence':[{'type':'track','object':'part','offset':[0,0,0],'steps':10,'workspace_min':[0,0,0],'workspace_max':[1,1,1]}]}
        scene={'objects':{'arm':{'kind':'asset','asset_path':'/a.usd','pose_follower':follower},'part':{'kind':'box','dynamic':True}}}
        self.assertFalse(validate(scene))
        follower['sequence'][0]['workspace_max']=[-1,1,1]
        self.assertTrue(any('workspace bounds' in issue['message'] for issue in validate(scene)))

    def test_self_collision_setting_must_be_boolean(self):
        from simscene.scene import validate
        follower={'experimental':True,'model_directory':'/models','tool_frame':'tcp','tcp_prim':'hand','target_position':[0,0,0],'self_collision_enabled':True}
        scene={'objects':{'arm':{'kind':'asset','asset_path':'/tmp/arm.usd','pose_follower':follower}}}
        self.assertFalse(validate(scene))
        follower['self_collision_enabled']='true'
        self.assertTrue(any('self_collision_enabled must be boolean' in x['message'] for x in validate(scene)))
        follower['self_collision_enabled']=True;follower['self_collision_exclusions']=[['finger_a','finger_b']]
        self.assertFalse(validate(scene))
        follower['self_collision_exclusions']=[['../outside','finger_b']]
        self.assertTrue(any('self_collision_exclusions' in x['message'] for x in validate(scene)))

    def test_remote_asset_url_requires_acquisition(self):
        with tempfile.TemporaryDirectory() as root:
            store=SceneStore(root);store.open('scene')
            with self.assertRaisesRegex(SceneError,'acquire the online asset'):
                store.apply('scene',0,'remote',[{'op':'add','id':'asset','object':{'kind':'asset','asset_path':'https://example.org/asset.usd'}}])
    def test_atomic_revision_and_retry(self):
        with tempfile.TemporaryDirectory() as root:
            store = SceneStore(root)
            store.open('scene')
            ops = [{'op':'add','id':'cube','object':{'kind':'box','position':[0,0,1]}}]
            self.assertEqual(store.apply('scene', 0, 'req1', ops)['revision'], 1)
            self.assertTrue(store.apply('scene', 0, 'req1', ops)['replayed'])
            with self.assertRaises(SceneError): store.apply('scene', 0, 'req2', ops)
            with self.assertRaises(SceneError): store.apply('scene', 1, 'req3', [{'op':'add','id':'bad','object':{'kind':'box','size':[-1,1,1]}}])
            self.assertEqual(list(store.get('scene')['objects']), ['cube'])

    def test_path_traversal(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(SceneError): SceneStore(root).apply('../outside', 0, 'req', [])

    def test_usd_export(self):
        from simscene.usd_export import export_scene
        from pxr import Usd
        with tempfile.TemporaryDirectory() as root:
            store = SceneStore(root)
            store.open('scene')
            store.apply('scene', 0, 'req', [{'op':'add','id':'cube','object':{'kind':'box','position':[0,0,1],'dynamic':True}}])
            result = export_scene(store.get('scene'), root + '/scene.usda')
            stage = Usd.Stage.Open(result['path'])
            self.assertTrue(stage.GetPrimAtPath('/World/cube'))

class PlacementTest(unittest.TestCase):
    def test_support_and_outside_failure(self):
        with tempfile.TemporaryDirectory() as root:
            s = SceneStore(root); s.open('desk')
            s.apply('desk', 0, 'create', [
                {'op':'add','id':'table','object':{'kind':'box','position':[0,0,1],'size':[2,2,1]}},
                {'op':'add','id':'part','object':{'kind':'box','size':[.2,.2,.2]}},
                {'op':'place_on','id':'part','support':'table','offset_xy':[.5,0]}])
            self.assertEqual(s.get('desk')['objects']['part']['position'], [.5, 0, 1.6])
            with self.assertRaises(SceneError):
                s.apply('desk', 1, 'bad', [{'op':'place_on','id':'part','support':'table','offset_xy':[1,0]}])
            self.assertEqual(s.get('desk')['revision'], 1)

class ConveyorTest(unittest.TestCase):
    def test_bind_validates_surface(self):
        with tempfile.TemporaryDirectory() as root:
            s=SceneStore(root); s.open('line')
            s.apply('line', 0, 'setup', [{'op':'add','id':'belt','object':{'kind':'box','size':[3,1,.1]}},{'op':'bind_conveyor','id':'belt','speed_m_s':.08}])
            self.assertEqual(s.get('line')['objects']['belt']['conveyor']['speed_m_s'], .08)
            with self.assertRaises(SceneError):
                s.apply('line', 1, 'invalid', [{'op':'bind_conveyor','id':'belt','speed_m_s':.1,'direction':[0,0,0]}])

class ArrangementTest(unittest.TestCase):
    def test_new_row_and_spacing_check(self):
        with tempfile.TemporaryDirectory() as root:
            store = SceneStore(root); store.open('table')
            ops = [{'op':'add', 'id':'box'+str(i), 'object':{'kind':'box','size':[.1,.1,.1]}} for i in range(3)]
            ops.append({'op':'arrange_line','ids':['box0','box1','box2'],'origin':[0,1,0], 'spacing':.2})
            store.apply('table', 0, 'setup', ops)
            self.assertEqual(store.get('table')['objects']['box2']['position'], [.4,1,0])
            with self.assertRaises(SceneError):
                store.apply('table', 1, 'bad', [{'op':'arrange_line','ids':['box0','box1'],'origin':[0,0,0], 'spacing':.05}])

class AssetValidationTest(unittest.TestCase):
    def test_visual_asset_units_and_y_up_are_normalized(self):
        from pxr import Gf,Usd,UsdGeom
        from simscene.usd_export import export_scene
        with tempfile.TemporaryDirectory() as root:
            source=Usd.Stage.CreateNew(root+'/visual.usda');UsdGeom.SetStageMetersPerUnit(source,.01);UsdGeom.SetStageUpAxis(source,UsdGeom.Tokens.y)
            model=UsdGeom.Xform.Define(source,'/Model');source.SetDefaultPrim(model.GetPrim())
            cube=UsdGeom.Cube.Define(source,'/Model/Cube');cube.CreateSizeAttr(100);cube.AddTranslateOp().Set(Gf.Vec3d(0,50,0));source.GetRootLayer().Save()
            out=export_scene({'revision':0,'objects':{'item':{'kind':'asset','asset_path':root+'/visual.usda','position':[1,2,0]}}},root+'/out.usda')
            stage=Usd.Stage.Open(out['path']);bound=UsdGeom.BBoxCache(Usd.TimeCode.Default(),[UsdGeom.Tokens.default_]).ComputeWorldBound(stage.GetPrimAtPath('/World/item')).ComputeAlignedRange()
            for value,expected in zip(bound.GetMin(),[.5,1.5,0]):self.assertAlmostEqual(value,expected,places=5)
            for value,expected in zip(bound.GetMax(),[1.5,2.5,1]):self.assertAlmostEqual(value,expected,places=5)
            self.assertEqual(out['normalized_visual_assets']['item']['source_up_axis'],'Y')

    def test_physics_asset_unit_conversion_requires_explicit_import(self):
        from pxr import Usd,UsdGeom,UsdPhysics
        from simscene.usd_export import export_scene
        with tempfile.TemporaryDirectory() as root:
            source=Usd.Stage.CreateNew(root+'/physics.usda');UsdGeom.SetStageMetersPerUnit(source,.01);UsdGeom.SetStageUpAxis(source,UsdGeom.Tokens.z)
            cube=UsdGeom.Cube.Define(source,'/Cube');source.SetDefaultPrim(cube.GetPrim());UsdPhysics.CollisionAPI.Apply(cube.GetPrim());source.GetRootLayer().Save()
            with self.assertRaisesRegex(SceneError,'has physics'):
                export_scene({'revision':0,'objects':{'item':{'kind':'asset','asset_path':root+'/physics.usda'}}},root+'/out.usda')
    def test_unknown_units_are_rejected(self):
        from pxr import Usd, UsdGeom
        from simscene.usd_export import export_scene
        with tempfile.TemporaryDirectory() as root:
            stage = Usd.Stage.CreateNew(root + '/asset.usda')
            UsdGeom.Xform.Define(stage, '/Thing')
            stage.GetRootLayer().Save()
            scene = {'revision':0, 'objects':{'thing':{'kind':'asset', 'asset_path':root+'/asset.usda'}}}
            with self.assertRaisesRegex(SceneError, 'unspecified unit or up axis'):
                export_scene(scene, root + '/scene.usda')

class ConveyorGeometryTest(unittest.TestCase):
    def test_conveyor_dimensions_are_baked_without_velocity_scaling(self):
        from pxr import Usd, UsdGeom
        from simscene.usd_export import export_scene
        with tempfile.TemporaryDirectory() as root:
            s=SceneStore(root); s.open('s')
            s.apply('s', 0, 'make', [{'op':'add','id':'belt','object':{'kind':'box','size':[3,1,.1]}}, {'op':'bind_conveyor','id':'belt','speed_m_s':.2}])
            path=export_scene(s.get('s'), root+'/scene.usda')['path']
            stage=Usd.Stage.Open(path)
            prim=stage.GetPrimAtPath('/World/belt')
            self.assertTrue(prim.IsA(UsdGeom.Mesh))
            self.assertFalse(any(op.GetOpType() == UsdGeom.XformOp.TypeScale for op in UsdGeom.Xformable(prim).GetOrderedXformOps()))
            self.assertAlmostEqual(UsdGeom.Mesh(prim).GetExtentAttr().Get()[1][0], 1.5)

class CameraAimTest(unittest.TestCase):
    def test_orbit_camera_has_time_sampled_positions(self):
        from pxr import Usd,UsdGeom
        from simscene.usd_export import export_scene
        with tempfile.TemporaryDirectory() as root:
            obj={'kind':'camera','camera_orbit':{'center':[0,0,.5],'radius_m':2,'height_m':2,'duration_s':4}}
            result=export_scene({'revision':0,'objects':{'view':obj}},root+'/orbit.usda')
            stage=Usd.Stage.Open(result['path']);prim=stage.GetPrimAtPath('/World/view')
            for tick,expected in [(0,[2,0,2.5]),(60,[0,2,2.5]),(120,[-2,0,2.5])]:
                pos=UsdGeom.XformCache(Usd.TimeCode(tick)).GetLocalToWorldTransform(prim).ExtractTranslation()
                for a,b in zip(pos,expected):self.assertAlmostEqual(a,b,places=5)
            orient=next(op for op in UsdGeom.Xformable(prim).GetOrderedXformOps() if op.GetOpType()==UsdGeom.XformOp.TypeOrient)
            quats=[orient.Get(Usd.TimeCode(t)) for t in orient.GetTimeSamples()]
            values=[[q.GetReal(),*q.GetImaginary()] for q in quats]
            self.assertTrue(all(sum(a*b for a,b in zip(x,y))>=0 for x,y in zip(values,values[1:])))

    def test_orbit_rejects_invalid_schema(self):
        with tempfile.TemporaryDirectory() as root:
            store=SceneStore(root);store.open('s')
            with self.assertRaises(SceneError):
                store.apply('s',0,'bad',[{'op':'add','id':'view','object':{'kind':'camera','camera_orbit':{'center':[0,0,0],'radius_m':0,'height_m':1,'duration_s':2}}}])
    def test_look_at_points_camera_minus_z_towards_target(self):
        from pxr import Gf
        with tempfile.TemporaryDirectory() as root:
            store=SceneStore(root); store.open('s')
            store.apply('s', 0, 'setup', [{'op':'add','id':'camera','object':{'kind':'camera','position':[2,0,1]}},{'op':'look_at','id':'camera','target':[0,0,1]}])
            q=store.get('s')['objects']['camera']['orientation_wxyz']
            direction=Gf.Rotation(Gf.Quatd(q[0],Gf.Vec3d(*q[1:]))).TransformDir(Gf.Vec3d(0,0,-1))
            self.assertAlmostEqual(direction[0],-1,places=6)
            self.assertAlmostEqual(direction[1],0,places=6)
            self.assertAlmostEqual(direction[2],0,places=6)

class ConveyorDirectionTest(unittest.TestCase):
    def test_direction_is_normalized(self):
        with tempfile.TemporaryDirectory() as root:
            s=SceneStore(root); s.open('s')
            s.apply('s',0,'make',[{'op':'add','id':'b','object':{'kind':'box'}},{'op':'bind_conveyor','id':'b','speed_m_s':.2,'direction':[2,0,0]}])
            self.assertEqual(s.get('s')['objects']['b']['conveyor']['direction'],[1,0,0])

    def test_referenced_asset_keeps_its_own_transform(self):
        from pxr import Gf,Usd,UsdGeom
        from simscene.usd_export import export_scene
        with tempfile.TemporaryDirectory() as root:
            stage=Usd.Stage.CreateNew(root+'/asset.usda')
            UsdGeom.SetStageMetersPerUnit(stage,1.0);UsdGeom.SetStageUpAxis(stage,UsdGeom.Tokens.z)
            prim=UsdGeom.Xform.Define(stage,'/Model'); stage.SetDefaultPrim(prim.GetPrim())
            prim.AddTranslateOp().Set(Gf.Vec3d(0,0,2));stage.GetRootLayer().Save()
            scene={'revision':0,'objects':{'item':{'kind':'asset','asset_path':root+'/asset.usda','position':[1,0,0]}}}
            result=export_scene(scene,root+'/scene.usda'); out=Usd.Stage.Open(result['path'])
            target=out.GetPrimAtPath('/World/item/Asset')
            position=UsdGeom.XformCache().GetLocalToWorldTransform(target).ExtractTranslation()
            self.assertEqual(list(position),[1,0,2])

class PoseFollowerSchemaTest(unittest.TestCase):
    def test_requires_explicit_experimental_and_valid_target(self):
        with tempfile.TemporaryDirectory() as root:
            store=SceneStore(root);store.open('s')
            asset={'kind':'asset','asset_path':'/robot.usd','pose_follower':{'model_directory':'/model','tool_frame':'tcp','tcp_prim':'tcp','target_position':[0,0,1]}}
            with self.assertRaises(SceneError): store.apply('s',0,'bad',[{'op':'add','id':'r','object':asset}])
            asset['pose_follower']['experimental']=True
            asset['pose_follower']['arm_drives_enabled']='false'
            with self.assertRaises(SceneError):store.apply('s',0,'bad_drives',[{'op':'add','id':'r','object':asset}])
            asset['pose_follower']['arm_drives_enabled']=False
            asset['pose_follower']['suction_enabled']=False
            with self.assertRaises(SceneError):store.apply('s',0,'bad_suction',[{'op':'add','id':'r','object':asset}])
            del asset['pose_follower']['suction_enabled']
            store.apply('s',0,'good',[{'op':'add','id':'r','object':asset}])
            self.assertTrue(store.get('s')['objects']['r']['pose_follower']['experimental'])
            self.assertFalse(store.get('s')['objects']['r']['pose_follower']['arm_drives_enabled'])

    def test_sequence_validation_rejects_invalid_or_incomplete_phases(self):
        with tempfile.TemporaryDirectory() as root:
            store=SceneStore(root);store.open('s')
            cfg={'experimental':True,'model_directory':'/m','tool_frame':'tcp','tcp_prim':'tcp','target_position':[0,0,1], 'sequence':[{'type':'gripper','value':.5,'steps':30}]}
            with self.assertRaises(SceneError): store.apply('s',0,'bad',[{'op':'add','id':'r','object':{'kind':'asset','asset_path':'/r.usd','pose_follower':cfg}}])
            cfg['gripper_urdf']='/r.urdf';cfg['gripper_joint']='finger'
            cfg['sequence'].append({'type':'move','position':[0,1,2],'max_steps':10})
            with self.assertRaises(SceneError): store.apply('s',0,'bad2',[{'op':'add','id':'r','object':{'kind':'asset','asset_path':'/r.usd','pose_follower':cfg}}])
            cfg['sequence']=[{'type':'move','position':[0,1,2],'avoid_collisions':True}]
            with self.assertRaises(SceneError): store.apply('s',0,'bad3',[{'op':'add','id':'r','object':{'kind':'asset','asset_path':'/r.usd','pose_follower':cfg}}])

class TrackingSchemaTest(unittest.TestCase):
    def test_track_requires_valid_dynamic_object(self):
        with tempfile.TemporaryDirectory() as root:
            s=SceneStore(root);s.open('s')
            config={'experimental':True,'model_directory':'/m','tool_frame':'tcp','tcp_prim':'tcp','target_position':[0,0,1], 'sequence':[{'type':'track','object':'part','offset':[0,0,0],'steps':30}]}
            with self.assertRaises(SceneError):s.apply('s',0,'bad',[{'op':'add','id':'robot','object':{'kind':'asset','asset_path':'/r.usd','pose_follower':config}}])
            s.apply('s',0,'ok',[{'op':'add','id':'part','object':{'kind':'box','dynamic':True}}, {'op':'add','id':'robot','object':{'kind':'asset','asset_path':'/r.usd','pose_follower':config}}])

class NativeCubeTest(unittest.TestCase):
    def test_reserved_and_equivalent_usd_names_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            store=SceneStore(root);store.open('s')
            with self.assertRaises(SceneError):
                store.apply('s',0,'reserved',[{'op':'add','id':'Looks','object':{'kind':'box'}}])
            with self.assertRaises(SceneError):
                store.apply('s',0,'collision',[{'op':'add','id':'a-b','object':{'kind':'box'}},{'op':'add','id':'a_b','object':{'kind':'box'}}])

    def test_preview_material_is_bound_to_geometry(self):
        from pxr import Usd,UsdShade
        from simscene.usd_export import export_scene
        with tempfile.TemporaryDirectory() as root:
            scene={'revision':0,'objects':{'cube':{'kind':'box','material':{'color':[.2,.4,.6],'roughness':.25,'metallic':.8}}}}
            stage=Usd.Stage.Open(export_scene(scene,root+'/scene.usda')['path'])
            material,_=UsdShade.MaterialBindingAPI(stage.GetPrimAtPath('/World/cube')).ComputeBoundMaterial()
            self.assertEqual(str(material.GetPath()),'/World/Looks/cube')
            shader=UsdShade.Shader(stage.GetPrimAtPath('/World/Looks/cube/PreviewSurface'))
            self.assertAlmostEqual(shader.GetInput('roughness').Get(),.25)
            self.assertAlmostEqual(shader.GetInput('metallic').Get(),.8,places=5)

    def test_invalid_material_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            store=SceneStore(root);store.open('s')
            with self.assertRaises(SceneError):
                store.apply('s',0,'bad',[{'op':'add','id':'b','object':{'kind':'box','material':{'roughness':2}}}])

    def test_unsupported_asset_physics_and_invalid_light_are_not_silent(self):
        with tempfile.TemporaryDirectory() as root:
            store=SceneStore(root);store.open('s')
            with self.assertRaises(SceneError):
                store.apply('s',0,'bad-asset',[{'op':'add','id':'asset','object':{'kind':'asset','asset_path':'/a.usd','dynamic':True}}])
            with self.assertRaises(SceneError):
                store.apply('s',0,'bad-light',[{'op':'add','id':'light','object':{'kind':'light','intensity':-1}}])

    def test_uniform_cube_uses_native_size_for_surface_queries(self):
        from pxr import Usd,UsdGeom
        from simscene.usd_export import export_scene
        with tempfile.TemporaryDirectory() as root:
            stage=Usd.Stage.Open(export_scene({'revision':0,'objects':{'cube':{'kind':'box','size':[.04,.04,.04]}}},root+'/scene.usda')['path'])
            cube=UsdGeom.Cube(stage.GetPrimAtPath('/World/cube'))
            self.assertAlmostEqual(cube.GetSizeAttr().Get(),.04)
            self.assertFalse(any(op.GetOpType()==UsdGeom.XformOp.TypeScale for op in UsdGeom.Xformable(cube).GetOrderedXformOps()))

class AssetVariantTest(unittest.TestCase):
    def test_local_asset_reference_survives_moving_run_directory(self):
        from pathlib import Path
        import shutil
        from pxr import Usd,UsdGeom
        from simscene.usd_export import export_scene
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'run';(root/'assets').mkdir(parents=True)
            source=Usd.Stage.CreateNew(str(root/'assets'/'asset.usda'))
            UsdGeom.SetStageMetersPerUnit(source,1);UsdGeom.SetStageUpAxis(source,UsdGeom.Tokens.z)
            prim=UsdGeom.Xform.Define(source,'/Model').GetPrim();source.SetDefaultPrim(prim)
            UsdGeom.Cube.Define(source,'/Model/Cube');source.GetRootLayer().Save()
            export_scene({'revision':0,'objects':{'model':{'kind':'asset','asset_path':str(root/'assets'/'asset.usda')}}},root/'scene.usda')
            moved=Path(d)/'moved';shutil.move(root,moved)
            stage=Usd.Stage.Open(str(moved/'scene.usda'))
            self.assertTrue(stage.GetPrimAtPath('/World/model/Asset/Cube'))

    def test_variant_applied_on_referenced_asset(self):
        from pxr import Usd,UsdGeom
        from simscene.usd_export import export_scene
        with tempfile.TemporaryDirectory() as d:
            source=Usd.Stage.CreateNew(d+'/asset.usda');UsdGeom.SetStageMetersPerUnit(source,1);UsdGeom.SetStageUpAxis(source,UsdGeom.Tokens.z)
            prim=UsdGeom.Xform.Define(source,'/Model').GetPrim();source.SetDefaultPrim(prim)
            variants=prim.GetVariantSets().AddVariantSet('Style');variants.AddVariant('A');variants.AddVariant('B');variants.SetVariantSelection('A');source.GetRootLayer().Save()
            spec={'revision':0,'objects':{'model':{'kind':'asset','asset_path':d+'/asset.usda','variants':{'Style':'B'}}}}
            output=export_scene(spec,d+'/scene.usda');stage=Usd.Stage.Open(output['path']);self.assertEqual(stage.GetPrimAtPath('/World/model/Asset').GetVariantSet('Style').GetVariantSelection(),'B')

class ScheduledObjectTest(unittest.TestCase):
    def test_scheduled_primitive_excluded_from_initial_stage(self):
        from pxr import Usd
        from simscene.usd_export import export_scene
        with tempfile.TemporaryDirectory() as root:
            s=SceneStore(root);s.open('s')
            s.apply('s',0,'setup',[{'op':'add','id':'late','object':{'kind':'box','dynamic':True,'spawn_step':30,'mass_kg':.05}},{'op':'add','id':'now','object':{'kind':'box','dynamic':True}}])
            stage=Usd.Stage.Open(export_scene(s.get('s'),root+'/scene.usda')['path'])
            self.assertFalse(stage.GetPrimAtPath('/World/late'))
            self.assertTrue(stage.GetPrimAtPath('/World/now'))

    def test_wait_requires_dynamic_object_and_bounded_interval(self):
        with tempfile.TemporaryDirectory() as root:
            s=SceneStore(root);s.open('s')
            c={'experimental':True,'model_directory':'/m','tool_frame':'tcp','tcp_prim':'tcp','target_position':[0,0,1],'sequence':[{'type':'wait_object','object':'part','axis':'x','minimum':0,'maximum':1,'max_steps':200}]}
            s.apply('s',0,'setup',[{'op':'add','id':'part','object':{'kind':'box','dynamic':True,'spawn_step':30}},{'op':'add','id':'r','object':{'kind':'asset','asset_path':'/r.usd','pose_follower':c}}])
            self.assertEqual(s.get('s')['revision'],1)
