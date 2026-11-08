import copy
import unittest
from simscene.preparation.container import validate_container,wall_boxes,check_geometry
from simscene.preparation.profiles import validate_parameters,PreparationError


def proxy():
    return {'interior_bounds':{'min':[-.2,-.15,0.],'max':[.2,.15,.2]},'wall_thickness_m':.01,
            'floor_thickness_m':.01,'opening_axis':'+Z','test_object_size_m':[.05,.05,.05],
            'geometry_note':'Measured fixture inside surfaces and upward open cavity; experimental receiver'}


def add_box_mesh(stage,path,size,position):
    from pxr import UsdGeom
    mesh=UsdGeom.Mesh.Define(stage,path)
    points=[[position[i]+sign[i]*size[i]/2 for i in range(3)] for sign in
            [(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)]]
    mesh.CreatePointsAttr(points);mesh.CreateFaceVertexCountsAttr([4]*6)
    mesh.CreateFaceVertexIndicesAttr([0,3,2,1,4,5,6,7,0,1,5,4,1,2,6,5,2,3,7,6,3,0,4,7])
    return mesh


class ContainerTests(unittest.TestCase):
    def stage(self,seal=False):
        try:from pxr import Usd,UsdGeom
        except ImportError:self.skipTest('CPU OpenUSD fixture requires pxr')
        stage=Usd.Stage.CreateInMemory();root=UsdGeom.Xform.Define(stage,'/Asset');stage.SetDefaultPrim(root.GetPrim())
        UsdGeom.SetStageMetersPerUnit(stage,1.);UsdGeom.SetStageUpAxis(stage,UsdGeom.Tokens.z)
        for name,item in wall_boxes(proxy()).items():add_box_mesh(stage,'/Asset/'+name,item['size_m'],item['position_m'])
        if seal:add_box_mesh(stage,'/Asset/SealedTop',[.42,.32,.01],[0.,0.,.2])
        return stage

    def test_explicit_five_walls_leave_opening_and_measured_surface_agreement(self):
        boxes=wall_boxes(proxy());self.assertEqual(set(boxes),{'floor','left','right','front','back'})
        report=check_geometry(self.stage(),proxy(),.002)
        self.assertLess(report['max_surface_error_m'],1e-6)
        self.assertEqual(report['runtime_validation'],'not_run')
        with self.assertRaisesRegex(PreparationError,'obstructed'):check_geometry(self.stage(True),proxy(),.002)
        sealed=self.stage();add_box_mesh(sealed,'/Asset/ExactOpeningSeal',[.42,.32,.01],[0.,0.,.205])
        with self.assertRaisesRegex(PreparationError,'obstructed'):check_geometry(sealed,proxy(),.002)
        bad=proxy();bad['interior_bounds']['min'][0]=-.1
        with self.assertRaisesRegex(PreparationError,'surface'):check_geometry(self.stage(),bad,.002)

    def test_probe_fit_units_measurement_and_convex_seal_recipe_rejected(self):
        base={'source_physics_policy':'replace_visual_only','collision_method':'box_proxy',
              'proxy_tolerance_m':.002,'container_proxy':proxy()}
        self.assertEqual(validate_parameters('container_v1',base)['container_proxy'],proxy())
        for update in ({'collision_method':'convex_hull'},{'source_physics_policy':'preserve_valid'},
                       {'scale_mode':'fit_longest','target_longest_extent_m':.3}):
            with self.assertRaises(PreparationError):validate_parameters('container_v1',dict(base,**update))
        for key,value in [('opening_axis','+X'),('test_object_size_m',[.5,.05,.05]),('wall_thickness_m',0.),('geometry_note','')]:
            p=proxy();p[key]=value
            with self.subTest(key=key),self.assertRaises(PreparationError):validate_container(p)

    def test_actual_passage_and_retention_fail_for_closed_top_or_missing_floor(self):
        from test_rigid_asset_smoke import fixture
        from simscene.verification.container_asset_smoke import evaluate
        run,case=fixture();case['schema']='simscene.container_asset_smoke.v1'
        case['container']={'object_id':'receiver','prepared_manifest_sha256':'a'*64,
            'interior_bounds':{'min':[-.5,-.5,0.],'max':[.5,.5,.5]},
            'opening':{'min_xy':[-.5,-.5],'max_xy':[.5,.5],'z_m':.5}}
        self.assertTrue(evaluate(run,case)['passed'])
        # A convex cap arrests probe above opening: no full passage/retention.
        for frame in run['samples']:
            if frame['bounds']['item']['min'][2]<.5:
                frame['bounds']['item']={'min':[-.1,-.1,.5],'max':[.1,.1,.7]}
        self.assertFalse(evaluate(run,case)['passed'])
        run,_=fixture()
        run['samples'][-1]['bounds']['item']={'min':[-.1,-.1,-.5],'max':[.1,.1,-.3]}
        self.assertFalse(evaluate(run,case)['passed'])
