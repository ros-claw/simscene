"""Synthetic local USD only; no fresh house assets, trajectories or GPU."""
import hashlib
import math
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade
from experiments.usd_geometry_probe import probe


def stage_at(path, metres=1, up='Z'):
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, metres);UsdGeom.SetStageUpAxis(stage, up)
    return stage


def mesh(stage, path, faces, scheme='none'):
    result = UsdGeom.Mesh.Define(stage, path)
    result.CreatePointsAttr([point for face in faces for point in face])
    result.CreateFaceVertexCountsAttr([len(face) for face in faces])
    result.CreateFaceVertexIndicesAttr(list(range(sum(map(len, faces)))))
    if scheme is not None:result.CreateSubdivisionSchemeAttr(scheme)
    return result


def plane(z=0):return [(-1,-1,z),(1,-1,z),(1,1,z),(-1,1,z)]
def ray(origin=(0,0,2), direction=(0,0,-1), **kwargs):return {'origin_world_m': list(origin), 'direction_world': list(direction), **kwargs}


def open_container(stage):
    # A genuinely open rectangular shell: distinct inner floor, outer bottom,
    # four inner/outer walls and rim, rather than a whole-object bounding box.
    faces = [[(-.5,-.5,.2),(.5,-.5,.2),(.5,.5,.2),(-.5,.5,.2)],
             [(-.7,-.7,0),(-.7,.7,0),(.7,.7,0),(.7,-.7,0)],
             [(-.5,-.5,.2),(-.5,.5,.2),(-.5,.5,1),(-.5,-.5,1)],
             [(.5,.5,.2),(.5,-.5,.2),(.5,-.5,1),(.5,.5,1)],
             [(.5,-.5,.2),(-.5,-.5,.2),(-.5,-.5,1),(.5,-.5,1)],
             [(-.5,.5,.2),(.5,.5,.2),(.5,.5,1),(-.5,.5,1)],
             [(-.7,.7,0),(-.7,-.7,0),(-.7,-.7,1),(-.7,.7,1)],
             [(.7,-.7,0),(.7,.7,0),(.7,.7,1),(.7,-.7,1)],
             [(-.7,-.7,0),(.7,-.7,0),(.7,-.7,1),(-.7,-.7,1)],
             [(.7,.7,0),(-.7,.7,0),(-.7,.7,1),(.7,.7,1)],
             [(-.7,-.7,1),(.7,-.7,1),(.5,-.5,1),(-.5,-.5,1)],
             [(.7,-.7,1),(.7,.7,1),(.5,.5,1),(.5,-.5,1)],
             [(.7,.7,1),(-.7,.7,1),(-.5,.5,1),(.5,.5,1)],
             [(-.7,.7,1),(-.7,-.7,1),(-.5,-.5,1),(-.5,.5,1)]]
    return mesh(stage, '/Cup', faces)


