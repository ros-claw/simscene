"""External v4 generic regressions; all evidence is synthetic/static."""
import ast
import copy
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import weakref

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments import whole_home_fidelity_v7 as f
from experiments import whole_home_suite_v7 as suite
from experiments import whole_home_fidelity as legacy
from test_structural_loads import gravity_pad_fixture, journal_for, support_contact


def auxiliary_fixture():
    fixture = gravity_pad_fixture(False)
    spec, run = fixture['spec'], fixture['run']
    for sample in run['samples']: sample['contact_pairs'] = []
    spec['objects']['cue'] = {'kind': 'sphere', 'dynamic': True, 'collision': True,
        'size': [.05]*3, 'position': [2, 0, 1], 'orientation_wxyz': [1, 0, 0, 0],
        'mass_kg': .05, 'spawn_step': 5}
    for sample in run['samples'][5:]:
        for key, value in [('positions', [2, 0, 1]), ('orientations_wxyz', [1, 0, 0, 0]),
                           ('linear_velocities_m_s', [0, 0, 0]), ('angular_velocities_rad_s', [0, 0, 0])]:
            sample[key]['/World/cue'] = value[:]
    case = {'trigger_id': 'cue', 'terminal': {'body_id': 'block', 'receiver_id': 'vessel'},
        'handoffs': [{'body_path': ['tray']}], 'household_categories': {}, 'events': {},
        'activity': {'stages': []}, 'rope_body_ids': [], 'mechanism_cases': {}, 'structural_loads': {}}
    return fixture, case


def auxiliary_result(fixture, case, ids=None, journal=None):
    return f.non_contact_auxiliary_bodies(fixture['run'], fixture['spec'], case,
        ['pad'] if ids is None else ids, fixture['dt'], _journal=journal)


