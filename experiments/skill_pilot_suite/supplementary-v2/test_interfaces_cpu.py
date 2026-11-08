"""Real USD export/readback interface regressions; no Isaac or physics run."""
from pathlib import Path
import ast,copy,hashlib,json,os,sys,tempfile,unittest
from pxr import Usd,UsdPhysics
from simscene.usd_export import export_scene
import simscene
import score_v2 as checker

BASE=Path(__file__).resolve().parents[2]
ORIGINAL = Path(os.environ.get("PILOT_ORIGINAL_DESIGN", str(BASE / "pilot-private-design"))).expanduser().resolve()


class CompiledCollisionInterfaces(unittest.TestCase):
    def fixture(self,kind='box',collision='ABSENT',scheduled=False):
        self.folder=tempfile.TemporaryDirectory(prefix='supp-v2-usd-regression-')
        self.addCleanup(self.folder.cleanup)
        root=Path(self.folder.name)
        obj={'kind':kind,'dynamic':True,'mass_kg':0.1,'position':[0,0,0.2]}
        if kind=='compound':obj['parts']=[{'kind':'box','size':[0.1]*3,'position':[0,0,0]}]
        else:obj['size']=[0.1]*3
        if collision!='ABSENT':obj['collision']=collision
        if scheduled:obj['spawn_step']=60
        spec={'schema_version':'0.1','scene_id':'unrelated_cpu_export','revision':0,'world':{'units':'m','up_axis':'Z'},'objects':{'probe':obj},'requests':{}}
        export_scene(spec,root/'scene.usda')
        package=Path(simscene.__file__).resolve().parent
        dependencies=('usd_export.py','passive.py','materials.py','attachments.py','capture.py','d6.py','geometry.py','scene.py','worker/spawn.py')
        lock={'worker_code_sha256':{n:hashlib.sha256((package/n).read_bytes()).hexdigest() for n in dependencies}}
        case={'allowed_geometry':['box','sphere','cylinder','capsule','compound'],'dynamic_ids':['probe']}
        return root,spec,case,lock

    def evaluate(self,fixture):return checker.effective_compiled_collisions(*fixture)

    def test_real_exported_dynamic_box_without_collision_key(self):
        fixture=self.fixture()
        stage=Usd.Stage.Open(str(fixture[0]/'scene.usda'));body=stage.GetPrimAtPath('/World/probe')
        self.assertTrue(body.HasAPI(UsdPhysics.CollisionAPI))
        self.assertTrue(body.HasAPI(UsdPhysics.RigidBodyAPI))
        report=self.evaluate(fixture)
        self.assertTrue(report['passed'],report)
        self.assertEqual(report['bodies']['probe']['source_collision_field'],'ABSENT')

    def test_real_exported_dynamic_compound_colliders(self):
        report=self.evaluate(self.fixture('compound'))
        self.assertTrue(report['passed'],report)
        self.assertEqual(report['bodies']['probe']['enabled_colliders'],['/World/probe/part_0/Shape'])

    def test_dynamic_true_export_policy_remains_effective_when_source_collision_false(self):
        fixture=self.fixture(collision=False)
        stage=Usd.Stage.Open(str(fixture[0]/'scene.usda'))
        self.assertTrue(stage.GetPrimAtPath('/World/probe').HasAPI(UsdPhysics.CollisionAPI))
        self.assertTrue(self.evaluate(fixture)['passed'])

    def test_source_true_does_not_hide_missing_compiled_collision_api(self):
        fixture=self.fixture(collision=True)
        stage=Usd.Stage.Open(str(fixture[0]/'scene.usda'));body=stage.GetPrimAtPath('/World/probe')
        body.RemoveAPI(UsdPhysics.CollisionAPI);stage.GetRootLayer().Save()
        self.assertFalse(self.evaluate(fixture)['passed'])

    def test_source_true_does_not_hide_disabled_compiled_collider(self):
        fixture=self.fixture(collision=True)
        stage=Usd.Stage.Open(str(fixture[0]/'scene.usda'))
        UsdPhysics.CollisionAPI(stage.GetPrimAtPath('/World/probe')).CreateCollisionEnabledAttr(False)
        stage.GetRootLayer().Save()
        self.assertFalse(self.evaluate(fixture)['passed'])

    def test_disabled_compiled_rigid_body_fails(self):
        fixture=self.fixture();stage=Usd.Stage.Open(str(fixture[0]/'scene.usda'))
        UsdPhysics.RigidBodyAPI(stage.GetPrimAtPath('/World/probe')).CreateRigidBodyEnabledAttr(False)
        stage.GetRootLayer().Save();self.assertFalse(self.evaluate(fixture)['passed'])

    def test_kinematic_compiled_body_fails(self):
        fixture=self.fixture();stage=Usd.Stage.Open(str(fixture[0]/'scene.usda'))
        UsdPhysics.RigidBodyAPI(stage.GetPrimAtPath('/World/probe')).CreateKinematicEnabledAttr(True)
        stage.GetRootLayer().Save();self.assertFalse(self.evaluate(fixture)['passed'])

    def test_scheduled_body_uses_cpu_compilation_without_touching_sealed_stage(self):
        fixture=self.fixture('sphere',scheduled=True);file=fixture[0]/'scene.usda';before=file.read_bytes()
        stage=Usd.Stage.Open(str(file));self.assertFalse(stage.GetPrimAtPath('/World/probe'))
        report=self.evaluate(fixture)
        self.assertTrue(report['passed'],report)
        self.assertIn('CPU source-equivalent',report['bodies']['probe']['stage_witness'])
        self.assertEqual(file.read_bytes(),before)
        self.assertEqual(fixture[1]['objects']['probe']['spawn_step'],60)

    def test_unpinned_compiler_is_not_substituted(self):
        fixture=self.fixture();fixture[3]['worker_code_sha256']['usd_export.py']='0'*64
        report=self.evaluate(fixture)
        self.assertFalse(report['passed']);self.assertFalse(report['compiler_identity']['usd_export.py'])


