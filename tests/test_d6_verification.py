"""Synthetic CPU counterexamples, never evidence of Isaac rope success."""
import ast
import copy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from simscene.d6 import AXES, read_frames, read_limits
from simscene.usd_export import export_scene
from simscene.verification import d6_admission as a
from simscene.verification import mechanism as old_m
from simscene.verification import mechanism_v2 as m
from simscene.verification import passive_network as old_p
from simscene.verification import passive_network_v3 as p
from test_mechanism_check import fixture, make_strict, spoon_fixture, wheel_fixture
from test_passive_network import wrapped_fixture


def synthetic_d6():
    from pxr import Usd
    from simscene.worker.joint_observation import sample as read_sample
    run, spec, case = fixture()
    case.update(schema=m.SCHEMA_D6, rope_joint_model=a.MODEL, require_strict_initial_state=True)
    for name in case['rope']['joint_ids'][1:-1]:
        cfg = spec['objects'][name]['joint']
        cfg.update(type='d6', dof_limits={axis:'locked' for axis in AXES})
        cfg['dof_limits'].update(rotX=[-15,15],rotY=[-75,75],rotZ=[-75,75])
        for i in (0,1):
            cfg['local_rot'+str(i)+'_wxyz'] = [math.sqrt(.5),0,-math.sqrt(.5),0]
    make_strict(run,spec)
    with tempfile.TemporaryDirectory() as root:
        path = Path(root)/'scene.usda'
        export_scene(spec,path)
        stage = Usd.Stage.Open(str(path))
        for loaded in run['mechanism_configuration']['joints']:
            prim = stage.GetPrimAtPath(loaded['path'])
            if prim.GetTypeName() == 'PhysicsJoint':
                loaded.update(type='PhysicsJoint',**read_frames(prim),**read_limits(prim))
        for state in [run['initial_observation'],*run['samples']]:
            measured = read_sample(stage,spec['objects'],native_state=state)
            state['joints'].update({n:v for n,v in measured.items() if v['type']=='d6'})
        run['initial_joint_states'] = copy.deepcopy(run['initial_observation']['joints'])
    return run,spec,case


def typed_d6_network():
    from test_structural_loads import gravity_pad_fixture
    _,spec,case,_ = wrapped_fixture()
    load=gravity_pad_fixture(False)
    spec['objects']['drawer']=copy.deepcopy(load['spec']['objects']['tray'])
    spec['objects']['drawer']['class_label']='drawer'
    for name in ('pad','pad_slide'):
        spec['objects'][name]=copy.deepcopy(load['spec']['objects'][name])
    case['schema']=p.SCHEMA_V3
    case['structural_loads']=copy.deepcopy(load['declarations'])
    case['structural_loads']['pad'].update(support_body_id='drawer',support_motion_event='drawer_opens')
    case['quiet_limits']['pad']=copy.deepcopy(load['quiet_limits']['pad'])
    case['quiet_limits']['drawer']=copy.deepcopy(load['quiet_limits']['tray'])
    case['controls']['no_trigger']['downstream_body_ids'].append('pad')
    case['initial_hold_steps']=4
    nested=case['mechanism_cases']['wrapped_cable']
    _,source,local=synthetic_d6()
    nested.update(schema=m.SCHEMA_D6,rope_joint_model=a.MODEL)
    for name in local['rope']['joint_ids'][1:-1]:
        spec['objects'][name]=copy.deepcopy(source['objects'][name])
    return spec,case


