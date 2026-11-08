import copy
import math
import unittest

from simscene.worker.mechanism import (MechanismController, measure_joint,
    usd_drive_values, validate_binding, validate_config)
from simscene.preparation.profiles import validate_parameters, PreparationError


def binding(kind='revolute'):
    return {'joints':{'main':{'joint_path':'/World/valve/Asset/Native/Hinge',
        'type':kind,'parent_body':'/World/valve/Asset/Native/Base',
        'child_body':'/World/valve/Asset/Native/Handle','axis':'Z',
        'limits':[-.2,3.5] if kind=='revolute' else [-.2,.4],
        'position_unit':'rad' if kind=='revolute' else 'm',
        'passive':True,'drive':None,'local_pos0_m':[0.,0.,0.],
        'local_pos1_m':[0.,0.,0.],'local_rot0_wxyz':[1.,0.,0.,0.],
        'local_rot1_wxyz':[1.,0.,0.,0.]}}}


def command(step=0,target=1.,unit='rad'):
    return {'joint_id':'main','trigger':{'type':'at_step','physics_step':step},
            'target_position':target,'position_unit':unit,
            'stiffness':12.,'damping':2.,'max_effort':4.}


def native(joint,angle=0.,x=0.):
    return {'positions':{joint['parent_body']:[1.,2.,3.],joint['child_body']:[1.+x,2.,3.]},
            'orientations_wxyz':{joint['parent_body']:[1.,0.,0.,0.],joint['child_body']:[math.cos(angle/2),0.,0.,math.sin(angle/2)]}}


class FakeBackend:
    def __init__(self):self.calls=[]
    def apply_drive(self,joint,cmd):self.calls.append(copy.deepcopy(cmd));return usd_drive_values(joint,cmd)
    def observe(self,binding,step,native_state=None):return {'main':{'position':0.,'physics_step':step,'measurement_source':'fixture_actual_readback'}}