class GeometryProbeTest(unittest.TestCase):
    def test_open_cavity_inner_floor_outer_bottom_and_inner_wall_are_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'synthetic.usda';stage = stage_at(path);open_container(stage);stage.GetRootLayer().Save()
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            result = probe(path, '/Cup', [ray((0,0,2)), ray((0,0,.6),(1,0,0)), ray((.6,0,2))])
            self.assertTrue(result['complete'], result['unsupported'])
            inner, outer = result['rays'][0]['hits']
            self.assertAlmostEqual(inner['point_world_m'][2], .2, places=7)
            self.assertAlmostEqual(outer['point_world_m'][2], 0, places=8)
            self.assertEqual([inner['face_index'],outer['face_index']], [0,1])
            self.assertEqual(inner['normal_world'], [0,0,1]);self.assertEqual(outer['normal_world'], [0,0,-1])
            self.assertTrue(inner['front_facing']);self.assertFalse(outer['front_facing'])
            wall = result['rays'][1]['hits']
            self.assertEqual([hit['face_index'] for hit in wall], [3,7])
            self.assertAlmostEqual(wall[0]['distance_m'], .5, places=7)
            self.assertAlmostEqual(wall[1]['distance_m'], .7, places=7)
            self.assertAlmostEqual(result['rays'][2]['hits'][0]['point_world_m'][2], 1.)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
            self.assertFalse(stage.GetRootLayer().dirty)

    def test_unauthored_stage_units_are_reported_as_defaults_not_assumed_metres(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'defaults.usda';stage=Usd.Stage.CreateNew(str(path));UsdGeom.Cube.Define(stage,'/Box');stage.GetRootLayer().Save()
            result=probe(path,'/Box',[ray((0,0,.03))])
            self.assertEqual(result['units']['metres_per_stage_unit'],.01)
            self.assertFalse(result['units']['metres_per_unit_authored']);self.assertFalse(result['units']['up_axis_authored'])
            self.assertAlmostEqual(result['rays'][0]['hits'][0]['distance_m'],.02)

    def test_nonuniform_mirror_rotation_units_and_up_axis(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'units.usda';stage = stage_at(path,.01,'Y')
            parent = UsdGeom.Xform.Define(stage,'/Group');xf = UsdGeom.Xformable(parent)
            xf.AddTranslateOp().Set(Gf.Vec3d(100,200,300));xf.AddRotateYOp().Set(90);xf.AddScaleOp().Set(Gf.Vec3f(-2,3,1))
            value = mesh(stage,'/Group/Surface',[plane()]);stage.GetRootLayer().Save()
            result = probe(path,'/Group',[ray((2,2,3),(-2,0,0))])
            hit = result['rays'][0]['hits'][0]
            self.assertAlmostEqual(hit['distance_m'],1,places=8)
            for actual,expected in zip(hit['point_world_m'],[1,2,3]):self.assertAlmostEqual(actual,expected,places=8)
            for actual,expected in zip(hit['normal_world'],[1,0,0]):self.assertAlmostEqual(actual,expected,places=8)
            self.assertEqual(result['units']['up_axis'],'Y');self.assertEqual(result['units']['metres_per_stage_unit'],.01)
            self.assertEqual(result['meshes'][0]['transform_handedness'],-1)
            value.CreateOrientationAttr('leftHanded');stage.GetRootLayer().Save()
            flipped = probe(path,'/Group',[ray((2,2,3),(-1,0,0))])['rays'][0]['hits'][0]
            self.assertAlmostEqual(flipped['normal_world'][0],-1,places=8)

    def test_native_instances_keep_real_instance_paths_and_explicit_reference_scale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);model = stage_at(root/'model.usda',.01)
            model.SetDefaultPrim(UsdGeom.Xform.Define(model,'/Model').GetPrim())
            mesh(model,'/Model/Surface',[plane(10)]);model.GetRootLayer().Save()
            path=root/'instances.usda';stage=stage_at(path);UsdGeom.Xform.Define(stage,'/World')
            for name,z in [('Low',1),('High',3)]:
                prim=UsdGeom.Xform.Define(stage,'/World/'+name).GetPrim();prim.GetReferences().AddReference('./model.usda');prim.SetInstanceable(True)
                transform=UsdGeom.Xformable(prim);transform.AddTranslateOp().Set(Gf.Vec3d(0,0,z));transform.AddScaleOp().Set(Gf.Vec3f(.01))
            stage.GetRootLayer().Save()
            result=probe(path,'/World',[ray((0,0,4))])
            self.assertTrue(result['complete'])
            hits=result['rays'][0]['hits']
            self.assertEqual([h['mesh_path'] for h in hits],['/World/High/Surface','/World/Low/Surface'])
            self.assertTrue(all(h['prototype_mesh_path'] for h in hits))
            self.assertAlmostEqual(hits[0]['distance_m'],.9,places=7);self.assertAlmostEqual(hits[1]['distance_m'],2.9,places=7)
            subtree=probe(path,'/World/High/Surface',[ray((0,0,4))])
            self.assertEqual(len(subtree['rays'][0]['hits']),1)
            self.assertEqual(subtree['rays'][0]['hits'][0]['mesh_path'],'/World/High/Surface')

    def test_fan_diagonal_deduplicates_without_faking_a_polygon_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'face.usda';stage=stage_at(path);mesh(stage,'/Surface',[plane()]);stage.GetRootLayer().Save()
            result=probe(path,'/Surface',[ray((0,0,1)),ray((1,1,1)),ray((1.00001,0,1)),ray((.25,0,0))])
            center=result['rays'][0]['hits'];self.assertEqual(len(center),1);self.assertFalse(center[0]['boundary']);self.assertEqual(len(center[0]['triangle_indices']),2)
            self.assertTrue(result['rays'][1]['hits'][0]['boundary'])
            self.assertEqual(result['rays'][2]['hits'],[])
            self.assertEqual(result['rays'][3]['hits'][0]['distance_m'],0);self.assertTrue(result['rays'][3]['hits'][0]['at_origin'])

    def test_cube_faces_stay_distinct_at_shared_edges_and_range_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'cube.usda';stage=stage_at(path);UsdGeom.Cube.Define(stage,'/Box');stage.GetRootLayer().Save()
            result=probe(path,'/Box',[ray((2,2,0),(-1,-1,0)),ray((0,0,3),maximum_distance_m=1)])
            hits=result['rays'][0]['hits'];self.assertEqual(len(hits),4)
            self.assertAlmostEqual(hits[0]['distance_m'],math.sqrt(2));self.assertAlmostEqual(hits[1]['distance_m'],math.sqrt(2))
            self.assertNotEqual(hits[0]['face_index'],hits[1]['face_index'])
            self.assertEqual(result['rays'][1]['hits'],[])

    def test_parallel_coplanar_and_bounded_coplanar_queries_are_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'plane.usda';stage=stage_at(path);mesh(stage,'/Surface',[plane()]);stage.GetRootLayer().Save()
            result=probe(path,'/Surface',[ray((0,0,1),(1,0,0)),ray((-2,0,0),(1,0,0)),ray((-2,0,0),(1,0,0),maximum_distance_m=.5)])
            self.assertTrue(result['rays'][0]['complete_for_supported_query']);self.assertEqual(result['rays'][0]['hits'],[])
            self.assertFalse(result['rays'][1]['complete_for_supported_query']);self.assertTrue(result['rays'][1]['ambiguities'])
            self.assertTrue(result['rays'][2]['complete_for_supported_query']);self.assertEqual(result['rays'][2]['ambiguities'],[])

    def test_direction_normalization_handles_small_and_large_finite_magnitudes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'directions.usda';stage=stage_at(path);mesh(stage,'/Surface',[plane()]);stage.GetRootLayer().Save()
            result=probe(path,'/Surface',[ray(direction=(0,0,-1e-300)),ray(direction=(0,0,-1e308))])
            self.assertTrue(result['complete'])
            for value in result['rays']:
                self.assertEqual(value['direction_world_unit'],[0,0,-1]);self.assertAlmostEqual(value['hits'][0]['distance_m'],2)

    def test_holes_visibility_and_purpose_do_not_invent_surfaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'filters.usda';stage=stage_at(path);UsdGeom.Xform.Define(stage,'/Root')
            hole=mesh(stage,'/Root/Hole',[plane(1)]);hole.CreateHoleIndicesAttr([0])
            hidden=mesh(stage,'/Root/Hidden',[plane(.5)]);hidden.CreateVisibilityAttr('invisible')
            proxy=mesh(stage,'/Root/Proxy',[plane(0)]);proxy.CreatePurposeAttr('proxy');stage.GetRootLayer().Save()
            default=probe(path,'/Root',[ray()]);self.assertEqual(default['rays'][0]['hits'],[]);self.assertFalse(default['complete'])
            all_surfaces=probe(path,'/Root',[ray()],include_invisible=True,purposes=('default','render','proxy'))
            self.assertEqual([hit['mesh_path'] for hit in all_surfaces['rays'][0]['hits']],['/Root/Hidden','/Root/Proxy'])

    def test_subdivision_default_and_other_primitives_are_not_cage_fallbacks(self):
        for kind in ('subdivision_default','subdivision_bilinear','sphere','point_instancer'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'unsupported.usda';stage=stage_at(path)
                if kind.startswith('subdivision'):mesh(stage,'/Shape',[plane()],None if kind.endswith('default') else 'bilinear')
                elif kind=='sphere':UsdGeom.Sphere.Define(stage,'/Shape')
                else:UsdGeom.PointInstancer.Define(stage,'/Shape')
                stage.GetRootLayer().Save();result=probe(path,'/Shape',[ray()])
                self.assertFalse(result['complete']);self.assertTrue(result['unsupported']);self.assertEqual(result['rays'][0]['hits'],[])

    def test_bad_concave_nonplanar_topology_and_degenerate_faces_are_unknown(self):
        for kind in ('concave','nonplanar','bad_index','degenerate'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'bad.usda';stage=stage_at(path)
                faces=[[(0,0,0),(2,0,0),(1,1,0),(2,2,0),(0,2,0)]] if kind=='concave' else [plane()]
                value=mesh(stage,'/Shape',faces)
                if kind=='nonplanar':value.GetPointsAttr().Set([(-1,-1,0),(1,-1,0),(1,1,.1),(-1,1,0)])
                elif kind=='bad_index':value.GetFaceVertexIndicesAttr().Set([0,1,2,99])
                elif kind=='degenerate':value.GetPointsAttr().Set([(0,0,0),(1,0,0),(2,0,0),(3,0,0)])
                stage.GetRootLayer().Save();result=probe(path,'/Shape',[ray()])
                self.assertFalse(result['complete']);self.assertTrue(result['unsupported']);self.assertEqual(result['rays'][0]['hits'],[])

    def test_displacement_cannot_silently_use_base_mesh(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'displacement.usda';stage=stage_at(path);value=mesh(stage,'/Surface',[plane()])
            material=UsdShade.Material.Define(stage,'/Material');shader=UsdShade.Shader.Define(stage,'/Material/Shader');shader.CreateOutput('out',Sdf.ValueTypeNames.Float)
            material.CreateDisplacementOutput().ConnectToSource(shader.ConnectableAPI(),'out');UsdShade.MaterialBindingAPI.Apply(value.GetPrim()).Bind(material)
            stage.GetRootLayer().Save();result=probe(path,'/Surface',[ray()]);self.assertFalse(result['complete']);self.assertIn('displacement',result['unsupported'][0]['reason'])

    def test_unsupported_overlay_cannot_make_a_partial_floor_measurement_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'partial.usda';stage=stage_at(path);UsdGeom.Xform.Define(stage,'/Root')
            mesh(stage,'/Root/Polygon',[plane()]);mesh(stage,'/Root/Subdivision',[plane(1)],None);stage.GetRootLayer().Save()
            result=probe(path,'/Root',[ray()])
            self.assertFalse(result['complete']);self.assertEqual(len(result['rays'][0]['hits']),1)
            self.assertEqual(result['rays'][0]['hits'][0]['mesh_path'],'/Root/Polygon')
            self.assertEqual(result['unsupported'][0]['path'],'/Root/Subdivision')

    def test_convex_ngon_is_supported_but_a_self_crossing_star_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'polygons.usda';stage=stage_at(path)
            vertices=[(math.cos(i*2*math.pi/5),math.sin(i*2*math.pi/5),0) for i in range(5)]
            value=mesh(stage,'/Polygon',[vertices]);stage.GetRootLayer().Save()
            self.assertTrue(probe(path,'/Polygon',[ray()])['complete'])
            value.GetPointsAttr().Set([vertices[i] for i in (0,2,4,1,3)]);stage.GetRootLayer().Save()
            result=probe(path,'/Polygon',[ray()]);self.assertFalse(result['complete']);self.assertEqual(result['rays'][0]['hits'],[])

    def test_singular_projective_and_deformed_geometry_is_not_approximated(self):
        for kind in ('singular','projective','skinning'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'transform.usda';stage=stage_at(path);value=mesh(stage,'/Shape',[plane()])
                if kind=='singular':UsdGeom.Xformable(value).AddScaleOp().Set(Gf.Vec3f(0,1,1))
                elif kind=='projective':
                    matrix=Gf.Matrix4d(1);matrix[0,3]=.1;UsdGeom.Xformable(value).AddTransformOp().Set(matrix)
                else:value.GetPrim().AddAppliedSchema('SkelBindingAPI')
                stage.GetRootLayer().Save();result=probe(path,'/Shape',[ray()])
                self.assertFalse(result['complete']);self.assertTrue(result['unsupported'])

    def test_nonlocal_or_missing_composition_is_rejected_before_stage_open(self):
        for reference in ('https://example.invalid/remote.usda','missing.usda'):
            with self.subTest(reference=reference),tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'root.usda'
                path.write_text('#usda 1.0\ndef Xform "Root" ( references = @'+reference+'@ ) {}\n')
                with patch.object(Usd.Stage,'Open',side_effect=AssertionError('must not compose/fetch invalid dependency')):
                    with self.assertRaises(ValueError):probe(path,'/Root',[ray()])

    def test_stale_clean_cache_is_rejected_without_discarding_unsaved_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'cached.usda';stage=stage_at(path);value=mesh(stage,'/Surface',[plane()]);stage.GetRootLayer().Save()
            text=path.read_text();path.write_text(text.replace('(-1, -1, 0)','(-1, -1, 9)'))
            self.assertFalse(stage.GetRootLayer().dirty)
            with self.assertRaisesRegex(ValueError,'stale'):probe(path,'/Surface',[ray()])
            self.assertEqual(value.GetPointsAttr().Get()[0][2],0)
            broken=Path(tmp)/'broken.usda';broken.write_text('not a USD document')
            with self.assertRaises(ValueError):probe(broken,'/Surface',[ray()])

    def test_missing_invalid_and_unsaved_sources_fail_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'plane.usda';stage=stage_at(path);value=mesh(stage,'/Surface',[plane()]);stage.GetRootLayer().Save()
            with self.assertRaises(ValueError):probe(Path(tmp)/'missing.usda','/Surface',[ray()])
            with self.assertRaises(ValueError):probe(path,'/Missing',[ray()])
            for invalid in (ray(direction=(0,0,0)),ray(origin=(math.nan,0,0)),ray(maximum_distance_m=-1)):
                with self.assertRaises(ValueError):probe(path,'/Surface',[invalid])
            saved=path.read_bytes();value.GetPointsAttr().Set([(-1,-1,9),(1,-1,9),(1,1,9),(-1,1,9)])
            with self.assertRaisesRegex(ValueError,'unsaved'):probe(path,'/Surface',[ray()])
            self.assertEqual(path.read_bytes(),saved);self.assertTrue(stage.GetRootLayer().dirty)

    def test_cli_reads_local_inputs_from_another_directory_and_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'synthetic.usda';stage=stage_at(path);open_container(stage);stage.GetRootLayer().Save()
            rays=root/'rays.json';rays.write_text(json.dumps([ray()]))
            output=root/'measurement.json';helper=Path(__file__).resolve().parents[1]/'experiments/usd_geometry_probe.py'
            args=[sys.executable,str(helper),str(path),'--prim','/Cup','--rays',str(rays),'--output',str(output)]
            result=subprocess.run(args,cwd=root,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            measured=json.loads(output.read_text());self.assertTrue(measured['complete'])
            self.assertEqual(measured['helper_sha256'],hashlib.sha256(helper.read_bytes()).hexdigest())
            before=output.read_bytes();again=subprocess.run(args,cwd=root,capture_output=True,text=True)
            self.assertNotEqual(again.returncode,0);self.assertEqual(output.read_bytes(),before)


class GeometryProbeV2ScopeTest(unittest.TestCase):
    def displacement_stage(self, path, context='', unknown=False, material_name='Material'):
        stage=stage_at(path);value=mesh(stage,'/Surface',[plane()])
        material=UsdShade.Material.Define(stage,'/'+material_name)
        shader=UsdShade.Shader.Define(stage,'/'+material_name+'/Shader')
        shader.CreateIdAttr('UnrecognizedDisplacementImplementation' if unknown else 'UsdPreviewSurface')
        if not unknown:shader.CreateInput('displacement',Sdf.ValueTypeNames.Float).Set(.25)
        shader.CreateOutput('displacement',Sdf.ValueTypeNames.Float)
        name=(context+':' if context else '')+'displacement'
        material.CreateOutput(name,Sdf.ValueTypeNames.Float).ConnectToSource(shader.ConnectableAPI(),'displacement')
        UsdShade.MaterialBindingAPI.Apply(value.GetPrim()).Bind(material);stage.GetRootLayer().Save()
        return stage,value,material,shader

    def test_every_render_context_displacement_terminal_is_rejected_by_default(self):
        for context in ('','mdl','ri','vendor:nested'):
            with self.subTest(context=context),tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'source.usda';stage,_,_,_=self.displacement_stage(path,context)
                result=probe(path,'/Surface',[ray()])
                self.assertFalse(result['complete']);self.assertEqual(result['rays'][0]['hits'],[])
                self.assertEqual(len(result['displacement_candidates']),1)
                self.assertEqual(result['displacement_candidates'][0]['terminal'],'outputs:'+((context+':') if context else '')+'displacement')
                self.assertEqual(result['rendered_surface_equivalence'],'not_established')

    def test_explicit_nonzero_displacement_authored_mode_never_proves_renderer_equivalence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'nonzero.usda';stage,value,material,shader=self.displacement_stage(path,'mdl')
            before=path.read_bytes();result=probe(path,'/Surface',[ray()],scope='authored_base_geometry')
            self.assertTrue(result['geometry_query_complete']);self.assertTrue(result['complete'])
            self.assertEqual(result['rays'][0]['hits'][0]['point_world_m'][2],0)
            self.assertEqual(shader.GetInput('displacement').Get(),.25)
            self.assertEqual(result['rendered_surface_equivalence'],'not_established');self.assertFalse(result['rendered_surface_query_complete'])
            self.assertEqual(result['displacement_evaluation'],'not_evaluated')
            self.assertEqual(path.read_bytes(),before);self.assertFalse(stage.GetRootLayer().dirty)
            self.assertTrue(material.GetOutput('mdl:displacement').HasConnectedSource())

    def test_unknown_implementation_and_material_name_never_become_a_zero_exception(self):
        for name in ('Material','OmniPBR','ArbitraryName'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'unknown.usda';stage,_,_,_=self.displacement_stage(path,'ri',unknown=True,material_name=name)
                strict=probe(path,'/Surface',[ray()]);authored=probe(path,'/Surface',[ray()],scope='authored_base_geometry')
                self.assertFalse(strict['complete']);self.assertTrue(authored['geometry_query_complete'])
                self.assertEqual(authored['rendered_surface_equivalence'],'not_established')
                self.assertEqual(authored['displacement_candidates'][0]['evaluation'],'not_evaluated')

    def test_unresolved_connection_is_unknown_not_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'unresolved.usda';stage=stage_at(path);value=mesh(stage,'/Surface',[plane()]);material=UsdShade.Material.Define(stage,'/Material')
            material.CreateOutput('mdl:displacement',Sdf.ValueTypeNames.Float).GetAttr().SetConnections([Sdf.Path('/MissingShader.outputs:displacement')])
            UsdShade.MaterialBindingAPI.Apply(value.GetPrim()).Bind(material);stage.GetRootLayer().Save()
            strict=probe(path,'/Surface',[ray()]);authored=probe(path,'/Surface',[ray()],scope='authored_base_geometry')
            self.assertFalse(strict['complete']);self.assertTrue(authored['geometry_query_complete'])
            self.assertEqual(authored['displacement_candidates'][0]['connections'],['/MissingShader.outputs:displacement'])
            self.assertFalse(authored['rendered_surface_query_complete'])

    def test_authored_scope_keeps_all_subdivision_and_topology_rejections(self):
        for kind in ('subdivision','concave','nonplanar','sphere'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'unsupported.usda';stage=stage_at(path)
                if kind=='sphere':UsdGeom.Sphere.Define(stage,'/Shape')
                elif kind=='concave':mesh(stage,'/Shape',[[(0,0,0),(2,0,0),(1,1,0),(2,2,0),(0,2,0)]])
                elif kind=='nonplanar':mesh(stage,'/Shape',[[(-1,-1,0),(1,-1,0),(1,1,.1),(-1,1,0)]])
                else:mesh(stage,'/Shape',[plane()],None)
                stage.GetRootLayer().Save();result=probe(path,'/Shape',[ray()],scope='authored_base_geometry')
                self.assertFalse(result['complete']);self.assertTrue(result['unsupported']);self.assertEqual(result['rays'][0]['hits'],[])

    def test_multiple_contexts_and_subset_bindings_are_all_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'contexts.usda';stage,value,material,shader=self.displacement_stage(path,'mdl')
            material.CreateOutput('ri:displacement',Sdf.ValueTypeNames.Float).ConnectToSource(shader.ConnectableAPI(),'displacement')
            subset=UsdGeom.Subset.Define(stage,'/Surface/Subset');subset.CreateElementTypeAttr('face');subset.CreateIndicesAttr([0])
            other=UsdShade.Material.Define(stage,'/Other');other.CreateOutput('vendor:displacement',Sdf.ValueTypeNames.Float).ConnectToSource(shader.ConnectableAPI(),'displacement')
            UsdShade.MaterialBindingAPI.Apply(subset.GetPrim()).Bind(other);stage.GetRootLayer().Save()
            strict=probe(path,'/Surface',[ray()]);authored=probe(path,'/Surface',[ray()],scope='authored_base_geometry')
            self.assertFalse(strict['complete']);self.assertTrue(authored['geometry_query_complete'])
            candidates=authored['displacement_candidates']
            self.assertEqual({c['terminal'] for c in candidates},{'outputs:mdl:displacement','outputs:ri:displacement','outputs:vendor:displacement'})
            self.assertEqual({c['binding_prim_path'] for c in candidates},{'/Surface','/Surface/Subset'})
            self.assertTrue(all(c['evaluation']=='not_evaluated' for c in candidates))

    def test_modes_use_identical_numeric_intersections_for_supported_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'same.usda';stage=stage_at(path,.01,'Y')
            value=mesh(stage,'/Surface',[plane()]);transform=UsdGeom.Xformable(value)
            transform.AddTranslateOp().Set(Gf.Vec3d(0,0,10));transform.AddScaleOp().Set(Gf.Vec3f(-2,3,1));stage.GetRootLayer().Save()
            rays=[ray((0,0,1)),ray((.01,.01,1))]
            strict=probe(path,'/Surface',rays);authored=probe(path,'/Surface',rays,scope='authored_base_geometry')
            self.assertTrue(strict['complete']);self.assertEqual(strict['rays'],authored['rays'])
            self.assertEqual(strict['rendered_surface_equivalence'],authored['rendered_surface_equivalence'])

    def test_cli_authored_summary_cannot_omit_the_renderer_unknown_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'nonzero.usda';stage,_,_,_=self.displacement_stage(path,'mdl')
            rays=root/'rays.json';rays.write_text(json.dumps([ray()]))
            helper=Path(__file__).resolve().parents[1]/'experiments/usd_geometry_probe.py';output=root/'base-query.json'
            result=subprocess.run([sys.executable,str(helper),str(path),'--prim','/Surface','--rays',str(rays),'--scope','authored_base_geometry','--output',str(output)],cwd=root,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr);summary=json.loads(result.stdout)
            self.assertTrue(summary['geometry_query_complete']);self.assertEqual(summary['rendered_surface_equivalence'],'not_established');self.assertFalse(summary['rendered_surface_query_complete'])


if __name__=='__main__':unittest.main()