class D6VerificationTest(unittest.TestCase):
    def test_original_modules_and_unchanged_numerical_helpers_are_retained(self):
        for old,new,expected,changed in (
            (old_m,m,m.LEGACY_NUMERICAL_SOURCE_SHA256,{'validate_case','passive_checks','evaluate'}),
            (old_p,p,p.LEGACY_NUMERICAL_SOURCE_SHA256,{'validate_case','bind_case','evaluate'})):
            self.assertEqual(hashlib.sha256(Path(old.__file__).read_bytes()).hexdigest(),expected)
            trees = [ast.parse(Path(module.__file__).read_text()) for module in (old,new)]
            helpers = [{node.name:ast.dump(node,include_attributes=False) for node in tree.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))} for tree in trees]
            self.assertEqual(set(helpers[0]),set(helpers[1]))
            for name in helpers[0].keys()-changed:
                with self.subTest(module=old.__name__,function=name):
                    self.assertEqual(helpers[0][name],helpers[1][name])
        self.assertEqual(old_m.PAIRED_MANIFEST_FIELDS,m.PAIRED_MANIFEST_FIELDS)
        self.assertEqual(len(m.PAIRED_MANIFEST_FIELDS),13)

    def test_legacy_numerical_reports_are_equal(self):
        for factory in (fixture,spoon_fixture,wheel_fixture):
            run,spec,case = factory()
            before = copy.deepcopy((run,spec,case))
            original = old_m.evaluate(run,spec,case)
            upgraded = m.evaluate(run,spec,case)
            self.assertTrue(upgraded['checks'].pop('declared_D6_loaded_modes_and_same_sample_frames'))
            self.assertEqual(upgraded,original)
            self.assertEqual((run,spec,case),before)

    def test_explicit_typed_model_and_same_sample_frames(self):
        run,spec,case = synthetic_d6()
        before = copy.deepcopy((run,spec,case))
        m.validate_case(case)
        self.assertTrue(a.rope_model(run,spec,case)['passed'])
        self.assertTrue(m.passive_checks(run,spec,case)['loaded_joint_inventory_matches_spec'])
        self.assertFalse(old_m.passive_checks(run,spec,case)['loaded_joint_inventory_matches_spec'])
        self.assertFalse(a.configuration(run,spec)['SDK_joint_getter_claimed'])
        self.assertFalse(a.configuration(run,spec)['pyramid_coordinate_bound_certificate_claimed'])
        with self.assertRaises(ValueError):old_m.validate_case(case)
        legacy_case={**case,'schema':m.SCHEMA};legacy_case.pop('rope_joint_model')
        with self.assertRaises(ValueError):m.evaluate(run,spec,legacy_case)
        self.assertEqual((run,spec,case),before)
        for patch_values in ({'schema':m.SCHEMA},{'require_strict_initial_state':False},{'rope_joint_model':'spherical'},{'mechanism':'spoon_sugar'}):
            with self.subTest(patch=patch_values),self.assertRaises(ValueError):m.validate_case({**case,**patch_values})

    def test_source_rejects_hidden_world_channels_and_unbounded_or_wrong_frames(self):
        _,spec,case = synthetic_d6()
        first = case['rope']['joint_ids'][1]
        edits = [
            lambda s:s['objects'].update(hidden={'kind':'joint','joint':{'type':'fixed','body1':case['rope']['segment_ids'][2]}}),
            lambda s:s['objects'].update(hidden={'kind':'joint','joint':{'type':'d6','body1':'weight','dof_limits':copy.deepcopy(s['objects'][first]['joint']['dof_limits'])}}),
            lambda s:s['objects'][first]['joint']['dof_limits'].update(transX='free'),
            lambda s:s['objects'][first]['joint']['dof_limits'].update(rotY='free'),
            lambda s:s['objects'][first]['joint']['dof_limits'].update(rotY='locked'),
            lambda s:s['objects'][first]['joint'].update(local_rot0_wxyz=[1,0,0,0]),
            lambda s:s['objects'][first]['joint'].update(enabled=False),
            lambda s:s['objects'][first]['joint'].update(type='spherical'),
            lambda s:s['objects'][case['rope']['segment_ids'][1]].update(kind='sphere'),
            lambda s:s['objects'][case['rope']['segment_ids'][1]].update(collision=False),
            lambda s:s['objects'][case['rope']['segment_ids'][1]].update(spawn_step=12),
        ]
        for edit in edits:
            source = copy.deepcopy(spec);edit(source)
            with self.subTest(edit=edit):self.assertFalse(a.rope_source(source,case)['passed'])

    def test_loaded_schema_modes_flags_and_frame_tampering_fail_closed(self):
        run,spec,_ = synthetic_d6()
        edits = [
            lambda v:v.update(type='PhysicsSphericalJoint'),
            lambda v:v['dof_limits'].update(rotX=[-16,16]),
            lambda v:v['dof_limit_attributes']['transX'].update(low=2),
            lambda v:v.update(exclude_from_articulation=False),
            lambda v:v.update(collision_enabled=True),
            lambda v:v['body_paths'].__setitem__(0,[]),
            lambda v:v['local_positions_m'][0].__setitem__(0,.01),
            lambda v:v.update(drives=['PhysicsDriveAPI:rotX']),
            lambda v:v.update(joint_attribute_time_samples={'physics:localPos0':[1]}),
            lambda v:v.update(unregistered_limit_schemas=['PhysicsLimitAPI:distance']),
            lambda v:v['resolved_applied_schemas'].append('PhysxLimitAPI'),
            lambda v:v.update(resolved_applied_schemas=[]),
            lambda v:v['local_positions_m'].append([0,0,0]),
            lambda v:v.update(local_positions_m=None),
        ]
        for edit in edits:
            current = copy.deepcopy(run)
            target = next(v for v in current['mechanism_configuration']['joints'] if v['type']=='PhysicsJoint')
            edit(target)
            with self.subTest(edit=edit):self.assertFalse(a.configuration(current,spec)['passed'])

    def test_tensor_coverage_dimensions_unit_endpoints_and_measurement_tampering_fail(self):
        run,spec,case = synthetic_d6();name=case['rope']['joint_ids'][1]
        body = old_m.path(spec['objects'][name]['joint']['body0'])
        edits = [
            lambda r:r['samples'].pop(10),
            lambda r:r['samples'][10].update(physics_steps=10),
            lambda r:r['initial_observation'].update(physics_steps=1),
            lambda r:r['mechanism_configuration']['joints'].append(copy.deepcopy(r['mechanism_configuration']['joints'][1])),
            lambda r:r['mechanism_configuration']['joints'].append(None),
            lambda r:r['samples'][10]['joints'][name].update(pose_source='loaded_USD_body_xforms'),
            lambda r:r['samples'][10]['joints'][name].update(relative_rotation_wxyz=[1,0,0,float('nan')]),
            lambda r:r['samples'][10]['joints'][name].update(anchor0_world_m=[0,0]),
            lambda r:r['samples'][10]['joints'][name].update(anchor_error_m=float('nan')),
            lambda r:r['samples'][10]['joints'][name].update(anchor_error_m=False),
            lambda r:r['samples'][10]['joints'][name].update(frame_separation_m=float('nan')),
            lambda r:r['samples'][10]['joints'][name].update(twist_x_degrees=2),
            lambda r:r['samples'][10]['joints'][name].update(swing_angle_degrees=2),
            lambda r:r['samples'][10]['joints'].__setitem__(name,None),
            lambda r:r['samples'][10]['orientations_wxyz'].__setitem__(body,[2,0,0,0]),
            lambda r:r['samples'][10]['positions'].__setitem__(body,[0,0,float('inf')]),
        ]
        for edit in edits:
            current=copy.deepcopy(run);edit(current)
            with self.subTest(edit=edit):self.assertFalse(a.configuration(current,spec)['passed'])

    def test_public_dispatch_does_not_silently_upgrade_legacy_schemas(self):
        from simscene.verification import case_runner
        for schema,public,target in ((m.SCHEMA,'mechanism','mechanism_adapter'),(m.SCHEMA_D6,'mechanism','mechanism_adapter_v2'),(p.SCHEMA_V2,'passive_network','passive_network'),(p.SCHEMA_V3,'passive_network','passive_network_v3')):
            with tempfile.TemporaryDirectory() as root:
                case=Path(root)/'case.json';case.write_text(json.dumps({'schema':schema}))
                fake=unittest.mock.Mock();fake.verify_run.return_value={'passed':False}
                with patch.object(case_runner.importlib,'import_module',return_value=fake) as load:
                    result=case_runner.evaluate(root,case)
                self.assertEqual(result['case_type'],public)
                self.assertEqual(load.call_args.args[0],'.'+target)
                with patch.object(case_runner.importlib,'import_module',return_value=fake):
                    if schema in (m.SCHEMA_D6,p.SCHEMA_V3):
                        with self.assertRaises(ValueError):case_runner.evaluate(root,case,'parallel')

    def test_failed_provenance_returns_failure_before_loading_a_case(self):
        from simscene.verification import mechanism_adapter_v2 as adapter
        with patch.object(adapter,'_read_locked',return_value={'passed':False,'integrity':{'worker_snapshot_pinned':False}}):
            result=adapter.verify_run('/synthetic/absent')
        self.assertFalse(result['passed'])

    def test_suite_dispatch_is_explicit_and_leaves_sealed_checks_to_authority(self):
        from simscene.verification import case_runner
        for schema,target in ((p.SCHEMA,'passive_network'),(p.SCHEMA_V2,'passive_network'),(p.SCHEMA_V3,'passive_network_v3')):
            with tempfile.TemporaryDirectory() as root:
                root=Path(root);case=root/'acceptance-case.json'
                case.write_text(json.dumps({'schema':schema}))
                (root/'run-lock.json').write_text(json.dumps({'acceptance_case_file':case.name}))
                fake=unittest.mock.Mock();fake.verify_suite.return_value={'passed':False}
                with patch.object(case_runner.importlib,'import_module',return_value=fake) as load:
                    self.assertFalse(case_runner.verify_passive_suite(root,{})['passed'])
                self.assertEqual(load.call_args.args[0],'.'+target)
                fake.verify_suite.assert_called_once_with(root,{},None)
                (root/'run-lock.json').write_text(json.dumps({'acceptance_case_file':'../outside.json'}))
                with self.assertRaises(ValueError):case_runner.verify_passive_suite(root,{})

    def test_network_binding_requires_one_explicit_real_material_axis_rope(self):
        spec,case=typed_d6_network()
        before=copy.deepcopy((spec,case))
        p.validate_case(case)
        binding=p.bind_case(case,spec)
        self.assertIn('pad',binding['typed_structural_loads']['body_ids'])
        self.assertEqual((spec,case),before)
        for schema in (old_p.SCHEMA,old_p.SCHEMA_V2):
            with self.subTest(schema=schema),self.assertRaises(ValueError):p.validate_case({**case,'schema':schema})
        no_rope=copy.deepcopy(case);no_rope['mechanism_cases']={}
        with self.assertRaises(ValueError):p.validate_case(no_rope)
        two_ropes=copy.deepcopy(case)
        two_ropes['mechanism_cases']['other_rope']=copy.deepcopy(two_ropes['mechanism_cases']['wrapped_cable'])
        with self.assertRaises(ValueError):p.validate_case(two_ropes)
        hidden=copy.deepcopy(spec)
        hidden['objects']['hidden']={'kind':'joint','joint':{'type':'d6','body1':'weight'}}
        with self.assertRaises(ValueError):p.bind_case(case,hidden)
        legacy=copy.deepcopy(case)
        legacy['schema']=old_p.SCHEMA_V2
        legacy['mechanism_cases']['wrapped_cable'].pop('rope_joint_model')
        legacy['mechanism_cases']['wrapped_cable']['schema']=m.SCHEMA
        p.validate_case(legacy)
        with self.assertRaises(ValueError):p.bind_case(legacy,spec)
