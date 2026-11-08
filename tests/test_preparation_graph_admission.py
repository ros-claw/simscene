import unittest
import hashlib,json,tempfile
from pathlib import Path
from simscene.preparation.inspect import inspect_stage
from simscene.preparation.profiles import PreparationError
try:
    from pxr import Usd,UsdGeom,Sdf,UsdShade
except ImportError:
    Usd=None


@unittest.skipIf(Usd is None,'USD unavailable')
class GraphAdmissionTests(unittest.TestCase):
    def stage(self):
        stage=Usd.Stage.CreateInMemory();root=UsdGeom.Xform.Define(stage,'/Asset')
        stage.SetDefaultPrim(root.GetPrim());mesh=UsdGeom.Mesh.Define(stage,'/Asset/Mesh')
        UsdGeom.SetStageMetersPerUnit(stage,1);UsdGeom.SetStageUpAxis(stage,UsdGeom.Tokens.z)
        mesh.CreatePointsAttr([(-1,-1,-1),(1,-1,1),(-1,1,1),(1,1,-1)])
        mesh.CreateFaceVertexCountsAttr([3]*4);mesh.CreateFaceVertexIndicesAttr([0,1,2,0,3,1,0,2,3,1,3,2])
        return stage

    def test_action_graph_is_rejected_before_entering_the_playing_stage(self):
        for type_name in ('OmniGraph','OmniGraphNode','PythonScript'):
            with self.subTest(type_name=type_name):
                stage=self.stage();stage.DefinePrim('/Asset/Program',type_name)
                with self.assertRaisesRegex(PreparationError,'executable USD graph'):inspect_stage(stage)
        stage=self.stage();node=stage.DefinePrim('/Asset/Program','Scope')
        node.CreateAttribute('node:type',Sdf.ValueTypeNames.Token).Set('omni.graph.scriptnode.ScriptNode')
        with self.assertRaisesRegex(PreparationError,'Python graph'):inspect_stage(stage)

    def test_material_node_graph_remains_supported_and_is_not_mistaken_for_code(self):
        stage=self.stage();UsdShade.NodeGraph.Define(stage,'/Asset/Looks/MaterialGraph')
        report=inspect_stage(stage)
        self.assertEqual(len(report['meshes']),1)

    def test_prepared_cache_binding_cannot_bypass_the_playback_admission_guard(self):
        from simscene.usd_export import export_scene
        from simscene.scene import SceneError
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);stage=self.stage();stage.DefinePrim('/Asset/Program','OmniGraph')
            path=root/'main.usda';stage.Export(str(path))
            digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
            manifest={'schema':'simscene.prepared_asset.v1','schema_version':1,'profile_id':'visual_prop_v1',
                      'main':'main.usda','default_prim':'/Asset','parameters':{'ccd':False},'body_map':{},
                      'files':[{'path':'main.usda','size_bytes':path.stat().st_size,'sha256':digest(path)}]}
            (root/'manifest.json').write_text(json.dumps(manifest))
            obj={'kind':'asset','asset_path':str(path),'asset_binding':{'manifest_path':str(root/'manifest.json'),
                 'manifest_sha256':digest(root/'manifest.json')}}
            with self.assertRaisesRegex(SceneError,'executable USD graph'):
                export_scene({'revision':0,'objects':{'source':obj}},root/'output.usda')


if __name__=='__main__':unittest.main()