class ArticulationTests(unittest.TestCase):
    def test_commands_once_exact_step_no_contact_trigger_and_no_pose_setters(self):
        b=binding();backend=FakeBackend();controller=MechanismController(b,{'commands':[command(3)]},backend=backend)
        for step in (0,1,2,3,3,4):controller.step(step,[{'type':'contact','actor_paths':['a','b']}])
        result=controller.observe()
        self.assertEqual(len(backend.calls),1)
        self.assertEqual(result['command_events'][0]['physics_step'],3)
        self.assertEqual(result['command_events'][0]['cause'],'declared_at_step_schedule')
        self.assertEqual(result['runtime_targets']['main']['target_position'],1.)
        self.assertEqual(result['joints']['main']['position'],0.)
        self.assertEqual(b,binding())
        late=MechanismController(b,{'commands':[command(2)]},backend=backend)
        with self.assertRaisesRegex(RuntimeError,'missed'):late.step(3)

    def test_passive_empty_commands_never_add_or_remove_native_drive(self):
        for driven in (False,True):
            b=binding()
            if driven:b['joints']['main'].update(passive=False,drive={'stiffness':1.,'damping':1.,'max_effort':2.})
            backend=FakeBackend();control=MechanismController(b,{},backend=backend)
            control.step(0);control.step(10)
            self.assertEqual(backend.calls,[])
            self.assertEqual(control.observe()['command_events'],[])

    def test_bad_joint_graph_units_limits_frames_and_native_parameters_rejected(self):
        changes=[('type','spherical'),('position_unit','degree'),('limits',[0,7]),
                 ('axis','W'),('local_rot0_wxyz',[2,0,0,0]),('child_body','/World/x/../bad'),
                 ('passive',False),('limits',[0,float('inf')]),('parent_body','/World/valve/Asset/Native/Handle')]
        for key,value in changes:
            b=binding();b['joints']['main'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):validate_binding(b)
        b=binding();b['joints']['second']=copy.deepcopy(b['joints']['main'])
        with self.assertRaises(ValueError):validate_binding(b)

    def test_unknown_or_outside_target_bad_gain_duplicate_and_contact_schedule_rejected(self):
        mutations=[('joint_id','missing'),('target_position',4.),('position_unit','degree'),
                   ('stiffness',0.),('damping',-1.),('max_effort',float('inf')),
                   ('trigger',{'type':'contact','physics_step':0}),
                   ('trigger',{'type':'at_step','physics_step':True})]
        for key,value in mutations:
            c=command();c[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):validate_config(binding(),{'commands':[c]})
        with self.assertRaisesRegex(ValueError,'conflicting'):
            validate_config(binding(),{'commands':[command(),command()]})

    def test_angular_targets_and_gains_are_explicitly_converted_not_just_target(self):
        values=usd_drive_values(binding()['joints']['main'],command(target=math.pi/2))
        self.assertAlmostEqual(values['target_position'],90.)
        self.assertAlmostEqual(values['stiffness'],12*math.pi/180)
        self.assertAlmostEqual(values['damping'],2*math.pi/180)
        self.assertEqual(values['max_force'],4.)
        values=usd_drive_values(binding('prismatic')['joints']['main'],command(target=.1,unit='m'))
        self.assertEqual((values['target_position'],values['stiffness']),(.1,12.))

    def test_actual_relative_frame_measurement_and_unwrap_not_command_echo(self):
        joint=binding()['joints']['main']
        first=measure_joint(joint,native(joint,math.radians(170)),physics_step=0,physics_dt_s=.1)
        second=measure_joint(joint,native(joint,math.radians(-170)),first,physics_step=1,physics_dt_s=.1)
        self.assertAlmostEqual(second['position'],math.radians(190))
        self.assertAlmostEqual(second['velocity'],math.radians(20)/.1)
        # Parent/child have identical frame rotation => zero independent of world rotation.
        state=native(joint,1.)
        state['orientations_wxyz'][joint['parent_body']]=state['orientations_wxyz'][joint['child_body']]
        zero=measure_joint(joint,state,physics_step=0,physics_dt_s=.1)
        self.assertAlmostEqual(zero['position'],0.)
        state['positions'].pop(joint['child_body'])
        with self.assertRaises(ValueError):measure_joint(joint,state,physics_step=1,physics_dt_s=.1)
        slider=binding('prismatic')['joints']['main'];slider['axis']='X'
        result=measure_joint(slider,native(slider,x=.12),physics_step=0,physics_dt_s=.1)
        self.assertAlmostEqual(result['position'],.12)

    def test_native_profile_refuses_unit_scale_rewrite_and_synthesized_physics(self):
        base={'source_physics_policy':'preserve_valid','collision_method':'preserve','proxy_tolerance_m':.002}
        self.assertEqual(validate_parameters('articulated_prop_v1',base)['scale_mode'],'preserve')
        for change in ({'scale_mode':'fit_longest','target_longest_extent_m':1.},
                       {'source_physics_policy':'replace_visual_only'},{'collision_method':'convex_hull'}):
            with self.assertRaises(PreparationError):validate_parameters('articulated_prop_v1',dict(base,**change))


def smoke_fixture():
    from simscene.worker.mechanism import measure_joint
    b=binding();joint=b['joints']['main'];joint['limits']=[0.,1.5]
    frames=[];previous=None;events=[]
    for step in range(301):
        position=min(step/60.,1.) if step<150 else max(0.,1.-(step-150)/60.)
        state=native(joint,position);state.update(physics_steps=step,simulation_time_s=step/60)
        if step in (0,150):
            c=command(step,1. if step==0 else 0.)
            events.append({'joint_id':'main','physics_step':step,'trigger':c['trigger'],'target_position':c['target_position'],'position_unit':'rad','cause':'declared_at_step_schedule','drive_readback':usd_drive_values(joint,c)})
        actual=measure_joint(joint,state,previous,physics_step=step,physics_dt_s=1/60);previous=actual
        state['mechanisms']={'valve':{'joints':{'main':actual},'command_events':copy.deepcopy(events),'runtime_targets':{'main':command(step)}}}
        frames.append(state)
    item={k:joint[k] for k in ('joint_path','parent_body','child_body','limits','position_unit')}
    item.update(joint_id='main',initial_position=0.,min_travel=.8,limit_tolerance=.01,anchor_tolerance_m=.002,
        waypoints=[{'command_step':0,'target_position':1.,'by_step':120,'tolerance':.02},
                   {'command_step':150,'target_position':0.,'by_step':280,'tolerance':.02}])
    case={'schema':'simscene.articulated_asset_smoke.v1','schema_version':1,'mode':'driven','objects':{'valve':item}}
    run={'initial_observation':frames[0],'samples':frames[1:],'body_bindings':{'valve':b},'actual_physics_steps':300,
         'requested_physics_steps':300,'observation_interval_steps':1,'simulation_time_s':5.,'partial':False,
         'samples_truncated':False,'contacts_truncated':False,'contact_geometry_incomplete':False,'followers':{}}
    return run,case


