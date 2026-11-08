"""Synthetic local USD and exact-SAT adversaries; no actual house candidates."""
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from pxr import Gf,Sdf,Usd,UsdGeom,UsdShade
from experiments import usd_box_surface_probe as b


def stage_at(path,metres=1,up='Z'):
    stage=Usd.Stage.CreateNew(str(path));UsdGeom.SetStageMetersPerUnit(stage,metres);UsdGeom.SetStageUpAxis(stage,up)
    return stage


def mesh(stage,path,faces,scheme='none'):
    value=UsdGeom.Mesh.Define(stage,path)
    value.CreatePointsAttr([point for face in faces for point in face])
    value.CreateFaceVertexCountsAttr([len(face) for face in faces])
    value.CreateFaceVertexIndicesAttr(list(range(sum(map(len,faces)))))
    if scheme is not None:value.CreateSubdivisionSchemeAttr(scheme)
    return value


def plane(z=0):return [(-2,-2,z),(2,-2,z),(2,2,z),(-2,2,z)]
def box(center=(0,0,0),half=(.1,.1,.1),axes=None):
    return {'center_world_m':list(center),'half_size_m':list(half),
            'axes_world':axes or [[1,0,0],[0,1,0],[0,0,1]]}


class BoxSurfaceProbeTest(unittest.TestCase):
    def test_crossing_without_any_triangle_vertex_in_box(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'crossing.usda';stage=stage_at(path)
            triangle=[(-2,-2,0),(2,-2,0),(0,2,0)]
            self.assertTrue(all(any(abs(x)>.1 for x in vertex) for vertex in triangle))
            mesh(stage,'/Surface',[triangle]);stage.GetRootLayer().Save()
            before=hashlib.sha256(path.read_bytes()).hexdigest()
            result=b.probe(path,'/Surface',box())
            self.assertTrue(result['complete']);self.assertEqual(len(result['intersecting_faces']),1)
            self.assertFalse(result['surface_disjointness_established']);self.assertFalse(result['containment_established'])
            self.assertEqual(result['intersecting_faces'][0]['face_index'],0)
            self.assertEqual(result['triangles_examined'],1)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
            self.assertFalse(stage.GetRootLayer().dirty)

    def test_diagonal_separating_axis_despite_aabb_projection_overlap(self):
        triangle=[[2,0,0],[0,2,0],[2,2,0]]
        result=b.triangle_box(triangle,b._box(box(half=(.5,.5,.5))))
        self.assertEqual(result['classification'],'separated')
        self.assertTrue(result['separating_axis'].startswith('edge_'))

    def test_face_edge_and_point_tangencies_are_not_clear(self):
        triangles=[[[ -2,-2,.5],[2,-2,.5],[0,2,.5]],
                   [[.5,.5,-1],[.5,.5,1],[2,.5,0]],
                   [[.5,.5,.5],[2,.5,.5],[.5,2,.5]]]
        for triangle in triangles:
            with self.subTest(triangle=triangle):
                result=b.triangle_box(triangle,b._box(box(half=(.5,.5,.5))))
                self.assertEqual(result['classification'],'touching')
                self.assertTrue(result['exact_boundary_axes'])

    def test_expansion_only_uncertainty_does_not_become_clear_or_inside(self):
        for distance,expected in ((.5,'touching'),(.5+5e-10,'ambiguous'),(.5+2e-9,'separated')):
            with self.subTest(distance=distance),tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'boundary.usda';stage=stage_at(path)
                value=mesh(stage,'/Surface',[plane()])
                UsdGeom.Xformable(value).AddTranslateOp().Set(Gf.Vec3d(0,0,distance));stage.GetRootLayer().Save()
                result=b.probe(path,'/Surface',box(half=(.5,.5,.5)))
                if expected=='ambiguous':
                    self.assertFalse(result['complete']);self.assertEqual(len(result['ambiguous_faces']),2)
                    self.assertFalse(result['surface_disjointness_established'])
                elif expected=='touching':
                    self.assertTrue(result['complete']);self.assertTrue(result['touching_faces'])
                    self.assertFalse(result['surface_disjointness_established'])
                else:self.assertTrue(result['surface_disjointness_established'])
                self.assertFalse(result['containment_established'])

    def test_rotated_box_changes_real_relation_without_axis_snapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'rotated.usda';stage=stage_at(path)
            mesh(stage,'/Surface',[[(.28,.28,0),(.32,.28,0),(.3,.32,0)]])
            stage.GetRootLayer().Save();angle=math.pi/4
            axes=[[math.cos(angle),math.sin(angle),0],[-math.sin(angle),math.cos(angle),0],[0,0,1]]
            rotated=box(half=(.5,.05,.1),axes=axes)
            self.assertTrue(b.probe(path,'/Surface',box(half=(.5,.05,.1)))['surface_disjointness_established'])
            result=b.probe(path,'/Surface',rotated)
            self.assertTrue(result['complete']);self.assertTrue(result['intersecting_faces'])
            self.assertEqual(result['box']['axes_world'],axes)

    def test_almost_orthogonal_axes_need_true_cross_product_face_normals(self):
        axes=[[1,0,0],[1e-13,1,0],[0,0,1]]
        value=box(half=(1,1e6,1),axes=axes)
        triangle=[[.99999996,-5e5,-.1],[.99999996,-5e5+.1,.1],[.99999996,-5e5-.1,.1]]
        prepared=b._box(value)  # Accepted, but mathematically not orthogonal.
        naive_radius=sum(h*abs(b._dot(prepared['axes'][0],edge)) for h,edge in zip(prepared['half'],prepared['axes']))
        naive_projections=[b._dot(b._rational(point),prepared['axes'][0]) for point in triangle]
        self.assertLess(min(naive_projections),naive_radius)
        self.assertGreater(max(naive_projections),-naive_radius)
        result=b.triangle_box(triangle,prepared)
        self.assertEqual(result['classification'],'separated')
        self.assertEqual(result['separating_axis'],'box_face_0')

    def test_thin_valid_surface_and_degenerate_surface_are_distinct(self):
        for height,valid in ((1e-7,True),(0,False)):
            with self.subTest(height=height),tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'thin.usda';stage=stage_at(path)
                mesh(stage,'/Surface',[[(-1,0,0),(1,0,0),(0,height,0)]]);stage.GetRootLayer().Save()
                result=b.probe(path,'/Surface',box(half=(1e-8,1e-8,1e-8)))
                self.assertEqual(result['complete'],valid)
                if valid:self.assertTrue(result['intersecting_faces'])
                else:self.assertTrue(result['unsupported']);self.assertFalse(result['surface_disjointness_established'])
        result=b.triangle_box([[0,0,0],[1,0,0],[2,0,0]],b._box(box()))
        self.assertEqual(result['classification'],'ambiguous')

    def test_unit_scale_mirror_nonuniform_transform_and_up_axis(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'units.usda';stage=stage_at(path,.01,'Y')
            parent=UsdGeom.Xform.Define(stage,'/Group');transform=UsdGeom.Xformable(parent)
            transform.AddTranslateOp().Set(Gf.Vec3d(100,200,300));transform.AddRotateYOp().Set(90)
            transform.AddScaleOp().Set(Gf.Vec3f(-2,3,1));mesh(stage,'/Group/Surface',[plane()]);stage.GetRootLayer().Save()
            result=b.probe(path,'/Group',box(center=(1,2,3),half=(.01,.01,.01)))
            self.assertTrue(result['complete']);self.assertTrue(result['intersecting_faces'])
            self.assertEqual(result['units']['metres_per_stage_unit'],.01);self.assertEqual(result['units']['up_axis'],'Y')
            self.assertEqual(result['meshes'][0]['transform_handedness'],-1)
            self.assertAlmostEqual(result['intersecting_faces'][0]['normal_world'][0],1)
            self.assertTrue(b.probe(path,'/Group',box(center=(1.1,2,3),half=(.01,.01,.01)))['surface_disjointness_established'])

    def test_native_instance_identity_and_explicit_reference_units(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);model=stage_at(root/'model.usda',.01)
            model.SetDefaultPrim(UsdGeom.Xform.Define(model,'/Model').GetPrim());mesh(model,'/Model/Surface',[plane(10)]);model.GetRootLayer().Save()
            path=root/'instances.usda';stage=stage_at(path);UsdGeom.Xform.Define(stage,'/World')
            for name,z in (('Low',1),('High',3)):
                prim=UsdGeom.Xform.Define(stage,'/World/'+name).GetPrim();prim.GetReferences().AddReference('./model.usda');prim.SetInstanceable(True)
                xf=UsdGeom.Xformable(prim);xf.AddTranslateOp().Set(Gf.Vec3d(0,0,z));xf.AddScaleOp().Set(Gf.Vec3f(.01))
            stage.GetRootLayer().Save()
            result=b.probe(path,'/World',box(center=(0,0,1.1),half=(.05,.05,.05)))
            self.assertTrue(result['complete']);self.assertEqual(len(result['meshes']),2)
            self.assertEqual({f['mesh_path'] for f in result['intersecting_faces']},{'/World/Low/Surface'})
            self.assertTrue(all(f['prototype_mesh_path'] for f in result['intersecting_faces']))
            subtree=b.probe(path,'/World/Low/Surface',box(center=(0,0,1.1)))
            self.assertEqual(len(subtree['meshes']),1)

    def test_no_surface_intersection_never_decides_inside_or_cavity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'solid.usda';stage=stage_at(path);UsdGeom.Cube.Define(stage,'/Solid');stage.GetRootLayer().Save()
            for center in ((0,0,0),(3,0,0)):
                result=b.probe(path,'/Solid',box(center=center))
                self.assertTrue(result['complete']);self.assertTrue(result['surface_disjointness_established'])
                self.assertFalse(result['containment_established']);self.assertEqual(result['cavity_membership'],'not_assessed')
                self.assertEqual(result['triangles_examined'],12)
                self.assertEqual(result['meshes'][0]['authored_face_count'],6)

    def test_convex_fan_and_holes_keep_original_face_triangle_identities(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'faces.usda';stage=stage_at(path)
            value=mesh(stage,'/Surface',[plane(),plane(1)]);value.CreateHoleIndicesAttr([1]);stage.GetRootLayer().Save()
            result=b.probe(path,'/Surface',box())
            self.assertTrue(result['complete']);self.assertEqual(len(result['intersecting_faces']),2)
            self.assertEqual({f['face_index'] for f in result['intersecting_faces']},{0})
            self.assertEqual({f['triangle_index'] for f in result['intersecting_faces']},{0,1})
            self.assertEqual(result['meshes'][0]['hole_face_count'],1)

    def test_visibility_purpose_filters_are_explicit_and_not_hidden_clearance(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'filters.usda';stage=stage_at(path);UsdGeom.Xform.Define(stage,'/Root')
            mesh(stage,'/Root/Clear',[plane(10)])
            hidden=mesh(stage,'/Root/Hidden',[plane()]);hidden.CreateVisibilityAttr('invisible')
            proxy=mesh(stage,'/Root/Proxy',[plane()]);proxy.CreatePurposeAttr('proxy');stage.GetRootLayer().Save()
            selected=b.probe(path,'/Root',box());self.assertTrue(selected['surface_disjointness_established'])
            self.assertEqual(len(selected['excluded']),2)
            all_selected=b.probe(path,'/Root',box(),include_invisible=True,purposes=('default','render','proxy'))
            self.assertTrue(all_selected['complete']);self.assertFalse(all_selected['surface_disjointness_established'])
            self.assertEqual(len(all_selected['intersecting_faces']),4)

    def test_unsupported_or_invalid_geometry_makes_whole_query_incomplete(self):
        for kind in ('subdivision','sphere','point_instancer','bad_index','nonplanar','concave','skinning','singular','nonfinite'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'unknown.usda';stage=stage_at(path);UsdGeom.Xform.Define(stage,'/Root');mesh(stage,'/Root/Good',[plane(10)])
                if kind=='sphere':UsdGeom.Sphere.Define(stage,'/Root/Unknown')
                elif kind=='point_instancer':UsdGeom.PointInstancer.Define(stage,'/Root/Unknown')
                else:
                    value=mesh(stage,'/Root/Unknown',[plane()],None if kind=='subdivision' else 'none')
                    if kind=='bad_index':value.GetFaceVertexIndicesAttr().Set([0,1,2,99])
                    if kind=='nonplanar':value.GetPointsAttr().Set([(-2,-2,0),(2,-2,0),(2,2,.1),(-2,2,0)])
                    if kind=='concave':value.GetPointsAttr().Set([(0,0,0),(2,0,0),(.5,.5,0),(0,2,0)])
                    if kind=='skinning':value.GetPrim().CreateAttribute('primvars:skel:jointIndices',Sdf.ValueTypeNames.IntArray).Set([0])
                    if kind=='singular':UsdGeom.Xformable(value).AddScaleOp().Set(Gf.Vec3f(0,1,1))
                    if kind=='nonfinite':value.GetPointsAttr().Set([(float('nan'),0,0),(1,0,0),(1,1,0),(0,1,0)])
                stage.GetRootLayer().Save();result=b.probe(path,'/Root',box())
                self.assertFalse(result['complete']);self.assertTrue(result['unsupported']);self.assertFalse(result['surface_disjointness_established'])

    def test_displacement_contexts_strict_rejection_and_authored_unknown(self):
        for context in ('mdl','ri','vendor:nested'):
            with self.subTest(context=context),tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'material.usda';stage=stage_at(path);value=mesh(stage,'/Surface',[plane()])
                material=UsdShade.Material.Define(stage,'/Material');shader=UsdShade.Shader.Define(stage,'/Material/Shader')
                shader.CreateIdAttr('UsdPreviewSurface');shader.CreateInput('displacement',Sdf.ValueTypeNames.Float).Set(.25)
                shader.CreateOutput('out',Sdf.ValueTypeNames.Float)
                material.CreateDisplacementOutput(context).ConnectToSource(shader.ConnectableAPI(),'out')
                UsdShade.MaterialBindingAPI.Apply(value.GetPrim()).Bind(material);stage.GetRootLayer().Save()
                before=hashlib.sha256(path.read_bytes()).hexdigest()
                strict=b.probe(path,'/Surface',box());self.assertFalse(strict['complete']);self.assertTrue(strict['unsupported'])
                authored=b.probe(path,'/Surface',box(),scope='authored_base_geometry')
                self.assertTrue(authored['complete']);self.assertTrue(authored['intersecting_faces'])
                self.assertEqual(authored['rendered_surface_equivalence'],'not_established')
                self.assertFalse(authored['rendered_surface_query_complete']);self.assertFalse(authored['containment_established'])
                self.assertEqual(len(authored['displacement_candidates']),1)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)

    def test_triangle_face_and_prim_budget_failures_cannot_certify_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'budgets.usda';stage=stage_at(path);UsdGeom.Xform.Define(stage,'/Root')
            mesh(stage,'/Root/First',[plane(10)]);mesh(stage,'/Root/Second',[plane()]);stage.GetRootLayer().Save()
            for kwargs in ({'maximum_triangles':1},{'maximum_faces_per_prim':1},{'maximum_prims':2}):
                # A quad triangulates into two: per-prim triangle budget=1 also rejects a face.
                with self.subTest(kwargs=kwargs):
                    result=b.probe(path,'/Root',box(),**kwargs)
                    self.assertFalse(result['complete']);self.assertFalse(result['surface_disjointness_established'])
                    self.assertTrue(result['unsupported'] or result['resource_failures'])
                    self.assertLessEqual(result['sat_axis_checks'],result['selection']['maximum_total_sat_axis_checks'])

    def test_invalid_box_unknown_scope_and_invalid_budgets_fail_closed(self):
        invalid=[box(half=(0,1,1)),box(center=(float('inf'),0,0)),box(axes=[[1,0,0],[2e-12,1,0],[0,0,1]]),
                 box(axes=[[1,0,0],[1,0,0],[0,0,1]]),box(axes=[[2,0,0],[0,1,0],[0,0,1]]),
                 {'center_world_m':[0,0,0]},None]
        for value in invalid:
            result=b.probe('/not/read.usda','/Surface',value)
            self.assertFalse(result['complete']);self.assertTrue(result['input_errors']);json.dumps(result,allow_nan=False)
        for kwargs in ({'scope':'unknown'},{'maximum_triangles':0},{'maximum_triangles':100001},{'maximum_faces_per_prim':True},{'maximum_prims':0}):
            result=b.probe('/not/read.usda','/Surface',box(),**kwargs)
            self.assertFalse(result['complete']);self.assertTrue(result['input_errors'])

    def test_missing_empty_and_dirty_sources_and_changed_helper_fail_closed(self):
        self.assertFalse(b.probe('/no/file.usda','/Surface',box())['complete'])
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'source.usda';stage=stage_at(path);UsdGeom.Xform.Define(stage,'/Empty');stage.GetRootLayer().Save()
            self.assertFalse(b.probe(path,'/Missing',box())['complete']);self.assertFalse(b.probe(path,'/Empty',box())['complete'])
            mesh(stage,'/Surface',[plane()])  # Unsaved edits must not be substituted.
            result=b.probe(path,'/Surface',box());self.assertFalse(result['complete']);self.assertIn('unsaved',result['input_errors'][0]['reason'])
            with patch.object(b,'GEOMETRY_HELPER_SHA256','untrusted'):
                self.assertFalse(b.probe(path,'/Empty',box())['complete'])

    def test_nonlocal_composition_rejected_before_stage_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'nonlocal.usda'
            path.write_text('#usda 1.0\n( subLayers = [@https://example.invalid/untrusted.usda@] )\n')
            with patch.object(b.Usd.Stage,'Open',side_effect=AssertionError('must not open remote composition')):
                result=b.probe(path,'/Surface',box())
            self.assertFalse(result['complete']);self.assertIn('nonlocal',result['input_errors'][0]['reason'])

    def test_new_cli_process_reports_scope_and_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'source.usda';stage=stage_at(path);mesh(stage,'/Surface',[plane()]);stage.GetRootLayer().Save()
            boxfile=root/'box.json';boxfile.write_text(json.dumps(box()))
            output=root/'output.json'
            argv=[sys.executable,str(Path(b.__file__).resolve()),str(path),'--prim','/Surface','--box',str(boxfile),'--output',str(output)]
            completed=subprocess.run(argv,text=True,capture_output=True)
            self.assertEqual(completed.returncode,0,completed.stderr)
            result=json.loads(output.read_text());self.assertTrue(result['geometry_query_complete']);self.assertFalse(result['containment_established'])
            self.assertEqual(result['rendered_surface_equivalence'],'not_established')
            before=output.read_bytes();again=subprocess.run(argv,text=True,capture_output=True)
            self.assertNotEqual(again.returncode,0);self.assertEqual(output.read_bytes(),before)
            bad=root/'bad.json';boxfile.write_text(json.dumps(box(center=(float('nan'),0,0))))
            argv[-1]=str(bad);completed=subprocess.run(argv,text=True,capture_output=True)
            self.assertEqual(completed.returncode,1);self.assertFalse(json.loads(bad.read_text())['complete'])


if __name__=='__main__':unittest.main()