def functions(filename):
    return {node.name: ast.dump(node, include_attributes=False) for node in ast.parse(Path(filename).read_text()).body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


class WholeHomeV4Tests(unittest.TestCase):
    def test_v6_unchanged_physical_predicates_and_explicit_new_bridge_authority(self):
        here = Path(__file__).resolve().parents[1]/'experiments'
        old, new = functions(here/'whole_home_fidelity_v5.py'), functions(f.__file__)
        for name in ('canonical_spec', 'sealed_identities', 'suite_metadata', '_window', 'cart_rolling',
                     'cable_no_bypass', 'bind_non_contact_auxiliary_bodies', 'non_contact_auxiliary_bodies',
                     'export_motion_csv', 'activity_breakdown', 'canonical_joint_unbreakable_default',
                     'static_stage_catalog', 'mass_catalog'):
            self.assertEqual(old[name], new[name], name)
        old_suite = functions(here/'whole_home_suite_v5.py');new_suite = functions(suite.__file__)
        for name in ('consecutive_three', 'check_attempt_inventory', '_patch', '_world_anchor_path',
                     '_synchronized_world_anchors', 'verify_native'):
            self.assertEqual(old_suite[name], new_suite[name], name)
        self.assertEqual(old_suite['compare_variant'].replace("name='compare_variant'", "name='_compare_variant_core'"), new_suite['_compare_variant_core'])
        from test_composed_event_mechanisms import fixture
        run, spec, case, declarations, stock = fixture()
        stock['events'].update(start={'onset_step': 40}, end={'onset_step': 60})
        composition = f.composed.evaluate(run, spec, case, declarations, stock, 1/60)
        cfg = {'composed_mechanism_key': 'wheel', 'phase': {'start_event': 'start', 'end_event': 'end'}, 'minimum_support_callback_updates': 1}
        self.assertTrue(f.bridge_support(run, spec, stock, declarations, composition, cfg)['passed'])
        self.assertFalse(composition['mechanisms']['wheel']['raw_p1_report']['passed'])
        composition['mechanisms']['wheel']['passed'] = False
        self.assertFalse(f.bridge_support(run, spec, stock, declarations, composition, cfg)['passed'])

    def test_external_variant_changes_are_exact_geometry_only(self):
        from test_composed_event_mechanisms import fixture
        declarations = fixture()[3]
        base = {'schema': f.SCHEMA, 'composed_mechanisms': declarations, 'network_case_sha256': 'a'*64,
                'nominal_configuration_sha256': 'b'*64, 'static_review_sha256': 'c'*64,
                'physics_dt_s': 1/60, 'cart': {'minimum_progress_m': .1}, 'cable': {'model_description': 'unchanged'}}
        variant = copy.deepcopy(base)
        path = ['composed_mechanisms', 'spoon', 'mechanism_case', 'receiver', 'interior_world', 'min']
        before = copy.deepcopy(variant['composed_mechanisms']['spoon']['mechanism_case']['receiver']['interior_world']['min'])
        after = [before[0]-.2, *before[1:]]
        variant['composed_mechanisms']['spoon']['mechanism_case']['receiver']['interior_world']['min'] = after
        declaration = {'fidelity_geometry_changes': [{'path': path, 'before': before, 'after': after}]}
        self.assertTrue(suite.compare_variant_contract(base, variant, declaration)['passed'])
        for kind in ('threshold', 'input_body', 'handoff', 'trigger', 'release', 'cart', 'activity', 'extra_field', 'undeclared'):
            changed = copy.deepcopy(variant)
            if kind == 'threshold': changed['composed_mechanisms']['spoon']['mechanism_case']['thresholds']['terminal_hold_steps'] -= 1
            elif kind in ('input_body', 'handoff'): changed['composed_mechanisms']['spoon']['local_input_body_id' if kind == 'input_body' else 'incoming_handoff_id'] = 'different'
            elif kind in ('trigger', 'release'): changed['composed_mechanisms']['spoon']['mechanism_case']['trigger_id' if kind == 'trigger' else 'release_step'] = 'other' if kind == 'trigger' else 11
            elif kind == 'cart': changed['cart']['minimum_progress_m'] = .01
            elif kind == 'activity': changed['composed_mechanisms']['spoon']['mechanism_case']['activity'] = {}
            elif kind == 'extra_field': changed['unknown'] = True
            else: changed['composed_mechanisms']['wheel']['mechanism_case']['bridge_regions_world'][0]['min'][0] += .1
            with self.subTest(kind=kind): self.assertFalse(suite.compare_variant_contract(base, changed, declaration)['passed'])
        for path in (['composed_mechanisms', 'spoon'], ['composed_mechanisms', 'spoon', 'mechanism_case'],
                     ['composed_mechanisms', 'spoon', 'mechanism_case', 'thresholds', 'terminal_hold_steps'],
                     ['cart', 'minimum_progress_m']):
            bad = {'fidelity_geometry_changes': [{'path': path, 'before': None, 'after': None}]}
            with self.subTest(path=path), self.assertRaises(ValueError): suite.compare_variant_contract(base, variant, bad)

    def test_bridge_never_accepts_synthetic_stock_nested_report(self):
        from test_composed_event_mechanisms import fixture
        run, spec, case, declarations, stock = fixture()
        stock['events'].update(start={'onset_step': 40}, end={'onset_step': 60})
        stock['mechanism_cases'] = {'wheel': {'report': {'passed': True}}}
        composition = {'passed': False, 'mechanisms': {'wheel': {'passed': False}}}
        cfg = {'composed_mechanism_key': 'wheel', 'phase': {'start_event': 'start', 'end_event': 'end'}, 'minimum_support_callback_updates': 1}
        self.assertFalse(f.bridge_support(run, spec, stock, declarations, composition, cfg)['passed'])

    def test_real_usd_canonical_unbreakable_defaults_preserved_not_omitted(self):
        from pxr import Usd, UsdPhysics
        from experiments import whole_home_fidelity_v4 as old
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'generic.usda';stage = Usd.Stage.CreateNew(str(path))
            joint = UsdPhysics.PrismaticJoint.Define(stage, '/World/generic_joint')
            joint.CreateBreakForceAttr().Set(float('inf'));joint.CreateBreakTorqueAttr().Set(float('inf'))
            stage.GetRootLayer().Save()
            self.assertFalse(old.static_stage_catalog(path)['passed'])
            result = f.static_stage_catalog(path)
            self.assertTrue(result['passed'], result)
            for name in ('physics:breakForce', 'physics:breakTorque'):
                value = result['physics_attributes']['/World/generic_joint'][name]
                self.assertEqual(value['value'], {'nonfinite_schema_value': 'inf'})
                self.assertTrue(value['authored_value_opinion'])
                self.assertEqual(value['canonical_default_interpretation']['schema_attribute_type'], 'float')
            self.assertEqual(len(result['canonical_passive_joint_defaults']), 2)
            json.dumps(result, allow_nan=False)

    def test_only_typed_known_positive_default_without_time_samples_is_recognized(self):
        from pxr import Usd, UsdPhysics, Sdf
        for kind in ('wrong_prim', 'wrong_name', 'negative_inf', 'nan', 'time_sample', 'wrong_type'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/'generic.usda';stage = Usd.Stage.CreateNew(str(path))
                prim = stage.DefinePrim('/World/generic', 'Xform') if kind == 'wrong_prim' else UsdPhysics.FixedJoint.Define(stage, '/World/generic').GetPrim()
                name = 'physics:unknownForce' if kind == 'wrong_name' else 'physics:breakForce'
                attr = prim.CreateAttribute(name, Sdf.ValueTypeNames.Double if kind == 'wrong_type' else Sdf.ValueTypeNames.Float)
                value = float('-inf') if kind == 'negative_inf' else float('nan') if kind == 'nan' else float('inf')
                attr.Set(value, Usd.TimeCode(1) if kind == 'time_sample' else Usd.TimeCode.Default())
                if kind == 'wrong_type':
                    # Typed Usd.CreateAttribute retains the schema type. Raw
                    # Sdf authoring creates an actually conflicting declaration.
                    prim.RemoveProperty(name)
                    opinion = Sdf.AttributeSpec(stage.GetRootLayer().GetPrimAtPath('/World/generic'), name, Sdf.ValueTypeNames.Double)
                    opinion.default = value
                stage.GetRootLayer().Save()
                result = f.static_stage_catalog(path)
                self.assertFalse(result['passed'], result)
                json.dumps(result, allow_nan=False)

    def test_changed_or_missing_sdk_canonical_fallback_is_not_trusted(self):
        from pxr import Usd, UsdPhysics
        stage = Usd.Stage.CreateInMemory();prim = UsdPhysics.FixedJoint.Define(stage, '/joint').GetPrim()
        attr = prim.GetAttribute('physics:breakForce');attr.Set(float('inf'))
        real_definition = Usd.SchemaRegistry().FindConcretePrimDefinition('PhysicsFixedJoint')
        # The prim/attribute are real USD; the narrow registry shim simulates a
        # future SDK with absent/changed fallback, without a custom plugin.
        for fallback in (None, 0., float('-inf'), float('nan')):
            class Definition:
                def GetSchemaAttributeSpec(self, name): return real_definition.GetSchemaAttributeSpec(name)
                def GetAttributeFallbackValue(self, name): return fallback
            class Registry:
                def FindConcretePrimDefinition(self, name): return Definition()
            with patch.object(Usd, 'SchemaRegistry', new=lambda: Registry()):
                self.assertIsNone(f.canonical_joint_unbreakable_default(prim, 'physics:breakForce', attr))

    def test_legal_break_default_never_exempts_active_physics_or_other_infinities(self):
        from pxr import Usd, UsdPhysics, Sdf, Gf
        for kind in ('drive', 'kinematic', 'external_force', 'mass_inf'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/'generic.usda';stage = Usd.Stage.CreateNew(str(path))
                prim = UsdPhysics.RevoluteJoint.Define(stage, '/joint').GetPrim()
                prim.GetAttribute('physics:breakForce').Set(float('inf'))
                if kind == 'drive': UsdPhysics.DriveAPI.Apply(prim, 'angular')
                elif kind == 'kinematic': UsdPhysics.RigidBodyAPI.Apply(prim).CreateKinematicEnabledAttr().Set(True)
                elif kind == 'external_force': prim.CreateAttribute('physxForce:force', Sdf.ValueTypeNames.Float3).Set(Gf.Vec3f(1, 0, 0))
                else: UsdPhysics.MassAPI.Apply(prim).CreateMassAttr().Set(float('inf'))
                stage.GetRootLayer().Save()
                self.assertFalse(f.static_stage_catalog(path)['passed'])

    def test_new_contract_excludes_loads_and_auxiliaries_from_credit(self):
        # Focused contract fixture; complete P3 schema/physics are tested by the
        # real stock tests, not claimed by this deliberately small declaration.
        case = {'rope_body_ids': ['line'], 'structural_loads': {'pad': {}},
            'mechanism_cases': {'rope': {'mechanism': 'rope_drawer', 'rope_model': 'segmented_over_free_pulley',
                'roles': {'pulley': 'sheave', 'weight': 'weight', 'drawer': 'drawer'}, 'joints': {'drawer_end': 'cut'}},
                'door': {'mechanism': 'wheel_door_bridge', 'roles': {'door': 'door'}, 'joints': {'door': 'hinge'}}},
            'activity': {'stages': [{'id': 'rolling', 'start_event': 'open', 'end_event': 'hit',
                'bodies': [{'id': 'cart', 'direction_world': [0, 1, 0], 'minimum_speed_m_s': .01}]}]},
            'controls': {'broken_rope': {'joint_id': 'cut'}, 'locked_door': {'door_body_id': 'door', 'joint_id': 'hinge'}}}
        contract = {'schema': f.SCHEMA, 'network_case_sha256': 'a'*64, 'nominal_configuration_sha256': 'b'*64,
            'static_review_sha256': 'c'*64, 'physics_dt_s': 1/60,
            'cart': {'body_id': 'cart', 'phase': {'start_event': 'open', 'end_event': 'hit'},
                'direction_world': [0, 1, 0], 'minimum_progress_speed_m_s': .01,
                'wheels': [{'body_id': 'roller', 'carrier_body_id': 'carrier'}]},
            'cable': {'load_attachment_joint_id': 'cut', 'weight_body_id': 'weight', 'load_body_id': 'drawer'},
            'bridge': {'mechanism_case_key': 'door'}, 'activity_groups': {'act': ['rolling']},
            'activity_excluded_body_ids': ['line', 'sheave', 'roller', 'pad', 'guide'],
            'non_contact_auxiliary_body_ids': ['guide']}
        from test_composed_event_mechanisms import fixture as composed_fixture
        _, _, incoming_case, definitions, _ = composed_fixture()
        case.update({k: incoming_case[k] for k in ('require_strict_initial_state', 'trigger_id', 'release_step')})
        case['mechanism_cases'].pop('door')
        case['controls']['locked_door']['joint_id'] = 'door_axle'
        contract['composed_mechanisms'] = definitions
        contract['bridge'] = {'composed_mechanism_key': 'wheel'}
        with patch.object(f, 'validate_floors', new=lambda *args: True):
            self.assertEqual(f.validate_contract(contract, case, 1/60), contract)
            for omitted in ('pad', 'guide'):
                changed = copy.deepcopy(contract);changed['activity_excluded_body_ids'].remove(omitted)
                with self.assertRaises(ValueError): f.validate_contract(changed, case, 1/60)
            for role in ('cart', 'roller', 'carrier'):
                changed = copy.deepcopy(contract);changed['non_contact_auxiliary_body_ids'] = [role]
                changed['activity_excluded_body_ids'].append(role)
                with self.assertRaises(ValueError): f.validate_contract(changed, case, 1/60)

    def test_every_original_step_zero_callback_proof_is_separate_from_physics(self):
        fixture, case = auxiliary_fixture()
        result = auxiliary_result(fixture, case)
        self.assertTrue(result['passed'], result)
        self.assertEqual(result['original_steps_examined'], 12)
        self.assertEqual(result['original_callback_records_examined'], 0)
        self.assertFalse(result['formal_stage_accepted'])
        self.assertFalse(result['activity_or_category_credit'])

    def test_cue_support_static_and_other_auxiliary_contact_fail(self):
        for other in ('cue', 'tray', 'floor', 'other_aux'):
            fixture, case = auxiliary_fixture()
            if other in ('floor', 'other_aux'):
                fixture['spec']['objects'][other] = {'kind': 'box', 'collision': True, 'size': [1]*3}
            record = support_contact(7)
            record.update(body_ids=['pad', other], actor_paths=['/World/pad', '/World/'+other],
                          collider_paths=['/World/pad', '/World/'+other])
            fixture['run']['samples'][6]['contact_pairs'].append(record)
            result = auxiliary_result(fixture, case)
            self.assertFalse(result['passed'], result)
            self.assertEqual(result['contact_records'][0]['observation_step'], 7)

    def test_raw_contact_cannot_be_hidden_by_false_journal_or_aggregate(self):
        fixture, case = auxiliary_fixture()
        fixture['run']['samples'][3]['contact_pairs'] = [support_contact(4)]
        result = auxiliary_result(fixture, case, journal={'passed': True, 'records': []})
        self.assertFalse(result['passed'])
        self.assertTrue(result['contact_records'])
        fixture, case = auxiliary_fixture()
        # Aggregate headers are not treated as per-step nonempty callbacks.
        fixture['run']['contact_counts'] = {'pad|/World/tray|': {'count': 9, 'first_contact_physics_step': 1}}
        self.assertTrue(auxiliary_result(fixture, case)['passed'])
        fixture['run']['samples'][3].pop('contact_pairs')
        self.assertFalse(auxiliary_result(fixture, case)['passed'])

    def test_clock_actor_boundary_and_truncation_fail_closed(self):
        mutations = [lambda r: r['samples'].pop(3), lambda r: r['samples'][3].update(physics_steps=6),
                     lambda r: r['samples'][3].update(absolute_physics_step=99),
                     lambda r: r['initialization_reset'].update(setters_during_task=True),
                     lambda r: r.update(contacts_truncated=True)]
        for mutate in mutations:
            fixture, case = auxiliary_fixture(); mutate(fixture['run'])
            self.assertFalse(auxiliary_result(fixture, case)['passed'])
        fixture, case = auxiliary_fixture()
        record = support_contact(4);record['actor_paths'][0] = '/World/cue'
        fixture['run']['samples'][3]['contact_pairs'] = [record]
        self.assertFalse(auxiliary_result(fixture, case)['passed'])

    def test_auxiliary_cannot_receive_any_task_role_or_load_credit(self):
        mutations = [lambda c: c['handoffs'][0]['body_path'].append('pad'),
                     lambda c: c['events'].update(pad_activated={'conditions': [{'kind': 'body_displacement', 'body_id': 'pad'}]}),
                     lambda c: c['household_categories'].update(fake={'body_ids': ['pad']}),
                     lambda c: c['activity']['stages'].append({'bodies': [{'id': 'pad'}]}),
                     lambda c: c['structural_loads'].update(pad={}),
                     lambda c: c['mechanism_cases'].update(fake={'roles': {'pulley': 'pad'}}),
                     lambda c: c['terminal'].update(body_id='pad')]
        for mutate in mutations:
            fixture, case = auxiliary_fixture(); mutate(case)
            self.assertFalse(auxiliary_result(fixture, case)['passed'])
        for ids in (['pad', 'pad'], ['cue'], ['missing'], [False]):
            fixture, case = auxiliary_fixture()
            self.assertFalse(auxiliary_result(fixture, case, ids)['passed'])

    def test_auxiliary_requires_initial_real_dynamic_collision_body(self):
        for change in ({'dynamic': False}, {'collision': False}, {'spawn_step': 1}, {'kind': 'asset'}):
            fixture, case = auxiliary_fixture();fixture['spec']['objects']['pad'].update(change)
            self.assertFalse(auxiliary_result(fixture, case)['passed'])

    def test_nonfinite_unbounded_schema_defaults_survive_strict_json(self):
        from pxr import Usd, UsdPhysics
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'generic.usda';stage = Usd.Stage.CreateNew(str(path))
            joint = UsdPhysics.RevoluteJoint.Define(stage, '/World/hinge')
            stage.GetRootLayer().Save()
            catalog = f.static_stage_catalog(path)
            value = catalog['physics_attributes']['/World/hinge']['physics:lowerLimit']
            self.assertEqual(value['value'], {'nonfinite_schema_value': '-inf'})
            self.assertFalse(value['authored_value_opinion'])
            self.assertTrue(catalog['passed'])
            json.dumps(catalog, allow_nan=False)
            joint.CreateLowerLimitAttr().Set(float('-inf'));stage.GetRootLayer().Save()
            catalog = f.static_stage_catalog(path)
            self.assertFalse(catalog['passed'])
            self.assertTrue(catalog['physics_attributes']['/World/hinge']['physics:lowerLimit']['authored_value_opinion'])
            json.dumps(catalog, allow_nan=False)

    def test_authored_nonfinite_quaternion_is_tagged_and_rejected(self):
        from pxr import Usd, UsdPhysics, Gf
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'generic.usda';stage = Usd.Stage.CreateNew(str(path))
            joint = UsdPhysics.PrismaticJoint.Define(stage, '/World/slide')
            joint.CreateLocalRot0Attr().Set(Gf.Quatf(float('nan'), Gf.Vec3f(0)))
            stage.GetRootLayer().Save()
            catalog = f.static_stage_catalog(path)
            self.assertFalse(catalog['passed'])
            self.assertEqual(catalog['physics_attributes']['/World/slide']['physics:localRot0']['value']['real'], {'nonfinite_schema_value': 'nan'})
            json.dumps(catalog, allow_nan=False)

    def test_nonfinite_gravity_and_velocity_remain_rejected_serializable_evidence(self):
        from pxr import Usd, UsdPhysics, UsdGeom, Gf
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'generic.usda';stage = Usd.Stage.CreateNew(str(path))
            UsdPhysics.Scene.Define(stage, '/World/physics').CreateGravityMagnitudeAttr().Set(float('nan'))
            cube = UsdGeom.Cube.Define(stage, '/World/body')
            UsdPhysics.RigidBodyAPI.Apply(cube.GetPrim()).CreateVelocityAttr().Set(Gf.Vec3f(float('inf'), 0, 0))
            stage.GetRootLayer().Save()
            catalog = f.static_stage_catalog(path)
            self.assertFalse(catalog['passed'])
            self.assertEqual(catalog['physics_scenes'][0]['gravity_magnitude_m_s2'], {'nonfinite_schema_value': 'nan'})
            self.assertEqual(catalog['rigid_bodies'][0]['velocity'][0], {'nonfinite_schema_value': 'inf'})
            json.dumps(catalog, allow_nan=False)

    def test_old_physical_geometry_time_and_variant_functions_remain_identical(self):
        here = Path(__file__).resolve().parents[1]/'experiments'
        old, new = functions(here/'whole_home_fidelity.py'), functions(here/'whole_home_fidelity_v4.py')
        for name in ('validate_floors', 'canonical_spec', 'sealed_identities', 'suite_metadata', '_window',
                     'cart_rolling', 'cable_no_bypass', 'bridge_support', 'export_motion_csv', 'activity_breakdown', 'mass_catalog'):
            self.assertEqual(old[name], new[name], name)
        old, new = functions(here/'whole_home_suite.py'), functions(here/'whole_home_suite_v4.py')
        for name in ('verify_freeze', 'consecutive_three', 'check_attempt_inventory', '_patch', '_world_anchor_path',
                     '_synchronized_world_anchors', 'compare_variant', 'verify_native', 'verify_suite'):
            self.assertEqual(old[name], new[name], name)

    def test_legacy_v3_rejects_current_new_kernel(self):
        with self.assertRaisesRegex(ValueError, 'frozen v40 kernel changed'):
            legacy.assert_kernel()
        f.assert_kernel()
        self.assertEqual(f.ORCHESTRATION_VERSION, 7)
        self.assertEqual(suite.f.__file__, f.__file__)

    def test_control_auxiliary_failure_gates_after_stock_and_releases_raw(self):
        # Explicitly mocked custody/physics collaborators test only ordering,
        # all-mode gating and bounded retention, not a synthetic physics pass.
        class Raw(dict):
            pass
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);(root/'run-lock.json').write_text('{}')
            (root/'evidence-lock.json').write_text(json.dumps({'artifacts': {'result.json': {'sha256': 'e'*64}}}))
            review = {'passed': True, 'scope': 'nominal_static_preflight', 'reviewer_role': 'independent_examiner',
                'nominal_configuration_sha256': 'n'*64, 'network_case_sha256': 'f'*64,
                'role_asset_proxy_review_passed': True, 'energy_force_catalog_passed': True,
                'non_contact_auxiliary_review_passed': True, 'non_contact_auxiliary_body_ids': ['guide']}
            review_path = root/'review.json';review_path.write_text(json.dumps(review))
            contract = {'static_review_sha256': f.sha(review_path), 'nominal_configuration_sha256': 'n'*64,
                        'network_case_sha256': 'f'*64, 'non_contact_auxiliary_body_ids': ['guide']}
            contract_path = root/'contract.json';contract_path.write_text(json.dumps(contract))
            calls = [];references = []
            def stock(*args, **kwargs):
                self.assertEqual(calls, []);calls.append('stock_complete')
                return {'passed': True, 'contact_journal': {'passed': True, 'record_count': 0, 'errors': [], 'scope': f.p.contact_journal({'samples': []}, {'objects': {}})['scope']}}
            def read(*args, **kwargs):
                self.assertEqual(calls, ['stock_complete']);calls.append('outer_read')
                raw = Raw(samples=[{'synthetic_sample': i, 'physics_steps': i+1, 'contact_pairs': []} for i in range(1000)], videos={}, mechanism_configuration={})
                references.append(weakref.ref(raw))
                return {'passed': True, 'root': root, 'run': raw, 'spec': {'objects': {}}, 'case': {},
                        'lock': {'physics_dt_s': 1/60}, 'integrity': {'case_sha256': 'f'*64}}
            with ExitStack() as stack:
                stack.enter_context(patch.object(f.p, 'verify_run', new=stock))
                stack.enter_context(patch.object(f.p, '_read_locked', new=read))
                stack.enter_context(patch.object(f, 'validate_contract', new=lambda *args: True))
                stack.enter_context(patch.object(f, 'sealed_identities', new=lambda *args: {}))
                stack.enter_context(patch.object(f, 'static_stage_catalog', new=lambda *args: {'passed': True}))
                stack.enter_context(patch.object(f, 'mass_catalog', new=lambda *args: {'passed': True}))
                stack.enter_context(patch.object(f, 'non_contact_auxiliary_bodies', new=lambda *args, **kwargs: {'passed': False}))
                for mode in ('no_trigger', 'broken_rope', 'locked_door'):
                    calls.clear()
                    result = f.verify_one(root, contract_path, review_path, mode=mode, reference_run='synthetic_reference')
                    self.assertFalse(result['passed'], mode)
                    self.assertTrue(result['stock']['passed'], mode)
                    self.assertFalse(result['non_contact_auxiliaries']['passed'], mode)
                    self.assertEqual(calls, ['stock_complete', 'outer_read'])
            self.assertTrue(all(value() is None for value in references), 'raw run escaped into retained report/metadata')


if __name__ == '__main__':
    unittest.main()