class ArticulatedCheckerTests(unittest.TestCase):
    def test_frozen_actual_forward_reverse_and_partial_missing_samples(self):
        from simscene.verification.articulated_asset_smoke import evaluate
        run,case=smoke_fixture();self.assertTrue(evaluate(run,case)['passed'])
        for key in ('partial','samples_truncated','contacts_truncated','contact_geometry_incomplete'):
            bad=copy.deepcopy(run);bad[key]=True
            with self.subTest(key=key):self.assertFalse(evaluate(bad,case)['passed'])
        bad=copy.deepcopy(run);del bad['samples'][5]
        self.assertFalse(evaluate(bad,case)['passed'])

    def test_command_echo_without_link_motion_and_wrong_body_fail(self):
        from simscene.verification.articulated_asset_smoke import evaluate
        run,case=smoke_fixture()
        for frame in run['samples']:frame['orientations_wxyz']=copy.deepcopy(run['initial_observation']['orientations_wxyz'])
        self.assertFalse(evaluate(run,case)['passed'])
        run,case=smoke_fixture();case['objects']['valve']['child_body']='/World/valve'
        self.assertFalse(evaluate(run,case)['passed'])
        run,case=smoke_fixture();run['samples'][-1]['mechanisms']['valve']['command_events'][0]['cause']='contact'
        self.assertFalse(evaluate(run,case)['passed'])

    def test_passive_mode_rejects_active_schedule_and_unobserved_contact(self):
        from simscene.verification.articulated_asset_smoke import evaluate
        run,case=smoke_fixture();case['mode']='passive';case['objects']['valve']['waypoints']=[]
        self.assertFalse(evaluate(run,case)['passed'])
        for frame in [run['initial_observation']]+run['samples']:
            frame['mechanisms']['valve']['command_events']=[];frame['mechanisms']['valve']['runtime_targets']={}
        self.assertTrue(evaluate(run,case)['passed'])
        case['objects']['valve']['required_contact_actors']=['/World/striker']
        self.assertFalse(evaluate(run,case)['passed'])