class EmptyJointInterfaces(unittest.TestCase):
    def test_native_no_joint_encoding_accepts_omitted_sample_key(self):
        self.assertTrue(checker.empty_joint_observations_valid([{'joints':{}},{'physics_steps':1},{'physics_steps':2}]))

    def test_explicit_empty_maps_remain_valid(self):
        self.assertTrue(checker.empty_joint_observations_valid([{'joints':{}},{'joints':{}}]))

    def test_none_is_not_an_empty_map(self):
        self.assertFalse(checker.empty_joint_observations_valid([{'joints':{}},{'joints':None}]))

    def test_unexpected_joint_observation_fails(self):
        self.assertFalse(checker.empty_joint_observations_valid([{'joints':{}},{'joints':{'extra':{}}}]))


class UnchangedPhysicsContract(unittest.TestCase):
    def test_original_numeric_and_causal_functions_ast_identical(self):
        a=ast.parse((ORIGINAL/'examiner/score.py').read_text());b=ast.parse(Path(checker.__file__).read_text())
        fa={n.name:ast.dump(n,include_attributes=False) for n in a.body if isinstance(n,ast.FunctionDef)}
        fb={n.name:ast.dump(n,include_attributes=False) for n in b.body if isinstance(n,ast.FunctionDef)}
        changed={name for name,body in fa.items() if fb.get(name)!=body}
        self.assertEqual(changed,{'source_checks','load_native','main'})
        for name in ('task_predicates','driver_metrics','isolated_intervention','strict_initial_state' if 'strict_initial_state' in fa else 'body_quiet'):
            self.assertEqual(fa[name],fb[name])

    def test_original_freeze_and_cases_unchanged(self):
        checker.ROOT=ORIGINAL
        self.assertTrue(checker.frozen_design()['passed'])
        original= json.loads((ORIGINAL/'DESIGN-FREEZE.json').read_text())
        for rel in ('public/P1/public-case.json','public/P2/public-case.json'):
            self.assertEqual(hashlib.sha256((ORIGINAL/rel).read_bytes()).hexdigest(),original['files_sha256'][rel])


if __name__=='__main__':unittest.main()