class NativeGraphTests(unittest.TestCase):
    def stage(self):
        try:from pxr import Usd,UsdGeom,UsdPhysics
        except ImportError:self.skipTest('OpenUSD CPU fixture requires pxr')
        stage=Usd.Stage.CreateInMemory();root=UsdGeom.Xform.Define(stage,'/Native');stage.SetDefaultPrim(root.GetPrim())
        UsdGeom.SetStageMetersPerUnit(stage,1.);UsdGeom.SetStageUpAxis(stage,UsdGeom.Tokens.z)
        for name in ('Base','Door'):
            prim=UsdGeom.Xform.Define(stage,'/Native/'+name).GetPrim();UsdPhysics.RigidBodyAPI.Apply(prim)
            UsdPhysics.MassAPI.Apply(prim).CreateMassAttr(1.)
            shape=UsdGeom.Cube.Define(stage,'/Native/'+name+'/Collider');UsdPhysics.CollisionAPI.Apply(shape.GetPrim())
        hinge=UsdPhysics.RevoluteJoint.Define(stage,'/Native/Hinge');hinge.CreateBody0Rel().SetTargets(['/Native/Base']);hinge.CreateBody1Rel().SetTargets(['/Native/Door'])
        hinge.CreateAxisAttr('X');hinge.CreateLowerLimitAttr(0.);hinge.CreateUpperLimitAttr(80.)
        return stage

    def test_native_graph_preserves_joint_and_auto_inertia_provenance(self):
        from simscene.preparation.articulation import inspect_articulation
        stage=self.stage();before=stage.GetRootLayer().ExportToString();result=inspect_articulation(stage)
        self.assertEqual(stage.GetRootLayer().ExportToString(),before)
        self.assertEqual(result['joint_map']['main']['relative_prim_path'],'Hinge')
        self.assertAlmostEqual(result['joint_map']['main']['limits'][1],math.radians(80))
        self.assertIsNone(result['body_map']['link0']['diagonal_inertia_kg_m2'])
        self.assertIn('engine_computes',result['body_map']['link0']['inertia_provenance'])

    def test_missing_mass_axis_limit_units_or_unsafe_scale_explicitly_rejected(self):
        from simscene.preparation.articulation import inspect_articulation
        from pxr import UsdGeom
        for mutation in ('mass','axis','limit','units','scale','extra_joint'):
            stage=self.stage()
            if mutation=='mass':stage.GetPrimAtPath('/Native/Door').RemoveProperty('physics:mass')
            elif mutation=='axis':stage.GetPrimAtPath('/Native/Hinge').RemoveProperty('physics:axis')
            elif mutation=='limit':stage.GetPrimAtPath('/Native/Hinge').RemoveProperty('physics:upperLimit')
            elif mutation=='units':UsdGeom.SetStageMetersPerUnit(stage,.01)
            elif mutation=='scale':UsdGeom.Xformable(stage.GetDefaultPrim()).AddScaleOp().Set((2.,2.,2.))
            else:
                from pxr import UsdPhysics
                UsdPhysics.RevoluteJoint.Define(stage,'/Native/Other')
            with self.subTest(mutation=mutation),self.assertRaises(PreparationError):inspect_articulation(stage)


class PreparedArticulationIntegrationTests(unittest.TestCase):
    def stage(self):
        return NativeGraphTests.stage(self)
    def package(self,directory):
        import hashlib,json
        from pathlib import Path
        from pxr import Usd,UsdGeom
        from simscene.preparation.articulation import inspect_articulation
        root=Path(directory);native=self.stage();native.GetRootLayer().Export(str(root/'native.usda'))
        stage=Usd.Stage.CreateNew(str(root/'main.usda'));asset=UsdGeom.Xform.Define(stage,'/Asset');stage.SetDefaultPrim(asset.GetPrim())
        UsdGeom.SetStageMetersPerUnit(stage,1.);UsdGeom.SetStageUpAxis(stage,UsdGeom.Tokens.z)
        UsdGeom.Xform.Define(stage,'/Asset/Native').GetPrim().GetReferences().AddReference('./native.usda')
        stage.GetRootLayer().Save();report=inspect_articulation(stage)
        manifest={'schema':'simscene.prepared_asset.v1','schema_version':1,'profile_id':'articulated_prop_v1',
                  'main':'main.usda','default_prim':'/Asset','body_map':report['body_map'],
                  'joint_map':report['joint_map'],'articulation_report':report,'parameters':{'ccd':False},
                  'files':[{'path':p.name,'size_bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in [root/'native.usda',root/'main.usda']]}
        path=root/'manifest.json';path.write_text(json.dumps(manifest));binding={'manifest_path':str(path),'manifest_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        return {'kind':'asset','asset_path':str(root/'main.usda'),'asset_binding':binding,'dynamic':True,'position':[1.,2.,3.]}

    def test_export_multiple_real_links_and_joint_then_mutation_rejected(self):
        import tempfile
        from pathlib import Path
        from simscene.usd_export import export_scene
        from simscene.physics_binding import validate_asset_binding
        from simscene.scene import validate
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);package=root/'package';package.mkdir();obj=self.package(package)
            scene={'scene_id':'native','revision':1,'objects':{'mechanism':obj},'observation':{'sample_interval_steps':1,'strict_start':True,'record_contact_pairs':True}}
            self.assertEqual(validate(scene),[])
            result=export_scene(scene,root/'scene.usda');bound=result['body_bindings']['mechanism']
            self.assertEqual(len(bound['motion_bodies']),2)
            self.assertEqual(bound['joints']['main']['joint_path'],'/World/mechanism/Asset/Native/Hinge')
            self.assertEqual(bound['joints']['main']['child_body'],'/World/mechanism/Asset/Native/Door')
            validate_asset_binding(obj['asset_binding'])
            (package/'native.usda').write_text((package/'native.usda').read_text()+'\n# changed source\n')
            with self.assertRaisesRegex(ValueError,'changed'):validate_asset_binding(obj['asset_binding'])

    def test_native_bounds_and_camera_plans_preserve_source_and_never_start_drives(self):
        import tempfile
        from pathlib import Path
        from simscene.placement import bounds,measure
        from simscene.presentation import plan
        with tempfile.TemporaryDirectory() as tmp:
            obj=self.package(tmp)
            before={p.name:p.read_bytes() for p in Path(tmp).iterdir() if p.is_file()}
            for driven in (False,True):
                subject=copy.deepcopy(obj)
                if driven:subject['mechanism']={'commands':[command(target=.5)]}
                scene={'revision':1,'objects':{'cabinet':subject,'unrelated':{'kind':'box','size':[100,100,100]}},
                       'observation':{'sample_interval_steps':1,'strict_start':True}}
                original=copy.deepcopy(scene)
                expected={'min':[0.,1.,2.],'max':[2.,3.,4.]}
                self.assertEqual(bounds(subject),expected)
                self.assertEqual(measure(scene,['cabinet'])['objects']['cabinet']['world_bounds_m'],expected)
                self.assertEqual(len(plan(scene,['cabinet'])['cameras']),1)
                self.assertEqual(scene,original)
            self.assertEqual({p.name:p.read_bytes() for p in Path(tmp).iterdir() if p.is_file()},before)

    def test_bound_commands_require_declared_joint_and_strict_observation(self):
        import tempfile
        from simscene.scene import validate
        with tempfile.TemporaryDirectory() as tmp:
            obj=self.package(tmp);obj['mechanism']={'commands':[command(target=.5)]}
            scene={'objects':{'mechanism':obj},'observation':{'sample_interval_steps':1,'strict_start':True}}
            self.assertEqual(validate(scene),[])
            obj['mechanism']['commands'][0]['joint_id']='guessed_joint'
            self.assertTrue(any('undeclared joint' in i['message'] for i in validate(scene)))
            obj['mechanism']={'commands':[]};scene['observation']['strict_start']=False
            self.assertTrue(any('strict_start' in i['message'] for i in validate(scene)))


class CollisionControlTests(unittest.TestCase):
    def test_explicit_dynamic_collision_false_is_real_while_default_remains_enabled(self):
        import tempfile
        from pathlib import Path
        try:from pxr import Usd,UsdPhysics
        except ImportError:self.skipTest('CPU OpenUSD required')
        from simscene.usd_export import export_scene
        for kind in ('box','sphere','cylinder','capsule','compound'):
            for flag in (None,True,False):
                obj={'kind':kind,'dynamic':True,'size':[.1,.1,.1]}
                if kind=='compound':obj.pop('size');obj['parts']=[{'kind':'box','size':[.1,.1,.1]}]
                if flag is not None:obj['collision']=flag
                with self.subTest(kind=kind,flag=flag),tempfile.TemporaryDirectory() as tmp:
                    path=Path(tmp)/'scene.usda';export_scene({'revision':1,'objects':{'impactor':obj}},path)
                    stage=Usd.Stage.Open(str(path));root=stage.GetPrimAtPath('/World/impactor')
                    self.assertTrue(root.HasAPI(UsdPhysics.RigidBodyAPI))
                    colliders=[p for p in stage.Traverse() if p.HasAPI(UsdPhysics.CollisionAPI) and UsdPhysics.CollisionAPI(p).GetCollisionEnabledAttr().Get()]
                    self.assertEqual(bool(colliders),flag is not False)
